"""Architecture health scores (SPEC.md section 6). The drift curve applies
the normalized score to every history snapshot (snapshots.py)."""


def compute_health_normalized(violations: list, checks_by_rule: dict, rules: dict):
    """Health in [0, 100] that a real repo can actually move along.

    The legacy formula below divides weighted violations by the NUMBER OF
    RULES, so one severity-3 violation against one rule is already 0 and any
    real repo sits at 0 forever. Here each rule contributes its violation
    RATE (violations / edges it judged), weighted by severity:

        health = 100 * (1 - sum_r(sev_r * viol_r / checks_r) / sum_r(sev_r))

    over the rules that judged at least one edge — SPEC's "rule-checks
    actually evaluable at that commit". Returns None when no rule could be
    evaluated (e.g. no module carries a layer), rather than a misleading 100.
    """
    counts = {}
    for v in violations:
        counts[v["rule_name"]] = counts.get(v["rule_name"], 0) + 1
    evaluable = [r for r in rules["rules"]
                 if r["allowed"] is False and checks_by_rule.get(r["name"], 0) > 0 and r["severity"] > 0]
    if not evaluable:
        return None
    total_severity = sum(r["severity"] for r in evaluable)
    weighted_rate = sum(r["severity"] * min(1.0, counts.get(r["name"], 0) / checks_by_rule[r["name"]])
                        for r in evaluable)
    return round(100 * (1 - weighted_rate / total_severity), 1)


def compute_health(violations: list, total_applicable_rules: int) -> float:
    if total_applicable_rules == 0:
        return 100.0
    weighted_violations = sum(v["severity"] for v in violations)
    score = 100 - 100 * (weighted_violations / total_applicable_rules)
    return max(0, min(100, score))
