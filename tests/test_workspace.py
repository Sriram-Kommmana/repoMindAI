import os
import tempfile
import time

import workspace


def test_sweep_only_removes_old_workspaces(monkeypatch):
    tmp = tempfile.gettempdir()
    fresh_ws = tempfile.mkdtemp(prefix=workspace.WORKSPACE_PREFIX)
    old_ws = tempfile.mkdtemp(prefix=workspace.WORKSPACE_PREFIX)
    other = tempfile.mkdtemp(prefix="repomind_eval_")
    old = time.time() - workspace.STALE_AFTER_SECONDS - 60
    os.utime(old_ws, (old, old))
    os.utime(other, (old, old))
    try:
        workspace.sweep_stale()
        assert os.path.isdir(fresh_ws)          # may belong to another running server
        assert not os.path.exists(old_ws)       # crashed run, a day old
        assert os.path.isdir(other)             # not a workspace at all
    finally:
        for p in (fresh_ws, old_ws, other):
            workspace.remove_tree(p)
    assert tmp
