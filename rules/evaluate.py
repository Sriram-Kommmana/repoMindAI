"""Pure, in-memory rule evaluation over parsed repository data.

Same semantics as the Cypher rule engine (rules/rule_engine.py), so it can
score historical snapshots that never get loaded into Neo4j — and the two
are cross-checked against each other on HEAD. It also reports, per rule,
how many edges the rule actually judged ("checks"), which the normalized
health score needs.
"""


def _qualified(class_name, name):
    return f"{class_name}.{name}" if class_name else name


def _disallowed(rules: dict) -> list:
    return [r for r in rules["rules"] if r["allowed"] is False]


def evaluate(data: dict, rules: dict) -> dict:
    """Returns {"violations": [...], "checks_by_rule": {name: n},
    "total_applicable_rules": n}. A check is an edge leaving a from_layer
    module and landing in any layer-tagged module."""
    layer_of = {m["path"]: m.get("layer_type") for m in data["modules"]}
    violations = []
    checks = {}
    for rule in _disallowed(rules):
        edge = rule.get("edge", "calls")
        judged = 0
        if edge == "imports":
            for e in data["imports"]:
                if layer_of.get(e["from"]) != rule["from_layer"] or not layer_of.get(e["to"]):
                    continue
                judged += 1
                if layer_of[e["to"]] == rule["to_layer"]:
                    violations.append(_violation(rule, e["from"], None, None, e["to"], None, None))
        else:
            for c in data["calls"]:
                if layer_of.get(c["caller_module"]) != rule["from_layer"] or not layer_of.get(c["callee_module"]):
                    continue
                judged += 1
                if layer_of[c["callee_module"]] == rule["to_layer"]:
                    violations.append(_violation(rule, c["caller_module"], c["caller_class"], c["caller_name"],
                                                 c["callee_module"], c["callee_class"], c["callee_name"]))
        checks[rule["name"]] = judged
    violations.sort(key=violation_key)
    return {"violations": violations, "checks_by_rule": checks, "total_applicable_rules": len(_disallowed(rules))}


def _violation(rule, caller_module, caller_class, caller_name, callee_module, callee_class, callee_name):
    return {
        "rule_name": rule["name"], "severity": rule["severity"], "edge": rule.get("edge", "calls"),
        "caller_module": caller_module, "caller_class": caller_class, "caller_name": caller_name,
        "callee_module": callee_module, "callee_class": callee_class, "callee_name": callee_name,
    }


def violation_key(v: dict) -> tuple:
    return (v["rule_name"], v["caller_module"], v["caller_class"] or "", v["caller_name"] or "",
            v["callee_module"], v["callee_class"] or "", v["callee_name"] or "")


def format_violation(v: dict) -> dict:
    """The shape the API, docs and Q&A show: imports-rule violations are
    module -> module; calls-rule violations are function -> function."""
    if v.get("edge") == "imports" or v.get("caller_name") is None:
        caller, callee = v["caller_module"], v["callee_module"]
    else:
        caller = f"{v['caller_module']}::{_qualified(v['caller_class'], v['caller_name'])}"
        callee = f"{v['callee_module']}::{_qualified(v['callee_class'], v['callee_name'])}"
    return {"rule": v["rule_name"], "severity": v["severity"], "edge": v.get("edge", "calls"),
            "caller": caller, "callee": callee}
