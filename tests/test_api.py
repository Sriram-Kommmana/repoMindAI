"""End-to-end API tests: the real pipeline (clone, parse, graph, rules,
history, snapshots) on a local scripted repository, with a fake LLM so no
network or API budget is used."""
import json
import re
from types import SimpleNamespace

import pytest

import cache
import llm
import workspace
from fixtures.make_history_repo import make_history_repo

ADR_DECISION = re.compile(r"\[([0-9a-f]{7})\][^\n]*DECISION COMMIT")


def fake_chat(messages, *, purpose, tools=None, **kwargs):
    user = messages[-1]["content"]
    if purpose == "docs":
        if "GROUP SUMMARIES" in user:
            return _r("## Overview\nA small layered app.\n\n## Architecture & Layers\nController, service, database.")
        return _r("#### file\nDescribed.")
    if purpose == "drift":
        return _r(json.dumps({"summary": "s", "why_it_matters": "w", "suggested_fix": "f", "caveat": ""}))
    if purpose == "adr":
        short = ADR_DECISION.search(messages[1]["content"]).group(1)
        return _r(json.dumps({"title": "Reconstructed", "context": "c", "decision": "d", "consequences": "",
                              "alternatives": "", "evidence": [{"commit": short, "shows": "the change"}],
                              "inference": "Inferred reason.", "confidence": 0.6, "confidence_reason": "ok"}))
    if purpose == "qa":
        if tools and not any(m["role"] == "tool" for m in messages):
            tc = SimpleNamespace(id="t1", function=SimpleNamespace(name="get_repository_overview", arguments="{}"))
            return _r("", [tc])
        return _r("Three layers. **Confidence:** High — from the overview.")
    raise AssertionError(f"unexpected purpose {purpose}")


def _r(content, tool_calls=()):
    return llm.ChatResult(content=content, tool_calls=list(tool_calls), finish_reason="stop", provider="fake")


@pytest.fixture(scope="module")
def client(neo4j, tmp_path_factory):
    from fastapi.testclient import TestClient
    import server

    mp = pytest.MonkeyPatch()
    mp.setenv("REPOMIND_ALLOW_LOCAL_REPOS", "1")
    mp.setattr(cache, "CACHE_DIR", str(tmp_path_factory.mktemp("cache")))
    mp.setattr(llm, "chat", fake_chat)
    mp.setattr(llm, "describe", lambda purpose: {"provider": "fake", "model": "m", "keys": 1, "parallelism": 1})
    mp.setattr(llm, "parallelism", lambda purpose: 1)
    repo = make_history_repo(str(tmp_path_factory.mktemp("api") / "repo"))
    with TestClient(server.app) as c:
        c.repo = repo
        yield c
    mp.undo()


@pytest.fixture(scope="module")
def analysis(client):
    resp = client.post("/analyze", json={"repo_url": client.repo})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.parametrize("url", ["--upload-pack=calc.exe", "file:///etc/passwd", "C:\\Windows", "ftp://x/y", "https://"])
def test_bad_urls_are_rejected(client, monkeypatch, url):
    monkeypatch.delenv("REPOMIND_ALLOW_LOCAL_REPOS")
    resp = client.post("/analyze", json={"repo_url": url})
    assert resp.status_code == 400 and "https://" in resp.json()["detail"]


def test_analyze(analysis):
    assert analysis["files_parsed"] == 6 and analysis["violations"] == []
    assert analysis["health_score"] == 100.0
    h = analysis["history"]
    assert h["commits"] == 8 and len(h["snapshots"]) == 8 and not h["truncated"]
    assert [s["violations"] for s in h["snapshots"]] == [0, 0, 2, 2, 2, 2, 2, 0]
    assert h["contributors"][0]["name"] == "Ada Dev"
    assert set(analysis["timings"]) >= {"clone", "parse", "graph_load", "rules", "history_mining", "snapshots"}


def test_lazy_sections(client, analysis):
    ref = {"analysis_id": analysis["analysis_id"]}
    assert client.post("/violations/explain", json=ref).json()["groups"] == []

    adrs = client.post("/adrs", json=ref).json()
    assert adrs["detected"] >= 2 and all(a["status"] == "Reconstructed (inferred)" for a in adrs["decisions"])
    assert all(a["evidence"][0]["decision_commit"] for a in adrs["decisions"])

    docs = client.post("/documentation", json=ref).json()
    assert docs["documentation_error"] is None and "## Known Architecture Issues" in docs["documentation"]
    assert docs["cached"] is False
    assert client.post("/documentation", json=ref).json()["cached"] is True

    snap = client.get(f"/history/snapshot/2?analysis_id={analysis['analysis_id']}").json()
    assert snap["health"] < 100 and "flowchart LR" in snap["mermaid_diagram"]
    assert client.get(f"/history/snapshot/99?analysis_id={analysis['analysis_id']}").status_code == 404


def test_ask(client, analysis):
    answer = client.post("/ask", json={"question": "How is this repository organized?"}).json()
    assert answer["intents"] == ["structural"]
    assert [e["tool"] for e in answer["evidence"]] == ["get_repository_overview"]
    assert "Confidence" in answer["answer"]


def test_stale_and_busy(client, analysis):
    assert client.post("/documentation", json={"analysis_id": "nope"}).status_code == 409
    assert client.get("/history/snapshot/0?analysis_id=nope").status_code == 409
    assert workspace._analysis_lock.acquire(blocking=False)
    try:
        assert client.post("/analyze", json={"repo_url": client.repo}).status_code == 409
    finally:
        workspace._analysis_lock.release()


def test_invalid_rules(client):
    resp = client.post("/analyze", json={"repo_url": client.repo, "rules_yaml": "rules: [1, 2]"})
    assert resp.status_code == 400 and resp.json()["detail"].startswith("Invalid rules")


def test_default_rules_and_index(client):
    assert client.get("/rules/default").text.startswith("# RepoMind AI architecture rules")
    page = client.get("/")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
