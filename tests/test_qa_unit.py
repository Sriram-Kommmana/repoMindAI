import json

import qa_engine as q


def test_clean_citations_keeps_locations_and_drops_noise():
    text = "Violated here【/commentary::get_architecture_health】. Returns it【controller.py:L5-L7】."
    assert q.clean_citations(text) == "Violated here. Returns it (`controller.py:L5-L7`)."
    assert q.clean_citations("Health is 100 (`repo_browser.get_drift_trend†L1-L12`).") == "Health is 100."
    assert q.clean_citations("zero violations `repo_browser.get_architecture_health†L1-L9`.") == "zero violations."


def test_resolve_source_path():
    sources = {"src/core/state.js": "", "src/modules/state.js": "", "src/index.js": ""}
    assert q._resolve_source_path(sources, "src/index.js") == ("src/index.js", [])
    assert q._resolve_source_path(sources, "./index.js") == ("src/index.js", [])
    path, candidates = q._resolve_source_path(sources, "state.js")
    assert path is None and sorted(candidates) == ["src/core/state.js", "src/modules/state.js"]


def test_read_source_window_and_caps():
    sources = {"a.py": "\n".join(f"line {i}" for i in range(1, 501))}
    result, summary = q._tool_read_source(None, sources, {"path": "a.py", "start_line": 10, "end_line": 9999})
    assert result["start_line"] == 10
    assert result["end_line"] - result["start_line"] < q.SOURCE_LINES_PER_READ
    assert result["content"].splitlines()[0].strip().startswith("10 | line 10")


def test_run_tool_handles_bad_input():
    text, args, summary = q._run_tool(None, {}, "get_module_details", "{not json")
    assert json.loads(text)["error"] and summary == "invalid arguments"
    text, args, summary = q._run_tool(None, {}, "no_such_tool", "{}")
    assert "unknown tool" in json.loads(text)["error"]


def test_synthesis_messages_flatten_tool_traffic():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "what depends on a.py?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "get_change_impact", "arguments": '{"path": "a.py"}'}}]},
        {"role": "tool", "tool_call_id": "1", "content": '{"direct_dependents": ["b.py"]}'},
    ]
    out = q.synthesis_messages(messages)
    assert all("tool_calls" not in m and m["role"] != "tool" for m in out)
    assert out[0] == {"role": "system", "content": "sys"}
    assert "get_change_impact" in out[-1]["content"] and "b.py" in out[-1]["content"]


def test_repeated_tool_call_is_not_rerun():
    def call(id_, args):
        return {"id": id_, "name": "read_source", "arguments": args}

    sources = {"a.py": "print(1)\n"}
    seen = set()
    msgs, evidence = q.execute_tool_calls(None, sources, [call("1", '{"path": "a.py"}')], seen)
    assert len(evidence) == 1 and "print(1)" in msgs[0]["content"]
    msgs, evidence = q.execute_tool_calls(None, sources, [call("2", '{ "path" : "a.py" }')], seen)
    assert evidence == [] and msgs[0]["content"] == q._REPEAT_NOTE and msgs[0]["tool_call_id"] == "2"


def test_fit_context_trims_oldest_tool_results_only():
    big = "x" * 9000
    messages = [
        {"role": "system", "content": "s"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": big},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "2"}]},
        {"role": "tool", "tool_call_id": "2", "content": big},
    ]
    q.fit_context(messages)
    assert messages[2]["content"] == q._TRIMMED_PLACEHOLDER
    assert messages[4]["content"] == big
