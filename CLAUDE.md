# RepoMind AI

## What this is
An agentic platform that builds a **temporal knowledge graph** of a Git repository (structure + evolution) and uses it to power three capabilities: Architecture Drift Detection, ADR Reconstruction, and Repository Q&A. Full design lives in `SPEC.md` — read it before starting work on any module.

## CURRENT PHASE — READ THIS FIRST
**Phases 1-4, 5a, 5b, and 6 are complete and verified.** The pipeline (parsing, knowledge graph, deterministic drift detection, Git mining, Mermaid diagram export, URL-to-clone) now works across Python, JavaScript, and TypeScript — tested against 11 real repos total, 7 genuine bugs found and fixed, with a confirmed cross-language proof (check_drift.py and export_diagram.py run unmodified on a TS-loaded graph). Full details in SPEC.md.

We are now building **Phase 7: a minimal web interface for live demo purposes**, per SPEC.md's "Implementation Scope — Phase 7" section. Goal: let someone paste a GitHub URL into a browser page and see the analysis results (parse summary, drift violations, health score, dependency diagram) rendered visually — instead of running CLI commands and reading terminal output.

**This is explicitly a THIN WRAPPER around existing logic, not a rebuild.** Every piece of actual analysis (parsing, graph loading, drift checking, diagram generation) already exists and is verified — this phase only adds:
1. A FastAPI backend with ONE endpoint that calls the existing pipeline functions (from `analyze_repo.py`, `rules/rule_engine.py` + `rules/scoring.py`, `export_diagram.py`) and returns their results as JSON
2. A single static HTML page with an input box, a button, and JavaScript that calls the endpoint and renders the results (including the Mermaid diagram via the Mermaid.js CDN script)

Do NOT build any of the following — this must stay small and demo-focused:
- Authentication, user accounts, persistence/database beyond what already exists (Neo4j)
- A build step, bundler, or frontend framework (React, Vue, etc.) — plain HTML/CSS/JS only
- Styling polish beyond basic readability — this is a functional demo interface, not a designed product
- Multiple pages, routing, or navigation — one page is enough
- ADR Reconstruction, Repository Q&A, LLM/agent logic of any kind — this phase still has ZERO AI involvement, it's purely exposing existing deterministic results through a browser instead of a terminal
- Java support, temporal versioning — unrelated to this phase

Do not modify `parser/`, `graph/`, `rules/`, `check_drift.py`, `mine_history.py`, `export_diagram.py`, `main.py`, or `analyze_repo.py` — this phase only calls into their existing functions from a new FastAPI layer, it does not change their logic.

See the "Implementation Scope — Phase 7" section of `SPEC.md` for the exact API contract, page layout, and Definition of Done. Follow it precisely rather than expanding scope — this needs to be reliable and fast to build since it's demo-critical for tomorrow.

### Known status (for honest reporting)
- No LLM/agentic components exist anywhere in the codebase — this phase does not change that, it's still a UI layer over deterministic analysis
- ADR Reconstruction and Repository Q&A are fully unbuilt
- This web interface is a demo tool, not a production frontend — no auth, no persistence beyond the existing graph, no polish

## Non-negotiable design rules (apply to the FULL system — several are deferred until later phases, see above)
IMPORTANT — these are the rules that make this project what it is. Do not let convenience during implementation violate them.

- **Deterministic before generative.** Unaffected — this phase adds zero AI, it only exposes existing deterministic results visually.
- **Evidence / Inference / Confidence.** Not relevant to Phase 7.
- **One shared graph.** Unaffected — the web endpoint calls the same pipeline that already reads/writes the one shared Neo4j graph.
- **Temporal, not static.** Still deferred.
- **Rules are data.** Unaffected — the web endpoint just calls the existing rule engine, doesn't change how rules work.

## Tech stack (full target system)
- Parsing: Tree-sitter ← **done — Python, JS, TS**
- Graph DB: Neo4j + Cypher ← **done**
- Git mining: PyDriller + GitHub REST API ← **PyDriller done**
- Repo acquisition: `git clone` via subprocess ← **done**
- Agent orchestration: LangGraph + LangChain — not started
- LLMs: GPT-4o / Gemini Pro — not started
- Backend: FastAPI (Python) ← **Phase 7 (current) — minimal, single endpoint**
- Structured storage: PostgreSQL — not started
- Frontend: React + TypeScript, React Flow, Mermaid ← **Phase 7 uses plain HTML/JS + Mermaid.js CDN, NOT React — React remains a later, separate upgrade if ever needed**, Monaco Editor — not started

## Phase 7 scope (current work)
- One FastAPI endpoint, e.g. `POST /analyze`, accepting `{"repo_url": "..."}`, that:
  1. Clones the repo (reuse `analyze_repo.py`'s clone logic)
  2. Parses and loads it into Neo4j (reuse the existing `run_pipeline`/parsing logic)
  3. Runs the drift rule engine (reuse `rules/rule_engine.py` + `rules/scoring.py`)
  4. Generates the Mermaid diagram (reuse `export_diagram.py`'s query+format logic)
  5. Returns one JSON response containing: parse summary (files/classes/functions/nodes), violations list, health score, and the raw Mermaid diagram string
- One static HTML page (`index.html` or similar) served by FastAPI, containing:
  - A text input for the GitHub URL and a submit button
  - JavaScript that calls `POST /analyze`, shows a loading state while waiting, then renders: the parse summary, the violations list with the health score, and the Mermaid diagram (rendered via the Mermaid.js CDN's `mermaid.render()` or `mermaid.init()`)
  - Basic, readable styling — not polished, just clean enough for a live demo
- Exact API contract and Definition of Done: see `SPEC.md` → "Implementation Scope — Phase 7"
- After writing code, RUN it and demo it yourself end-to-end (paste a real URL, watch it work in the browser) before considering it done

## Workflow
- Plan before implementing — use plan mode. Review the plan before approving.
- Every module needs a runnable verification step before it's "done."
- Keep code simple — this phase especially should be built fast and kept minimal, since it's needed for tomorrow's demo, not for long-term architecture.
- Since this reuses existing, already-verified logic, this phase should be faster than Phase 6 — resist the urge to add extra features "while you're at it."

## Not yet decided — fill in as the project solidifies
- Python lint/format command:
- TypeScript/React lint/format command:
- Backend test command:
- Frontend test command:
- Repo folder structure (once scaffolded):