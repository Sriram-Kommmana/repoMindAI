"""RepoMind AI — Phase 2 CLI entry point: architecture drift checking.

Usage: python check_drift.py
Assumes the graph has already been loaded via `python main.py <repo_path>`.
"""
from rules.rule_engine import load_rules, run_rule_engine
from rules.scoring import compute_health


def _qualified(class_name, name):
    return f"{class_name}.{name}" if class_name else name


def main():
    rules = load_rules("rules.yaml")
    violations, total_applicable_rules = run_rule_engine(rules)

    if not violations:
        print("No violations found.")
    for v in violations:
        caller = f"{v['caller_module']}::{_qualified(v['caller_class'], v['caller_name'])}"
        callee = f"{v['callee_module']}::{_qualified(v['callee_class'], v['callee_name'])}"
        print(f"VIOLATION [{v['rule_name']}] severity={v['severity']}: {caller} -> {callee}")

    health = compute_health(violations, total_applicable_rules)
    print(f"ArchitectureHealth = {health}")


if __name__ == "__main__":
    main()
