"""Which modules use which external packages — a deterministic regex scan
(the parser keeps only imports that resolve inside the repository). ADR
reconstruction uses it to find the code a dependency decision affects.
"""
import os
import re

_PY_IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import\b|import\s+([A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*))",
                        re.MULTILINE)
_JS_IMPORT = re.compile(r"""(?:\bfrom\s+|\brequire\s*\(\s*|\bimport\s*\(\s*|^\s*import\s+)['"]([^'"]+)['"]""",
                        re.MULTILINE)

# PyPI distribution names whose import name differs.
_PY_IMPORT_NAMES = {
    "pyjwt": "jwt", "python-jose": "jose", "beautifulsoup4": "bs4", "python-dotenv": "dotenv",
    "psycopg2-binary": "psycopg2", "psycopg-binary": "psycopg", "scikit-learn": "sklearn", "pyyaml": "yaml",
    "pillow": "PIL", "opencv-python": "cv2", "mysqlclient": "MySQLdb", "pymysql": "pymysql",
    "python-multipart": "multipart", "attrs": "attr", "protobuf": "google", "msgpack-python": "msgpack",
    "typing-extensions": "typing_extensions", "email-validator": "email_validator", "aioredis": "aioredis",
    "kafka-python": "kafka", "confluent-kafka": "confluent_kafka", "aio-pika": "aio_pika",
    "strawberry-graphql": "strawberry", "tortoise-orm": "tortoise", "django-rest-framework": "rest_framework",
    "djangorestframework": "rest_framework", "elasticsearch-dsl": "elasticsearch_dsl", "sentry-sdk": "sentry_sdk",
}


def import_name(package: str, ecosystem: str) -> str:
    if ecosystem == "npm":
        return package
    return _PY_IMPORT_NAMES.get(package.lower(), package.lower().replace("-", "_"))


def scan_file(path: str, text: str) -> set:
    """Top-level external import names in one source file (relative imports
    excluded). For npm scoped packages the scope is kept: @nestjs/core."""
    names = set()
    if path.endswith(".py"):
        for from_mod, plain in _PY_IMPORT.findall(text):
            for mod in ([from_mod] if from_mod else [m.strip() for m in plain.split(",")]):
                if mod and not mod.startswith("."):
                    names.add(mod.split(".")[0])
    elif path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
        for spec in _JS_IMPORT.findall(text):
            if spec.startswith((".", "/")):
                continue
            parts = spec.split("/")
            names.add("/".join(parts[:2]) if spec.startswith("@") else parts[0])
    return names


def scan_repo(repo_path: str, module_paths: list) -> dict:
    """module path -> set of external import names."""
    usage = {}
    for rel in module_paths:
        try:
            with open(os.path.join(repo_path, rel), "r", encoding="utf-8", errors="replace") as f:
                usage[rel] = scan_file(rel, f.read())
        except OSError:
            continue
    return usage


def modules_using(usage: dict, package: str, ecosystem: str) -> list:
    name = import_name(package, ecosystem)
    return sorted(path for path, names in usage.items() if name in names or package in names)
