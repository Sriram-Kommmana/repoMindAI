import json
from types import SimpleNamespace

import pytest

import cache
import llm
from adr.detect import parse_manifest, rank
from adr.relevance import TfIdf, focus_files, score_evidence, tokens
from agents import adr_graph
from external_imports import modules_using, scan_file, scan_repo
from fixtures.make_history_repo import make_history_repo
from history import mine_commits
from layers import apply_layers
from parser import ast_extractor
from rules.config import load_rules_config
from snapshots import build_snapshots

RULES = load_rules_config()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    repo = make_history_repo(str(tmp_path_factory.mktemp("adr") / "repo"))
    commits = mine_commits(repo)["commits"]
    head = ast_extractor.parse_repo(repo)
    apply_layers(head, RULES)
    by_hash = {c["hash"]: c for c in commits}
    snaps = build_snapshots(repo, RULES, head, 0.0, lambda sha: by_hash[sha])
    decisions = adr_graph.detect(repo, head, commits, snaps)
    return SimpleNamespace(repo=repo, commits=commits, head=head, snaps=snaps, decisions=decisions,
                           usage=scan_repo(repo, [m["path"] for m in head["modules"]]))


# ---------------------------------------------------------------- manifests & scanning

def test_parse_manifests():
    assert parse_manifest("requirements.txt", "Flask==3.0  # web\nredis>=5\n-r base.txt\n\ngit+https://x\n") == {
        "flask": {"dev": False, "ecosystem": "pypi"}, "redis": {"dev": False, "ecosystem": "pypi"}}
    pkg = parse_manifest("package.json", json.dumps({"dependencies": {"Express": "^4"}, "devDependencies": {"jest": "1"}}))
    assert pkg == {"express": {"dev": False, "ecosystem": "npm"}, "jest": {"dev": True, "ecosystem": "npm"}}
    pyproject = ('[project]\nname = "x"\ndependencies = [\n  "fastapi>=0.100",\n  "SQLAlchemy[asyncio]",\n]\n'
                 '[project.optional-dependencies]\ndev = ["pytest"]\n'
                 '[tool.poetry.dependencies]\npython = "^3.10"\nhttpx = "^0.27"\n')
    assert parse_manifest("pyproject.toml", pyproject) == {
        "fastapi": {"dev": False, "ecosystem": "pypi"}, "sqlalchemy": {"dev": False, "ecosystem": "pypi"},
        "pytest": {"dev": True, "ecosystem": "pypi"}, "httpx": {"dev": False, "ecosystem": "pypi"}}
    assert parse_manifest("package.json", "{broken") == {}


def test_external_import_scan():
    assert scan_file("a.py", "import redis, os.path\nfrom jwt import encode\nfrom .local import x\n") == {"redis", "os", "jwt"}
    assert scan_file("a.ts", "import x from 'axios';\nconst y = require(\"@nestjs/core/x\");\nimport './side';") == {"axios", "@nestjs/core"}
    usage = {"auth.py": {"jwt"}, "cache.py": {"redis"}}
    assert modules_using(usage, "pyjwt", "pypi") == ["auth.py"]


# ---------------------------------------------------------------- detection

def test_planted_decisions_are_detected(world):
    subjects = {d["kind"]: d for d in world.decisions}
    adopt = next(d for d in world.decisions if d["kind"] == "dependency_change")
    assert adopt["subject"] == "Adopt redis (cache)" and adopt["short"] == world.commits[2]["short"]
    assert adopt["packages"] == ["redis"] and adopt["manifest"] == "requirements.txt"
    assert subjects["initial_stack"]["short"] == world.commits[0]["short"]
    assert "flask (web framework)" in subjects["initial_stack"]["subject"]
    resolved = subjects["violation_resolved"]
    assert resolved["short"] == world.commits[7]["short"] and "controller.py -> database.py" in resolved["subject"]
    assert [d["date"] for d in world.decisions] == sorted(d["date"] for d in world.decisions)


def test_removal_only_commit(tmp_path):
    from fixtures.make_history_repo import _run
    import subprocess
    repo = str(tmp_path / "r")
    subprocess.run(["git", "init", "-q", repo], check=True)
    (tmp_path / "r" / "requirements.txt").write_text("flask\npytest\n")
    _run(repo, "add", "-A", when=1_700_000_000)
    _run(repo, "commit", "-qm", "init", when=1_700_000_000)
    (tmp_path / "r" / "requirements.txt").write_text("flask\n")
    _run(repo, "commit", "-qam", "drop pytest", when=1_700_086_400)
    from adr.detect import detect_dependency_decisions
    decisions = detect_dependency_decisions(repo, mine_commits(repo)["commits"])
    assert [d["subject"] for d in decisions][-1] == "Drop pytest (testing)"


def test_rank_keeps_one_decision_per_commit_and_kind_and_caps_kinds():
    def d(i, kind, sig, sha=None):
        return {"id": str(i), "sha": sha or f"s{i}", "kind": kind, "significance": sig, "files": ["a"], "date": f"2024-01-{i + 1:02d}"}
    decisions = ([d(i, "infrastructure", 1.0) for i in range(5)] + [d(9, "dependency_change", 2.0, sha="s0"),
                 d(10, "dependency_replace", 1.0, sha="s0")])
    kept = rank(decisions)
    assert sum(1 for k in kept if k["kind"] == "infrastructure") == 3
    assert sorted(k["kind"] for k in kept if k["sha"] == "s0") == ["dependency_change", "infrastructure"]
    assert len(rank(decisions, limit=50, per_kind_cap=50)) == 6


def test_same_commit_manifests_merge():
    from adr.detect import _merge_same_commit
    base = {"sha": "abc", "short": "abc", "date": "2024-01-01", "idx": 0, "kind": "initial_stack", "commit_subject": "init",
            "significance": 1.0, "removed": []}
    merged = _merge_same_commit([
        {**base, "id": "1", "subject": "x", "files": ["web/package.json"], "packages": ["next"], "added": ["next", "lerna"],
         "manifest": "web/package.json"},
        {**base, "id": "2", "subject": "y", "files": ["core/package.json"], "packages": ["lunr"], "added": ["lunr"],
         "manifest": "core/package.json"}])
    assert len(merged) == 1 and merged[0]["manifest"] == "core/package.json, web/package.json"
    assert set(merged[0]["added"]) == {"next", "lerna", "lunr"} and "next (web framework)" in merged[0]["subject"]


# ---------------------------------------------------------------- relevance

def test_tfidf_and_tokens():
    assert tokens("Add RedisCache to src/services/user_service.py") == ["redis", "cache", "services", "user", "service"]
    tf = TfIdf([["redis", "cache"], ["user", "model"], ["redis", "client"]])
    assert TfIdf.cosine(tf.vector(["redis", "cache"]), tf.vector(["redis", "cache"])) == pytest.approx(1.0)
    assert TfIdf.cosine(tf.vector(["redis"]), tf.vector(["user"])) == 0.0


def test_focus_ignores_manifests_and_bots_are_not_evidence():
    from adr.relevance import is_bot
    focus = focus_files({"files": ["package.json", "yarn.lock", "src/app.js"]}, [], [])
    assert focus == {"src/app.js": 1.0}
    assert is_bot({"author": "dependabot[bot]"}) and not is_bot({"author": "Ada Dev"})


def test_tech_names_are_not_flagged_as_files():
    assert adr_graph._TECH_NAME.match("Node.js") and not adr_graph._TECH_NAME.match("src/app.js")


def test_relevance_finds_the_commits_that_build_on_the_decision(world):
    adopt = next(d for d in world.decisions if d["kind"] == "dependency_change")
    focus = focus_files(adopt, modules_using(world.usage, "redis", "pypi"), world.head["imports"])
    assert focus["cache.py"] == 1.0 and focus["service.py"] == 0.5
    scored = score_evidence(adopt, world.commits, focus)
    picked = [e["commit"]["subject"] for e in scored["evidence"]]
    assert picked[0] == "wip" and scored["evidence"][0]["decision_commit"]
    for related in ("add cache", "use cache in service", "cache ttl"):
        assert related in picked
    assert "Add order model" not in picked and "Rename utils to helpers" not in picked
    assert all(e["relevance"] >= 0.35 for e in scored["evidence"])


# ---------------------------------------------------------------- the agent

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(llm, "describe", lambda purpose: {"provider": "fake", "model": "m", "keys": 1, "parallelism": 1})


def _draft(commits, cite, extra_text=""):
    return json.dumps({
        "title": "Use Redis for caching", "context": "Orders were saved on every request." + extra_text,
        "decision": "Add redis and a cache module.", "consequences": "The service now remembers orders.",
        "alternatives": "", "inference": "Likely added to reduce repeated work; the commit message doesn't say.",
        "evidence": [{"commit": c, "shows": "relevant"} for c in cite], "confidence": 0.9, "confidence_reason": "ok"})


def test_validator_rejects_invented_commits_then_accepts_the_fix(world, isolated, monkeypatch):
    adopt = next(d for d in world.decisions if d["kind"] == "dependency_change")
    wip, cache_commit = world.commits[2]["short"], world.commits[3]["short"]
    replies = [_draft(world.commits, [wip, "deadbee"], " See [deadbee] and config/settings.py."),
               _draft(world.commits, [wip, cache_commit])]
    prompts = []

    def chat(messages, **kwargs):
        prompts.append(messages)
        return SimpleNamespace(content=replies[len(prompts) - 1])
    monkeypatch.setattr(adr_graph.llm, "chat", chat)

    adr, warnings, hit = adr_graph.reconstruct_one("local:fx", "head1", world.repo, RULES, world.head, world.commits,
                                                    adopt, world.usage)
    assert len(prompts) == 2 and not hit
    assert "deadbee" in prompts[1][-1]["content"] and "config/settings.py" in prompts[1][-1]["content"]
    assert [e["short"] for e in adr["evidence"]] == [wip, cache_commit]
    assert adr["status"] == "Reconstructed (inferred)"
    assert adr["confidence"] <= adr["validation"]["cap"] < 0.9          # capped by evidence quality
    assert adr["confidence_label"] in ("Low", "Medium", "High")
    assert "cache.py" in adr["affected_modules"]
    assert "redis" in prompts[0][1]["content"] and "+redis==5.0" in prompts[0][1]["content"]   # diff reached the prompt

    again, _, hit = adr_graph.reconstruct_one("local:fx", "head1", world.repo, RULES, world.head, world.commits,
                                               adopt, world.usage)
    assert hit and again == adr and len(prompts) == 2


def test_failed_synthesis_falls_back_to_evidence_only(world, isolated, monkeypatch):
    adopt = next(d for d in world.decisions if d["kind"] == "dependency_change")
    monkeypatch.setattr(adr_graph.llm, "chat", lambda messages, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    adr, warnings, hit = adr_graph.reconstruct_one("local:fx", "head2", world.repo, RULES, world.head, world.commits,
                                                    adopt, world.usage)
    assert adr["fallback"] and adr["confidence_label"] == "Low" and adr["evidence"]
    assert warnings and "could not be synthesized" in warnings[0]


def test_store_decisions_in_neo4j(neo4j, world, isolated, monkeypatch):
    from graph import loader
    from graph.history_loader import load_history
    from history import introduced_at
    from snapshots import import_intervals, module_presence

    loader.load_graph(world.head)
    adopt = next(d for d in world.decisions if d["kind"] == "dependency_change")
    monkeypatch.setattr(adr_graph.llm, "chat", lambda messages, **kw: SimpleNamespace(
        content=_draft(world.commits, [world.commits[2]["short"], world.commits[3]["short"]])))
    adr, _, _ = adr_graph.reconstruct_one("local:fx", "head3", world.repo, RULES, world.head, world.commits, adopt, world.usage)
    driver = loader._get_driver()
    try:
        with driver.session() as session:
            load_history(session, world.commits, world.snaps, import_intervals(world.snaps),
                         module_presence(world.snaps), introduced_at(world.commits), {m["path"] for m in world.head["modules"]})
            adr_graph.store_decisions(session, [adr])
            row = session.run("MATCH (d:Decision {id: $id})-[r:EVIDENCED_BY]->(c:Commit) "
                              "RETURN count(c) AS n, d.status AS status", id=adr["id"]).single()
            assert row["n"] == 2 and row["status"] == "Reconstructed (inferred)"
            affects = session.run("MATCH (:Decision {id: $id})-[:AFFECTS]->(m:Module) RETURN collect(m.path) AS p",
                                  id=adr["id"]).single()["p"]
            assert "cache.py" in affects
    finally:
        driver.close()
