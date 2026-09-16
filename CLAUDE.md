# RepoMind AI

## What this is
An agentic platform that builds a **temporal knowledge graph** of a Git repository (structure + evolution) and uses it to power three capabilities: Architecture Drift Detection, ADR Reconstruction, and Repository Q&A. Full design lives in `SPEC.md` — read it before starting work on any module.

## CURRENT PHASE — READ THIS FIRST
**Phases 1-4, 5a, 5b, 6, and 7 are complete and verified.** The pipeline (parsing, knowledge graph, deterministic drift detection, Git mining, Mermaid diagram export, URL-to-clone) works across Python, JavaScript, and TypeScript — tested against 11 real repos total, 7 genuine bugs found and fixed, with a confirmed cross-language proof. Phase 7 added a minimal FastAPI + static-HTML web interface (`server.py`, `static/index.html`) exposing that pipeline through a browser: paste a GitHub URL, see the parse summary, drift violations, health score, and Mermaid diagram. Full details in SPEC.md.

**Phase 8 (LLM-generated documentation) and Phase 8b (map-reduce redesign) are both complete and verified.** Goal: generate one comprehensive Markdown documentation page for the analyzed repo (in the spirit of tools like deepwiki-open) and render it as a new section of the same Phase 7 page — the first generative/LLM component this project has ever had. LLM provider: **Groq** (`openai/gpt-oss-120b`, OpenAI-compatible API) — reached after trying Gemini (persistent transient 503s even with retry logic) and OpenRouter's free NVIDIA Nemotron 3.5 Lightning (never completed a single request across three tries, up to 150s).

**Phase 8b replaced the single-call design with map-reduce, on explicit user request, after confirming a real completeness bug: a single prompt covering the whole repo meant most files got no real source coverage, and large repos even had their structural summary truncated — some modules never appeared in the prompt at all.** A RAG/retrieval pipeline was evaluated and explicitly rejected (narrows scope to answer one query — the opposite of "cover every file"); the fix is map-reduce summarization instead. See SPEC.md's "Implementation Scope — Phase 8b" for full detail, bugs found, and verification. Current architecture, across `grouping.py` (new) and `docs_generator.py`:
1. `grouping.group_modules()` groups modules the same way the diagram does (`layer_type` first, then folder, then a flat root bucket), then splits each group into batches of ≤10 modules
2. **Map phase**: one LLM call per batch (parallelized, 2 at a time) producing only that batch's module-by-module section, with every module in the batch getting a real source excerpt (not just a repo-wide priority subset)
3. **Reduce phase**: one final call synthesizes the Overview/Architecture narrative from the (much smaller) per-batch results — never sees raw source
4. `## Known Architecture Issues` and `## Key Relationships & Dependencies` are now 100% deterministic Python templating — zero LLM involvement, since both are exhaustive structured data already available
5. Every per-batch or reduce failure degrades to a clearly-marked deterministic fallback instead of failing the whole document — surfaced via a new `documentation_warnings` field, not just `documentation_error`
6. A repo whose modules all land in one group (rare — even small repos usually span 2+ folders) skips map-reduce entirely via a single-call fast path
7. Render the returned Markdown in `static/index.html`, sanitized with DOMPurify before insertion (the underlying repo is untrusted content); warnings render in their own notice above the doc

Do NOT build any of the following — this must stay small and demo-focused:
- Multi-page wiki, navigation, or per-module documentation pages — one Markdown doc, one page (map-reduce is an internal generation strategy, not a UI change)
- A chat/Q&A interface — that's Repository Q&A (Capability 3), still fully unbuilt and out of scope
- RAG, embeddings, or a vector database — deliberately rejected for this use case (see Phase 8b above); map-reduce chunking is not retrieval
- Authentication, user accounts, persistence/database beyond what already exists (Neo4j)
- A build step, bundler, or frontend framework (React, Vue, etc.) — plain HTML/CSS/JS only
- An async/background-job architecture — stays fully synchronous within `POST /analyze`, by explicit user decision, even though that means no wall-clock cap on a large repo's generation time
- Java support, temporal versioning — unrelated to this phase

Do not modify `parser/`, `graph/`, `rules/`, `check_drift.py`, `mine_history.py`, `main.py`, or `analyze_repo.py` — Phase 8/8b only added `docs_generator.py` and `grouping.py`, and made additive changes to `server.py`/`static/index.html`; none of it changed existing pipeline logic. **Exception:** `export_diagram.py`'s `build_mermaid` was extended post-Phase-8, on explicit user request, to also group modules by folder (not just the demo fixture's `layer_type`) — see SPEC.md's Phase 4 section, "Post-Phase-8 enhancement." That's the only sanctioned change to a previously-frozen file; don't take it as license to touch the others without an equally explicit instruction. `grouping.py`'s grouping logic deliberately duplicates that same precedence rather than importing it, to avoid pulling `export_diagram.py`'s neo4j dependency into a pure function — see SPEC.md's Phase 8b section for why.

See the "Implementation Scope — Phase 8" and "Phase 8b" sections of `SPEC.md` for the exact design, prompt contracts, and Definition of Done. Follow them precisely rather than expanding scope.

### Known status (for honest reporting)
- Phase 8/8b add this project's first-ever generative/LLM component (Groq, via the `openai` SDK, serving `openai/gpt-oss-120b`, map-reduce orchestrated with automatic retry on transient errors and Groq's own reported wait-time on rate limits); everything before it (Phases 1-7) was purely deterministic
- The LLM only writes descriptive prose on top of already-established deterministic facts — it never decides what counts as a violation or invents structure it wasn't given, and as of Phase 8b it isn't even asked to reproduce the violations list or dependency graph verbatim (both are pure Python templating now)
- ADR Reconstruction and Repository Q&A (the other two target capabilities) remain fully unbuilt — Phase 8's documentation generation is a separate, narrower thing, not either of those
- This web interface is still a demo tool, not a production frontend — no auth, no persistence beyond the existing graph, no polish; LLM calls have per-call hard timeouts + automatic retry, and any failure that survives retries degrades gracefully into `documentation_warnings` rather than failing the whole document
- Groq's free-tier ~8,000 TPM budget is shared account-wide and gets saturated under heavy same-day testing load — real (not just theoretical) rate-limit handling was needed and is now tuned against this account's observed limits, not a generic assumption

## Non-negotiable design rules (apply to the FULL system — several are deferred until later phases, see above)
IMPORTANT — these are the rules that make this project what it is. Do not let convenience during implementation violate them.

- **Deterministic before generative.** Directly load-bearing for Phase 8: the LLM call is only ever handed already-established facts (graph structure, rule-engine violations, health score) and bounded raw source, and is explicitly instructed not to invent structure or override violations. It never decides what counts as a violation.
- **Evidence / Inference / Confidence.** Phase 8's system prompt is a narrow, single-purpose analog of this (ground the output in the provided structural evidence, say so when uncertain) but does not yet implement the full three-part Evidence/Inference/Confidence output contract that ADR Reconstruction will need — that remains deferred.
- **One shared graph.** Unaffected — the web endpoint calls the same pipeline that already reads/writes the one shared Neo4j graph.
- **Temporal, not static.** Still deferred.
- **Rules are data.** Unaffected — the web endpoint just calls the existing rule engine, doesn't change how rules work.

## Tech stack (full target system)
- Parsing: Tree-sitter ← **done — Python, JS, TS**
- Graph DB: Neo4j + Cypher ← **done**
- Git mining: PyDriller + GitHub REST API ← **PyDriller done**
- Repo acquisition: `git clone` via subprocess ← **done**
- Agent orchestration: LangGraph + LangChain — not started
- LLMs: GPT-4o / Gemini Pro ← **Phase 8/8b — Groq (`openai/gpt-oss-120b`), via the `openai` SDK, map-reduce orchestrated across multiple narrow documentation-generation calls (with retry on transient errors); LangGraph orchestration still not started**
- Backend: FastAPI (Python) ← **done (Phase 7), extended in Phase 8**
- Structured storage: PostgreSQL — not started
- Frontend: React + TypeScript, React Flow, Mermaid ← **Phase 7/8 use plain HTML/JS + Mermaid.js/marked/DOMPurify CDN scripts, NOT React — React remains a later, separate upgrade if ever needed**, Monaco Editor — not started

## Phase 8/8b scope
- `grouping.py`: `group_modules()`, the same layer/folder/root precedence already verified for the Mermaid diagram
- `docs_generator.py`: chunks modules into batches via `grouping.group_modules`, runs a map call per batch (2 concurrent) plus one reduce call, templates the Known-Issues/Relationships sections deterministically, and assembles everything into one Markdown document — a single-group repo takes a one-call fast path instead. Every per-batch/reduce failure degrades to a deterministic fallback rather than failing the whole thing. See `SPEC.md` → "Implementation Scope — Phase 8b" for the exact design, and its "Phase 8" section for the original single-call design this replaced.
- `server.py`'s `/analyze` handler calls `generate_documentation` before cleaning up the temp clone dir; it now returns a dict (`markdown`/`warnings`/`stats`), surfaced as `documentation`/`documentation_warnings` alongside the existing `documentation_error` (which now only fires for catastrophic setup failure, e.g. a missing key)
- `static/index.html` renders the Markdown (via `marked`, sanitized with `DOMPurify`) plus a separate notice for any `documentation_warnings`
- `GROQ_API_KEY` / optional `GROQ_MODEL` in `.env`, same convention as the existing Neo4j credentials
- Exact contract and Definition of Done: see `SPEC.md` → "Implementation Scope — Phase 8" and "Phase 8b"
- After writing code, RUN it and demo it yourself end-to-end (paste a real URL, watch it work in the browser, including a negative test with a bad API key) before considering it done

## Workflow
- Plan before implementing — use plan mode. Review the plan before approving.
- Every module needs a runnable verification step before it's "done."
- Keep code simple — this phase especially should be built fast and kept minimal, since it's needed for tomorrow's demo, not for long-term architecture.
- Since this reuses existing, already-verified logic and adds only one new module, this phase should be faster than Phase 6 — resist the urge to add extra features "while you're at it" (no multi-page wiki, no chat, no RAG).

## Not yet decided — fill in as the project solidifies
- Python lint/format command:
- TypeScript/React lint/format command:
- Backend test command:
- Frontend test command:
- Repo folder structure (once scaffolded):