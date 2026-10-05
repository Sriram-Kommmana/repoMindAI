"""Decision-point detection for ADR reconstruction (pure functions over git
history and snapshots; no LLM).

A decision point is a commit where an architectural choice became visible:
  - dependency_change: a package added, removed, or replaced in a manifest
    (requirements*.txt, pyproject.toml, Pipfile, package.json)
  - initial_stack: the dependencies a manifest started with
  - infrastructure: Docker, CI, migrations, TypeScript or bundler config introduced
  - structure: a top-level (or src/-level) folder with several modules
    appearing or disappearing between snapshots
  - restructure: a commit that moves many files
  - violation: an architecture violation introduced or resolved
Each emits {id, sha, kind, subject, files, packages, significance, ...};
rank() keeps the most significant few.
"""
import fnmatch
import hashlib
import json
import math
import os
import re
import subprocess

from history import git

MAX_DECISIONS = 8
MAX_PER_KIND = 3
STRUCTURE_MIN_MODULES = 3
RESTRUCTURE_MIN_RENAMES = 5

KIND_WEIGHT = {"dependency_replace": 1.0, "dependency_change": 0.8, "initial_stack": 0.7, "structure": 0.7,
               "restructure": 0.6, "infrastructure": 0.55, "violation_introduced": 0.5, "violation_resolved": 0.45}

# Curated packages: category boosts significance and names the decision well.
CATEGORIES = {
    "web framework": ["flask", "django", "fastapi", "starlette", "tornado", "sanic", "bottle", "pyramid", "falcon",
                      "litestar", "express", "koa", "fastify", "@hapi/hapi", "hapi", "@nestjs/core", "next", "nuxt",
                      "@remix-run/node", "hono"],
    "frontend framework": ["react", "vue", "@angular/core", "svelte", "solid-js", "preact", "jquery"],
    "ORM / data access": ["sqlalchemy", "sqlmodel", "peewee", "tortoise-orm", "pony", "django-orm", "mongoengine",
                          "beanie", "odmantic", "mongoose", "sequelize", "typeorm", "prisma", "@prisma/client",
                          "knex", "objection", "@mikro-orm/core", "drizzle-orm"],
    "database driver": ["psycopg2", "psycopg2-binary", "psycopg", "asyncpg", "pymysql", "mysqlclient",
                        "pymongo", "motor", "sqlite3", "pg", "mysql", "mysql2", "mongodb", "better-sqlite3",
                        "cassandra-driver", "neo4j", "elasticsearch"],
    "cache": ["redis", "aioredis", "ioredis", "pymemcache", "memcached", "node-cache"],
    "message queue / jobs": ["celery", "rq", "dramatiq", "kafka-python", "confluent-kafka", "aiokafka", "pika",
                             "aio-pika", "kombu", "bull", "bullmq", "amqplib", "kafkajs", "agenda"],
    "migrations": ["alembic", "yoyo-migrations", "flyway", "umzug", "db-migrate"],
    "validation / schemas": ["pydantic", "marshmallow", "cerberus", "attrs", "joi", "yup", "zod", "class-validator",
                             "ajv"],
    "auth / security": ["pyjwt", "python-jose", "passlib", "authlib", "bcrypt", "argon2-cffi", "jsonwebtoken",
                        "passport", "bcryptjs", "next-auth", "helmet"],
    "HTTP client": ["requests", "httpx", "aiohttp", "urllib3", "axios", "node-fetch", "got", "superagent"],
    "testing": ["pytest", "nose", "hypothesis", "jest", "mocha", "vitest", "jasmine", "chai", "cypress",
                "playwright", "@playwright/test", "supertest"],
    "build tooling": ["webpack", "vite", "rollup", "parcel", "esbuild", "babel", "@babel/core", "typescript",
                      "ts-node", "setuptools", "poetry", "hatchling"],
    "API style": ["graphene", "strawberry-graphql", "ariadne", "graphql", "apollo-server", "@apollo/server",
                  "grpcio", "@grpc/grpc-js", "djangorestframework", "socket.io", "ws", "channels"],
    "server / runtime": ["gunicorn", "uvicorn", "hypercorn", "waitress", "pm2", "nodemon"],
    "observability": ["sentry-sdk", "@sentry/node", "prometheus-client", "opentelemetry-api", "winston", "pino",
                      "structlog", "loguru"],
    "cloud SDK": ["boto3", "aws-sdk", "@aws-sdk/client-s3", "google-cloud-storage", "azure-storage-blob"],
    "configuration": ["python-dotenv", "dotenv", "pydantic-settings", "dynaconf", "python-decouple", "config",
                      "convict", "envalid"],
}
# Folders that hold build output or docs, not architecture.
_NON_ARCHITECTURAL_FOLDERS = {"dist", "build", "out", "coverage", "docs", "doc", "site", "public", "static",
                              "assets", "vendor", "examples", "example", "node_modules", "__pycache__"}
# Unknown packages add significance with diminishing returns, so a regenerated
# lock-style requirements file listing many transitive dependencies doesn't
# outrank a deliberate choice of one known framework.
_UNCURATED_SIGNIFICANCE_CAP = 1.2
PACKAGE_CATEGORY = {pkg: cat for cat, pkgs in CATEGORIES.items() for pkg in pkgs}
_LOW_SIGNAL = re.compile(r"^(@types/|eslint|prettier|flake8|black$|pylint|mypy$|isort$|ruff$|pre-commit$|"
                         r"stylelint|husky$|lint-staged$|types-)")

INFRA_PATTERNS = {
    "Dockerfile": "Docker containerization", "docker-compose*.yml": "Docker Compose services",
    "docker-compose*.yaml": "Docker Compose services", ".github/workflows/*": "GitHub Actions CI",
    ".gitlab-ci.yml": "GitLab CI", "Jenkinsfile": "Jenkins CI", ".travis.yml": "Travis CI",
    ".circleci/config.yml": "CircleCI", "alembic.ini": "Alembic database migrations",
    "*/migrations/*.py": "database migrations", "tsconfig.json": "TypeScript",
    "webpack.config.*": "webpack bundling", "vite.config.*": "Vite bundling", "k8s/*": "Kubernetes deployment",
    "kubernetes/*": "Kubernetes deployment", "helm/*": "Helm charts", "serverless.yml": "Serverless deployment",
    "terraform/*": "Terraform infrastructure", "*.tf": "Terraform infrastructure",
}

_MANIFEST_NAMES = {"pyproject.toml", "Pipfile", "package.json"}


def is_manifest(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name in _MANIFEST_NAMES or (name.startswith("requirements") and name.endswith(".txt"))


def _norm(name: str) -> str:
    return name.strip().strip("\"'").lower().replace("_", "-")


def _requirement_name(spec: str) -> str:
    spec = spec.strip().strip("\"'")
    if not spec or spec.startswith(("-", "#", "git+", "http")):
        return ""
    return _norm(re.split(r"[<>=!~;\[\s@(]", spec, 1)[0])


def _toml_section(text: str, header: str) -> str:
    match = re.search(rf"^\[{re.escape(header)}\]\s*$(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def _toml_keys(section: str) -> list:
    return [m.group(1) for m in re.finditer(r'^\s*"?([A-Za-z0-9_.@/-]+)"?\s*=', section, re.MULTILINE)]


def _toml_array(text: str, key: str) -> list:
    """String items of a TOML array; quote-aware, since items like
    "SQLAlchemy[asyncio]" contain brackets themselves."""
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*\[", text, re.MULTILINE)
    if not match:
        return []
    items, quote, current = [], None, []
    for ch in text[match.end():]:
        if quote:
            if ch == quote:
                items.append("".join(current))
                quote, current = None, []
            else:
                current.append(ch)
        elif ch in "\"'":
            quote = ch
        elif ch == "]":
            break
    return items


def parse_manifest(path: str, text: str) -> dict:
    """package -> {"dev": bool, "ecosystem": "pypi"|"npm"}. Tolerant: a
    manifest that can't be parsed yields {}."""
    name = path.rsplit("/", 1)[-1]
    deps = {}
    if not text:
        return deps
    if name == "package.json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return deps
        for section, dev in (("dependencies", False), ("peerDependencies", False), ("devDependencies", True)):
            for pkg in (data.get(section) or {}):
                deps.setdefault(pkg.lower(), {"dev": dev, "ecosystem": "npm"})
        return deps
    if name.startswith("requirements"):
        dev = any(tag in name for tag in ("dev", "test", "lint", "doc"))
        for line in text.splitlines():
            pkg = _requirement_name(line.split("#", 1)[0])
            if pkg:
                deps[pkg] = {"dev": dev, "ecosystem": "pypi"}
        return deps
    if name == "pyproject.toml":
        project = _toml_section(text, "project")
        for spec in _toml_array(project, "dependencies"):
            if _requirement_name(spec):
                deps[_requirement_name(spec)] = {"dev": False, "ecosystem": "pypi"}
        for spec in re.findall(r"""["']([^"']+)["']""", _toml_section(text, "project.optional-dependencies")):
            if _requirement_name(spec):
                deps.setdefault(_requirement_name(spec), {"dev": True, "ecosystem": "pypi"})
        for pkg in _toml_keys(_toml_section(text, "tool.poetry.dependencies")):
            if pkg.lower() != "python":
                deps[_norm(pkg)] = {"dev": False, "ecosystem": "pypi"}
        for header in re.findall(r"^\[(tool\.poetry\.(?:dev-dependencies|group\.[\w-]+\.dependencies))\]", text,
                                 re.MULTILINE):
            for pkg in _toml_keys(_toml_section(text, header)):
                deps.setdefault(_norm(pkg), {"dev": True, "ecosystem": "pypi"})
        return deps
    if name == "Pipfile":
        for pkg in _toml_keys(_toml_section(text, "packages")):
            deps[_norm(pkg)] = {"dev": False, "ecosystem": "pypi"}
        for pkg in _toml_keys(_toml_section(text, "dev-packages")):
            deps.setdefault(_norm(pkg), {"dev": True, "ecosystem": "pypi"})
    return deps


class BlobReader:
    """Reads `rev:path` contents through one `git cat-file --batch` process."""

    def __init__(self, repo_path: str):
        self.proc = subprocess.Popen(["git", "-C", repo_path, "cat-file", "--batch"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self, rev: str, path: str) -> str:
        self.proc.stdin.write(f"{rev}:{path}\n".encode("utf-8"))
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) != 3:
            return ""  # "<object> missing"
        content = self.proc.stdout.read(int(header[2]))
        self.proc.stdout.read(1)
        return content.decode("utf-8", errors="replace")

    def close(self):
        self.proc.stdin.close()
        self.proc.wait()


def _decision_id(sha: str, kind: str, subject: str) -> str:
    return hashlib.sha1(f"{sha}|{kind}|{subject}".encode()).hexdigest()[:10]


def _decision(commit: dict, kind: str, subject: str, significance: float, files=None, packages=None, **extra):
    return {"id": _decision_id(commit["hash"], kind, subject), "sha": commit["hash"], "short": commit["short"],
            "date": commit["date"], "idx": commit.get("idx"), "kind": kind, "subject": subject,
            "commit_subject": commit.get("subject", ""), "significance": round(significance, 3),
            "files": sorted(files or {f["path"] for f in commit["files"]}), "packages": packages or [], **extra}


def _package_weight(pkg: str, dev: bool) -> float:
    weight = 1.5 if pkg in PACKAGE_CATEGORY else 0.6
    if dev:
        weight *= 0.4
    if _LOW_SIGNAL.match(pkg):
        weight *= 0.2
    return weight


def _describe(pkgs: list) -> str:
    return ", ".join(f"{p} ({PACKAGE_CATEGORY[p]})" if p in PACKAGE_CATEGORY else p for p in pkgs)


def _curated_first(pkgs: list) -> list:
    return sorted(pkgs, key=lambda p: (p not in PACKAGE_CATEGORY, bool(_LOW_SIGNAL.match(p)), p))


def _significance(pkgs: list, manifest: dict) -> float:
    curated = sum(_package_weight(p, manifest[p]["dev"]) for p in pkgs if p in PACKAGE_CATEGORY)
    other = sum(_package_weight(p, manifest[p]["dev"]) for p in pkgs if p not in PACKAGE_CATEGORY)
    return curated + min(other, _UNCURATED_SIGNIFICANCE_CAP)


def detect_dependency_decisions(repo_path: str, commits: list, excluded=lambda path: False) -> list:
    decisions = []
    reader = BlobReader(repo_path)
    try:
        for c in commits:
            for f in c["files"]:
                path = f["path"]
                if not is_manifest(path) or excluded(path):
                    continue
                before_rev = c["parents"][0] if c["parents"] else None
                before_path = f.get("old_path", path)
                before = parse_manifest(path, reader.read(before_rev, before_path)) if before_rev else {}
                after = parse_manifest(path, reader.read(c["hash"], path))
                added = _curated_first(set(after) - set(before))
                removed = _curated_first(set(before) - set(after))
                if not added and not removed:
                    continue
                first = (added or removed)[0]
                ecosystem = (after.get(first) or before.get(first))["ecosystem"]
                if not before:
                    notable = [p for p in added if p in PACKAGE_CATEGORY and not after[p]["dev"]] or added[:5]
                    significance = sum(_package_weight(p, after[p]["dev"]) for p in notable[:6]) / 2
                    # files={path}: an initial commit usually touches every file, which would make
                    # every later commit look related; the modules using the packages are added
                    # as focus during evidence gathering instead.
                    decisions.append(_decision(
                        c, "initial_stack", f"Initial technology stack: {_describe(notable[:6])}", significance,
                        files={path}, packages=notable[:12], manifest=path, ecosystem=ecosystem, added=added,
                        removed=[]))
                    continue
                weight_added = _significance(added, after)
                weight_removed = _significance(removed, before)
                same_category = {PACKAGE_CATEGORY.get(p) for p in added} & {PACKAGE_CATEGORY.get(p) for p in removed} - {None}
                if added and removed and (same_category or (len(added) == 1 and len(removed) == 1)):
                    kind = "dependency_replace"
                    subject = f"Replace {_describe(removed)} with {_describe(added)}"
                elif added:
                    kind = "dependency_change"
                    subject = f"Adopt {_describe(added[:4])}" + (f" (and {len(added) - 4} more)" if len(added) > 4 else "")
                    if removed:
                        subject += f"; drop {_describe(removed[:3])}"
                else:
                    kind = "dependency_change"
                    subject = f"Drop {_describe(removed[:4])}"
                decisions.append(_decision(c, kind, subject, weight_added + 0.8 * weight_removed,
                                           packages=(added + removed)[:12], manifest=path, ecosystem=ecosystem,
                                           added=added, removed=removed))
    finally:
        reader.close()
    return _merge_same_commit(decisions)


def _merge_same_commit(decisions: list) -> list:
    """One commit can change several manifests (a monorepo, a squash). Merge
    its decisions of the same kind into one, so they aren't deduplicated
    away and the record describes the whole change."""
    groups = {}
    for d in decisions:
        groups.setdefault((d["sha"], d["kind"]), []).append(d)
    merged = []
    for (sha, kind), ds in groups.items():
        if len(ds) == 1:
            merged.append(ds[0])
            continue
        added = _curated_first({p for d in ds for p in d.get("added", [])})
        removed = _curated_first({p for d in ds for p in d.get("removed", [])})
        packages = _curated_first({p for d in ds for p in d["packages"]})
        if kind == "initial_stack":
            subject = f"Initial technology stack: {_describe(packages[:6])}"
        elif kind == "dependency_replace":
            subject = f"Replace {_describe(removed[:3])} with {_describe(added[:3])}"
        else:
            subject = (f"Adopt {_describe(added[:4])}" if added else f"Drop {_describe(removed[:4])}") +                 (f" (and {len(added) - 4} more)" if len(added) > 4 else "")
        base = max(ds, key=lambda d: d["significance"])
        merged.append({**base, "id": _decision_id(sha, kind, subject), "subject": subject,
                       "significance": round(sum(d["significance"] for d in ds), 3),
                       "files": sorted({f for d in ds for f in d["files"]}), "packages": packages[:12],
                       "added": added, "removed": removed,
                       "manifest": ", ".join(sorted({d["manifest"] for d in ds}))})
    return merged


def detect_infrastructure(commits: list, excluded=lambda path: False) -> list:
    seen = set()
    decisions = []
    for c in commits:
        for f in c["files"]:
            path = f["path"]
            if excluded(path):
                continue
            for pattern, label in INFRA_PATTERNS.items():
                if label not in seen and (fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path.rsplit("/", 1)[-1], pattern)):
                    seen.add(label)
                    decisions.append(_decision(c, "infrastructure", f"Introduce {label}", 1.0,
                                               files={p["path"] for p in c["files"]}))
    return decisions


def _top_folder(path: str):
    parts = path.split("/")
    if len(parts) < 2 or parts[0].lower() in _NON_ARCHITECTURAL_FOLDERS:
        return None
    if parts[0] in ("src", "lib", "app", "packages") and len(parts) >= 3:
        return "/".join(parts[:2])
    return parts[0]


def detect_structure(repo_path: str, snapshots: list, by_hash: dict, excluded=lambda path: False) -> list:
    decisions = []
    for prev, cur in zip(snapshots, snapshots[1:]):
        def folders(s):
            counts = {}
            for path, _layer in s["modules"]:
                folder = _top_folder(path)
                if folder and not excluded(path):
                    counts[folder] = counts.get(folder, 0) + 1
            return counts
        before, after = folders(prev), folders(cur)
        for folder in sorted(set(before) | set(after)):
            appeared = after.get(folder, 0) >= STRUCTURE_MIN_MODULES and before.get(folder, 0) == 0
            vanished = before.get(folder, 0) >= STRUCTURE_MIN_MODULES and after.get(folder, 0) == 0
            if not (appeared or vanished):
                continue
            pinned = git(repo_path, "log", "--reverse", "--format=%H", f"--diff-filter={'A' if appeared else 'D'}",
                         f"{prev['sha']}..{cur['sha']}", "--", folder).split()
            commit = next((by_hash[sha] for sha in pinned if sha in by_hash), None)
            if commit is None:
                continue
            n = after.get(folder, 0) if appeared else before.get(folder, 0)
            subject = f"{'Introduce' if appeared else 'Remove'} the {folder}/ module group ({n} modules)"
            files = {p for p, _ in (cur if appeared else prev)["modules"] if p.startswith(folder + "/")}
            decisions.append(_decision(commit, "structure", subject, 0.8 + 0.1 * min(n, 10), files=files,
                                       folder=folder))
    return decisions


def detect_restructures(commits: list) -> list:
    decisions = []
    for c in commits:
        renames = [f for f in c["files"] if f.get("old_path")]
        if len(renames) >= RESTRUCTURE_MIN_RENAMES:
            decisions.append(_decision(c, "restructure", f"Restructure: {len(renames)} files moved or renamed",
                                       0.5 + 0.05 * min(len(renames), 20)))
    return decisions


def detect_violation_changes(repo_path: str, snapshots: list, by_hash: dict) -> list:
    decisions = []
    for prev, cur in zip(snapshots, snapshots[1:]):
        for kind, keys in (("violation_introduced", cur["diff"]["new_violations"]),
                           ("violation_resolved", cur["diff"]["resolved_violations"])):
            by_rule = {}
            for key in keys:
                by_rule.setdefault((key[0], key[1], key[4]), []).append(key)
            for (rule, caller, callee), group in sorted(by_rule.items()):
                needle = group[0][6] or os.path.splitext(os.path.basename(callee))[0]
                pinned = git(repo_path, "log", "--reverse", "--format=%H", f"-S{needle}",
                             f"{prev['sha']}..{cur['sha']}", "--", caller).split()
                commit = next((by_hash[sha] for sha in pinned if sha in by_hash), None)
                if commit is None:
                    continue
                verb = "Introduce" if kind == "violation_introduced" else "Resolve"
                decisions.append(_decision(commit, kind, f"{verb} {rule}: {caller} -> {callee}", 0.9,
                                           files={caller, callee}, rule=rule))
    return decisions


def rank(decisions: list, limit: int = MAX_DECISIONS, per_kind_cap: int = MAX_PER_KIND) -> list:
    """Most significant first; at most one decision per commit and kind, and
    at most per_kind_cap per kind (replacements and additions share the
    dependency budget) so one kind can't crowd out the rest."""
    def score(d):
        return KIND_WEIGHT[d["kind"]] * d["significance"] * (1 + math.log1p(len(d["files"])))
    kept, per_kind, seen = [], {}, set()
    for d in sorted(decisions, key=lambda d: (-score(d), d["date"] or "", d["id"])):
        bucket = "dependency" if d["kind"] in ("dependency_replace", "dependency_change") else d["kind"]
        if (d["sha"], bucket) in seen or per_kind.get(bucket, 0) >= per_kind_cap:
            continue
        kept.append({**d, "score": round(score(d), 3)})
        per_kind[bucket] = per_kind.get(bucket, 0) + 1
        seen.add((d["sha"], bucket))
        if len(kept) >= limit:
            break
    return sorted(kept, key=lambda d: (d["date"] or "", d["id"]))


def detect_decisions(repo_path: str, commits: list, snapshots: list, exclude_patterns=(), limit=MAX_DECISIONS) -> list:
    def excluded(path):
        return any(fnmatch.fnmatch(path, p) for p in exclude_patterns)
    # Bulk commits stay in: a squashed or initial commit that creates the
    # manifests IS a decision point. They're only excluded as evidence.
    usable = [c for c in commits if not (c["files"] and all(excluded(f["path"]) for f in c["files"]))]
    by_hash = {c["hash"]: c for c in usable}
    found = (detect_dependency_decisions(repo_path, usable, excluded) + detect_infrastructure(usable, excluded)
             + detect_structure(repo_path, snapshots, by_hash, excluded) + detect_restructures(usable)
             + detect_violation_changes(repo_path, snapshots, by_hash))
    return rank(found, limit, MAX_PER_KIND if limit <= MAX_DECISIONS else limit)
