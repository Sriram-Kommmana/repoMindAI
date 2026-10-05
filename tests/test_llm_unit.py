"""llm.py behaviour with fake clients — no network, no API budget."""
from types import SimpleNamespace

import pytest

import llm


def _response(content="ok", finish_reason="stop", tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
                           usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


class FakeClient:
    def __init__(self, name, script):
        self.name = name
        self.script = script  # shared list of (client_name, params) calls, plus a behaviour fn
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.script["calls"].append((self.name, params))
        return self.script["behaviour"](self.name, params, len(self.script["calls"]))


@pytest.fixture
def fake(monkeypatch):
    llm.reset_for_tests()
    script = {"calls": [], "behaviour": lambda name, params, n: _response()}
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))

    def build(name):
        if name == "groq":
            return llm._Provider("groq", "m", [FakeClient("g0", script), FakeClient("g1", script)], parallelism=2)
        return llm._Provider("bedrock", "m", [FakeClient("b0", script)], parallelism=4)

    monkeypatch.setattr(llm, "_build_provider", build)
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    yield SimpleNamespace(script=script, sleeps=sleeps)
    llm.reset_for_tests()


MSG = [{"role": "user", "content": "hi"}]


def test_rotating_moves_to_other_key_after_rate_limit(fake):
    def behaviour(name, params, n):
        if n == 1:
            raise Exception("Error code: 429 - rate_limit_exceeded. Please try again in 2.5s.")
        return _response()
    fake.script["behaviour"] = behaviour
    result = llm.chat(MSG, purpose="qa", max_tokens=100)
    assert result.content == "ok"
    first, second = fake.script["calls"][0][0], fake.script["calls"][1][0]
    assert first != second            # switched keys instead of waiting
    assert fake.sleeps == []          # the other key was free, so no wait at all


def test_pinned_slot_waits_out_its_own_cooldown(fake):
    def behaviour(name, params, n):
        if n == 1:
            raise Exception("Error code: 429 - rate_limit_exceeded. Please try again in 2.5s.")
        return _response()
    fake.script["behaviour"] = behaviour
    llm.chat(MSG, purpose="docs", max_tokens=100, key_slot=1)
    assert [c[0] for c in fake.script["calls"]] == ["g1", "g1"]
    assert fake.sleeps and 3.0 <= fake.sleeps[0] <= 3.6   # parsed 2.5s + 1s margin


def test_request_too_large_is_not_retried(fake):
    def behaviour(name, params, n):
        raise Exception("Error code: 413 - rate_limit_exceeded: Request too large, reduce your message size")
    fake.script["behaviour"] = behaviour
    with pytest.raises(Exception, match="Request too large"):
        llm.chat(MSG, purpose="qa", max_tokens=100)
    assert len(fake.script["calls"]) == 1


def test_gives_up_after_max_retries(fake):
    fake.script["behaviour"] = lambda name, params, n: (_ for _ in ()).throw(Exception("Error code: 503 - unavailable"))
    with pytest.raises(Exception, match="503"):
        llm.chat(MSG, purpose="qa", max_tokens=100)
    assert len(fake.script["calls"]) == llm.MAX_RETRIES + 1


def test_reasoning_is_stripped_and_length_retry_doubles_budget(fake):
    def behaviour(name, params, n):
        if n == 1:
            return _response(content="", finish_reason="length")
        return _response(content="<reasoning>thinking...</reasoning>Final answer")
    fake.script["behaviour"] = behaviour
    result = llm.chat(MSG, purpose="qa", max_tokens=300)
    assert result.content == "Final answer"
    assert [c[1]["max_tokens"] for c in fake.script["calls"]] == [300, 600]


def test_json_mode_falls_back_when_rejected(fake):
    def behaviour(name, params, n):
        if "response_format" in params:
            raise Exception("Error code: 400 - response_format json_object is not supported")
        return _response(content='Here: {"a": 1}')
    fake.script["behaviour"] = behaviour
    result = llm.chat(MSG, purpose="adr", max_tokens=100, json_mode=True)
    assert llm.parse_json(result.content) == {"a": 1}
    assert any("JSON mode" in n for n in llm.notices())


def test_bedrock_tool_rejection_falls_back_to_groq(fake, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")

    def behaviour(name, params, n):
        if name == "b0" and "tools" in params:
            raise Exception("Error code: 400 - tools are not supported for this model")
        return _response()
    fake.script["behaviour"] = behaviour
    result = llm.chat(MSG, purpose="qa", max_tokens=100, tools=[{"type": "function"}])
    assert result.provider == "groq"
    assert llm.provider_name("qa", needs_tools=True) == "groq"
    assert llm.provider_name("docs") == "bedrock"   # tool-free purposes stay on Bedrock


def test_provider_selection(monkeypatch):
    llm.reset_for_tests()
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_QA", raising=False)
    monkeypatch.setenv("BEDROCK_API_KEY", "x")
    assert llm.provider_name("qa") == "bedrock"
    monkeypatch.setenv("LLM_PROVIDER_QA", "groq")
    assert llm.provider_name("qa") == "groq"
    assert llm.provider_name("docs") == "bedrock"
    monkeypatch.delenv("BEDROCK_API_KEY")
    monkeypatch.delenv("LLM_PROVIDER_QA")
    assert llm.provider_name("docs") == "groq"


def test_usage_is_counted(fake):
    llm.chat(MSG, purpose="docs", max_tokens=100)
    llm.chat(MSG, purpose="docs", max_tokens=100)
    assert llm.usage_snapshot()["docs"] == {"calls": 2, "failures": 0, "prompt_tokens": 20, "completion_tokens": 10}


@pytest.mark.parametrize("message, seconds", [
    ("Please try again in 6.07s.", 6.07),
    ("Please try again in 532.5ms. Need more tokens?", 0.5325),
    ("Please try again in 1m30.5s.", 90.5),
    ("rate limited, no hint", llm.RATE_LIMIT_FALLBACK_SECONDS),
])
def test_extract_retry_after(message, seconds):
    assert llm.extract_retry_after(message) == pytest.approx(seconds)


def test_parse_json_tolerates_fences():
    assert llm.parse_json('```json\n{"x": [1, 2]}\n```') == {"x": [1, 2]}
