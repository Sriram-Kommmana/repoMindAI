"""RepoMind AI — FastAPI backend for the web UI.

Usage: python server.py   (serves on http://localhost:8000)

POST /analyze does all deterministic work (clone, parse, layers, graph,
rules, diagram, history and snapshots); the page then loads the generative
sections lazily from their own endpoints, each tied to the analysis_id so a
newer analysis can't be mixed in.
"""
import time
from collections import Counter
from contextlib import asynccontextmanager
from typing import Literal, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

import cache
import llm
import workspace
from agents.adr_graph import decisions_for, reconstruct, store_decisions
from agents.drift_graph import explain_violations
from docs_generator import generate_documentation
from export_diagram import build_folder_mermaid, build_mermaid, fetch_imports, fetch_modules
from graph import loader
from graph.history_loader import graph_at_snapshot, load_history
from history import commit_meta, contributors, introduced_at, mine_commits
from layers import apply_layers
from parser import ast_extractor
from qa_engine import answer_question, attach_analysis, clear_repo_context, set_repo_context
from rules.config import MAX_RULES_YAML_CHARS, RulesError, default_rules_text, load_rules_config
from rules.evaluate import evaluate, format_violation, violation_key
from rules.rule_engine import run_rule_engine
from rules.scoring import compute_health, compute_health_normalized
from snapshots import build_snapshots, import_intervals, module_presence, source_change_filter

TIMELINE_COMMITS = 15


@asynccontextmanager
async def lifespan(_app):
    workspace.sweep_stale()
    yield
    workspace.shutdown()


app = FastAPI(lifespan=lifespan)


class AnalyzeRequest(BaseModel):
    repo_url: str = Field(min_length=1, max_length=500)
    rules_yaml: Optional[str] = Field(None, max_length=MAX_RULES_YAML_CHARS)


class AnalysisRef(BaseModel):
    analysis_id: str = Field(min_length=1, max_length=64)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


@app.get("/")
def index():
    # Revalidate every load, so a browser never runs a stale copy of the page
    # against a newer API.
    return FileResponse("static/index.html", headers={"Cache-Control": "no-cache"})


@app.get("/rules/default", response_class=PlainTextResponse)
def default_rules():
    return default_rules_text()


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    try:
        rules = load_rules_config(req.rules_yaml if req.rules_yaml and req.rules_yaml.strip() else None)
    except RulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        with workspace.new_analysis(req.repo_url.strip()) as ws:
            return _analyze(ws, rules)
    except workspace.AnalysisBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except workspace.CloneError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class _Stopwatch:
    def __init__(self):
        self.marks = {}
        self._last = time.time()

    def lap(self, name):
        now = time.time()
        self.marks[name] = round(now - self._last, 2)
        self._last = now
        return self.marks[name]


def _analyze(ws, rules: dict) -> dict:
    t0 = time.time()
    watch = _Stopwatch()
    data = ast_extractor.parse_repo(ws.path)
    parse_seconds = watch.lap("parse")
    apply_layers(data, rules)

    clear_repo_context()
    loader.load_graph(data)
    set_repo_context(ws.repo_url, ws.path, [m["path"] for m in data["modules"]], rules)
    nodes_loaded = loader.count_nodes()
    watch.lap("graph_load")

    violations, total_applicable_rules = run_rule_engine(rules)
    violations.sort(key=violation_key)
    pure = evaluate(data, rules)
    if violations != pure["violations"]:
        print("[server] WARNING: graph rule engine and in-memory evaluator disagree", flush=True)
    health_score = compute_health_normalized(violations, pure["checks_by_rule"], rules)
    violations_payload = [format_violation(v) for v in violations]
    watch.lap("rules")

    driver = loader._get_driver()
    try:
        with driver.session() as session:
            mermaid_diagram = build_mermaid(fetch_modules(session), fetch_imports(session))
            watch.lap("diagram")
            history = _analyze_history(ws, session, data, rules, parse_seconds, watch)
    finally:
        driver.close()

    ws.results.update(data=data, rules=rules, violations=violations, violations_payload=violations_payload,
                      health=health_score, history=history)
    attach_analysis(ws.id)
    return {
        "analysis_id": ws.id,
        "repo_url": ws.repo_url,
        "head_sha": ws.head_sha,
        "files_parsed": len(data["modules"]),
        "classes_found": len(data["classes"]),
        "functions_found": len(data["functions"]),
        "nodes_loaded": nodes_loaded,
        "violations": violations_payload,
        "health_score": health_score,
        "health_score_legacy": compute_health(violations, total_applicable_rules),
        "weighted_violations": sum(v["severity"] for v in violations),
        "rule_checks": pure["checks_by_rule"],
        "layers": dict(Counter(m["layer_type"] or "untagged" for m in data["modules"])),
        "mermaid_diagram": mermaid_diagram,
        "history": history["summary"],
        "seconds": round(time.time() - t0 + ws.clone_seconds, 1),
        "timings": {"clone": ws.clone_seconds, **watch.marks},
    }


def _analyze_history(ws, session, data: dict, rules: dict, parse_seconds: float, watch) -> dict:
    mined = mine_commits(ws.path)
    commits = mined["commits"]
    by_hash = {c["hash"]: c for c in commits}
    watch.lap("history_mining")

    snapshots = build_snapshots(ws.path, rules, data, parse_seconds,
                                lambda sha: by_hash.get(sha) or commit_meta(ws.path, sha),
                                eligible=source_change_filter(commits))
    intervals = import_intervals(snapshots)
    watch.lap("snapshots")
    current_paths = {m["path"] for m in data["modules"]}
    written = load_history(session, commits, snapshots, intervals, module_presence(snapshots),
                           introduced_at(commits), current_paths)
    watch.lap("history_load")

    summary = {
        "commits": len(commits),
        "truncated": mined["truncated"],
        "first_commit": commits[0]["date"] if commits else None,
        "last_commit": commits[-1]["date"] if commits else None,
        "contributors": contributors(commits),
        "snapshots": [{
            "idx": s["idx"], "sha": s["sha"], "short": s["short"], "date": s["date"], "subject": s["subject"],
            "health": s["health"], "health_legacy": s["health_legacy"],
            "weighted_violations": s["weighted_violations"], "violations": len(s["violations"]),
            "modules": len(s["modules"]), "imports": len(s["imports"]),
            "changes": {k: len(v) for k, v in s["diff"].items()},
        } for s in snapshots],
        "timeline": [{"short": c["short"], "sha": c["hash"], "date": c["date"], "author": c["author"],
                      "subject": c["subject"], "files": c["n_files"]}
                     for c in reversed(commits[-TIMELINE_COMMITS:])],
        "graph_writes": written,
    }
    return {"summary": summary, "commits": commits, "snapshots": snapshots}


@app.post("/documentation")
def documentation(ref: AnalysisRef):
    try:
        with workspace.use(ref.analysis_id) as ws:
            r = ws.results
            try:
                path = cache.entry_path(ws.repo_url, ws.head_sha, "documentation", "docs", rules=r["rules"])
                result, hit = cache.cached(
                    path, lambda: generate_documentation(ws.path, r["data"], r["violations_payload"], r["health"]),
                    cacheable=lambda value: not value["warnings"])
            except Exception as exc:
                # generate_documentation only raises for setup failures (no LLM
                # key); str(exc) can be "" for some exception types.
                return {"documentation": None, "documentation_warnings": [],
                        "documentation_error": str(exc) or type(exc).__name__}
            return {"documentation": result["markdown"], "documentation_warnings": result["warnings"],
                    "documentation_error": None, "cached": hit}
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/violations/explain")
def violations_explain(ref: AnalysisRef):
    try:
        with workspace.use(ref.analysis_id) as ws:
            r = ws.results
            try:
                return explain_violations(ws.repo_url, ws.head_sha, ws.path, r["rules"], r["data"],
                                          r["history"]["snapshots"])
            except llm.LLMConfigError as exc:
                return {"groups": [], "warnings": [str(exc)], "error": str(exc)}
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/adrs")
def adrs(ref: AnalysisRef):
    try:
        with workspace.use(ref.analysis_id) as ws:
            r = ws.results
            try:
                result = reconstruct(ws.repo_url, ws.head_sha, ws.path, r["rules"], r["data"],
                                     r["history"]["commits"], r["history"]["snapshots"], decisions=decisions_for(ws))
            except llm.LLMConfigError as exc:
                return {"decisions": [], "detected": 0, "warnings": [str(exc)], "error": str(exc)}
            if workspace.is_current(ws.id):
                driver = loader._get_driver()
                try:
                    with driver.session() as session:
                        store_decisions(session, result["decisions"])
                finally:
                    driver.close()
            return result
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/history/snapshot/{idx}")
def history_snapshot(idx: int, analysis_id: str):
    try:
        with workspace.use(analysis_id) as ws:
            snapshots = ws.results["history"]["snapshots"]
            if not 0 <= idx < len(snapshots):
                raise HTTPException(status_code=404, detail="No such snapshot.")
            driver = loader._get_driver()
            try:
                with driver.session() as session:
                    graph = graph_at_snapshot(session, idx)
            finally:
                driver.close()
            s = snapshots[idx]
            return {
                "idx": idx, "short": s["short"], "date": s["date"], "subject": s["subject"],
                "health": s["health"], "violations": s["violations"],
                "modules": len(graph["modules"]), "imports": len(graph["imports"]),
                "mermaid_diagram": build_folder_mermaid(graph["modules"], graph["imports"]),
            }
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/ask")
def ask(req: AskRequest):
    try:
        return answer_question(req.question, [turn.model_dump() for turn in req.history])
    except Exception as exc:
        return {"answer": None, "evidence": [], "error": str(exc) or type(exc).__name__}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
