"""Tree-sitter based parsing of TypeScript source into the SAME output
shape parser/ast_extractor.py and parser/js_extractor.py produce, so
graph/loader.py needs no changes to accept it.

TypeScript reuses the exact same node types as JavaScript for every
construct this project extracts (function_declaration, arrow_function,
class_declaration, method_definition, import_statement, call_expression —
confirmed empirically, no renaming or wrapping) — typed parameters and
return types just add sibling `type_annotation` children without changing
node types, so raw-text signature capture keeps working unmodified, and
class/method decorators are a plain repeated `decorator` field (unlike
Python's wrapping `decorated_definition`), so no unwrapping is needed.
TS-only constructs (`interface_declaration`, `type_alias_declaration`) are
type-only — deliberately not extracted as Class/Function since they don't
exist at runtime.

All node-level extraction logic is reused directly from js_extractor.py;
this module only supplies its own Language/Parser setup, file walk, and
top-level parse_repo/merge, exactly mirroring js_extractor.parse_repo.
"""
from __future__ import annotations

import os

import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

from parser import js_extractor
from parser.js_extractor import (
    _extract_class,
    _extract_function,
    _extract_import,
    _extract_require,
)

TS_LANGUAGE = Language(tsts.language_typescript())
TSX_LANGUAGE = Language(tsts.language_tsx())

_SKIP_DIRS = js_extractor._SKIP_DIRS
_TS_EXTENSIONS = (".ts",)
_TSX_EXTENSIONS = (".tsx",)


def parse_repo(repo_path: str) -> dict:
    """Parse every .ts/.tsx file under repo_path and resolve CALLS/IMPORTS
    edges. Returns the same dict shape as ast_extractor.parse_repo."""
    ts_parser = Parser(TS_LANGUAGE)
    tsx_parser = Parser(TSX_LANGUAGE)

    raw_files = {}
    for rel_path, abs_path in _iter_ts_files(repo_path, _TS_EXTENSIONS):
        raw_files[rel_path] = _parse_one(ts_parser, abs_path)
    for rel_path, abs_path in _iter_ts_files(repo_path, _TSX_EXTENSIONS):
        raw_files[rel_path] = _parse_one(tsx_parser, abs_path)

    known_paths = set(raw_files)

    modules = [
        {"path": path, "language": "typescript", "layer_type": None} for path in raw_files
    ]

    classes = [
        {"name": cls["name"], "module_path": path}
        for path, file_data in raw_files.items()
        for cls in file_data["classes"]
    ]

    functions = []
    for path, file_data in raw_files.items():
        for fn in file_data["functions"]:
            functions.append(
                {
                    "name": fn["name"],
                    "signature": fn["signature"],
                    "module_path": path,
                    "class_name": None,
                }
            )
        for cls in file_data["classes"]:
            for fn in cls["functions"]:
                functions.append(
                    {
                        "name": fn["name"],
                        "signature": fn["signature"],
                        "module_path": path,
                        "class_name": cls["name"],
                    }
                )

    imports = _resolve_ts_imports(raw_files, known_paths)
    calls = _resolve_ts_calls(raw_files, known_paths)

    return {
        "modules": modules,
        "classes": classes,
        "functions": functions,
        "calls": calls,
        "imports": imports,
    }


def _parse_one(parser: Parser, abs_path: str) -> dict:
    with open(abs_path, "rb") as f:
        source = f.read()
    tree = parser.parse(source)
    return _extract_ts_file(tree.root_node)


def _iter_ts_files(repo_path: str, extensions: tuple):
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith(extensions):
                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, repo_path).replace(os.sep, "/")
                yield rel_path, abs_path


def _extract_ts_file(root_node) -> dict:
    """Same top-level dispatch as js_extractor._extract_file — reuses the
    identical node-extraction helpers, since every construct's shape is
    confirmed identical between the JS and TS grammars. `interface`/`type
    alias` declarations simply don't match any branch below and are
    silently skipped, same as any other unrecognized top-level statement."""
    functions = []
    classes = []
    raw_imports = []

    for node in root_node.children:
        _extract_ts_statement(node, functions, classes, raw_imports)

    return {"functions": functions, "classes": classes, "imports": raw_imports}


def _extract_ts_statement(node, functions: list, classes: list, raw_imports: list) -> None:
    if node.type == "export_statement":
        inner = node.child_by_field_name("declaration") or node.child_by_field_name("value")
        if inner is not None:
            _extract_ts_statement(inner, functions, classes, raw_imports)
        return

    if node.type in ("function_declaration", "function_expression"):
        functions.append(_extract_function(node))
    elif node.type == "class_declaration":
        classes.append(_extract_class(node))
    elif node.type in ("lexical_declaration", "variable_declaration"):
        functions.extend(_extract_ts_declared_functions(node))
        raw_imports.extend(_extract_ts_declared_requires(node))
    elif node.type == "import_statement":
        raw_imports.extend(_extract_import(node))
    elif node.type == "expression_statement" and node.child_count:
        req = _extract_require(node.children[0])
        if req is not None:
            raw_imports.append(req)


def _extract_ts_declared_functions(node) -> list:
    results = []
    for child in node.children:
        if child.type != "variable_declarator":
            continue
        name_node = child.child_by_field_name("name")
        value_node = child.child_by_field_name("value")
        if name_node is None or value_node is None:
            continue
        if value_node.type in ("arrow_function", "function_expression"):
            results.append(_extract_function(value_node, name_override=name_node.text.decode()))
    return results


def _extract_ts_declared_requires(node) -> list:
    results = []
    for child in node.children:
        if child.type != "variable_declarator":
            continue
        value_node = child.child_by_field_name("value")
        if value_node is None:
            continue
        req = _extract_require(value_node)
        if req is not None:
            results.append(req)
    return results


def _resolve_ts_imports(raw_files: dict, known_paths: set) -> list:
    edges = set()
    for path, file_data in raw_files.items():
        for spec, _imported_name, _alias in file_data["imports"]:
            target_path = _resolve_ts_module_path(spec, path, known_paths)
            if target_path and target_path != path:
                edges.add((path, target_path))
    return [{"from": src, "to": dst} for src, dst in edges]


def _resolve_ts_module_path(spec: str, importer_path: str, known_paths: set) -> str | None:
    if not spec.startswith("."):
        return None
    importer_dir = os.path.dirname(importer_path)
    candidate = os.path.normpath(os.path.join(importer_dir, spec)).replace(os.sep, "/")
    for suffix in ("", ".ts", ".tsx", "/index.ts", "/index.tsx"):
        probe = candidate + suffix
        if probe in known_paths:
            return probe
    return None


def _resolve_ts_calls(raw_files: dict, known_paths: set) -> list:
    """Same 3-pattern deterministic resolution as js_extractor._resolve_calls
    (plain same-file calls, `this.x()` methods, named-import calls) — logic
    duplicated rather than imported since it closes over TS's own
    known_paths/module-resolution, but the algorithm is identical."""
    module_functions = {
        path: {fn["name"] for fn in fd["functions"]} for path, fd in raw_files.items()
    }
    module_classes = {
        path: {cls["name"]: {fn["name"] for fn in cls["functions"]} for cls in fd["classes"]}
        for path, fd in raw_files.items()
    }

    imported_symbols = {}
    for path, file_data in raw_files.items():
        symbols = {}
        for spec, imported_name, alias in file_data["imports"]:
            if imported_name in (None, "default", "*"):
                continue
            target_path = _resolve_ts_module_path(spec, path, known_paths)
            if target_path:
                symbols[alias] = (target_path, imported_name)
        imported_symbols[path] = symbols

    calls = set()

    def resolve_plain(caller_module: str, name: str):
        if name in module_functions.get(caller_module, ()):
            return (caller_module, None, name)
        target = imported_symbols.get(caller_module, {}).get(name)
        if target:
            target_path, orig_name = target
            if orig_name in module_functions.get(target_path, ()):
                return (target_path, None, orig_name)
        return None

    def resolve_this(caller_module: str, caller_class: str, name: str):
        if caller_class and name in module_classes.get(caller_module, {}).get(caller_class, ()):
            return (caller_module, caller_class, name)
        return None

    for path, file_data in raw_files.items():
        for fn in file_data["functions"]:
            caller_key = (path, None, fn["name"])
            for kind, callee_name in fn["calls"]:
                if kind == "plain":
                    callee_key = resolve_plain(path, callee_name)
                    if callee_key:
                        calls.add((caller_key, callee_key))
        for cls in file_data["classes"]:
            for fn in cls["functions"]:
                caller_key = (path, cls["name"], fn["name"])
                for kind, callee_name in fn["calls"]:
                    if kind == "plain":
                        callee_key = resolve_plain(path, callee_name)
                    else:
                        callee_key = resolve_this(path, cls["name"], callee_name)
                    if callee_key:
                        calls.add((caller_key, callee_key))

    return [
        {
            "caller_module": c[0][0], "caller_class": c[0][1], "caller_name": c[0][2],
            "callee_module": c[1][0], "callee_class": c[1][1], "callee_name": c[1][2],
        }
        for c in calls
    ]
