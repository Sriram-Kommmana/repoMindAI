"""Loads rules.yaml and checks it against the already-loaded Neo4j graph.

Rules are data: this module contains no rule-specific logic. The same
generic Cypher check runs for any from_layer/to_layer pair found in
rules.yaml — adding a new disallowed rule requires no code changes here.

A rule checks a direct one-hop edge between the two layers: CALLS between
their functions (`edge: calls`, the default) or IMPORTS between their
modules (`edge: imports`). rules/evaluate.py implements the same semantics
in memory, and the two are cross-checked on every analysis.
"""
import os

import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

_VIOLATION_QUERY = """
MATCH (fm:Module {layer_type: $from_layer})
MATCH (tm:Module {layer_type: $to_layer})
MATCH (caller:Function {module_path: fm.path})-[:CALLS]->(callee:Function {module_path: tm.path})
RETURN fm.path AS caller_module, caller.class_name AS caller_class, caller.name AS caller_name,
       tm.path AS callee_module, callee.class_name AS callee_class, callee.name AS callee_name
"""

_IMPORT_VIOLATION_QUERY = """
MATCH (fm:Module {layer_type: $from_layer})-[:IMPORTS]->(tm:Module {layer_type: $to_layer})
RETURN fm.path AS caller_module, null AS caller_class, null AS caller_name,
       tm.path AS callee_module, null AS callee_class, null AS callee_name
"""


def load_rules(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def _get_driver():
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    return GraphDatabase.driver(uri, auth=(user, password))


def run_rule_engine(rules: dict):
    """Returns (violations, total_applicable_rules)."""
    disallowed = [r for r in rules["rules"] if r["allowed"] is False]

    violations = []
    driver = _get_driver()
    try:
        with driver.session() as session:
            for rule in disallowed:
                edge = rule.get("edge", "calls")
                records = session.run(
                    _IMPORT_VIOLATION_QUERY if edge == "imports" else _VIOLATION_QUERY,
                    from_layer=rule["from_layer"],
                    to_layer=rule["to_layer"],
                )
                for r in records:
                    violations.append(
                        {
                            "rule_name": rule["name"],
                            "severity": rule["severity"],
                            "edge": edge,
                            "caller_module": r["caller_module"],
                            "caller_class": r["caller_class"],
                            "caller_name": r["caller_name"],
                            "callee_module": r["callee_module"],
                            "callee_class": r["callee_class"],
                            "callee_name": r["callee_name"],
                        }
                    )
    finally:
        driver.close()

    return violations, len(disallowed)


_CALL_CHECKS_QUERY = """
MATCH (fm:Module {layer_type: $from_layer})
MATCH (caller:Function {module_path: fm.path})-[:CALLS]->(callee:Function)
MATCH (tm:Module {path: callee.module_path}) WHERE tm.layer_type IS NOT NULL
RETURN count(*) AS n
"""

_IMPORT_CHECKS_QUERY = """
MATCH (fm:Module {layer_type: $from_layer})-[:IMPORTS]->(tm:Module) WHERE tm.layer_type IS NOT NULL
RETURN count(*) AS n
"""


def count_checks(rules: dict, session=None) -> dict:
    """Per disallowed rule, how many edges it judged: edges leaving a
    from_layer module and landing in any layer-tagged module. Same
    definition as rules/evaluate.py; feeds compute_health_normalized."""
    def _run(s):
        checks = {}
        for rule in rules["rules"]:
            if rule["allowed"] is not False:
                continue
            query = _IMPORT_CHECKS_QUERY if rule.get("edge", "calls") == "imports" else _CALL_CHECKS_QUERY
            checks[rule["name"]] = s.run(query, from_layer=rule["from_layer"]).single()["n"]
        return checks

    if session is not None:
        return _run(session)
    driver = _get_driver()
    try:
        with driver.session() as s:
            return _run(s)
    finally:
        driver.close()
