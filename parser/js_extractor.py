"""Tree-sitter based parsing of JavaScript source into the SAME output
shape parser/ast_extractor.py produces for Python, so graph/loader.py
needs no changes to accept it (see ast_extractor.parse_repo's docstring
for the shape: modules/classes/functions/calls/imports).

CALLS/IMPORTS resolution mirrors ast_extractor.py's scope and
limitations: a bounded set of deterministic patterns, not full type
inference. Unlike Python's dotted-module-name resolution, JS resolves
imports through relative FILE PATHS (see _resolve_module_path) — bare
package specifiers (npm packages) are external and left unresolved,
same as Python leaves external library imports unresolved.
"""
from __future__ import annotations

import os

import tree_sitter_javascript as tsjavascript
from tree_sitter import Language, Parser

JS_LANGUAGE = Language(tsjavascript.language())

_SKIP_DIRS = {".git", "venv", ".venv", "env", "__pycache__", "node_modules"}
_EXTENSIONS = (".js", ".jsx")

# Node types that start a new CALLS scope — a nested definition's calls
# belong to its own scope, not the enclosing one (mirrors ast_extractor.py's
# treatment of Python nested defs: they're simply not attributed upward).
_SCOPE_BOUNDARY_TYPES = (
    "function_declaration",
    "function_expression",
    "arrow_function",
    "class_declaration",
    "method_definition",
)


def parse_repo(repo_path: str) -> dict:
    """Parse every .js/.jsx file under repo_path and resolve CALLS/IMPORTS
    edges. Returns the same dict shape as ast_extractor.parse_repo."""
    parser = Parser(JS_LANGUAGE)

    raw_files = {}
    for rel_path, abs_path in _iter_js_files(repo_path):
        with open(abs_path, "rb") as f:
            source = f.read()
        tree = parser.parse(source)
        raw_files[rel_path] = _extract_file(tree.root_node)

    known_paths = set(raw_files)

    modules = [
        {"path": path, "language": "javascript", "layer_type": None} for path in raw_files
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

    imports = _resolve_imports(raw_files, known_paths)
    calls = _resolve_calls(raw_files, known_paths)

    return {
        "modules": modules,
        "classes": classes,
        "functions": functions,
        "calls": calls,
        "imports": imports,
    }


def _iter_js_files(repo_path: str):
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith(_EXTENSIONS):
                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, repo_path).replace(os.sep, "/")
                yield rel_path, abs_path


def _resolve_module_path(spec: str, importer_path: str, known_paths: set) -> str | None:
    """Resolve a relative import/require specifier (e.g. './utils',
    '../lib/foo') to a repo-relative path that was actually parsed. Bare
    package specifiers (no leading '.') are external npm packages and
    intentionally left unresolved."""
    if not spec.startswith("."):
        return None
    importer_dir = os.path.dirname(importer_path)
    candidate = os.path.normpath(os.path.join(importer_dir, spec)).replace(os.sep, "/")
    for suffix in ("", ".js", ".jsx", "/index.js", "/index.jsx"):
        probe = candidate + suffix
        if probe in known_paths:
            return probe
    return None


def _string_value(node) -> str:
    text = node.text.decode()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"', "`"):
        return text[1:-1]
    return text


def _extract_file(root_node) -> dict:
    """Extract module-level functions, classes+methods, and raw imports
    (unresolved) from one file's AST — direct children of root_node only,
    same "no descending into nested scopes" limitation ast_extractor.py has
    for Python."""
    functions = []
    classes = []
    raw_imports = []

    for node in root_node.children:
        _extract_statement(node, functions, classes, raw_imports)

    return {"functions": functions, "classes": classes, "imports": raw_imports}


def _extract_statement(node, functions: list, classes: list, raw_imports: list) -> None:
    """Dispatch one top-level statement, unwrapping `export` one layer first
    (mirrors ast_extractor.py's `decorated_definition` unwrap for Python)."""
    if node.type == "export_statement":
        inner = node.child_by_field_name("declaration") or node.child_by_field_name("value")
        if inner is not None:
            _extract_statement(inner, functions, classes, raw_imports)
        return

    if node.type in ("function_declaration", "function_expression"):
        functions.append(_extract_function(node))
    elif node.type == "class_declaration":
        classes.append(_extract_class(node))
    elif node.type in ("lexical_declaration", "variable_declaration"):
        functions.extend(_extract_declared_functions(node))
        raw_imports.extend(_extract_declared_requires(node))
    elif node.type == "import_statement":
        raw_imports.extend(_extract_import(node))
    elif node.type == "expression_statement" and node.child_count:
        req = _extract_require(node.children[0])
        if req is not None:
            raw_imports.append(req)


def _extract_declared_functions(node) -> list:
    """Extract Function entries from `const/let/var` declarations whose
    initializer is an arrow function or function expression — the common
    `const foo = () => {...}` pattern. Other initializers (plain values)
    are ignored; this extractor doesn't model variables generally."""
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


def _extract_declared_requires(node) -> list:
    """Extract IMPORTS entries from `const/let/var` declarations whose
    initializer is a `require(...)` call — covers both `const foo =
    require('./foo')` and destructured `const { a, b } = require('./foo')`
    (the destructured names aren't tracked for CALLS resolution, same as
    Python leaves plain `import X` untracked for calls)."""
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


def _extract_function(node, name_override: str | None = None) -> dict:
    name_node = node.child_by_field_name("name")
    name = name_override or (name_node.text.decode() if name_node is not None else "<anonymous>")

    params_node = node.child_by_field_name("parameters")
    if params_node is not None:
        params_text = params_node.text.decode()
    else:
        param_node = node.child_by_field_name("parameter")  # single-param arrow: `a => ...`
        params_text = f"({param_node.text.decode()})" if param_node is not None else "()"

    body_node = node.child_by_field_name("body")
    return {
        "name": name,
        "signature": f"{name}{params_text}",
        "calls": _extract_calls(body_node) if body_node is not None else [],
    }


def _extract_class(node) -> dict:
    name_node = node.child_by_field_name("name")
    body_node = node.child_by_field_name("body")
    methods = []
    if body_node is not None:
        for child in body_node.children:
            if child.type == "method_definition":
                methods.append(_extract_function(child))
    name = name_node.text.decode() if name_node is not None else "<anonymous>"
    return {"name": name, "functions": methods}


def _extract_calls(node) -> list:
    """Recursively collect raw call sites within a function/method body,
    without descending into nested scopes (their calls belong to their own
    scope) — same behavior as ast_extractor.py's Python equivalent."""
    calls = []

    def walk(n):
        if n.type in _SCOPE_BOUNDARY_TYPES:
            return
        if n.type == "call_expression":
            fn_node = n.child_by_field_name("function")
            if fn_node is not None:
                if fn_node.type == "identifier":
                    calls.append(("plain", fn_node.text.decode()))
                elif fn_node.type == "member_expression":
                    obj_node = fn_node.child_by_field_name("object")
                    attr_node = fn_node.child_by_field_name("property")
                    if obj_node is not None and attr_node is not None and obj_node.type == "this":
                        calls.append(("this", attr_node.text.decode()))
        for child in n.children:
            walk(child)

    walk(node)
    return calls


def _extract_require(node) -> tuple | None:
    """Returns (spec, None, None) if `node` is a bare `require('spec')`
    call expression, else None."""
    if node.type != "call_expression":
        return None
    fn_node = node.child_by_field_name("function")
    if fn_node is None or fn_node.type != "identifier" or fn_node.text.decode() != "require":
        return None
    args_node = node.child_by_field_name("arguments")
    if args_node is None:
        return None
    for arg in args_node.children:
        if arg.type == "string":
            return (_string_value(arg), None, None)
    return None


def _extract_import(node) -> list:
    """Returns a list of (spec, imported_name_or_None, local_alias_or_name).

    `spec` is a raw import specifier (relative path or bare package name),
    resolved to a repo path later via _resolve_module_path. `imported_name`
    uses "default"/"*" sentinels for default/namespace imports, since (unlike
    Python's `from X import name`) there's no fixed target-module symbol
    name to resolve calls against for those forms — _resolve_calls skips
    them accordingly.
    """
    results = []
    source_node = node.child_by_field_name("source")
    if source_node is None:
        return results
    spec = _string_value(source_node)

    clause = next((c for c in node.children if c.type == "import_clause"), None)
    if clause is None:
        return results  # bare `import 'mod'` — side-effect only, no names

    for child in clause.children:
        if child.type == "identifier":
            results.append((spec, "default", child.text.decode()))
        elif child.type == "named_imports":
            for spec_node in child.children:
                if spec_node.type != "import_specifier":
                    continue
                name_node = spec_node.child_by_field_name("name")
                alias_node = spec_node.child_by_field_name("alias")
                name = name_node.text.decode()
                alias = alias_node.text.decode() if alias_node is not None else name
                results.append((spec, name, alias))
        elif child.type == "namespace_import":
            ns_name = next((c.text.decode() for c in child.children if c.type == "identifier"), None)
            if ns_name:
                results.append((spec, "*", ns_name))
    return results


def _resolve_imports(raw_files: dict, known_paths: set) -> list:
    edges = set()
    for path, file_data in raw_files.items():
        for spec, _imported_name, _alias in file_data["imports"]:
            target_path = _resolve_module_path(spec, path, known_paths)
            if target_path and target_path != path:
                edges.add((path, target_path))
    return [{"from": src, "to": dst} for src, dst in edges]


def _resolve_calls(raw_files: dict, known_paths: set) -> list:
    """Resolve raw call sites to (caller_key, callee_key) Function pairs.

    Only these deterministic patterns are resolved (no type inference):
      1. `name(...)` matching a function defined at module level in the
         same file.
      2. `this.name(...)` matching a method defined on the enclosing class.
      3. `name(...)` where `name` was brought in via a named ES import
         (`import { name } from './mod'`) and matches a function in the
         resolved target module.
    Default/namespace imports (`import Foo from './Foo'`) and arbitrary
    `obj.method()`/`require(...)()` patterns are left unresolved — same
    "don't guess" philosophy as ast_extractor.py.
    """
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
                continue  # no fixed target-module symbol name to resolve against
            target_path = _resolve_module_path(spec, path, known_paths)
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
