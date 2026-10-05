"""Regression baseline: the test_repo fixture's numbers have been fixed since
Phase 2 and must never change. Uses the frozen Phase 2 rules file, so the
engine is tested against a fixed rule set even as the default rules grow."""
import os

from conftest import ROOT, TEST_REPO

from graph import loader
from parser import ast_extractor
from rules.rule_engine import load_rules, run_rule_engine
from rules.scoring import compute_health


def test_parse_counts():
    data = ast_extractor.parse_repo(TEST_REPO)
    assert len(data["modules"]) == 6
    assert len(data["classes"]) == 2
    assert len(data["functions"]) == 15


def test_graph_and_rules(neo4j):
    data = ast_extractor.parse_repo(TEST_REPO)
    loader.load_graph(data)
    assert loader.count_nodes() == 23

    violations, total_applicable = run_rule_engine(load_rules(os.path.join(ROOT, "tests", "fixtures", "rules_phase2.yaml")))
    assert [(v["rule_name"], v["caller_module"], v["caller_name"], v["callee_module"], v["callee_name"])
            for v in violations] == [
        ("no-controller-to-db", "controller.py", "handle_request_direct", "database.py", "save_record")
    ]
    assert compute_health(violations, total_applicable) == 0
