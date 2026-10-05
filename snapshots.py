"""Sampled historical snapshots: the architecture (modules, import edges,
rule violations, health) at N commits spread evenly along the first-parent
history, HEAD included. This is what the drift curve and the temporal graph
are built from.

Snapshots are materialized from git objects (`git ls-tree` + one
`git cat-file --batch` process) into a scratch directory, never by checking
out the workspace, whose HEAD files stay intact for source reading.
"""
import os
import shutil
import subprocess
import tempfile
import time

from history import git
from layers import apply_layers
from parser import ast_extractor
from rules.evaluate import evaluate, format_violation, violation_key
from rules.scoring import compute_health, compute_health_normalized

HISTORY_SNAPSHOTS = int(os.environ.get("HISTORY_SNAPSHOTS", 12))
MIN_SNAPSHOTS = 4
SNAPSHOT_TIME_BUDGET_SECONDS = 90  # used only to size N, never to stop early
MAX_BLOB_BYTES = 1_000_000
MAX_PATH_CHARS = 240
SOURCE_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx")
# Must match the parsers' own walk exactly, or the HEAD snapshot (which reuses
# the parser's output) would differ from history for reasons that aren't real.
_SKIP_DIRS = ast_extractor._SKIP_DIRS


def pick_snapshot_commits(repo_path: str, n: int, eligible=None) -> list:
    """Evenly spaced first-parent commits, oldest first, always ending at HEAD.

    eligible(sha, is_merge) filters candidates: real histories are often
    dominated by dependency-bump commits that never touch code, and spacing
    snapshots over those wastes most of them on identical architecture."""
    lines = git(repo_path, "rev-list", "--first-parent", "--topo-order", "--parents", "HEAD").splitlines()
    entries = [(parts[0], len(parts) > 2) for parts in (line.split() for line in reversed(lines)) if parts]
    head = entries[-1][0]
    shas = [sha for sha, is_merge in entries if eligible is None or eligible(sha, is_merge)]
    if not shas or shas[-1] != head:
        shas.append(head)
    if len(shas) <= n:
        return shas
    step = (len(shas) - 1) / (n - 1)
    picked = sorted({round(i * step) for i in range(n)})
    return [shas[i] for i in picked]


def adaptive_snapshot_count(head_parse_seconds: float, requested: int = HISTORY_SNAPSHOTS) -> int:
    if head_parse_seconds <= 0:
        return requested
    affordable = int(SNAPSHOT_TIME_BUDGET_SECONDS / head_parse_seconds)
    return max(MIN_SNAPSHOTS, min(requested, affordable))


def _safe_relative(path: str) -> bool:
    if not path or len(path) > MAX_PATH_CHARS or path.startswith(("/", "\\")) or ":" in path:
        return False
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return False
    return not any(p in _SKIP_DIRS or p.startswith(".") for p in parts[:-1])


def _wanted(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.endswith(SOURCE_EXTENSIONS)


def materialize(repo_path: str, sha: str, dest: str) -> int:
    """Writes the source files of commit `sha` into dest. Returns the count."""
    listing = git(repo_path, "ls-tree", "-r", "-l", "-z", sha, binary=True).decode("utf-8", errors="replace")
    entries = []
    for line in listing.split("\0"):
        if not line:
            continue
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if len(fields) != 4:
            continue
        mode, kind, blob, size = fields
        if kind != "blob" or mode in ("120000", "160000") or not size.isdigit():
            continue
        if int(size) > MAX_BLOB_BYTES or not _wanted(path) or not _safe_relative(path):
            continue
        entries.append((blob, path))
    if not entries:
        return 0

    proc = subprocess.Popen(["git", "-C", repo_path, "cat-file", "--batch"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    written = 0
    try:
        for blob, path in entries:
            proc.stdin.write(f"{blob}\n".encode())
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob":
                continue
            content = proc.stdout.read(int(header[2]))
            proc.stdout.read(1)  # trailing newline after each object
            target = os.path.join(dest, *path.split("/"))
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(content)
                written += 1
            except OSError:
                continue
    finally:
        proc.stdin.close()
        proc.wait()
    return written


def summarize(data: dict, rules: dict) -> dict:
    """Architecture facts for one snapshot from already-parsed (and
    layer-tagged) data."""
    result = evaluate(data, rules)
    violations = result["violations"]
    return {
        "modules": sorted((m["path"], m.get("layer_type")) for m in data["modules"]),
        "imports": sorted((e["from"], e["to"]) for e in data["imports"]),
        "violation_keys": [list(violation_key(v)) for v in violations],
        "violations": [format_violation(v) for v in violations],
        "health": compute_health_normalized(violations, result["checks_by_rule"], rules),
        "health_legacy": compute_health(violations, result["total_applicable_rules"]),
        "weighted_violations": sum(v["severity"] for v in violations),
        "n_calls": len(data["calls"]),
    }


def _snapshot_of(repo_path: str, sha: str, rules: dict) -> dict:
    scratch = tempfile.mkdtemp(prefix="repomind_snap_")
    try:
        materialize(repo_path, sha, scratch)
        data = ast_extractor.parse_repo(scratch)
        apply_layers(data, rules)
        return summarize(data, rules)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def source_change_filter(commits: list):
    """eligible() for pick_snapshot_commits from mined commits: a commit is a
    snapshot candidate if it changed a source file, is a merge, or is older
    than the mined window (unknown, so kept)."""
    mined = {c["hash"] for c in commits}
    changed_source = {c["hash"] for c in commits
                      if any(f["path"].endswith(SOURCE_EXTENSIONS) or f.get("old_path", "").endswith(SOURCE_EXTENSIONS)
                             for f in c["files"])}
    return lambda sha, is_merge: is_merge or sha not in mined or sha in changed_source


def build_snapshots(repo_path: str, rules: dict, head_data: dict, head_parse_seconds: float,
                    commit_lookup, eligible=None) -> list:
    """Returns snapshots oldest first. head_data is the already-parsed HEAD,
    reused instead of re-parsed. commit_lookup(sha) -> commit metadata."""
    n = adaptive_snapshot_count(head_parse_seconds)
    shas = pick_snapshot_commits(repo_path, n, eligible)
    snapshots = []
    for idx, sha in enumerate(shas):
        t0 = time.time()
        facts = summarize(head_data, rules) if idx == len(shas) - 1 else _snapshot_of(repo_path, sha, rules)
        meta = commit_lookup(sha)
        snapshots.append({"idx": idx, "sha": sha, "short": sha[:7], "date": meta.get("date"),
                          "subject": meta.get("subject", ""), "seconds": round(time.time() - t0, 2), **facts})
    _attach_diffs(snapshots)
    return snapshots


def _attach_diffs(snapshots: list) -> None:
    previous = None
    for s in snapshots:
        modules = {p for p, _ in s["modules"]}
        imports = {tuple(e) for e in s["imports"]}
        violations = {tuple(k) for k in s["violation_keys"]}
        if previous is None:
            s["diff"] = {"added_modules": [], "removed_modules": [], "added_imports": [], "removed_imports": [],
                         "new_violations": [], "resolved_violations": []}
        else:
            p_modules, p_imports, p_violations = previous
            s["diff"] = {
                "added_modules": sorted(modules - p_modules),
                "removed_modules": sorted(p_modules - modules),
                "added_imports": sorted(imports - p_imports),
                "removed_imports": sorted(p_imports - imports),
                "new_violations": sorted(violations - p_violations),
                "resolved_violations": sorted(p_violations - violations),
            }
        previous = (modules, imports, violations)


def import_intervals(snapshots: list) -> list:
    """Valid-time intervals for module import edges over the snapshot
    sequence: one entry per contiguous run of presence. valid_to_idx is the
    first snapshot where the edge is gone, or None if it is still live."""
    intervals = []
    open_since = {}
    for s in snapshots:
        present = {tuple(e) for e in s["imports"]}
        for edge in list(open_since):
            if edge not in present:
                intervals.append(_interval(edge, open_since.pop(edge), s, snapshots))
        for edge in present:
            open_since.setdefault(edge, s["idx"])
    for edge, start in open_since.items():
        intervals.append(_interval(edge, start, None, snapshots))
    return sorted(intervals, key=lambda i: (i["from"], i["to"], i["valid_from_idx"]))


def _interval(edge, start_idx, end_snapshot, snapshots):
    return {
        "from": edge[0], "to": edge[1],
        "valid_from_idx": start_idx, "valid_from_sha": snapshots[start_idx]["sha"],
        "valid_to_idx": end_snapshot["idx"] if end_snapshot else None,
        "valid_to_sha": end_snapshot["sha"] if end_snapshot else None,
    }


def module_presence(snapshots: list) -> dict:
    """path -> {"layer": latest layer seen, "snapshots": [idx, ...]}."""
    presence = {}
    for s in snapshots:
        for path, layer in s["modules"]:
            entry = presence.setdefault(path, {"layer": layer, "snapshots": []})
            entry["layer"] = layer
            entry["snapshots"].append(s["idx"])
    return presence
