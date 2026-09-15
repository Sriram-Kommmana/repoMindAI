# RepoMind AI

## What this is
An agentic platform that builds a **temporal knowledge graph** of a Git repository (structure + evolution) and uses it to power three capabilities: Architecture Drift Detection, ADR Reconstruction, and Repository Q&A. Full design lives in `SPEC.md` — read it before starting work on any module.

## CURRENT PHASE — READ THIS FIRST
**Phases 1-4 and 5a are complete and verified.**
- Phase 1 (parsing + Neo4j graph): verified — 23 nodes, correct CALLS/IMPORTS/CONTAINS relationships.
- Phase 2 (deterministic rule engine + drift scoring): verified — 1 violation correctly detected, no false positives, score clamped to [0, 100].
- Phase 3 (Git history mining via PyDriller): verified against the outer repo's real commit history — 2 commits correctly extracted.
- Phase 4 (Mermaid diagram export): verified — 3 layer-styled subgraphs, 3 ungrouped nodes, 5 edges, matching a pre-computed expected structure, visually confirmed rendering.
- Phase 5a (URL-to-local-clone wrapper): verified against a real public GitHub repo, `kennethreitz/samplemod` — 9 files, 2 classes, 5 functions, 16 nodes loaded. A genuine Windows read-only cleanup bug (`.git` internals) was found and fixed during this phase.

We are now on **Phase 5b: Robustness Testing Against Real Repos** — running `analyze_repo.py` against several more real, structurally-varied public repos to find and fix genuine parsing bugs, per SPEC.md's "Implementation Scope — Phase 5b" section.

**Critical distinction for this phase:** Phase 5b means FIXING actual bugs found in `parser/ast_extractor.py` when real code breaks it — it does NOT mean adding generic try/except or skip-and-warn behavior speculatively. That's Phase 5c, a separate later step. If something breaks in 5b, either fix the root cause properly, or explicitly flag it as a Phase 5c candidate — don't silently swallow errors in this phase.

**After ANY fix to `parser/ast_extractor.py`, re-run `python main.py ./test_repo` and confirm it still produces the exact original output** (6 files, 2 classes, 15 functions, 23 nodes) — no regression on the known-good fixture. This regression check is mandatory after every fix, not optional.

Do NOT build any of the following yet, even if referenced elsewhere in this file:
- Skip-and-warn / graceful degradation for unparseable constructs (that's Phase 5c)
- ADR Reconstruction / ADR synthesis (LLM-based)
- Evidence correlation / relevance scoring
- Repository Q&A (Capability 3)
- Any LangGraph agent, LLM call, or AI reasoning logic
- FastAPI backend or React dashboard
- Testing against large/complex repos (keep test repos small and single-purpose)
- Temporal versioning (`valid_from_commit` / `valid_to_commit`)

See the "Implementation Scope — Phase 5b" section of `SPEC.md` for the exact test repo list, process, and Definition of Done. Follow it precisely rather than expanding scope. If anything in this file's "Non-negotiable design rules" or "Tech stack" below conflicts with Phase 5b scope, **Phase 5b scope wins** — those sections describe the target system, not today's task.

Only `parser/ast_extractor.py` should need changes in this phase (to fix genuine parsing bugs). Do not modify `graph/`, `rules/`, `check_drift.py`, `mine_history.py`, `export_diagram.py`, `main.py`, or `analyze_repo.py` unless a specific bug genuinely requires it — and if so, explain why before doing so.

### Known status (for honest reporting)
- No web UI / dashboard — everything is CLI/terminal-based
- ADR Reconstruction and Repository Q&A are fully unbuilt
- As of Phase 5a, parsing has been verified against test_repo AND one real repo (samplemod) — Phase 5b is actively expanding this real-world verification

## Non-negotiable design rules (apply to the FULL system — several are deferred until later phases, see above)
IMPORTANT — these are the rules that make this project what it is. Do not let convenience during implementation violate them.

- **Deterministic before generative.** Architectural violations are found via Cypher graph queries against hand-authored rules — never by asking an LLM whether something is a violation. LLMs only explain, prioritize, and synthesize evidence; they never decide what counts as a fact. *(Unaffected by Phase 5b — parsing bug fixes don't touch analysis logic.)*
- **Evidence / Inference / Confidence.** Every AI-generated claim (ADR text, drift explanation, Q&A answer) must be structured into what was found (evidence), what's inferred (reasoning), and a confidence score — never presented as unqualified fact. *(Not relevant to Phase 5b.)*
- **One shared graph.** Drift Detection, ADR Reconstruction, and Q&A all read from the same Neo4j knowledge graph. Never build a second, disconnected data model for a new feature — if a capability needs new data, extend the shared graph schema. *(Unaffected by Phase 5b.)*
- **Temporal, not static.** Graph relationships are versioned intervals (`valid_from_commit` / `valid_to_commit`), not mutable edges. The graph must be able to answer "what did this look like at commit X," not just "what does it look like now." *(Still deferred.)*
- **Rules are data.** Architecture rules are configuration, not hardcoded logic — a new rule must be addable without touching the rule-checking engine's code. *(Unaffected by Phase 5b.)*

## Tech stack (full target system)
- Parsing: Tree-sitter ← **Phase 1 (done), hardened in Phase 5b**
- Graph DB: Neo4j + Cypher ← **Phase 1 (done), extended in Phase 2, read in Phase 4**
- Graph analytics: NetworkX
- Git mining: PyDriller + GitHub REST API ← **PyDriller done (Phase 3); GitHub API deferred**
- Repo acquisition: `git clone` via subprocess ← **Phase 5a (done), tested against real repos in Phase 5b**
- Agent orchestration: LangGraph + LangChain
- LLMs: GPT-4o / Gemini Pro
- Backend: FastAPI (Python)
- Structured storage: PostgreSQL (commits, PRs, reports)
- Frontend: React + TypeScript, React Flow (graph viz), Mermaid (diagrams) ← **script-based generation done (Phase 4)**, Monaco Editor (code viewer)

## Phase 5b scope (current work)
- Run `analyze_repo.py <url>` against at least 4 different real, small, structurally-varied public Python repos (see SPEC.md for the suggested list: a simple module, a Flask app, a CLI tool with decorators, a package with relative imports)
- For each, diagnose any crash or incorrect output, and fix the ROOT CAUSE in `parser/ast_extractor.py` if it's a genuine, general parsing bug
- Do NOT add speculative try/except or generic error suppression — only fix things that actually broke, on real code that actually triggered the bug
- After every fix, re-run `python main.py ./test_repo` to confirm zero regression on the known-good fixture
- Document each repo's result (worked cleanly / bug found+fixed / deferred to 5c) for later use in the report
- Exact test repo list, process, and Definition of Done: see `SPEC.md` → "Implementation Scope — Phase 5b"
- After writing any fix, RUN it against the repo that triggered the bug and show the actual corrected output, rather than just describing the fix

## Workflow
- Plan before implementing any of the 5 major modules — use plan mode. Don't let a module that touches the graph schema go straight to code.
- Every module needs a runnable verification step before it's "done": a test, a query that returns the expected structural result, or a comparison against a real fixture repo.
- When a correction repeats, add a rule to this file instead of re-explaining it each session.
- Keep code simple and readable — this is a capstone project under review, not a production system. Prioritize correctness and clarity over premature optimization.
- Start a fresh session (or `/clear`) when moving between phases rather than carrying over a long context.
- This phase is iterative by nature (test → find bug → fix → re-verify → next repo) — expect multiple rounds rather than one clean pass, and treat each round as its own small, verified step.

## Not yet decided — fill in as the project solidifies
- Python lint/format command:
- TypeScript/React lint/format command:
- Backend test command:
- Frontend test command:
- Repo folder structure (once scaffolded):