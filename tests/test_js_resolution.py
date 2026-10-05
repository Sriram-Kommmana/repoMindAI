"""JavaScript/TypeScript import and call resolution."""
from parser import ast_extractor


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _edges(data):
    imports = {(e["from"], e["to"]) for e in data["imports"]}
    calls = {(c["caller_module"], c["caller_name"], c["callee_module"], c["callee_name"]) for c in data["calls"]}
    return imports, calls


def test_destructured_require_calls_resolve(tmp_path):
    _write(tmp_path, "src/db/users.js", "function findUser(id) { return id; }\nmodule.exports = { findUser };\n")
    _write(tmp_path, "src/api/handler.js",
           "const { findUser, findUser: lookup } = require('../db/users');\n"
           "function handle(id) { return findUser(id); }\n"
           "function handle2(id) { return lookup(id); }\n")
    imports, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert ("src/api/handler.js", "src/db/users.js") in imports
    assert ("src/api/handler.js", "handle", "src/db/users.js", "findUser") in calls
    assert ("src/api/handler.js", "handle2", "src/db/users.js", "findUser") in calls


def test_plain_require_still_only_imports(tmp_path):
    _write(tmp_path, "a.js", "function f() {}\nmodule.exports = { f };\n")
    _write(tmp_path, "b.js", "const a = require('./a');\nfunction g() { return a.f(); }\n")
    imports, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert ("b.js", "a.js") in imports and calls == set()


def test_es_named_imports_in_typescript(tmp_path):
    _write(tmp_path, "src/services/user.service.ts", "export function getUser(id: string): string { return id; }\n")
    _write(tmp_path, "src/controllers/user.controller.ts",
           "import { getUser } from '../services/user.service';\n"
           "export function show(id: string) { return getUser(id); }\n")
    imports, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert ("src/controllers/user.controller.ts", "src/services/user.service.ts") in imports
    assert ("src/controllers/user.controller.ts", "show", "src/services/user.service.ts", "getUser") in calls
