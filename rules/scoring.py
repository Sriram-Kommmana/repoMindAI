"""ArchitectureHealth formula (SPEC.md section 6), current-state only —
no historical/multi-commit drift curve yet (that's a later phase)."""


def compute_health(violations: list, total_applicable_rules: int) -> float:
    if total_applicable_rules == 0:
        return 100.0
    weighted_violations = sum(v["severity"] for v in violations)
    score = 100 - 100 * (weighted_violations / total_applicable_rules)
    return max(0, min(100, score))
