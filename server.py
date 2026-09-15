"""RepoMind AI — Phase 7: minimal FastAPI backend for the demo web UI.

Usage: python server.py   (serves on http://localhost:8000)

Thin wrapper only — every actual step (clone, parse+load, drift check,
diagram) calls existing, already-verified pipeline functions. No new
analysis logic lives here.
"""
import shutil
import tempfile

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from analyze_repo import clone_repo, _remove_readonly
from check_drift import _qualified
from export_diagram import _get_driver as _diagram_driver, build_mermaid, fetch_imports, fetch_modules
from graph import loader
from parser import ast_extractor
from rules.rule_engine import load_rules, run_rule_engine
from rules.scoring import compute_health

app = FastAPI()


class AnalyzeRequest(BaseModel):
    repo_url: str


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    temp_dir = tempfile.mkdtemp(prefix="repomind_")
    try:
        clone_repo(req.repo_url, temp_dir)

        data = ast_extractor.parse_repo(temp_dir)
        loader.load_graph(data)
        nodes_loaded = loader.count_nodes()
    finally:
        shutil.rmtree(temp_dir, onerror=_remove_readonly)

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

    return {
        "files_parsed": len(data["modules"]),
        "classes_found": len(data["classes"]),
        "functions_found": len(data["functions"]),
        "nodes_loaded": nodes_loaded,
        "violations": [
            {
                "rule": v["rule_name"],
                "severity": v["severity"],
                "caller": f"{v['caller_module']}::{_qualified(v['caller_class'], v['caller_name'])}",
                "callee": f"{v['callee_module']}::{_qualified(v['callee_class'], v['callee_name'])}",
            }
            for v in violations
        ],
        "health_score": health_score,
        "mermaid_diagram": mermaid_diagram,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
