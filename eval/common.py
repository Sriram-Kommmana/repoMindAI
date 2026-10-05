"""Shared helpers for the evaluation scripts."""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "eval", "results")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.chdir(ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from workspace import remove_tree  # noqa: E402


def clone(url: str, depth=None) -> str:
    dest = tempfile.mkdtemp(prefix="repomind_eval_")
    args = ["git", "clone", "-q", "--single-branch", "--no-tags"] + (["--depth", str(depth)] if depth else [])
    subprocess.run(args + ["--", url, dest], check=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    return dest


def prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(f1, 3)}


def write_report(name: str, markdown: str, data: dict) -> str:
    os.makedirs(RESULTS, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md_path = os.path.join(RESULTS, f"{name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown.rstrip() + f"\n\n_Generated {stamp} by `eval/eval_{name}.py`._\n")
    with open(os.path.join(RESULTS, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return md_path


def table(headers: list, rows: list) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)
