import json
from types import SimpleNamespace

import pytest

import cache
import llm
from agents import drift_graph
from conftest import TEST_REPO
from layers import apply_layers
from parser import ast_extractor
from rules.config import load_rules_config

RULES = load_rules_config()


def _v(rule, sev, caller_mod, callee_mod, edge="imports", caller_name=None, callee_name=None):
    return {"rule_name": rule, "severity": sev, "edge": edge, "caller_module": caller_mod, "caller_class": None,
            "caller_name": caller_name, "callee_module": callee_mod, "callee_class": None, "callee_name": callee_name}


def test_prioritize_is_deterministic_and_explainable():
    data = {"imports": [{"from": f"m{i}.py", "to": "db/core.py"} for i in range(6)] + [{"from": "x.py", "to": "db/minor.py"}]}
    violations = [
        _v("no-controller-imports-db", 2, "api/a.py", "db/core.py"),
        _v("no-controller-imports-db", 2, "api/b.py", "db/core.py"),
        _v("no-db-imports-controller", 2, "db/minor.py", "api/a.py"),
    ]
    snapshots = [{"idx": 0, "short": "aaa", "date": "d0", "violation_keys": []},
                 {"idx": 1, "short": "bbb", "date": "d1",
                  "violation_keys": [list(drift_graph.violation_key(v)) for v in violations[:2]]},
                 {"idx": 2, "short": "ccc", "date": "d2",
                  "violation_keys": [list(drift_graph.violation_key(v)) for v in violations]}]
    out = drift_graph._prioritize({"data": data, "violations": violations, "snapshots": snapshots})
    groups = out["groups"]
    assert [g["rule"] for g in groups] == ["no-controller-imports-db", "no-db-imports-controller"]
    top = groups[0]
    assert top["rank"] == 1 and top["priority"] == "High" and top["occurrences"] == 2
    assert top["max_fan_in"] == 6 and top["introduced"]["short"] == "bbb"
    assert groups[1]["priority"] in ("Medium", "Low")
    assert out == drift_graph._prioritize({"data": data, "violations": violations, "snapshots": snapshots})


@pytest.fixture
def test_repo_state(neo4j, tmp_path, monkeypatch):
    from graph import loader
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(llm, "describe", lambda purpose: {"provider": "fake", "model": "m", "keys": 1, "parallelism": 1})
    data = ast_extractor.parse_repo(TEST_REPO)
    apply_layers(data, RULES)
    loader.load_graph(data)
    return {"repo_url": "local:test_repo", "head_sha": "abc123", "repo_path": TEST_REPO, "rules": RULES,
            "data": data, "snapshots": [], "warnings": []}


def _fake_chat(calls, fail=False):
    def chat(messages, **kwargs):
        calls.append(messages[1]["content"])
        if fail:
            raise RuntimeError("provider down")
        return SimpleNamespace(content=json.dumps({
            "summary": "controller.py reaches database.py directly.",
            "why_it_matters": "It couples HTTP handling to storage.",
            "suggested_fix": "Call service.process_order instead.", "caveat": ""}))
    return chat


def test_full_graph_explains_and_caches(test_repo_state, monkeypatch):
    calls = []
    monkeypatch.setattr(drift_graph.llm, "chat", _fake_chat(calls))
    result = drift_graph.DRIFT_GRAPH.invoke(dict(test_repo_state))["result"]
    groups = result["groups"]
    assert [g["rule"] for g in groups] == ["no-controller-to-db", "no-controller-imports-db"]   # severity 3 first
    assert all(g["explanation"]["suggested_fix"] for g in groups)
    assert len(calls) == 2 and result["warnings"] == []
    call_group = groups[0]
    assert any("save_record" in s for s in call_group["explanation"]["snippets"])
    assert "controller.py::handle_request_direct" in calls[0]            # the facts reach the prompt

    again = drift_graph.DRIFT_GRAPH.invoke(dict(test_repo_state))["result"]
    assert len(calls) == 2 and again["llm_calls_saved"] == 2                # warm cache: no new calls
    assert again["groups"] == groups


def test_llm_failure_degrades_to_facts_and_is_not_cached(test_repo_state, monkeypatch):
    calls = []
    monkeypatch.setattr(drift_graph.llm, "chat", _fake_chat(calls, fail=True))
    result = drift_graph.DRIFT_GRAPH.invoke(dict(test_repo_state))["result"]
    assert all(g["explanation"]["fallback"] for g in result["groups"])
    assert len(result["warnings"]) == 2
    drift_graph.DRIFT_GRAPH.invoke(dict(test_repo_state))
    assert len(calls) == 4   # failures were not cached


def test_stale_graph_aborts(test_repo_state, monkeypatch):
    monkeypatch.setattr(drift_graph.llm, "chat", _fake_chat([]))
    state = dict(test_repo_state)
    state["data"] = {**state["data"], "imports": [], "calls": []}   # no longer matches the graph
    with pytest.raises(RuntimeError, match="no longer matches"):
        drift_graph.DRIFT_GRAPH.invoke(state)
