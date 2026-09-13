"""RepoMind AI — Phase 3 CLI entry point: Git history mining.

Usage: python mine_history.py [repo_path]  (defaults to ".", the repoMindAI repo itself)

Walks the repo's commit history via PyDriller and prints each commit's hash,
message, author, date, and modified files. No Neo4j/.env access is needed.
"""
import sys

from pydriller import Repository


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    repo_path = sys.argv[1] if len(sys.argv) > 1 else "."

    commit_count = 0
    for commit in Repository(repo_path).traverse_commits():
        short_hash = commit.hash[:7]
        files_changed = [f.filename for f in commit.modified_files]
        print(
            f'COMMIT {short_hash} | {commit.author_date.isoformat()} | '
            f'{commit.author.name} | "{commit.msg}" | files: {", ".join(files_changed)}'
        )
        commit_count += 1

    print(f"Mined {commit_count} commits from {repo_path}")


if __name__ == "__main__":
    main()
