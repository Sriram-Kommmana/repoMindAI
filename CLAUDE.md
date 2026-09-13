# RepoMind AI

## What this is
An agentic platform that builds a **temporal knowledge graph** of a Git repository (structure + evolution) and uses it to power three capabilities: Architecture Drift Detection, ADR Reconstruction, and Repository Q&A. Full design lives in `SPEC.md` — read it before starting work on any module.

## CURRENT PHASE — READ THIS FIRST
**Phase 1 is complete and verified** (parsing + Neo4j graph, confirmed working — 15 nodes, 21 relationships against test_repo).

We are now building **Phase 2 only**: Module 3 (Architecture Analysis Engine) — the deterministic rule engine, violation detection, and drift scoring, per SPEC.md's "Implementation Scope — Phase 2" section.

Do NOT build any of the following yet, even if referenced elsewhere in this file:
- LLM explanation or prioritization of violations
- ADR Reconstruction (Module 4)
- Repository Q&A (Capability 3)
- Any LangGraph agent, LLM call, or AI reasoning logic
- FastAPI backend or React dashboard
- Git history mining (PyDriller) — that's part of Module 4, later
- Temporal versioning (`valid_from_commit` / `valid_to_commit`) — still deferred
- Historical/multi-commit drift scoring (a drift curve across commits) — Phase 2 computes the health score for the CURRENT graph state only

See the "Implementation Scope — Phase 2" section of `SPEC.md` for the exact fixture extension, rule format, folder structure, and Definition of Done. Follow it precisely rather than inventing scope. If anything in this file's "Non-negotiable design rules" or "Tech stack" below conflicts with Phase 2 scope, **Phase 2 scope wins** — those sections describe the target system, not today's task.

Do not modify Phase 1 code (`parser/`, `graph/loader.py`, `graph/schema.py`, `main.py`) except to extend it as explicitly described in SPEC.md's Phase 2 section (e.g., adding a `layer_type` property).

## Non-negotiable design rules (apply to the FULL system — several are deferred until later phases, see above)
IMPORTANT — these are the rules that make this project what it is. Do not let convenience during implementation violate them.

- **Deterministic before generative.** Architectural violations are found via Cypher graph queries against hand-authored rules — never by asking an LLM whether something is a violation. LLMs only explain, prioritize, and synthesize evidence; they never decide what counts as a fact. *(Directly relevant in Phase 2 — the rule engine IS this principle in practice. No LLM involvement yet.)*
- **Evidence / Inference / Confidence.** Every AI-generated claim (ADR text, drift explanation, Q&A answer) must be structured into what was found (evidence), what's inferred (reasoning), and a confidence score — never presented as unqualified fact. *(Not yet relevant — no AI/LLM output exists yet in Phase 2.)*
- **One shared graph.** Drift Detection, ADR Reconstruction, and Q&A all read from the same Neo4j knowledge graph. Never build a second, disconnected data model for a new feature — if a capability needs new data, extend the shared graph schema. *(Applies now — Phase 2 extends the existing Phase 1 graph with a `layer_type` property rather than creating a separate store.)*
- **Temporal, not static.** Graph relationships are versioned intervals (`valid_from_commit` / `valid_to_commit`), not mutable edges. The graph must be able to answer "what did this look like at commit X," not just "what does it look like now." *(Still deferred — Phase 2 scores the current state only.)*
- **Rules are data.** Architecture rules are configuration, not hardcoded logic — a new rule must be addable without touching the rule-checking engine's code. *(Directly relevant in Phase 2 — this is what `rules.yaml` is for. The rule engine must read rules generically, not hardcode the specific "no-controller-to-db" check.)*

## Tech stack (full target system)
- Parsing: Tree-sitter ← **Phase 1 (done)**
- Graph DB: Neo4j + Cypher ← **Phase 1 (done), extended in Phase 2**
- Graph analytics: NetworkX
- Git mining: PyDriller + GitHub REST API
- Agent orchestration: LangGraph + LangChain
- LLMs: GPT-4o / Gemini Pro
- Backend: FastAPI (Python)
- Structured storage: PostgreSQL (commits, PRs, reports)
- Frontend: React + TypeScript, React Flow (graph viz), Mermaid (diagrams), Monaco Editor (code viewer)

## Phase 2 scope (current work)
- Extend `test_repo/` with a layered fixture (controller.py, service.py, database.py) containing one deliberate architecture violation — see SPEC.md for exact structure
- Add a `layer_type` property to relevant Module nodes
- Build a generic rule engine that reads `rules.yaml` and compiles rules into Cypher queries — do not hardcode the specific rule being tested
- Compute the Architecture Health Score for the current graph state
- Node properties, rule format, folder structure, and Definition of Done: see `SPEC.md` → "Implementation Scope — Phase 2"
- After writing code, RUN it and show the actual output (violations found + health score), rather than just describing what it should do
- Read Neo4j credentials from `.env` (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`) — never hardcode credentials in source files

## Workflow
- Plan before implementing any of the 5 major modules — use plan mode. Don't let a module that touches the graph schema go straight to code.
- Every module needs a runnable verification step before it's "done": a test, a query that returns the expected structural result, or a comparison against a real fixture repo (e.g. Spring PetClinic).
- When a correction repeats, add a rule to this file instead of re-explaining it each session.
- Keep code simple and readable — this is a capstone project under review, not a production system. Prioritize correctness and clarity over premature optimization.
- Start a fresh session (or `/clear`) when moving between phases rather than carrying over a long context.

## Not yet decided — fill in as the project solidifies
- Python lint/format command:
- TypeScript/React lint/format command:
- Backend test command:
- Frontend test command:
- Repo folder structure (once scaffolded):