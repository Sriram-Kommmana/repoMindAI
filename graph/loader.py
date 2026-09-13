"""Neo4j connection and write logic for the Phase 1 knowledge graph.

Credentials are read from .env (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) —
never hardcoded, per CLAUDE.md.
"""
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


def _get_driver():
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    return GraphDatabase.driver(uri, auth=(user, password))


def load_graph(data: dict) -> None:
    """Wipes the graph and loads the current-state Module/Class/Function
    nodes and CONTAINS/CALLS/IMPORTS relationships from `data` (as returned
    by parser.ast_extractor.parse_repo).

    Phase 1 has no temporal/incremental model, so a full wipe-and-reload on
    every run is the simplest correct behavior.
    """
    driver = _get_driver()
    try:
        with driver.session() as session:
            session.execute_write(lambda tx: tx.run("MATCH (n) DETACH DELETE n"))
            session.execute_write(_write_modules, data["modules"])
            session.execute_write(_write_classes, data["classes"])
            session.execute_write(_write_functions, data["functions"])
            session.execute_write(_write_module_contains_class, data["classes"])
            session.execute_write(_write_module_contains_function, data["functions"])
            session.execute_write(_write_class_contains_function, data["functions"])
            session.execute_write(_write_imports, data["imports"])
            session.execute_write(_write_calls, data["calls"])
    finally:
        driver.close()


def count_nodes() -> int:
    driver = _get_driver()
    try:
        with driver.session() as session:
            record = session.run("MATCH (n) RETURN count(n) AS c").single()
            return record["c"]
    finally:
        driver.close()


def _write_modules(tx, modules):
    tx.run(
        "UNWIND $rows AS row "
        "MERGE (m:Module {path: row.path}) SET m.language = row.language",
        rows=modules,
    )


def _write_classes(tx, classes):
    tx.run(
        "UNWIND $rows AS row "
        "MERGE (c:Class {module_path: row.module_path, name: row.name})",
        rows=classes,
    )


def _write_functions(tx, functions):
    # Split by class_name because a null-valued property can never appear in
    # a MERGE map's match key (Cypher's `= null` is never true) — module-level
    # functions simply never get a class_name property at all.
    module_level = [f for f in functions if f["class_name"] is None]
    methods = [f for f in functions if f["class_name"] is not None]
    tx.run(
        "UNWIND $rows AS row "
        "MERGE (f:Function {module_path: row.module_path, name: row.name}) "
        "SET f.signature = row.signature",
        rows=module_level,
    )
    tx.run(
        "UNWIND $rows AS row "
        "MERGE (f:Function {module_path: row.module_path, class_name: row.class_name, name: row.name}) "
        "SET f.signature = row.signature",
        rows=methods,
    )


def _write_module_contains_class(tx, classes):
    tx.run(
        "UNWIND $rows AS row "
        "MATCH (m:Module {path: row.module_path}) "
        "MATCH (c:Class {module_path: row.module_path, name: row.name}) "
        "MERGE (m)-[:CONTAINS]->(c)",
        rows=classes,
    )


def _write_module_contains_function(tx, functions):
    rows = [f for f in functions if f["class_name"] is None]
    tx.run(
        "UNWIND $rows AS row "
        "MATCH (m:Module {path: row.module_path}) "
        "MATCH (f:Function {module_path: row.module_path, name: row.name}) "
        "WHERE f.class_name IS NULL "
        "MERGE (m)-[:CONTAINS]->(f)",
        rows=rows,
    )


def _write_class_contains_function(tx, functions):
    rows = [f for f in functions if f["class_name"] is not None]
    tx.run(
        "UNWIND $rows AS row "
        "MATCH (c:Class {module_path: row.module_path, name: row.class_name}) "
        "MATCH (f:Function {module_path: row.module_path, class_name: row.class_name, name: row.name}) "
        "MERGE (c)-[:CONTAINS]->(f)",
        rows=rows,
    )


def _write_imports(tx, imports):
    tx.run(
        "UNWIND $rows AS row "
        "MATCH (from:Module {path: row.from}) "
        "MATCH (to:Module {path: row.to}) "
        "MERGE (from)-[:IMPORTS]->(to)",
        rows=imports,
    )


def _write_calls(tx, calls):
    tx.run(
        "UNWIND $rows AS row "
        "MATCH (caller:Function {module_path: row.caller_module, name: row.caller_name}) "
        "WHERE (row.caller_class IS NULL AND caller.class_name IS NULL) OR caller.class_name = row.caller_class "
        "MATCH (callee:Function {module_path: row.callee_module, name: row.callee_name}) "
        "WHERE (row.callee_class IS NULL AND callee.class_name IS NULL) OR callee.class_name = row.callee_class "
        "MERGE (caller)-[:CALLS]->(callee)",
        rows=calls,
    )
