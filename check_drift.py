"""RepoMind AI — CLI entry point: architecture drift checking.

Usage: python check_drift.py [rules.yaml]
Assumes the graph has already been loaded via `python main.py <repo_path>`.
"""
import sys

from rules.config import DEFAULT_RULES_PATH, load_rules_config
from rules.evaluate import format_violation, violation_key
from rules.rule_engine import count_checks, run_rule_engine
from rules.scoring import compute_health, compute_health_normalized


def _qualified(class_name, name):
    return f"{class_name}.{name}" if class_name else name


def main():
    rules = load_rules_config(path=sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RULES_PATH)
    violations, total_applicable_rules = run_rule_engine(rules)
    violations.sort(key=violation_key)

    if not violations:
        print("No violations found.")
    for v in violations:
        f = format_violation(v)
        print(f"VIOLATION [{f['rule']}] severity={f['severity']} ({f['edge']}): {f['caller']} -> {f['callee']}")

    health = compute_health_normalized(violations, count_checks(rules), rules)
    print(f"ArchitectureHealth = {health if health is not None else 'n/a (nothing to check)'}")
    print(f"ArchitectureHealth (legacy formula) = {compute_health(violations, total_applicable_rules)}")


if __name__ == "__main__":
    main()
