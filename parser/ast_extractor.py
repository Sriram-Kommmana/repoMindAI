"""Tree-sitter based parsing of a Python repository into Phase 1 graph data.

Phase 1 scope only: current-state structure (no temporal versioning, no
Git history). CALLS resolution intentionally covers a limited set of
deterministic patterns rather than full type inference — see the
docstring on `_resolve_calls` for exactly what is and isn't resolved.
"""
from __future__ import annotations

import os

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from parser import js_extractor, ts_extractor

PY_LANGUAGE = Language(tspython.language())

_SKIP_DIRS = {".git", "venv", ".venv", "env", "__pycache__", "node_modules"}

# Phase 2: layer classification for the layered-architecture fixture, by
# filename convention. Files not listed here get layer_type=None.
_LAYER_BY_FILENAME = {
    "controller.py": "controller",
    "service.py": "service",
    "database.py": "database",
}


def parse_repo(repo_path: str) -> dict:
    """Parse every supported source file under repo_path (Python, plus
    JavaScript/TypeScript via the language-specific extractors) and merge
    their results into one dict with keys: modules, classes, functions,
    calls, imports — plain lists of dicts/tuples ready for graph/loader.py
    to write. Each language extractor produces this exact same shape
    independently, so merging is a plain per-key concatenation.
    """
    results = [
        _parse_python_repo(repo_path),
        js_extractor.parse_repo(repo_path),
        ts_extractor.parse_repo(repo_path),
    ]
    return {
        key: [item for r in results for item in r[key]]
        for key in ("modules", "classes", "functions", "calls", "imports")
    }


def _parse_python_repo(repo_path: str) -> dict:
    """Parse every .py file under repo_path and resolve CALLS/IMPORTS edges.

    Returns a dict with keys: modules, classes, functions, calls, imports —
    plain lists of dicts/tuples ready for graph/loader.py to write.
    """
    parser = Parser(PY_LANGUAGE)

    raw_files = {}
    for rel_path, abs_path in _iter_py_files(repo_path):
        with open(abs_path, "rb") as f:
            source = f.read()
        tree = parser.parse(source)
        raw_files[rel_path] = _extract_file(tree.root_node, rel_path)

    dotted_to_path = {_dotted_name(path): path for path in raw_files}

    modules = [
        {
            "path": path,
            "language": "python",
            "layer_type": _LAYER_BY_FILENAME.get(os.path.basename(path)),
        }
        for path in raw_files
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

    imports = _resolve_imports(raw_files, dotted_to_path)
    calls = _resolve_calls(raw_files, dotted_to_path)

    return {
        "modules": modules,
        "classes": classes,
        "functions": functions,
        "calls": calls,
        "imports": imports,
    }


def _iter_py_files(repo_path: str):
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith(".py"):
                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, repo_path).replace(os.sep, "/")
                yield rel_path, abs_path


def _dotted_name(module_path: str) -> str:
    return module_path[:-3].replace("/", ".") if module_path.endswith(".py") else module_path


def _extract_file(root_node, rel_path: str) -> dict:
    """Extract module-level functions, classes+methods, raw imports, and raw
    call sites (unresolved) from one file's AST."""
    functions = []
    classes = []
    raw_imports = []

    for node in root_node.children:
        if node.type == "decorated_definition":
            node = node.child_by_field_name("definition")
        if node.type == "function_definition":
            functions.append(_extract_function(node))
        elif node.type == "class_definition":
            classes.append(_extract_class(node))
        elif node.type in ("import_statement", "import_from_statement"):
            raw_imports.extend(_extract_import(node, rel_path))

    return {
        "functions": functions,
        "classes": classes,
        "imports": raw_imports,
    }


def _extract_function(node) -> dict:
    name_node = node.child_by_field_name("name")
    params_node = node.child_by_field_name("parameters")
    body_node = node.child_by_field_name("body")
    name = name_node.text.decode()
    signature = f"{name}{params_node.text.decode()}"
    return {
        "name": name,
        "signature": signature,
        "calls": _extract_calls(body_node) if body_node is not None else [],
    }


def _extract_class(node) -> dict:
    name_node = node.child_by_field_name("name")
    body_node = node.child_by_field_name("body")
    methods = []
    if body_node is not None:
        for child in body_node.children:
            if child.type == "decorated_definition":
                child = child.child_by_field_name("definition")
            if child.type == "function_definition":
                methods.append(_extract_function(child))
    return {"name": name_node.text.decode(), "functions": methods}


def _extract_calls(node) -> list:
    """Recursively collect raw call sites within a function/method body,
    without descending into nested function/class definitions (their calls
    belong to their own scope)."""
    calls = []

    def walk(n):
        if n.type in ("function_definition", "class_definition"):
            return
        if n.type == "call":
            fn_node = n.child_by_field_name("function")
            if fn_node.type == "identifier":
                calls.append(("plain", fn_node.text.decode()))
            elif fn_node.type == "attribute":
                obj_node = fn_node.child_by_field_name("object")
                attr_node = fn_node.child_by_field_name("attribute")
                if obj_node.type == "identifier" and obj_node.text.decode() == "self":
                    calls.append(("self", attr_node.text.decode()))
        for child in n.children:
            walk(child)

    walk(node)
    return calls


def _resolve_relative_module(node, rel_path: str) -> str | None:
    """Resolve a `relative_import` node (e.g. `..a.a`, raw text still carrying
    its leading dots) to an absolute dotted module name, relative to the
    importing file's own package.

    Follows the same level-counting rule as Python's importlib
    (`_resolve_name`): each leading dot drops one trailing dotted segment
    from the importing module's own package name. Returns None if there's
    no dotted name to resolve against (e.g. a bare `from . import x`, or a
    relative import that goes above the top-level package).
    """
    prefix_node = next((c for c in node.children if c.type == "import_prefix"), None)
    if prefix_node is None:
        return None
    level = prefix_node.text.decode().count(".")
    name_node = next((c for c in node.children if c.type == "dotted_name"), None)
    trailing = name_node.text.decode() if name_node is not None else None

    own_dotted = _dotted_name(rel_path)
    own_package = own_dotted.rsplit(".", 1)[0] if "." in own_dotted else ""
    base = own_package.rsplit(".", level - 1)[0]

    if trailing:
        return f"{base}.{trailing}" if base else trailing
    return base or None


def _extract_import(node, rel_path: str) -> list:
    """Returns a list of (module_stem, imported_name_or_None, local_alias_or_name).

    For `import X [as Y]`: (X, None, Y or X).
    For `from X import a, b as c`: (X, a, a) and (X, b, c) respectively.
    """
    results = []
    if node.type == "import_statement":
        for child in node.children:
            if child.type == "dotted_name":
                stem = child.text.decode()
                results.append((stem, None, stem))
            elif child.type == "aliased_import":
                dotted = child.child_by_field_name("name")
                alias = child.child_by_field_name("alias")
                results.append((dotted.text.decode(), None, alias.text.decode()))
    elif node.type == "import_from_statement":
        module_node = node.child_by_field_name("module_name")
        if module_node is None:
            return results  # no module name at all — not seen in practice, nothing to resolve
        if module_node.type == "relative_import":
            stem = _resolve_relative_module(module_node, rel_path)
            if stem is None:
                return results
        else:
            stem = module_node.text.decode()
        for child in node.children:
            if child.id == module_node.id:
                continue
            if child.type == "dotted_name":
                name = child.text.decode()
                results.append((stem, name, name))
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                results.append((stem, name_node.text.decode(), alias_node.text.decode()))
            elif child.type == "wildcard_import":
                # `from X import *` — no fixed symbol to track for CALLS
                # resolution, but the module-level IMPORTS edge still holds.
                results.append((stem, None, None))
    return results


def _resolve_imports(raw_files: dict, dotted_to_path: dict) -> list:
    edges = set()
    for path, file_data in raw_files.items():
        for stem, _imported_name, _alias in file_data["imports"]:
            target_path = dotted_to_path.get(stem)
            if target_path and target_path != path:
                edges.add((path, target_path))
    return [{"from": src, "to": dst} for src, dst in edges]


def _resolve_calls(raw_files: dict, dotted_to_path: dict) -> list:
    """Resolve raw call sites to (caller_key, callee_key) Function pairs.

    Only these deterministic patterns are resolved (no type inference):
      1. `name(...)` matching a function defined at module level in the
         same module.
      2. `self.name(...)` matching a method defined on the enclosing class.
      3. `name(...)` where `name` was brought in via `from X import name`
         and matches a function in module X, or matches a class in X (in
         which case the edge targets that class's `__init__`).
    Anything else (arbitrary `obj.method()`, `module.func()` via plain
    `import module`) is left unresolved.
    """
    module_functions = {
        path: {fn["name"] for fn in fd["functions"]} for path, fd in raw_files.items()
    }
    module_classes = {
        path: {cls["name"]: {fn["name"] for fn in cls["functions"]} for cls in fd["classes"]}
        for path, fd in raw_files.items()
    }

    # local_name -> (target_module_path, original_name), only for
    # `from X import name [as alias]` where X resolves inside the repo.
    imported_symbols = {}
    for path, file_data in raw_files.items():
        symbols = {}
        for stem, imported_name, alias in file_data["imports"]:
            if imported_name is None:
                continue  # plain `import X` — not tracked for call resolution
            target_path = dotted_to_path.get(stem)
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
            if orig_name in module_classes.get(target_path, {}):
                if "__init__" in module_classes[target_path][orig_name]:
                    return (target_path, orig_name, "__init__")
        return None

    def resolve_self(caller_module: str, caller_class: str, name: str):
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
                        callee_key = resolve_self(path, cls["name"], callee_name)
                    if callee_key:
                        calls.add((caller_key, callee_key))

    return [
        {
            "caller_module": c[0][0], "caller_class": c[0][1], "caller_name": c[0][2],
            "callee_module": c[1][0], "callee_class": c[1][1], "callee_name": c[1][2],
        }
        for c in calls
    ]
