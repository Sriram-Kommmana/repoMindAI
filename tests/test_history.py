import pytest

from fixtures.make_history_repo import make_history_repo
from history import contributors, introduced_at, mine_commits
from layers import apply_layers
from parser import ast_extractor
from rules.config import load_rules_config
from snapshots import build_snapshots, import_intervals, module_presence, pick_snapshot_commits

RULES = load_rules_config()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return make_history_repo(str(tmp_path_factory.mktemp("history") / "repo"))


@pytest.fixture(scope="module")
def mined(repo):
    return mine_commits(repo)


@pytest.fixture(scope="module")
def snapshots(repo, mined):
    head = ast_extractor.parse_repo(repo)
    apply_layers(head, RULES)
    by_hash = {c["hash"]: c for c in mined["commits"]}
    return build_snapshots(repo, RULES, head, 0.0, lambda sha: by_hash[sha])


def test_commits_are_mined_oldest_first(mined):
    commits = mined["commits"]
    assert not mined["truncated"]
    assert [c["subject"] for c in commits] == [
        "Initial layered app", "Add order model", "wip", "add cache", "use cache in service", "cache ttl",
        "Rename utils to helpers", "Route controller through the service layer again"]
    assert [c["idx"] for c in commits] == list(range(8))
    assert all(c["author"] == "Ada Dev" for c in commits)
    assert "ada@example.com" not in str(commits)  # emails are never kept
    wip = commits[2]
    assert {f["path"] for f in wip["files"]} == {"controller.py", "requirements.txt"}


def test_rename_is_detected(mined):
    rename = mined["commits"][6]["files"]
    assert rename == [{"added": 0, "deleted": 0, "old_path": "utils.py", "path": "helpers.py"}]


def test_truncation(repo):
    capped = mine_commits(repo, max_commits=3)
    assert capped["truncated"] and [c["subject"] for c in capped["commits"]][-1].startswith("Route controller")


def test_introduced_and_contributors(mined):
    first = introduced_at(mined["commits"])
    assert first["database.py"]["idx"] == 0
    assert first["cache.py"]["idx"] == 3
    assert first["helpers.py"]["idx"] == 6
    assert contributors(mined["commits"]) == [{"name": "Ada Dev", "commits": 8, "lines": pytest.approx(
        sum(f["added"] + f["deleted"] for c in mined["commits"] for f in c["files"]))}]


def test_snapshot_sampling(repo):
    assert len(pick_snapshot_commits(repo, 12)) == 8
    picked = pick_snapshot_commits(repo, 4)
    assert len(picked) == 4 and picked[-1] == pick_snapshot_commits(repo, 12)[-1]


def test_snapshots_skip_commits_that_touch_no_source(repo, mined):
    from snapshots import source_change_filter
    commits = [dict(c) for c in mined["commits"]]
    commits[3] = {**commits[3], "files": [{"path": "README.md", "added": 1, "deleted": 0}]}
    picked = pick_snapshot_commits(repo, 12, source_change_filter(commits))
    assert commits[3]["hash"] not in picked and len(picked) == 7
    assert picked[-1] == mined["commits"][-1]["hash"]


def test_drift_curve(snapshots):
    assert [s["idx"] for s in snapshots] == list(range(8))
    counts = [len(s["violations"]) for s in snapshots]
    assert counts == [0, 0, 2, 2, 2, 2, 2, 0]   # the calls rule and the imports rule both fire
    health = [s["health"] for s in snapshots]
    assert health[0] == health[1] == health[7] == 100.0
    assert all(h < 100 for h in health[2:7])
    assert snapshots[2]["diff"]["new_violations"] and snapshots[7]["diff"]["resolved_violations"]
    assert snapshots[3]["diff"]["added_modules"] == ["cache.py"]
    assert snapshots[6]["diff"]["added_modules"] == ["helpers.py"]
    assert snapshots[6]["diff"]["removed_modules"] == ["utils.py"]


def test_import_intervals(snapshots):
    intervals = {(i["from"], i["to"], i["valid_from_idx"]): i for i in import_intervals(snapshots)}
    violating = intervals[("controller.py", "database.py", 2)]
    assert violating["valid_to_idx"] == 7
    assert intervals[("controller.py", "service.py", 0)]["valid_to_idx"] is None
    assert intervals[("service.py", "cache.py", 4)]["valid_to_idx"] is None


def test_module_presence(snapshots):
    presence = module_presence(snapshots)
    assert presence["utils.py"]["snapshots"] == [0, 1, 2, 3, 4, 5]
    assert presence["controller.py"]["layer"] == "controller"


def test_temporal_graph_in_neo4j(neo4j, repo, mined, snapshots):
    from graph import loader
    from graph.history_loader import graph_at_snapshot, load_history

    head = ast_extractor.parse_repo(repo)
    apply_layers(head, RULES)
    loader.load_graph(head)
    driver = loader._get_driver()
    try:
        with driver.session() as session:
            written = load_history(session, mined["commits"], snapshots, import_intervals(snapshots),
                                   module_presence(snapshots), introduced_at(mined["commits"]),
                                   {m["path"] for m in head["modules"]})
            assert written["commits"] == 8 and written["snapshots"] == 8 and written["developers"] == 1

            def edges_at(k):
                return {(e["from_path"], e["to_path"]) for e in graph_at_snapshot(session, k)["imports"]}
            assert ("controller.py", "database.py") in edges_at(3)
            assert ("controller.py", "database.py") not in edges_at(7)
            assert ("controller.py", "database.py") not in edges_at(1)

            row = session.run("MATCH (m:Module {path: 'cache.py'}) RETURN m.introduced_at AS at").single()
            assert row["at"].startswith("2023-11-17")
            n = session.run("MATCH (:Commit)-[:MODIFIED]->(:Module {path: 'controller.py'}) RETURN count(*) AS n").single()["n"]
            assert n == 3   # initial, wip, fix
            chain = session.run("MATCH p = (:Snapshot {idx: 0})-[:NEXT*]->(:Snapshot {idx: 7}) RETURN length(p) AS n").single()
            assert chain["n"] == 7
    finally:
        driver.close()
