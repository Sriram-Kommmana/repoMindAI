"""RepoMind AI — Phase 7/8: FastAPI backend for the demo web UI.

Usage: python server.py   (serves on http://localhost:8000)

Thin wrapper only — every deterministic step (clone, parse+load, drift
check, diagram) calls existing, already-verified pipeline functions. The
only generative pieces are the documentation call (docs_generator.py) and
repository Q&A (qa_engine.py), both grounded in that same deterministic
output.
"""
import shutil
import tempfile
from typing import Literal

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from analyze_repo import clone_repo, _remove_readonly
from check_drift import _qualified
from docs_generator import generate_documentation
from export_diagram import _get_driver as _diagram_driver, build_mermaid, fetch_imports, fetch_modules
from graph import loader
from parser import ast_extractor
from qa_engine import answer_question, clear_repo_context, set_repo_context
from rules.rule_engine import load_rules, run_rule_engine
from rules.scoring import compute_health

app = FastAPI()


class AnalyzeRequest(BaseModel):
    repo_url: str


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    temp_dir = tempfile.mkdtemp(prefix="repomind_")
    try:
        clone_repo(req.repo_url, temp_dir)

        data = ast_extractor.parse_repo(temp_dir)
        clear_repo_context()
        loader.load_graph(data)
        set_repo_context(req.repo_url, temp_dir, [m["path"] for m in data["modules"]])
        nodes_loaded = loader.count_nodes()

        rules = load_rules("rules.yaml")
        violations, total_applicable_rules = run_rule_engine(rules)
        health_score = compute_health(violations, total_applicable_rules)

        driver = _diagram_driver()
        try:
            with driver.session() as session:
                modules = fetch_modules(session)
                imports = fetch_imports(session)
        finally:
            driver.close()
        mermaid_diagram = build_mermaid(modules, imports)

        violations_payload = [
            {
                "rule": v["rule_name"],
                "severity": v["severity"],
                "caller": f"{v['caller_module']}::{_qualified(v['caller_class'], v['caller_name'])}",
                "callee": f"{v['callee_module']}::{_qualified(v['callee_class'], v['callee_name'])}",
            }
            for v in violations
        ]

        documentation = None
        documentation_error = None
        documentation_warnings = []
        try:
            doc_result = generate_documentation(temp_dir, data, violations_payload, health_score)
            documentation = doc_result["markdown"]
            documentation_warnings = doc_result["warnings"]
        except Exception as exc:
            # str(exc) can be "" for some exception types (e.g. the stdlib's
            # bare TimeoutError) — always fall back to a non-empty message so
            # the frontend's truthy check never silently hides a real failure.
            # generate_documentation now only raises for catastrophic setup
            # failures (e.g. missing GROQ_API_KEY) — every per-batch/reduce
            # failure inside it degrades into documentation_warnings instead.
            documentation_error = str(exc) or type(exc).__name__
    finally:
        shutil.rmtree(temp_dir, onerror=_remove_readonly)

    return {
        "files_parsed": len(data["modules"]),
        "classes_found": len(data["classes"]),
        "functions_found": len(data["functions"]),
        "nodes_loaded": nodes_loaded,
        "violations": violations_payload,
        "health_score": health_score,
        "mermaid_diagram": mermaid_diagram,
        "documentation": documentation,
        "documentation_error": documentation_error,
        "documentation_warnings": documentation_warnings,
    }


@app.post("/ask")
def ask(req: AskRequest):
    try:
        return answer_question(req.question, [turn.model_dump() for turn in req.history])
    except Exception as exc:
        return {"answer": None, "evidence": [], "error": str(exc) or type(exc).__name__}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
