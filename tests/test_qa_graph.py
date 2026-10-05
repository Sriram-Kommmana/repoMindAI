import json
from types import SimpleNamespace

import pytest

import llm
import qa_engine as qa
from agents import qa_graph
from fixtures.make_history_repo import make_history_repo
from history import introduced_at, mine_commits
from layers import apply_layers
from parser import ast_extractor
from rules.config import load_rules_config
from snapshots import build_snapshots, import_intervals, module_presence

RULES = load_rules_config()


@pytest.mark.parametrize("question, intents", [
    ("Give me an overview of how this repository is organized.", ["structural"]),
    ("What does handle_request in controller.py do?", ["structural"]),
    ("What depends on the cache module?", ["structural"]),
    ("Are there any architecture violations?", ["architectural"]),
    ("Who changed database.py last?", ["structural", "historical"]),
    ("Why was redis introduced?", ["historical", "rationale"]),
    ("How has the architecture health changed over time?", ["architectural", "historical"]),
    ("Why did they switch to joi instead of @hapi/joi?", ["rationale"]),
    ("Does any controller talk to the database directly?", ["architectural"]),
])
def test_route_intents(question, intents):
    assert qa_graph.route_intents(question) == intents


def test_tools_follow_intents():
    names = lambda intents: {t["function"]["name"] for t in qa_graph.tools_for(intents)}
    assert {"get_repository_overview", "search_entities"} <= names(["rationale"])
    assert "explain_decision" in names(["rationale"]) and "explain_decision" not in names(["structural"])
    assert "get_file_history" in names(["historical"]) and "get_file_history" not in names(["structural"])
    assert len(qa_graph.tools_for(["structural"])) < len(qa.TOOLS)


@pytest.fixture(scope="module")
def history_graph(neo4j, tmp_path_factory):
    from graph import loader
    from graph.history_loader import load_history

    repo = make_history_repo(str(tmp_path_factory.mktemp("qa") / "repo"))
    commits = mine_commits(repo)["commits"]
    head = ast_extractor.parse_repo(repo)
    apply_layers(head, RULES)
    by_hash = {c["hash"]: c for c in commits}
    snaps = build_snapshots(repo, RULES, head, 0.0, lambda sha: by_hash[sha])
    loader.load_graph(head)
    driver = loader._get_driver()
    with driver.session() as session:
        load_history(session, commits, snaps, import_intervals(snaps), module_presence(snaps),
                     introduced_at(commits), {m["path"] for m in head["modules"]})
    qa.set_repo_context("local:history-fixture", repo, [m["path"] for m in head["modules"]], RULES)
    yield SimpleNamespace(driver=driver, commits=commits, repo=repo)
    driver.close()


def test_history_tools(history_graph):
    with history_graph.driver.session() as s:
        result, summary = qa._tool_file_history(s, {}, {"path": "controller.py"})
        assert result["commits_touching"] == 3 and result["authors"] == [{"name": "Ada Dev", "commits": 3}]
        assert result["recent_commits"][0]["message"].startswith("Route controller")
        assert result["introduced"]["commit"] == history_graph.commits[0]["short"]

        gone, _ = qa._tool_file_history(s, {}, {"path": "utils.py"})   # deleted by the rename
        assert gone["commits_touching"] == 1

        wip = history_graph.commits[2]
        commit, _ = qa._tool_get_commit(s, {}, {"commit": wip["hash"][:8]})
        assert commit["message"] == "wip" and set(commit["files"]) == {"controller.py", "requirements.txt"}

        trend, summary = qa._tool_drift_trend(s, {}, {})
        assert [r["violations"] for r in trend["snapshots"]] == [0, 0, 2, 2, 2, 2, 2, 0]
        assert trend["largest_drop"]["to"] == wip["short"]

        diff, _ = qa._tool_compare_snapshots(s, {}, {"from_snapshot": 1, "to_snapshot": 2})
        assert "controller.py -> database.py" in diff["dependencies_added"]
        assert len(diff["violations_introduced"]) == 2

        people, _ = qa._tool_contributors(s, {}, {})
        assert people["contributors"][0]["commits"] == 8


def test_decision_tools_need_an_analysis(history_graph):
    qa.attach_analysis(None)
    with history_graph.driver.session() as s:
        result, summary = qa._tool_list_decisions(s, {}, {})
        assert "analysis" in result["error"] and summary == "no analysis"


def test_full_qa_graph_with_a_fake_model(history_graph, monkeypatch):
    calls = []

    def chat(messages, tools=None, **kwargs):
        calls.append({"tools": [t["function"]["name"] for t in tools or []], "messages": messages})
        if len(calls) == 1:
            tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="get_file_history",
                                                                     arguments=json.dumps({"path": "controller.py"})))
            return SimpleNamespace(content="", tool_calls=[tc])
        return SimpleNamespace(content="It was last changed in `f496ae3` by Ada Dev.", tool_calls=[])

    monkeypatch.setattr(qa_graph.llm, "chat", chat)
    monkeypatch.setattr(llm, "describe", lambda purpose: {"provider": "fake", "model": "m", "keys": 1, "parallelism": 1})
    result = qa_graph.run_qa("Who changed controller.py last?", [])
    assert result["intents"] == ["structural", "historical"]
    assert "get_file_history" in calls[0]["tools"] and "explain_decision" not in calls[0]["tools"]
    assert [e["tool"] for e in result["evidence"]] == ["get_file_history"]
    assert '"commits_touching": 3' in calls[1]["messages"][-1]["content"]   # the tool result reached the model
    assert "**Confidence:** Medium" in result["answer"]                      # added when the model omits it


def test_tool_budget_ends_in_synthesis(history_graph, monkeypatch):
    calls = []

    def chat(messages, tools=None, **kwargs):
        calls.append(tools)
        if tools:
            n = len(calls)
            tc = SimpleNamespace(id=f"c{n}", function=SimpleNamespace(name="get_contributors",
                                                                        arguments=json.dumps({"path": f"x{n}.py"})))
            return SimpleNamespace(content="", tool_calls=[tc])
        return SimpleNamespace(content="Best effort answer.\n\n**Confidence:** Low — ran out of lookups.", tool_calls=[])

    monkeypatch.setattr(qa_graph.llm, "chat", chat)
    monkeypatch.setattr(llm, "describe", lambda purpose: {"provider": "fake", "model": "m", "keys": 1, "parallelism": 1})
    result = qa_graph.run_qa("Who works on everything?", [])
    assert len(result["evidence"]) == qa.MAX_TOOL_ROUNDS
    assert calls[-1] is None                       # the final call offered no tools at all
    assert result["answer"].startswith("Best effort answer.")
