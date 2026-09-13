# RepoMind AI

## What this is
An agentic platform that builds a **temporal knowledge graph** of a Git repository (structure + evolution) and uses it to power three capabilities: Architecture Drift Detection, ADR Reconstruction, and Repository Q&A. Full design lives in `SPEC.md` — read it before starting work on any module.

## CURRENT PHASE — READ THIS FIRST
**Phases 1 and 2 are complete and verified.**
- Phase 1 (parsing + Neo4j graph): 6 modules, 2 classes, 15 functions parsed → 23 nodes loaded, correct CALLS/IMPORTS/CONTAINS relationships confirmed.
- Phase 2 (deterministic rule engine + drift scoring): exactly 1 violation correctly detected (`controller.py::handle_request_direct -> database.py::save_record`), the two legitimate layered calls correctly produced no false positives, Architecture Health Score computed and clamped to [0, 100].

We are now building **Phase 3 only**: a minimal, narrow slice of Module 4 — Git history mining via PyDriller, per SPEC.md's "Implementation Scope — Phase 3" section. This phase is deliberately small and time-boxed: extraction and printed output only.

Do NOT build any of the following yet, even if referenced elsewhere in this file:
- Evidence correlation / relevance scoring (the α/β/γ formula)
- ADR Reconstruction / ADR synthesis (LLM-based)
- Repository Q&A (Capability 3)
- Any LangGraph agent, LLM call, or AI reasoning logic
- GitHub PR/API integration
- FastAPI backend or React dashboard
- Temporal versioning (`valid_from_commit` / `valid_to_commit`) on graph edges
- Historical/multi-commit drift scoring (re-running Phase 2's health score across commit history) — that depends on this phase existing first, but is not itself part of Phase 3

See the "Implementation Scope — Phase 3" section of `SPEC.md` for the exact prerequisite, extraction fields, and Definition of Done. Follow it precisely rather than expanding scope. If anything in this file's "Non-negotiable design rules" or "Tech stack" below conflicts with Phase 3 scope, **Phase 3 scope wins** — those sections describe the target system, not today's task.

Do not modify Phase 1 or Phase 2 code (`parser/`, `graph/`, `main.py`, `rules/`, `check_drift.py`, `rules.yaml`) except where SPEC.md's Phase 3 section explicitly says to (e.g., optionally adding `Commit`/`Developer` nodes via the existing loader pattern).

## Non-negotiable design rules (apply to the FULL system — several are deferred until later phases, see above)
IMPORTANT — these are the rules that make this project what it is. Do not let convenience during implementation violate them.

- **Deterministic before generative.** Architectural violations are found via Cypher graph queries against hand-authored rules — never by asking an LLM whether something is a violation. LLMs only explain, prioritize, and synthesize evidence; they never decide what counts as a fact. *(Already implemented in Phase 2. Not touched in Phase 3 — no LLM involvement here either.)*
- **Evidence / Inference / Confidence.** Every AI-generated claim (ADR text, drift explanation, Q&A answer) must be structured into what was found (evidence), what's inferred (reasoning), and a confidence score — never presented as unqualified fact. *(Not yet relevant — Phase 3 produces raw extracted data, not AI-generated claims.)*
- **One shared graph.** Drift Detection, ADR Reconstruction, and Q&A all read from the same Neo4j knowledge graph. Never build a second, disconnected data model for a new feature — if a capability needs new data, extend the shared graph schema. *(Applies if Phase 3's optional Commit/Developer nodes are built — they go into the SAME graph, not a separate store.)*
- **Temporal, not static.** Graph relationships are versioned intervals (`valid_from_commit` / `valid_to_commit`), not mutable edges. The graph must be able to answer "what did this look like at commit X," not just "what does it look like now." *(Still deferred — Phase 3 does not add temporal versioning to existing structural edges.)*
- **Rules are data.** Architecture rules are configuration, not hardcoded logic — a new rule must be addable without touching the rule-checking engine's code. *(Already implemented in Phase 2. Not relevant to Phase 3's scope.)*

## Tech stack (full target system)
- Parsing: Tree-sitter ← **Phase 1 (done)**
- Graph DB: Neo4j + Cypher ← **Phase 1 (done), extended in Phase 2**
- Graph analytics: NetworkX
- Git mining: PyDriller + GitHub REST API ← **PyDriller in progress (Phase 3); GitHub API deferred**
- Agent orchestration: LangGraph + LangChain
- LLMs: GPT-4o / Gemini Pro
- Backend: FastAPI (Python)
- Structured storage: PostgreSQL (commits, PRs, reports)
- Frontend: React + TypeScript, React Flow (graph viz), Mermaid (diagrams), Monaco Editor (code viewer)

## Phase 3 scope (current work)
- Ensure `test_repo/` is a real Git repository with a small, realistic commit history (initialize one if it isn't already)
- Use PyDriller to walk that history and extract: commit hash, message, author, timestamp, modified files
- Print this data clearly per commit
- Optional, only if time allows: load `Commit` and `Developer` nodes into the existing Neo4j graph with `AUTHORED` and `MODIFIED` relationships
- Node properties, extraction fields, and Definition of Done: see `SPEC.md` → "Implementation Scope — Phase 3"
- After writing code, RUN it and show the actual output (the printed commit history), rather than just describing what it should do
- Read Neo4j credentials from `.env` (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`) — never hardcode credentials in source files

## Workflow
- Plan before implementing any of the 5 major modules — use plan mode. Don't let a module that touches the graph schema go straight to code.
- Every module needs a runnable verification step before it's "done": a test, a query that returns the expected structural result, or a comparison against a real fixture repo (e.g. Spring PetClinic).
- When a correction repeats, add a rule to this file instead of re-explaining it each session.
- Keep code simple and readable — this is a capstone project under review, not a production system. Prioritize correctness and clarity over premature optimization.
- Start a fresh session (or `/clear`) when moving between phases rather than carrying over a long context.
- This phase is time-boxed — keep scope narrow and stop once the Definition of Done is met rather than expanding into Phase 4 territory (evidence correlation, ADR synthesis).

## Not yet decided — fill in as the project solidifies
- Python lint/format command:
- TypeScript/React lint/format command:
- Backend test command:
- Frontend test command:
- Repo folder structure (once scaffolded):