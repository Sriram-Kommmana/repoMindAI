"""Builds a small git repository with a known, scripted history, for testing
history mining, snapshots, the temporal graph and (later) ADR detection.

Commit (idx) story:
  0  initial layered app: controller -> service -> database, flask in requirements
  1  add models
  2  "wip": controller imports and calls the database directly (violation),
     and redis is added to requirements
  3  add a redis-backed cache module
  4  service uses the cache
  5  cache gets a TTL
  6  rename utils.py -> helpers.py (identical content)
  7  fix: controller goes back through the service (violation resolved)
"""
import os
import subprocess

BASE_TIMESTAMP = 1_700_000_000  # 2023-11-14
DAY = 86_400

CONTROLLER_CLEAN = "from service import process_order\n\n\ndef handle_request(order):\n    return process_order(order)\n"
CONTROLLER_VIOLATING = (
    "from service import process_order\nfrom database import save_record\n\n\n"
    "def handle_request(order):\n    return process_order(order)\n\n\n"
    "def handle_request_direct(order):\n    return save_record(order)\n"
)
SERVICE = "from database import save_record\n\n\ndef process_order(order):\n    return save_record(order)\n"
SERVICE_WITH_CACHE = (
    "from database import save_record\nfrom cache import remember\n\n\n"
    "def process_order(order):\n    remember(order)\n    return save_record(order)\n"
)
DATABASE = "def save_record(data):\n    return data\n"
UTILS = "def add(a, b):\n    return a + b\n"
MODELS = "class Order:\n    def __init__(self, item):\n        self.item = item\n"
CACHE = "import redis\n\nclient = redis.Redis()\n\n\ndef remember(value):\n    client.set('last', value)\n"
CACHE_TTL = "import redis\n\nclient = redis.Redis()\n\n\ndef remember(value):\n    client.set('last', value, ex=60)\n"


def _run(repo, *args, when):
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "Ada Dev", "GIT_AUTHOR_EMAIL": "ada@example.com",
           "GIT_COMMITTER_NAME": "Ada Dev", "GIT_COMMITTER_EMAIL": "ada@example.com",
           "GIT_AUTHOR_DATE": f"@{when} +0000", "GIT_COMMITTER_DATE": f"@{when} +0000"}
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


def _write(repo, files):
    for rel, text in files.items():
        path = os.path.join(repo, rel)
        if text is None:
            os.remove(path)
            continue
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


def make_history_repo(repo: str) -> str:
    os.makedirs(repo, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "config", "core.autocrlf", "false"], check=True)
    steps = [
        ({"controller.py": CONTROLLER_CLEAN, "service.py": SERVICE, "database.py": DATABASE,
          "utils.py": UTILS, "requirements.txt": "flask==3.0\n"}, "Initial layered app"),
        ({"models.py": MODELS}, "Add order model"),
        ({"controller.py": CONTROLLER_VIOLATING, "requirements.txt": "flask==3.0\nredis==5.0\n"}, "wip"),
        ({"cache.py": CACHE}, "add cache"),
        ({"service.py": SERVICE_WITH_CACHE}, "use cache in service"),
        ({"cache.py": CACHE_TTL}, "cache ttl"),
        (None, "Rename utils to helpers"),
        ({"controller.py": CONTROLLER_CLEAN}, "Route controller through the service layer again"),
    ]
    for i, (files, message) in enumerate(steps):
        when = BASE_TIMESTAMP + i * DAY
        if files is None:
            _run(repo, "mv", "utils.py", "helpers.py", when=when)
        else:
            _write(repo, files)
        _run(repo, "add", "-A", when=when)
        _run(repo, "commit", "-q", "-m", message, when=when)
    return repo
