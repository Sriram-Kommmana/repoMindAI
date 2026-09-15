"""RepoMind AI — Phase 1 CLI entry point.

Usage: python main.py [repo_path]  (defaults to ./test_repo)
"""
import sys

from graph import loader
from parser import ast_extractor


def run_pipeline(repo_path: str) -> None:
    data = ast_extractor.parse_repo(repo_path)

    num_files = len(data["modules"])
    num_classes = len(data["classes"])
    num_functions = len(data["functions"])
    print(f"Parsed {num_files} files, found {num_classes} classes, {num_functions} functions")

    loader.load_graph(data)

    node_count = loader.count_nodes()
    print(f"Loaded into Neo4j. MATCH (n) RETURN count(n) -> {node_count}")


def main():
    repo_path = sys.argv[1] if len(sys.argv) > 1 else "./test_repo"
    run_pipeline(repo_path)


if __name__ == "__main__":
    main()
