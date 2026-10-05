"""Disk cache for LLM-generated artifacts (documentation, violation
explanations, ADRs).

The key covers everything that changes the output: repository, commit,
artifact, the active rules, the prompt version, and the provider/model.
Re-analyzing the same commit therefore makes zero LLM calls, and demo repos
can be pre-warmed. Degraded results (with warnings) are never cached, so a
rate-limited run doesn't become permanent.
"""
import hashlib
import json
import os
import re
import tempfile
import threading

import llm

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.environ.get("REPOMIND_CACHE_DIR", os.path.join(ROOT, ".cache"))
# Bump when a prompt or output format changes, so old entries stop matching.
PROMPT_VERSION = "2"

_lock = threading.Lock()
_stats = {"hits": 0, "misses": 0}


def _slug(repo_url: str) -> str:
    url = re.sub(r"^[a-z]+://", "", (repo_url or "local").strip().lower())
    url = re.sub(r"\.git$", "", url.rstrip("/"))
    return re.sub(r"[^a-z0-9._-]+", "_", url)[:120] or "repo"


def entry_path(repo_url: str, head_sha: str, artifact: str, purpose: str, rules=None, extra="") -> str:
    provider = llm.describe(purpose)
    fingerprint = json.dumps({"rules": rules, "prompt": PROMPT_VERSION, "provider": provider["provider"],
                              "model": provider["model"], "extra": extra}, sort_keys=True, default=str)
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]
    return os.path.join(CACHE_DIR, _slug(repo_url), (head_sha or "unknown")[:12], f"{artifact}-{digest}.json")


def get(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
    except (OSError, json.JSONDecodeError):
        with _lock:
            _stats["misses"] += 1
        return None
    with _lock:
        _stats["hits"] += 1
    return value


def put(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f)
    os.replace(tmp, path)


def cached(path: str, compute, cacheable=lambda value: True):
    """Returns (value, hit). compute() runs only on a miss; its value is
    stored if cacheable(value)."""
    value = get(path)
    if value is not None:
        return value, True
    value = compute()
    if cacheable(value):
        put(path, value)
    return value, False


def stats() -> dict:
    with _lock:
        return dict(_stats)


def reset_stats() -> None:
    with _lock:
        _stats.update(hits=0, misses=0)
