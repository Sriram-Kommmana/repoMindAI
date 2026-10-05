"""Git history mining: one streamed `git log` call instead of PyDriller's
per-commit diffs (about 10x faster on Windows, which matters because it runs
inside every analysis). mine_history.py remains as a standalone CLI.

Author emails are never stored or shown — only a short hash of them, used to
tell authors with the same display name apart.
"""
import hashlib
import os
import subprocess
from datetime import datetime, timezone

HISTORY_MAX_COMMITS = int(os.environ.get("HISTORY_MAX_COMMITS", 1500))
BULK_COMMIT_FILES = 100
MAX_BODY_CHARS = 2000

_FORMAT = "%x1e%H%x1f%P%x1f%an%x1f%ae%x1f%at%x1f%s%x1f%b%x1f"
_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def git(repo_path: str, *args: str, binary: bool = False):
    result = subprocess.run(["git", "-C", repo_path, "-c", "core.quotepath=off", *args],
                            capture_output=True, env=_GIT_ENV, check=True)
    return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")


def _author_id(email: str, name: str) -> str:
    return hashlib.sha1((email or name).strip().lower().encode("utf-8")).hexdigest()[:12]


def _to_int(value: str) -> int:
    return int(value) if value.isdigit() else 0  # "-" for binary files


def _parse_numstat(text: str) -> list:
    files = []
    tokens = text.split("\0")
    i = 0
    while i < len(tokens):
        token = tokens[i].strip("\n")
        i += 1
        if not token:
            continue
        parts = token.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        entry = {"added": _to_int(added), "deleted": _to_int(deleted)}
        if path:
            entry["path"] = path
        else:  # rename: the old and new paths follow as separate NUL-terminated fields
            if i + 1 >= len(tokens):
                break
            entry["old_path"], entry["path"] = tokens[i], tokens[i + 1]
            i += 2
        files.append(entry)
    return files


def parse_log(raw: str) -> list:
    """Parses `git log --numstat -z --format=_FORMAT` output, newest first."""
    commits = []
    for record in raw.split("\x1e"):
        if not record.strip("\0\n"):
            continue
        header_end = record.rfind("\x1f")
        header, rest = record[:header_end], record[header_end + 1:]
        fields = header.split("\x1f", 6)
        if len(fields) < 7:
            continue
        sha, parents, name, email, timestamp, subject, body = fields
        ts = int(timestamp) if timestamp.isdigit() else 0
        files = _parse_numstat(rest)
        commits.append({
            "hash": sha,
            "short": sha[:7],
            "parents": parents.split() if parents else [],
            "author": name.strip() or "unknown",
            "author_id": _author_id(email, name),
            "timestamp": ts,
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "subject": subject.strip(),
            "body": body.strip()[:MAX_BODY_CHARS],
            "files": files,
            "n_files": len(files),
            "bulk": len(files) > BULK_COMMIT_FILES,
        })
    return commits


def mine_commits(repo_path: str, max_commits: int = HISTORY_MAX_COMMITS) -> dict:
    """Returns {"commits": [...] oldest first, each with an "idx" position,
    "truncated": whether older history was cut off by max_commits}."""
    raw = git(repo_path, "log", "--no-merges", "-M", "--numstat", "-z", "--topo-order",
              f"--format={_FORMAT}", "-n", str(max_commits + 1))
    commits = parse_log(raw)
    truncated = len(commits) > max_commits
    commits = commits[:max_commits]
    commits.reverse()
    for idx, c in enumerate(commits):
        c["idx"] = idx
    return {"commits": commits, "truncated": truncated}


def commit_meta(repo_path: str, sha: str) -> dict:
    """Metadata for one commit that may be absent from mine_commits (merge
    commits are excluded there, but a first-parent snapshot can be one)."""
    raw = git(repo_path, "show", "-s", f"--format={_FORMAT}", sha)
    parsed = parse_log(raw)
    return parsed[0] if parsed else {"hash": sha, "short": sha[:7], "subject": "", "date": None, "timestamp": 0}


def introduced_at(commits: list) -> dict:
    """path -> the oldest mined commit touching it (approximate when history
    was truncated; renames count as introducing the new path)."""
    first = {}
    for c in commits:
        for f in c["files"]:
            first.setdefault(f["path"], c)
    return first


def contributors(commits: list, top: int = 10) -> list:
    counts = {}
    for c in commits:
        entry = counts.setdefault(c["author_id"], {"name": c["author"], "commits": 0, "lines": 0})
        entry["commits"] += 1
        entry["lines"] += sum(f["added"] + f["deleted"] for f in c["files"])
    return sorted(counts.values(), key=lambda e: (-e["commits"], e["name"]))[:top]
