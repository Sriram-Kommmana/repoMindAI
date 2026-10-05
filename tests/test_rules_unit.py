import copy

import pytest

from conftest import TEST_REPO
from layers import apply_layers, classify
from parser import ast_extractor
from rules.config import RulesError, load_rules_config, parse_rules
from rules.evaluate import evaluate, format_violation, violation_key
from rules.scoring import compute_health, compute_health_normalized

DEFAULT = load_rules_config()


def test_default_rules_file_is_valid():
    assert {"controller", "service", "database", "model"} <= set(DEFAULT["layers"])
    assert any(r.get("edge") == "imports" for r in DEFAULT["rules"])


@pytest.mark.parametrize("path, layer", [
    ("controller.py", "controller"),
    ("src/controllers/user.js", "controller"),
    ("src/user.controller.ts", "controller"),
    ("app/services/db/session.py", "database"),       # innermost folder wins
    ("app/db/services/cache.py", "service"),
    ("src/allocation/service_layer/handlers.py", "service"),
    ("src/allocation/adapters/repository.py", "database"),
    ("src/models/user.js", "model"),
    ("Controllers/Home.js", "controller"),            # case-insensitive
    ("app.py", None),
    ("models.py", None),                              # a file named models.py is not the models/ folder
])
def test_classify(path, layer):
    assert classify(path, DEFAULT["layers"]) == layer


@pytest.mark.parametrize("path", [
    "test/e2e/api/users.test.ts", "tests/controllers/test_user.py", "src/services/user.spec.js",
    "app/controllers/conftest.py", "src/__tests__/routes/x.js",
])
def test_tests_get_no_layer(path):
    assert classify(path, DEFAULT["layers"], DEFAULT["ignore"]) is None


def test_glob_overrides_everything():
    layers = {"controller": [{"dir": "api"}], "legacy": [{"glob": "src/api/old/*"}]}
    assert classify("src/api/old/x.py", layers) == "legacy"
    assert classify("src/api/new/x.py", layers) == "controller"


def test_no_layers_section_keeps_parser_layers():
    data = {"modules": [{"path": "controller.py", "layer_type": "controller"}]}
    apply_layers(data, {"rules": []})
    assert data["modules"][0]["layer_type"] == "controller"


@pytest.mark.parametrize("text, message", [
    ("rules: []", "rules"),
    ("layers:\n  web:\n    - dir: api\nrules:\n  - {name: r, from_layer: web, to_layer: db, allowed: false, severity: 1}",
     "doesn't define"),
    ("rules:\n  - {name: r, from_layer: a, to_layer: b, allowed: false, severity: 99}", "severity"),
    ("layers:\n  a:\n    - {dir: x, file: y}\nrules:\n  - {name: r, from_layer: a, to_layer: a, allowed: false, severity: 1}",
     "exactly one"),
    ("rules:\n  - {name: r, from_layer: a, to_layer: b, allowed: false, severity: 1, edge: inherits}", "edge"),
    (": : :", "parsed"),
    ("x" * 20_001, "too long"),
])
def test_invalid_rules_are_rejected_with_a_reason(text, message):
    with pytest.raises(RulesError, match=message):
        parse_rules(text)


def _test_repo_data():
    data = ast_extractor.parse_repo(TEST_REPO)
    apply_layers(data, DEFAULT)
    return data


def test_evaluate_test_repo_with_default_rules():
    data = _test_repo_data()
    result = evaluate(data, DEFAULT)
    formatted = [format_violation(v) for v in result["violations"]]
    assert formatted == [
        {"rule": "no-controller-imports-db", "severity": 2, "edge": "imports",
         "caller": "controller.py", "callee": "database.py"},
        {"rule": "no-controller-to-db", "severity": 3, "edge": "calls",
         "caller": "controller.py::handle_request_direct", "callee": "database.py::save_record"},
    ]
    assert result["checks_by_rule"] == {
        "no-controller-to-db": 2, "no-controller-imports-db": 2, "no-service-imports-controller": 1,
        "no-db-imports-service": 0, "no-db-imports-controller": 0,
    }
    # rates: 3*(1/2) + 2*(1/2) + 2*0 = 2.5 over evaluable severity 7
    assert compute_health_normalized(result["violations"], result["checks_by_rule"], DEFAULT) == 64.3
    assert compute_health(result["violations"], result["total_applicable_rules"]) == 0


def test_normalized_health_is_none_when_nothing_is_checkable():
    assert compute_health_normalized([], {"no-controller-to-db": 0}, DEFAULT) is None


def test_normalized_health_moves_with_violation_rate():
    rules = {"rules": [{"name": "r", "allowed": False, "severity": 3}]}
    def health(viol, checks):
        return compute_health_normalized([{"rule_name": "r"}] * viol, {"r": checks}, rules)
    assert health(0, 10) == 100.0
    assert health(1, 10) == 90.0
    assert health(5, 10) == 50.0
    assert health(10, 10) == 0.0


def test_evaluate_is_deterministic():
    data = _test_repo_data()
    shuffled = copy.deepcopy(data)
    shuffled["calls"].reverse()
    shuffled["imports"].reverse()
    assert evaluate(data, DEFAULT) == evaluate(shuffled, DEFAULT)


def test_cypher_engine_matches_pure_evaluator(neo4j):
    from graph import loader
    from rules.rule_engine import run_rule_engine

    data = _test_repo_data()
    loader.load_graph(data)
    cypher_violations, total = run_rule_engine(DEFAULT)
    pure = evaluate(data, DEFAULT)
    assert sorted(cypher_violations, key=violation_key) == pure["violations"]
    assert total == pure["total_applicable_rules"]

    from rules.rule_engine import count_checks
    assert count_checks(DEFAULT) == pure["checks_by_rule"]
