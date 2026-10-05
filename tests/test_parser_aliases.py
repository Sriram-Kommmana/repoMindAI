"""Python import resolution for src-layout and subfolder-rooted repos."""
from parser import ast_extractor


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_src_layout_and_package_imports_resolve(tmp_path):
    _write(tmp_path, "src/pkg/__init__.py", "")
    _write(tmp_path, "src/pkg/b.py", "def f():\n    return 1\n")
    _write(tmp_path, "src/pkg/a.py", "import pkg\nfrom pkg.b import f\n\ndef g():\n    return f()\n")
    _write(tmp_path, "scripts/run.py", "from pkg.a import g\n\ndef main():\n    g()\n")

    data = ast_extractor.parse_repo(str(tmp_path))
    imports = {(e["from"], e["to"]) for e in data["imports"]}
    assert ("src/pkg/a.py", "src/pkg/b.py") in imports
    assert ("src/pkg/a.py", "src/pkg/__init__.py") in imports
    assert ("scripts/run.py", "src/pkg/a.py") in imports

    calls = {(c["caller_module"], c["caller_name"], c["callee_module"], c["callee_name"]) for c in data["calls"]}
    assert ("src/pkg/a.py", "g", "src/pkg/b.py", "f") in calls
    assert ("scripts/run.py", "main", "src/pkg/a.py", "g") in calls


def test_ambiguous_suffix_is_not_guessed(tmp_path):
    _write(tmp_path, "svc_a/utils.py", "def h():\n    pass\n")
    _write(tmp_path, "svc_b/utils.py", "def h():\n    pass\n")
    _write(tmp_path, "main.py", "from utils import h\n")
    data = ast_extractor.parse_repo(str(tmp_path))
    assert [e for e in data["imports"] if e["from"] == "main.py"] == []
