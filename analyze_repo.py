"""RepoMind AI — Phase 5a CLI entry point: URL-to-local-clone wrapper.

Usage: python analyze_repo.py <github_url>

Clones a public GitHub repo to a temporary local directory, then feeds that
path into the existing, unchanged parsing/graph-loading pipeline
(main.run_pipeline). The clone is deleted after loading into Neo4j, since
downstream tools (check_drift.py, export_diagram.py) only ever query the
graph, never the local files.
"""
import glob
import os
import shutil
import stat
import subprocess
import sys
import tempfile

from main import run_pipeline


def clone_repo(url: str, dest: str) -> None:
    print(f"Cloning {url}...")
    subprocess.run(["git", "clone", "--depth", "1", url, dest], check=True)
    num_py_files = len(glob.glob(f"{dest}/**/*.py", recursive=True))
    print(f"Clone complete. Found {num_py_files} Python files.")


def _remove_readonly(func, path, _exc_info):
    # git marks some files under .git/ read-only on Windows, which makes
    # shutil.rmtree's default remover raise PermissionError on them.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_repo.py <github_url>")
        sys.exit(1)

    url = sys.argv[1]
    temp_dir = tempfile.mkdtemp(prefix="repomind_")

    try:
        clone_repo(url, temp_dir)
        print("Parsing and loading into Neo4j...")
        run_pipeline(temp_dir)
        print("Done.")
    finally:
        print(f"Cleaning up temporary clone at {temp_dir}")
        shutil.rmtree(temp_dir, onerror=_remove_readonly)


if __name__ == "__main__":
    main()
