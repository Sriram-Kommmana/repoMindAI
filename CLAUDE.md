# RepoMind AI

## What this is
An agentic platform that builds a **temporal knowledge graph** of a Git repository (structure + evolution) and uses it to power three capabilities: Architecture Drift Detection, ADR Reconstruction, and Repository Q&A. Full design lives in `SPEC.md` — read it before starting work on any module.

## CURRENT PHASE — READ THIS FIRST
**Phases 1, 2, 3, and 4 are complete and verified.**
- Phase 1 (parsing + Neo4j graph): verified — 23 nodes, correct CALLS/IMPORTS/CONTAINS relationships.
- Phase 2 (deterministic rule engine + drift scoring): verified — 1 violation correctly detected, no false positives, score clamped to [0, 100].
- Phase 3 (Git history mining via PyDriller): verified against the outer repo's real commit history — 2 commits correctly extracted.
- Phase 4 (Mermaid diagram export): verified — 3 layer-styled subgraphs, 3 ungrouped nodes, 5 edges, matching a pre-computed expected structure, visually confirmed rendering.

We are now building **Phase 5a only**: a URL-to-local-clone wrapper, so the pipeline can be pointed at ANY public GitHub repo URL instead of only a local folder path. Per SPEC.md's "Implementation Scope — Phase 5a" section.

**Important context for this phase:** Phase 5a is intentionally the FIRST of three planned steps (5a → 5b → 5c). Do NOT attempt 5b (testing against multiple real repos and fixing parsing edge cases) or 5c (graceful failure handling for unparseable constructs) in this session — those are separate, later steps with their own scope once 5a is verified working. Keep this phase strictly to: accept a URL, clone it, feed the local path into the EXISTING, UNCHANGED pipeline.

Do NOT build any of the following yet, even if referenced elsewhere in this file:
- ADR Reconstruction / ADR synthesis (LLM-based)
- Evidence correlation / relevance scoring
- Repository Q&A (Capability 3)
- Any LangGraph agent, LLM call, or AI reasoning logic
- FastAPI backend or React dashboard
- Robustness fixes for parsing edge cases not yet encountered (that's Phase 5b — don't speculatively add try/except blocks for problems you haven't actually seen yet)
- Temporal versioning (`valid_from_commit` / `valid_to_commit`)

See the "Implementation Scope — Phase 5a" section of `SPEC.md` for the exact approach, CLI interface, and Definition of Done. Follow it precisely rather than expanding scope. If anything in this file's "Non-negotiable design rules" or "Tech stack" below conflicts with Phase 5a scope, **Phase 5a scope wins** — those sections describe the target system, not today's task.

Do not modify `parser/ast_extractor.py`, `graph/loader.py`, `graph/schema.py`, `rules/`, `check_drift.py`, `rules.yaml`, `mine_history.py`, or `export_diagram.py` — Phase 5a only adds a new entry point in front of the existing, unchanged pipeline. If `main.py` needs a small change to accept either a local path OR delegate to the new clone step, that's the only existing file allowed to change, and only minimally.

### Known status (for honest reporting)
- No web UI / dashboard — everything is CLI/terminal-based
- ADR Reconstruction and Repository Q&A are fully unbuilt
- Parsing has only been verified against the small test_repo fixture — Phase 5b (next, not this session) will test against real-world repos and fix whatever breaks

## Non-negotiable design rules (apply to the FULL system — several are deferred until later phases, see above)
IMPORTANT — these are the rules that make this project what it is. Do not let convenience during implementation violate them.

- **Deterministic before generative.** Architectural violations are found via Cypher graph queries against hand-authored rules — never by asking an LLM whether something is a violation. LLMs only explain, prioritize, and synthesize evidence; they never decide what counts as a fact. *(Unaffected by Phase 5a — this phase only adds an input method, no analysis logic changes.)*
- **Evidence / Inference / Confidence.** Every AI-generated claim (ADR text, drift explanation, Q&A answer) must be structured into what was found (evidence), what's inferred (reasoning), and a confidence score — never presented as unqualified fact. *(Not relevant to Phase 5a.)*
- **One shared graph.** Drift Detection, ADR Reconstruction, and Q&A all read from the same Neo4j knowledge graph. Never build a second, disconnected data model for a new feature — if a capability needs new data, extend the shared graph schema. *(Unaffected — Phase 5a still feeds the same graph via the same loader.)*
- **Temporal, not static.** Graph relationships are versioned intervals (`valid_from_commit` / `valid_to_commit`), not mutable edges. The graph must be able to answer "what did this look like at commit X," not just "what does it look like now." *(Still deferred.)*
- **Rules are data.** Architecture rules are configuration, not hardcoded logic — a new rule must be addable without touching the rule-checking engine's code. *(Unaffected by Phase 5a.)*

## Tech stack (full target system)
- Parsing: Tree-sitter ← **Phase 1 (done)**
- Graph DB: Neo4j + Cypher ← **Phase 1 (done), extended in Phase 2, read in Phase 4**
- Graph analytics: NetworkX
- Git mining: PyDriller + GitHub REST API ← **PyDriller done (Phase 3); GitHub API deferred**
- Repo acquisition: `git clone` via GitPython or subprocess ← **Phase 5a (current)**
- Agent orchestration: LangGraph + LangChain
- LLMs: GPT-4o / Gemini Pro
- Backend: FastAPI (Python)
- Structured storage: PostgreSQL (commits, PRs, reports)
- Frontend: React + TypeScript, React Flow (graph viz), Mermaid (diagrams) ← **script-based Mermaid generation done (Phase 4)**, Monaco Editor (code viewer)

## Phase 5a scope (current work)
- Accept a GitHub repository URL as input (CLI argument)
- Clone it to a temporary local directory
- Feed that local path into the EXISTING pipeline (`main.py`'s parse+load logic) — no changes to parsing/graph logic itself
- Print clear status messages (cloning, parsing, done) since this will run live in front of a panel
- Clean up the temporary clone afterward (or leave it — see SPEC.md for the exact decision)
- Exact CLI interface and Definition of Done: see `SPEC.md` → "Implementation Scope — Phase 5a"
- After writing code, RUN it against a real small public GitHub repo URL and show the actual output, rather than just describing what it should do
- This is ONLY step 1 of 3 (5a → 5b → 5c) — do not expand into testing multiple repos or adding error handling for unseen edge cases in this session

## Workflow
- Plan before implementing any of the 5 major modules — use plan mode. Don't let a module that touches the graph schema go straight to code.
- Every module needs a runnable verification step before it's "done": a test, a query that returns the expected structural result, or a comparison against a real fixture repo.
- When a correction repeats, add a rule to this file instead of re-explaining it each session.
- Keep code simple and readable — this is a capstone project under review, not a production system. Prioritize correctness and clarity over premature optimization.
- Start a fresh session (or `/clear`) when moving between phases rather than carrying over a long context.
- Phases are intentionally small and sequential (5a, then 5b, then 5c) — resist the urge to combine them into one large session even with time/budget available; verifying each step independently is what has made every prior phase reliable.

## Not yet decided — fill in as the project solidifies
- Python lint/format command:
- TypeScript/React lint/format command:
- Backend test command:
- Frontend test command:
- Repo folder structure (once scaffolded):