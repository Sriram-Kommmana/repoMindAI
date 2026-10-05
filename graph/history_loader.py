"""Writes repository history and the temporal layer into Neo4j.

The current-state graph (Module/Class/Function, CONTAINS/IMPORTS/CALLS) is
untouched, so every existing query keeps meaning "at HEAD". History lives in
its own labels:

  (:Developer)-[:AUTHORED]->(:Commit)-[:MODIFIED {added, deleted}]->(:Module)
  (:Snapshot)-[:NEXT]->(:Snapshot), (:Snapshot)-[:AT]->(:Commit)
  (:HModule)-[:EXISTS_IN]->(:Snapshot)
  (:HModule)-[:H_IMPORTS {valid_from_idx, valid_to_idx, ...}]->(:HModule)

H_IMPORTS carries valid-time intervals at sampled-snapshot granularity: the
dependency graph at snapshot k is every H_IMPORTS edge with
valid_from_idx <= k and (valid_to_idx IS NULL or valid_to_idx > k).
Modules also get introduced_sha/introduced_at from the commit history.
"""
import json

MAX_FILES_PER_COMMIT_PROPERTY = 300
MAX_MODIFIED_PER_COMMIT = 50     # keeps a 1,500-commit history well inside AuraDB Free's limits
MAX_MODIFIED_TOTAL = 60_000
BATCH_ROWS = 2_000

AT_SNAPSHOT_QUERY = """
MATCH (a:HModule)-[r:H_IMPORTS]->(b:HModule)
WHERE r.valid_from_idx <= $k AND (r.valid_to_idx IS NULL OR r.valid_to_idx > $k)
RETURN a.path AS from_path, b.path AS to_path
"""

MODULES_AT_SNAPSHOT_QUERY = """
MATCH (h:HModule)-[:EXISTS_IN]->(:Snapshot {idx: $k})
RETURN h.path AS path, h.layer_type AS layer_type
"""


def _batched(session, query, rows):
    for i in range(0, len(rows), BATCH_ROWS):
        session.run(query, rows=rows[i:i + BATCH_ROWS]).consume()


def load_history(session, commits: list, snapshots: list, intervals: list, presence: dict,
                 introduced: dict, current_module_paths: set) -> dict:
    """All rows are written with UNWIND in batches. Returns write counts."""
    developers = {}
    for c in commits:
        developers[c["author_id"]] = c["author"]
    _batched(session, "UNWIND $rows AS row MERGE (d:Developer {id: row.id}) SET d.name = row.name",
             [{"id": k, "name": v} for k, v in developers.items()])

    commit_rows = [{
        "hash": c["hash"], "short": c["short"], "idx": c.get("idx"), "date": c["date"],
        "timestamp": c["timestamp"], "message": c["subject"], "body": c.get("body", ""),
        "files": [f["path"] for f in c["files"]][:MAX_FILES_PER_COMMIT_PROPERTY],
        "n_files": c["n_files"], "bulk": c["bulk"], "author_id": c["author_id"],
    } for c in commits]
    _batched(session, """
        UNWIND $rows AS row
        MERGE (c:Commit {hash: row.hash})
        SET c.short = row.short, c.idx = row.idx, c.date = row.date, c.timestamp = row.timestamp,
            c.message = row.message, c.body = row.body, c.files = row.files, c.n_files = row.n_files,
            c.bulk = row.bulk
        WITH c, row
        MATCH (d:Developer {id: row.author_id})
        MERGE (d)-[:AUTHORED]->(c)
    """, commit_rows)

    modified = []
    for c in commits:
        rows = [f for f in c["files"] if f["path"] in current_module_paths][:MAX_MODIFIED_PER_COMMIT]
        modified += [{"hash": c["hash"], "path": f["path"], "added": f["added"], "deleted": f["deleted"]}
                     for f in rows]
    modified = modified[-MAX_MODIFIED_TOTAL:]  # keep the most recent if capped
    _batched(session, """
        UNWIND $rows AS row
        MATCH (c:Commit {hash: row.hash})
        MATCH (m:Module {path: row.path})
        MERGE (c)-[r:MODIFIED]->(m)
        SET r.added = row.added, r.deleted = row.deleted
    """, modified)

    _batched(session, """
        UNWIND $rows AS row
        MATCH (m:Module {path: row.path})
        SET m.introduced_sha = row.sha, m.introduced_at = row.date
    """, [{"path": p, "sha": c["hash"], "date": c["date"]} for p, c in introduced.items()
          if p in current_module_paths])

    snapshot_rows = [{
        "idx": s["idx"], "sha": s["sha"], "short": s["short"], "date": s["date"], "subject": s["subject"],
        "health": s["health"], "health_legacy": s["health_legacy"],
        "weighted_violations": s["weighted_violations"], "n_modules": len(s["modules"]),
        "n_imports": len(s["imports"]), "n_calls": s["n_calls"], "n_violations": len(s["violations"]),
        "violations_json": json.dumps(s["violations"]), "diff_json": json.dumps(s["diff"]),
    } for s in snapshots]
    _batched(session, """
        UNWIND $rows AS row
        MERGE (s:Snapshot {idx: row.idx})
        SET s.sha = row.sha, s.short = row.short, s.date = row.date, s.subject = row.subject,
            s.health = row.health, s.health_legacy = row.health_legacy,
            s.weighted_violations = row.weighted_violations, s.n_modules = row.n_modules,
            s.n_imports = row.n_imports, s.n_calls = row.n_calls, s.n_violations = row.n_violations,
            s.violations_json = row.violations_json, s.diff_json = row.diff_json
        MERGE (c:Commit {hash: row.sha})
        ON CREATE SET c.short = row.short, c.date = row.date, c.message = row.subject, c.merge = true
        MERGE (s)-[:AT]->(c)
    """, snapshot_rows)
    session.run("""
        MATCH (a:Snapshot), (b:Snapshot) WHERE b.idx = a.idx + 1
        MERGE (a)-[:NEXT]->(b)
    """).consume()

    _batched(session, "UNWIND $rows AS row MERGE (h:HModule {path: row.path}) SET h.layer_type = row.layer",
             [{"path": p, "layer": v["layer"]} for p, v in presence.items()])
    _batched(session, """
        UNWIND $rows AS row
        MATCH (h:HModule {path: row.path}), (s:Snapshot {idx: row.idx})
        MERGE (h)-[:EXISTS_IN]->(s)
    """, [{"path": p, "idx": i} for p, v in presence.items() for i in v["snapshots"]])
    _batched(session, """
        UNWIND $rows AS row
        MATCH (a:HModule {path: row.from}), (b:HModule {path: row.to})
        CREATE (a)-[:H_IMPORTS {valid_from_idx: row.valid_from_idx, valid_to_idx: row.valid_to_idx,
                                valid_from_sha: row.valid_from_sha, valid_to_sha: row.valid_to_sha}]->(b)
    """, intervals)

    return {"developers": len(developers), "commits": len(commit_rows), "modified": len(modified),
            "snapshots": len(snapshot_rows), "hmodules": len(presence), "h_imports": len(intervals)}


def graph_at_snapshot(session, k: int) -> dict:
    """The module dependency graph as it was at snapshot k, from the
    temporal layer."""
    modules = session.run(MODULES_AT_SNAPSHOT_QUERY, k=k).data()
    imports = session.run(AT_SNAPSHOT_QUERY, k=k).data()
    return {"modules": modules, "imports": imports}
