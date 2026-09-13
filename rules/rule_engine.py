"""Loads rules.yaml and checks it against the already-loaded Neo4j graph.

Rules are data: this module contains no rule-specific logic. The same
generic Cypher check runs for any from_layer/to_layer pair found in
rules.yaml — adding a new disallowed rule requires no code changes here.

Phase 2 checks a direct one-hop CALLS edge between the two layers'
functions (not an arbitrary-length transitive path, and not DEPENDS_ON,
which doesn't exist in the Phase 1/2 schema yet).
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
                records = session.run(
                    _VIOLATION_QUERY,
                    from_layer=rule["from_layer"],
                    to_layer=rule["to_layer"],
                )
                for r in records:
                    violations.append(
                        {
                            "rule_name": rule["name"],
                            "severity": rule["severity"],
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
