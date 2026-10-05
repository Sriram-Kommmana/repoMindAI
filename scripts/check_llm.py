"""Live capability check for each configured LLM provider.

Usage: python scripts/check_llm.py [bedrock|groq ...]

Verifies everything RepoMind relies on: plain completions, tool calling
(auto), the tool-result round trip, a tool-free final answer, and JSON mode.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import llm  # noqa: E402

TOOL = {
    "type": "function",
    "function": {
        "name": "get_module_details",
        "description": "Details of one module in the repository.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
}


def _checks(provider):
    os.environ["LLM_PROVIDER"] = provider
    purpose = f"check_{provider}"

    plain = llm.chat([{"role": "user", "content": "Reply with exactly: pong"}], purpose=purpose, max_tokens=300)
    yield "plain completion", "pong" in plain.content.lower(), plain.content[:60]

    messages = [
        {"role": "system", "content": "Use tools to answer questions about the repository."},
        {"role": "user", "content": "What does src/app.py contain?"},
    ]
    first = llm.chat(messages, purpose=purpose, max_tokens=600, tools=[TOOL])
    called = [tc.function.name for tc in first.tool_calls]
    yield "tool call (auto)", called == ["get_module_details"], f"provider={first.provider} called={called}"
    if not first.tool_calls:
        return

    tc = first.tool_calls[0]
    messages.append({"role": "assistant", "content": first.content or "", "tool_calls": [
        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}]})
    messages.append({"role": "tool", "tool_call_id": tc.id,
                     "content": json.dumps({"path": "src/app.py", "functions": ["main()", "create_app(config)"]})})
    second = llm.chat(messages, purpose=purpose, max_tokens=600, tools=[TOOL])
    # The API accepting the tool result is what matters; a model that calls
    # the tool again instead of answering is still a working round trip.
    answered = "create_app" in second.content
    detail = second.content[:80].replace("\n", " ") if answered else f"accepted; model called {len(second.tool_calls)} more tool(s)"
    yield "tool result round trip", answered or bool(second.tool_calls), detail

    final = llm.chat([{"role": "user", "content": "Evidence: src/app.py defines main() and create_app(config). "
                                                  "Which function takes a config argument?"}],
                     purpose=purpose, max_tokens=400)
    yield "tool-free final answer", "create_app" in final.content, final.content[:60].replace("\n", " ")

    as_json = llm.chat([{"role": "user", "content": 'Return a JSON object {"ok": true, "n": 3}.'}],
                       purpose=purpose, max_tokens=300, json_mode=True)
    try:
        parsed = llm.parse_json(as_json.content)
        yield "JSON mode", parsed.get("ok") is True, json.dumps(parsed)
    except ValueError as exc:
        yield "JSON mode", False, str(exc)


def main():
    providers = sys.argv[1:] or ["bedrock", "groq"]
    failures = 0
    for provider in providers:
        print(f"\n== {provider} ==")
        try:
            for name, ok, detail in _checks(provider):
                failures += not ok
                print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        except llm.LLMConfigError as exc:
            print(f"  [SKIP] {exc}")
        except Exception as exc:
            failures += 1
            print(f"  [FAIL] {type(exc).__name__}: {exc}")
    notices = llm.notices()
    if notices:
        print("\nNotices:\n  " + "\n  ".join(notices))
    print("\nUsage:", json.dumps(llm.usage_snapshot()))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
