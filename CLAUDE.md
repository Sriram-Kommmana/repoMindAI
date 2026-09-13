# RepoMind AI

## What this is
An agentic platform that builds a **temporal knowledge graph** of a Git repository (structure + evolution) and uses it to power three capabilities: Architecture Drift Detection, ADR Reconstruction, and Repository Q&A. Full design lives in `SPEC.md` — read it before starting work on any module.

## CURRENT PHASE — READ THIS FIRST
We are building **Phase 1 only**: Module 1 (Ingestion & Parsing) and Module 2 (Software Knowledge Graph). Everything else described in this file and in SPEC.md is the target architecture, not what to build right now.

Do NOT build any of the following yet, even if referenced elsewhere in this file:
- Architecture Drift Detection (Module 3)
- ADR Reconstruction (Module 4)
- Repository Q&A (Capability 3)
- Any LangGraph agent, LLM call, or AI reasoning logic
- FastAPI backend or React dashboard
- Git history mining (PyDriller) — that's part of Module 4, later
- Temporal versioning (`valid_from_commit` / `valid_to_commit`) — Phase 1 uses current-state edges only; see Phase 1 scope below

See the "Implementation Scope — Phase 1" section of `SPEC.md` for exact node properties, relationship types, folder structure, and Definition of Done. Follow it precisely rather than inventing scope. If anything in this file's "Non-negotiable design rules" or "Tech stack" below conflicts with Phase 1 scope, **Phase 1 scope wins** — those sections describe the target system, not today's task.

## Non-negotiable design rules (apply to the FULL system — several are deferred in Phase 1, see above)
IMPORTANT — these are the rules that make this project what it is. Do not let convenience during implementation violate them.

- **Deterministic before generative.** Architectural violations are found via Cypher graph queries against hand-authored rules — never by asking an LLM whether something is a violation. LLMs only explain, prioritize, and synthesize evidence; they never decide what counts as a fact. *(Not yet relevant in Phase 1 — no rule-checking or LLM logic exists yet.)*
- **Evidence / Inference / Confidence.** Every AI-generated claim (ADR text, drift explanation, Q&A answer) must be structured into what was found (evidence), what's inferred (reasoning), and a confidence score — never presented as unqualified fact. *(Not yet relevant in Phase 1.)*
- **One shared graph.** Drift Detection, ADR Reconstruction, and Q&A all read from the same Neo4j knowledge graph. Never build a second, disconnected data model for a new feature — if a capability needs new data, extend the shared graph schema. *(Applies now — Phase 1's graph is that shared foundation; build its schema to be extended, not replaced, later.)*
- **Temporal, not static.** Graph relationships are versioned intervals (`valid_from_commit` / `valid_to_commit`), not mutable edges. The graph must be able to answer "what did this look like at commit X," not just "what does it look like now." *(Deferred in Phase 1 — current-state edges only for now; design the schema so versioning can be added later without a full rewrite.)*
- **Rules are data.** Architecture rules are configuration, not hardcoded logic — a new rule must be addable without touching the rule-checking engine's code. *(Not yet relevant in Phase 1 — no rule engine exists yet.)*

## Tech stack (full target system)
- Parsing: Tree-sitter ← **Phase 1**
- Graph DB: Neo4j + Cypher ← **Phase 1**
- Graph analytics: NetworkX
- Git mining: PyDriller + GitHub REST API
- Agent orchestration: LangGraph + LangChain
- LLMs: GPT-4o / Gemini Pro
- Backend: FastAPI (Python)
- Structured storage: PostgreSQL (commits, PRs, reports)
- Frontend: React + TypeScript, React Flow (graph viz), Mermaid (diagrams), Monaco Editor (code viewer)

## Phase 1 scope (current work)
- Language support: Python only for now (expand later)
- Node properties, relationship types, folder structure, and Definition of Done: see `SPEC.md` → "Implementation Scope — Phase 1"
- Test everything against `test_repo/` — a small sample repo in this project — before considering any part of Phase 1 done
- After writing code, RUN it against `test_repo/` and show the actual output (parsed summary + a Neo4j query result), rather than just describing what it should do
- Read Neo4j credentials from `.env` (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`) — never hardcode credentials in source files

## Workflow
- Plan before implementing any of the 5 major modules — use plan mode. Don't let a module that touches the graph schema go straight to code.
- Every module needs a runnable verification step before it's "done": a test, a query that returns the expected structural result, or a comparison against a real fixture repo (e.g. Spring PetClinic).
- When a correction repeats, add a rule to this file instead of re-explaining it each session.
- Keep Phase 1 code simple and readable — this is a capstone project under review, not a production system. Prioritize correctness and clarity over premature optimization.

## Not yet decided — fill in as the project solidifies
- Python lint/format command:
- TypeScript/React lint/format command:
- Backend test command:
- Frontend test command:
- Repo folder structure (once scaffolded):
