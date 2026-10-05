"""Node labels and relationship types of the current-state graph, plus the
indexes every label relies on.

These labels always describe HEAD. History (commits, snapshots, valid-time
intervals) lives in separate labels — see graph/history_loader.py.
"""

# Module also carries a `layer_type` property, assigned from the rules'
# `layers` patterns (see layers.py); None when no pattern matches.
MODULE = "Module"
CLASS = "Class"
FUNCTION = "Function"

CONTAINS = "CONTAINS"
CALLS = "CALLS"
IMPORTS = "IMPORTS"

# Without these, every MERGE scans its whole label, so loading a large repo
# is quadratic in node count.
_INDEXES = [
    "CREATE INDEX module_path IF NOT EXISTS FOR (m:Module) ON (m.path)",
    "CREATE INDEX class_key IF NOT EXISTS FOR (c:Class) ON (c.module_path, c.name)",
    "CREATE INDEX function_key IF NOT EXISTS FOR (f:Function) ON (f.module_path, f.name)",
    "CREATE INDEX commit_hash IF NOT EXISTS FOR (c:Commit) ON (c.hash)",
    "CREATE INDEX snapshot_idx IF NOT EXISTS FOR (s:Snapshot) ON (s.idx)",
    "CREATE INDEX hmodule_path IF NOT EXISTS FOR (h:HModule) ON (h.path)",
]


def ensure_schema(session) -> None:
    for statement in _INDEXES:
        session.run(statement).consume()
