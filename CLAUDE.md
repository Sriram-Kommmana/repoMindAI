# RepoMind AI

## What this is
An agentic platform that builds a **temporal knowledge graph** of a Git repository (structure + evolution) and uses it to power three capabilities: Architecture Drift Detection, ADR Reconstruction, and Repository Q&A. Full design lives in `SPEC.md` — read it before starting work on any module.

## CURRENT PHASE — READ THIS FIRST
**Phases 1, 2, and 3 are complete and verified.**
- Phase 1 (parsing + Neo4j graph): verified — 6 modules, 2 classes, 15 functions parsed → 23 nodes loaded, correct CALLS/IMPORTS/CONTAINS relationships.
- Phase 2 (deterministic rule engine + drift scoring): verified — exactly 1 violation correctly detected (`controller.py::handle_request_direct -> database.py::save_record`), no false positives on the two legitimate layered calls, Architecture Health Score computed and clamped to [0, 100].
- Phase 3 (Git history mining via PyDriller): verified against the outer repoMindAI repo's real commit history — 2 commits correctly extracted with matching hashes, messages, authors, dates, and modified files.

We are now building **Phase 4 only**: exporting the existing knowledge graph's module dependencies as a Mermaid diagram, per SPEC.md's "Implementation Scope — Phase 4" section. This is a small, self-contained visualization step — it queries data that already exists in the graph (Module nodes, IMPORTS relationships, layer_type), no new analysis, parsing, or graph-writing logic.

Do NOT build any of the following yet, even if referenced elsewhere in this file:
- ADR Reconstruction / ADR synthesis (LLM-based)
- Evidence correlation / relevance scoring
- Repository Q&A (Capability 3)
- Any LangGraph agent, LLM call, or AI reasoning logic
- FastAPI backend or React dashboard
- A web-based interactive diagram viewer (Phase 4 outputs a static Mermaid file, not a UI)
- Class-level or function-level diagrams (module-level dependency diagram only, for now)
- Temporal versioning (`valid_from_commit` / `valid_to_commit`)
- Automatic repo cloning from a pasted URL (that's a separate, later addition — see "Not yet built" note below)

See the "Implementation Scope — Phase 4" section of `SPEC.md` for the exact query approach, Mermaid output format, and Definition of Done. Follow it precisely rather than expanding scope. If anything in this file's "Non-negotiable design rules" or "Tech stack" below conflicts with Phase 4 scope, **Phase 4 scope wins** — those sections describe the target system, not today's task.

Do not modify Phase 1, 2, or 3 code (`parser/`, `graph/`, `main.py`, `rules/`, `check_drift.py`, `rules.yaml`, `mine_history.py`) — Phase 4 only reads from the existing graph, it does not need to change how data gets into it.

### Not yet built (known gaps, for honest status reporting)
- No automatic repo-cloning from a pasted GitHub URL — currently all scripts take a local folder path
- No web UI / dashboard — all output is terminal/file-based (printed text, `.md` diagram files)
- ADR Reconstruction and Repository Q&A are fully unbuilt

## Non-negotiable design rules (apply to the FULL system — several are deferred until later phases, see above)
IMPORTANT — these are the rules that make this project what it is. Do not let convenience during implementation violate them.

- **Deterministic before generative.** Architectural violations are found via Cypher graph queries against hand-authored rules — never by asking an LLM whether something is a violation. LLMs only explain, prioritize, and synthesize evidence; they never decide what counts as a fact. *(Already implemented in Phase 2. Phase 4 is also deterministic — it's a pure data query/formatting step, no LLM involvement.)*
- **Evidence / Inference / Confidence.** Every AI-generated claim (ADR text, drift explanation, Q&A answer) must be structured into what was found (evidence), what's inferred (reasoning), and a confidence score — never presented as unqualified fact. *(Not relevant to Phase 4 — no AI-generated claims here, just a direct rendering of graph data.)*
- **One shared graph.** Drift Detection, ADR Reconstruction, and Q&A all read from the same Neo4j knowledge graph. Never build a second, disconnected data model for a new feature — if a capability needs new data, extend the shared graph schema. *(Directly relevant — Phase 4 reads from the SAME graph Phases 1-2 built, it doesn't create a separate data source.)*
- **Temporal, not static.** Graph relationships are versioned intervals (`valid_from_commit` / `valid_to_commit`), not mutable edges. The graph must be able to answer "what did this look like at commit X," not just "what does it look like now." *(Still deferred — Phase 4 diagrams the current-state graph only.)*
- **Rules are data.** Architecture rules are configuration, not hardcoded logic — a new rule must be addable without touching the rule-checking engine's code. *(Already implemented in Phase 2. Not relevant to Phase 4.)*

## Tech stack (full target system)
- Parsing: Tree-sitter ← **Phase 1 (done)**
- Graph DB: Neo4j + Cypher ← **Phase 1 (done), extended in Phase 2, queried (read-only) in Phase 4**
- Graph analytics: NetworkX
- Git mining: PyDriller + GitHub REST API ← **PyDriller done (Phase 3); GitHub API deferred**
- Agent orchestration: LangGraph + LangChain
- LLMs: GPT-4o / Gemini Pro
- Backend: FastAPI (Python)
- Structured storage: PostgreSQL (commits, PRs, reports)
- Frontend: React + TypeScript, React Flow (graph viz), Mermaid (diagrams) ← **Mermaid generation starting in Phase 4 (script-based, not yet integrated into a frontend)**, Monaco Editor (code viewer)

## Phase 4 scope (current work)
- Query the existing Neo4j graph for all `Module` nodes and `IMPORTS` relationships (read-only — no writes to the graph)
- Generate valid Mermaid `flowchart` syntax representing module-level dependencies
- Group/style nodes by `layer_type` where present (controller/service/database), so the layered architecture is visually distinguishable
- Write output to `diagram_output.md` and also print it to the console
- Query approach, exact output format, and Definition of Done: see `SPEC.md` → "Implementation Scope — Phase 4"
- After writing code, RUN it and show the actual generated Mermaid output, rather than just describing what it should do

## Workflow
- Plan before implementing any of the 5 major modules — use plan mode. Don't let a module that touches the graph schema go straight to code.
- Every module needs a runnable verification step before it's "done": a test, a query that returns the expected structural result, or a comparison against a real fixture repo (e.g. Spring PetClinic).
- When a correction repeats, add a rule to this file instead of re-explaining it each session.
- Keep code simple and readable — this is a capstone project under review, not a production system. Prioritize correctness and clarity over premature optimization.
- Start a fresh session (or `/clear`) when moving between phases rather than carrying over a long context.
- This phase is small and self-contained — keep it that way rather than expanding into a full diagram-viewing UI.

## Not yet decided — fill in as the project solidifies
- Python lint/format command:
- TypeScript/React lint/format command:
- Backend test command:
- Frontend test command:
- Repo folder structure (once scaffolded):