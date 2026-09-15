# RepoMind AI

## What this is
An agentic platform that builds a **temporal knowledge graph** of a Git repository (structure + evolution) and uses it to power three capabilities: Architecture Drift Detection, ADR Reconstruction, and Repository Q&A. Full design lives in `SPEC.md` — read it before starting work on any module.

## CURRENT PHASE — READ THIS FIRST
**Phases 1-4, 5a, and 5b are complete and verified** (Python-only pipeline: parsing, knowledge graph, deterministic drift detection, Git mining, Mermaid diagram export, URL-to-clone wrapper, robustness-tested against 5 real repos with 3 genuine bugs found and fixed — decorators, relative imports, wildcard imports). Full details in SPEC.md.

We are now building **Phase 6: JavaScript + TypeScript support**, per SPEC.md's "Implementation Scope — Phase 6" section. Goal: extend `parser/ast_extractor.py` (or add parallel language-specific extractor modules) so the SAME pipeline (graph, drift detection, diagram export) works on JS/TS repos, not just Python.

**Process for this phase — same discipline as Phase 5b, do not skip steps:**
1. Add JS support first, fully tested against 2-3 real small JS repos, before starting TS.
2. Add TS support second (reusing JS logic where the grammars overlap), tested against 1-2 real small TS repos.
3. After EVERY change, re-run `python main.py ./test_repo` and confirm the original Python-only output is unchanged (6 files, 2 classes, 15 functions, 23 nodes) — Python support must not regress.
4. Document each bug found/fixed the same way Phase 5b did — this is real report material, not just internal notes.

Do NOT build any of the following yet, even if referenced elsewhere in this file:
- Java support (explicitly deferred — JS+TS only for this phase; Java is structurally different enough to warrant its own separate phase later)
- LLM Explanation Agent, ADR Reconstruction, Repository Q&A, any LangGraph/agent logic
- FastAPI backend or React dashboard
- Speculative try/except or skip-and-warn for edge cases not actually encountered (fix real bugs found via real repos, same rule as Phase 5b)
- Temporal versioning

See the "Implementation Scope — Phase 6" section of `SPEC.md` for the exact approach, test repo suggestions, and Definition of Done. Follow it precisely rather than expanding scope. If anything in this file's "Non-negotiable design rules" or "Tech stack" below conflicts with Phase 6 scope, **Phase 6 scope wins** — those sections describe the target system, not today's task.

### Known status (for honest reporting)
- No web UI / dashboard — everything is CLI/terminal-based
- ADR Reconstruction and Repository Q&A are fully unbuilt
- Zero LLM/agentic components exist anywhere in the codebase as of this phase — Phase 6 is still purely deterministic parsing/graph work, same as everything before it
- Java support not yet started (deferred to a later phase, out of scope for Phase 6)

## Non-negotiable design rules (apply to the FULL system — several are deferred until later phases, see above)
IMPORTANT — these are the rules that make this project what it is. Do not let convenience during implementation violate them.

- **Deterministic before generative.** Architectural violations are found via Cypher graph queries against hand-authored rules — never by asking an LLM whether something is a violation. LLMs only explain, prioritize, and synthesize evidence; they never decide what counts as a fact. *(Unaffected by Phase 6 — this is still pure parsing, no AI involved.)*
- **Evidence / Inference / Confidence.** Every AI-generated claim must be structured into evidence, inference, and confidence. *(Not relevant to Phase 6.)*
- **One shared graph.** All capabilities read from the same Neo4j knowledge graph. *(Directly relevant — JS/TS modules go into the SAME graph schema as Python modules, same Module/Class/Function node types, not a separate schema per language.)*
- **Temporal, not static.** Still deferred.
- **Rules are data.** Unaffected by Phase 6 — the existing `rules.yaml`/rule engine works on ANY language's graph data once loaded, since rules operate on `layer_type` and relationships, not language-specific syntax.

## Tech stack (full target system)
- Parsing: Tree-sitter ← **Python done (Phases 1, 5b); JS/TS in progress (Phase 6)** — new grammars needed: `tree-sitter-javascript`, `tree-sitter-typescript`
- Graph DB: Neo4j + Cypher ← **done, language-agnostic schema**
- Graph analytics: NetworkX
- Git mining: PyDriller + GitHub REST API ← **done (Python-repo-agnostic, works on any Git repo regardless of language)**
- Repo acquisition: `git clone` via subprocess ← **done, language-agnostic**
- Agent orchestration: LangGraph + LangChain — not started
- LLMs: GPT-4o / Gemini Pro — not started
- Backend: FastAPI (Python) — not started
- Structured storage: PostgreSQL — not started
- Frontend: React + TypeScript, React Flow, Mermaid ← **script-based Mermaid generation done (Phase 4), language-agnostic**, Monaco Editor — not started

## Phase 6 scope (current work)
- Add a JavaScript extraction path: map `tree-sitter-javascript` node types (`function_declaration`, `arrow_function`, `class_declaration`, `import_statement`/`require` calls, etc.) to the SAME output shape Python's extractor already produces (modules/classes/functions/imports/calls) — so `graph/loader.py` needs ZERO changes, it already accepts this shape regardless of source language
- Detect file language by extension (`.py` → Python path, `.js`/`.jsx` → JS path, `.ts`/`.tsx` → TS path) and route to the correct extractor
- Test JS support against 2-3 real small JS repos, fixing genuine bugs found (same process as Phase 5b)
- Add a TypeScript extraction path (reusing JS logic where grammars overlap — TS is a superset in AST terms for many constructs, but has its own grammar and additional node types for interfaces/types/generics)
- Test TS support against 1-2 real small TS repos
- After every change, confirm zero regression on Python's `test_repo` output
- Exact approach and Definition of Done: see `SPEC.md` → "Implementation Scope — Phase 6"

## Workflow
- Plan before implementing — use plan mode. Review the plan before approving.
- Every module needs a runnable verification step before it's "done."
- Keep code simple and readable — this is a capstone project under review, not a production system.
- This phase is iterative (add language → test against real repos → fix bugs → re-verify Python regression → repeat) — same proven process as Phase 5b, don't skip the regression check at any point.

## Not yet decided — fill in as the project solidifies
- Python lint/format command:
- TypeScript/React lint/format command:
- Backend test command:
- Frontend test command:
- Repo folder structure (once scaffolded):