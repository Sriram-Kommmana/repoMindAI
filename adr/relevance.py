"""Evidence gathering for a decision point (pure, deterministic):

    relevance(commit) = alpha * time_proximity + beta * graph_proximity + gamma * text_similarity

- time: 0.5*exp(-days/7) + 0.5*exp(-commits/10) — the commit-distance term
  keeps bursty repos (many commits in one day) from rating everything 1.0
- graph: overlap between the commit's files and the files the decision
  concerns (decision files, modules using the dependency, half weight for
  their direct import neighbours)
- text: TF-IDF cosine between commit and decision documents; documents
  include tokenized file paths, which carry meaning when messages are "wip"
"""
import math
import re
from collections import Counter
from datetime import datetime

ALPHA, BETA, GAMMA = 0.3, 0.45, 0.25
THRESHOLD = 0.35
TOP_K = 12
WINDOW_DAYS = 30
WINDOW_COMMITS = 40

_TOKEN = re.compile(r"[A-Za-z][a-z]+|[A-Z]+(?![a-z])|\d+")
_STOP = {"the", "and", "for", "with", "from", "into", "this", "that", "add", "added", "update", "updated", "fix",
         "fixed", "use", "using", "py", "js", "ts", "tsx", "jsx", "json", "txt", "md", "src", "lib", "app", "test",
         "tests", "index", "init", "main", "wip", "merge", "pull", "request", "branch", "of", "to", "in", "on",
         "a", "an", "is", "it", "be", "by", "as", "at", "or", "not", "more", "some", "new", "code"}
RATIONALE_WORDS = re.compile(r"\b(because|instead|replace[sd]?|migrat\w*|deprecat\w*|switch(ed|ing)? to|in favou?r of|"
                             r"so that|in order to|performance|scal\w+|security|reliab\w+|simplif\w+)\b", re.IGNORECASE)


def tokens(text: str) -> list:
    words = []
    for raw in re.split(r"[\s/_\-.:,;()\[\]{}'\"`=+<>!?#@*]+", text or ""):
        for t in _TOKEN.findall(raw):
            t = t.lower()
            if len(t) > 2 and t not in _STOP:
                words.append(t)
    return words


def commit_document(commit: dict) -> list:
    paths = " ".join(f["path"] for f in commit["files"][:50])
    return tokens(f"{commit.get('subject', '')} {commit.get('body', '')} {paths}")


class TfIdf:
    def __init__(self, documents: list):
        df = Counter()
        for doc in documents:
            df.update(set(doc))
        n = max(len(documents), 1)
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.default_idf = math.log(1 + n) + 1

    def vector(self, doc: list) -> dict:
        counts = Counter(doc)
        vec = {t: (1 + math.log(c)) * self.idf.get(t, self.default_idf) for t, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    @staticmethod
    def cosine(a: dict, b: dict) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(t, 0.0) for t, v in a.items())


def _days_between(a: str, b: str) -> float:
    try:
        return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds()) / 86_400
    except (TypeError, ValueError):
        return float(WINDOW_DAYS)


_DEPENDENCY_FILES = re.compile(r"(^|/)(package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|requirements[^/]*\.txt|"
                               r"pyproject\.toml|poetry\.lock|Pipfile(\.lock)?|setup\.(py|cfg))$")


def is_bot(commit: dict) -> bool:
    return "[bot]" in commit.get("author", "") or commit.get("author", "").lower() in ("dependabot", "renovate")


def focus_files(decision: dict, usage_modules: list, imports: list) -> dict:
    """file -> weight: the decision's own files and the modules using its
    packages count fully; their one-hop import neighbours count half.
    Manifests and lock files are left out: every dependency bump touches
    them, which would make unrelated bumps look like evidence."""
    weights = {f: 1.0 for f in decision["files"] if not _DEPENDENCY_FILES.search(f)}
    for m in usage_modules:
        weights[m] = 1.0
    core = set(weights)
    for e in imports:
        if e["from"] in core and e["to"] not in weights:
            weights[e["to"]] = 0.5
        elif e["to"] in core and e["from"] not in weights:
            weights[e["from"]] = 0.5
    return weights


def graph_proximity(commit: dict, focus: dict) -> float:
    files = [f["path"] for f in commit["files"]]
    if not files or not focus:
        return 0.0
    hit = sum(focus.get(f, 0.0) for f in files)
    return min(1.0, hit / min(len(files), len(focus)))


def time_proximity(commit: dict, decision: dict) -> float:
    days = _days_between(commit["date"], decision["date"])
    steps = abs((commit.get("idx") or 0) - (decision.get("idx") or 0))
    return 0.5 * math.exp(-days / 7) + 0.5 * math.exp(-steps / 10)


def decision_document(decision: dict, decision_commit: dict) -> list:
    from adr.detect import PACKAGE_CATEGORY
    categories = " ".join(PACKAGE_CATEGORY.get(p, "") for p in decision["packages"])
    return tokens(f"{decision['subject']} {' '.join(decision['packages'])} {categories} "
                  f"{decision_commit.get('subject', '')} {decision_commit.get('body', '')} "
                  f"{' '.join(decision['files'][:30])}")


def score_evidence(decision: dict, commits: list, focus: dict, weights=(ALPHA, BETA, GAMMA),
                   threshold=THRESHOLD, top_k=TOP_K, excluded=lambda path: False) -> dict:
    """Returns {"decision_commit": c, "evidence": [scored commits above the
    threshold, best first], "considered": n}. The decision commit is always
    evidence (relevance 1.0)."""
    alpha, beta, gamma = weights
    by_hash = {c["hash"]: c for c in commits}
    anchor = by_hash[decision["sha"]]
    tfidf = TfIdf([commit_document(c) for c in commits])
    query = tfidf.vector(decision_document(decision, anchor))

    scored = []
    considered = 0
    for c in commits:
        if c["hash"] == anchor["hash"] or c["bulk"] or is_bot(c):
            continue
        if abs((c.get("idx") or 0) - (anchor.get("idx") or 0)) > WINDOW_COMMITS:
            continue
        if _days_between(c["date"], anchor["date"]) > WINDOW_DAYS:
            continue
        if c["files"] and all(excluded(f["path"]) for f in c["files"]):
            continue
        considered += 1
        t = time_proximity(c, decision)
        g = graph_proximity(c, focus)
        x = TfIdf.cosine(tfidf.vector(commit_document(c)), query)
        relevance = alpha * t + beta * g + gamma * x
        if relevance >= threshold:
            scored.append({"commit": c, "relevance": round(relevance, 3),
                           "time": round(t, 3), "graph": round(g, 3), "text": round(x, 3)})
    scored.sort(key=lambda s: (-s["relevance"], s["commit"]["idx"] or 0))
    anchor_entry = {"commit": anchor, "relevance": 1.0, "time": 1.0, "graph": 1.0, "text": 1.0, "decision_commit": True}
    return {"decision_commit": anchor, "evidence": [anchor_entry] + scored[:top_k - 1], "considered": considered}
