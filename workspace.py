"""The analysis workspace: a full clone of the repository currently loaded
in the graph, kept on disk (with the analysis results in memory) so the
lazily loaded features — documentation, violation explanations, ADRs,
historical diagrams — can read source and git history after /analyze
returns.

One analysis runs at a time. Every lazy request names the analysis_id it
belongs to; a stale id is rejected rather than served another repo's data.
A workspace replaced by a newer analysis is deleted once its last reader
finishes, so a long-running request never has files vanish under it.
"""
import glob
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager

WORKSPACE_PREFIX = "repomind_ws_"
_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # fail instead of prompting for credentials


class AnalysisBusy(RuntimeError):
    pass


class StaleAnalysis(RuntimeError):
    pass


class CloneError(RuntimeError):
    pass


class Workspace:
    def __init__(self, path: str, repo_url: str):
        self.id = uuid.uuid4().hex[:12]
        self.path = path
        self.repo_url = repo_url
        self.head_sha = None
        self.clone_seconds = 0.0
        self.results = {}
        self.readers = 0
        self.retired = False


_state_lock = threading.Lock()
_analysis_lock = threading.Lock()
_current = None


def _remove_readonly(func, path, _exc_info):
    # git marks files under .git/ read-only on Windows.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(path: str) -> None:
    for attempt in range(3):
        try:
            shutil.rmtree(path, onerror=_remove_readonly)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.5 * (attempt + 1))  # antivirus/indexer briefly holding a file on Windows
    shutil.rmtree(path, ignore_errors=True)


STALE_AFTER_SECONDS = 24 * 3600
_SWEPT_PREFIXES = (WORKSPACE_PREFIX, "repomind_snap_")


def sweep_stale() -> int:
    """Deletes workspaces and snapshot scratch dirs left behind by a crashed
    run. Only folders untouched for a day are removed: another RepoMind
    process (a second server, the tests) may be using a recent one."""
    removed = 0
    cutoff = time.time() - STALE_AFTER_SECONDS
    for prefix in _SWEPT_PREFIXES:
        for path in glob.glob(os.path.join(tempfile.gettempdir(), prefix + "*")):
            try:
                stale = os.path.isdir(path) and os.path.getmtime(path) < cutoff
            except OSError:
                continue
            if stale and (_current is None or path != _current.path):
                remove_tree(path)
                removed += 1
    return removed


def _clone(url: str, dest: str) -> str:
    args = ["git", "clone", "--single-branch", "--no-tags", "--quiet"]
    if os.environ.get("CLONE_FILTER"):
        args.append(f"--filter={os.environ['CLONE_FILTER']}")
    # "--" so a URL can never be parsed as a git option (e.g. --upload-pack=...).
    result = subprocess.run(args + ["--", url, dest], capture_output=True, text=True, env=_GIT_ENV)
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        raise CloneError(f"Couldn't clone {url}: {detail[-1] if detail else 'git clone failed'}. "
                         "Check the URL and that the repository is public.")
    head = subprocess.run(["git", "-C", dest, "rev-parse", "HEAD"], capture_output=True, text=True, env=_GIT_ENV)
    if head.returncode != 0:
        raise CloneError("The repository has no commits yet, so there is nothing to analyze.")
    return head.stdout.strip()


_REMOTE_URL = re.compile(r"^https?://[^\s/]+/\S+$", re.IGNORECASE)


def validate_repo_url(url: str) -> None:
    """Only remote http(s) repositories: anything else could make the server
    clone its own filesystem. REPOMIND_ALLOW_LOCAL_REPOS=1 (tests, evaluation)
    additionally allows an existing local directory."""
    if _REMOTE_URL.match(url):
        return
    if os.environ.get("REPOMIND_ALLOW_LOCAL_REPOS") == "1" and os.path.isdir(url):
        return
    raise CloneError("Enter a public repository URL starting with https://, e.g. https://github.com/user/repo.")


def _retire(ws) -> None:
    ws.retired = True
    if ws.readers == 0:
        remove_tree(ws.path)


@contextmanager
def new_analysis(repo_url: str):
    """Clones repo_url into a fresh workspace and yields it. The workspace
    becomes current only if the body completes; on failure it is deleted."""
    global _current
    validate_repo_url(repo_url)
    if not _analysis_lock.acquire(blocking=False):
        raise AnalysisBusy("Another analysis is already running. Wait for it to finish.")
    try:
        with _state_lock:
            previous, _current = _current, None
            if previous is not None:
                _retire(previous)
        ws = Workspace(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX), repo_url)
        try:
            t0 = time.time()
            ws.head_sha = _clone(repo_url, ws.path)
            ws.clone_seconds = round(time.time() - t0, 2)
            yield ws
        except BaseException:
            remove_tree(ws.path)
            raise
        with _state_lock:
            _current = ws
    finally:
        _analysis_lock.release()


@contextmanager
def use(analysis_id: str):
    """Yields the current workspace if analysis_id is still current."""
    with _state_lock:
        ws = _current
        if ws is None or ws.id != analysis_id:
            if _analysis_lock.locked():
                raise StaleAnalysis("A new analysis is running; this result is out of date.")
            raise StaleAnalysis("This analysis is no longer current. Run the analysis again.")
        ws.readers += 1
    try:
        yield ws
    finally:
        with _state_lock:
            ws.readers -= 1
            if ws.retired and ws.readers == 0:
                remove_tree(ws.path)


def is_current(analysis_id: str) -> bool:
    with _state_lock:
        return _current is not None and _current.id == analysis_id


def shutdown() -> None:
    global _current
    with _state_lock:
        if _current is not None:
            _retire(_current)
            _current = None
