# RepoMind AI

RepoMind AI builds a **temporal knowledge graph** of a Git repository — its structure *and* how that structure evolved — and uses it to detect architecture drift, reconstruct the decisions behind the code, document it, and answer questions about it. Every fact comes from parsing and graph queries; the LLM only explains facts it is handed, and every AI claim carries its evidence and a confidence.

Paste a public GitHub URL and you get:

- **Architecture drift** — your architecture rules (as data) checked against the real dependency graph, a health score, violations ranked by a deterministic priority, and an AI explanation with a suggested fix for each rule group.
- **Drift over time** — health at evenly spaced points of the history, and the architecture as it was at any of those points, rebuilt from the temporal graph.
- **Architecture decisions** — decision points detected in the history (dependencies adopted or replaced, infrastructure and module groups introduced, violations introduced or resolved) and a reconstructed ADR for each, split into evidence, inference and confidence.
- **Documentation** — a grounded description of every module, generated map-reduce style.
- **Ask the repo** — a chat that answers structural, architectural, historical and "why" questions by querying the graph, the history and the ADR engine, and lists the exact queries behind every answer.

## How it works

```
GitHub URL
   │  git clone (full history)
   ▼
Tree-sitter parsing (Python, JavaScript, TypeScript) ──► Neo4j: Module / Class / Function, CONTAINS / IMPORTS / CALLS
   │                                                          │
   ├─ layers.py: folder/file patterns from rules.yaml ─────────┤
   ├─ rule engine (Cypher) ⇄ in-memory evaluator (cross-checked) ──► violations, health score
   ├─ history.py: one streamed `git log` ──────────────────────► Developer / Commit / MODIFIED
   └─ snapshots.py: N sampled commits ─────────────────────────► Snapshot / HModule / H_IMPORTS {valid_from, valid_to}
                                                              │
                     LangGraph agents (LLM explains, never decides)
   drift_graph:  load_rules → evaluate → prioritize → explain → assemble
   adr_graph:    gather → score → filter → synthesize → validate (↺ once) → finalize
   qa_graph:     route → agent ⇄ tools → synthesize → finalize
```

**Deterministic before generative.** Violations are Cypher query matches; priority is a formula (severity × callee fan-in × recency); decision points come from manifest diffs, folder appearance and renames. The LLM writes prose on top of those facts and is validated: an ADR may only cite commits from its evidence, file paths it names must appear in the evidence, and its confidence is capped by evidence quality.

**Temporal graph.** The current-state graph always describes HEAD. History lives in separate labels: snapshots at sampled commits, and module dependencies stored as `H_IMPORTS` relationships with valid-time intervals, so "the dependency graph at snapshot k" is a query. Granularity is the sampled snapshots, at module/dependency level.

**ADR relevance.** For each decision point, nearby commits are ranked by `relevance = 0.3·time + 0.45·graph + 0.25·text` — time decay in days and commits, overlap with the files and modules the decision concerns, and TF-IDF similarity over messages and tokenized file paths (no embeddings). Only commits above 0.35 become evidence.

**Health score.** `health = 100 · (1 − Σ severity·violations/judged_edges ÷ Σ severity)` over the rules that had anything to judge. A repository with no layer-tagged dependencies is reported as *not scored*, not as 100. The original per-rule formula is kept as the "legacy score".

## Quick start

Requirements: Python 3.10+, Git, a [Neo4j AuraDB](https://console.neo4j.io) Free instance, and an LLM key (Amazon Bedrock or Groq).

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env         # macOS/Linux: cp .env.example .env — then fill it in
python server.py
```

Open http://localhost:8000 and paste a repository URL, e.g. `https://github.com/nsidnev/fastapi-realworld-example-app`.

Check the LLM setup any time with:

```bash
python scripts/check_llm.py
```

### Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | AuraDB connection details (console → instance → Connect) |
| `LLM_PROVIDER` | `bedrock` or `groq`; defaults to Bedrock when `BEDROCK_API_KEY` is set |
| `LLM_PROVIDER_<PURPOSE>` | Per-feature override: `DOCS`, `QA`, `DRIFT`, `ADR` |
| `BEDROCK_API_KEY`, `BEDROCK_REGION`, `BEDROCK_MODEL` | Bedrock OpenAI-compatible endpoint (default model `openai.gpt-oss-120b-1:0`) |
| `BEDROCK_MAX_CONCURRENCY` | Parallel Bedrock calls (default 4) |
| `GROQ_API_KEYS` | Comma-separated Groq keys, one per account; calls rotate across them |
| `HISTORY_MAX_COMMITS` | Commits mined per analysis (default 1500) |
| `HISTORY_SNAPSHOTS` | History snapshots (default 12; reduced automatically for large repositories) |
| `CLONE_FILTER` | e.g. `blob:none` for very large repositories |
| `REPOMIND_CACHE_DIR` | Where generated artifacts are cached (default `.cache/`) |

If Bedrock rejects tool calling, tool-using features switch to Groq automatically and say so.

## Architecture rules

`rules.yaml` (or the **Architecture rules** editor on the page, per analysis) declares:

```yaml
layers:                    # which modules belong to which layer
  controller:
    - dir: controllers     # a folder name (innermost match wins)
    - file: "*.controller.ts"
  database:
    - dir: repositories
    - glob: "src/legacy/db_*"   # full-path pattern, wins over everything
ignore:                    # modules that get no layer (tests by default)
  - dir: tests
rules:
  - name: no-controller-imports-db
    edge: imports          # or calls (default)
    from_layer: controller
    to_layer: database
    allowed: false
    severity: 2
```

The defaults cover common layouts (controllers/routes/views, services/use cases, repositories/db/adapters, models/entities/domain, NestJS file suffixes). Models get a layer but no rules by default, since MVC and Django code uses them everywhere.

## API

| Endpoint | Purpose |
|---|---|
| `POST /analyze` `{repo_url, rules_yaml?}` | Deterministic analysis; returns `analysis_id`, stats, violations, health, diagram, history and drift curve, stage timings |
| `POST /violations/explain` `{analysis_id}` | Prioritized violation groups with AI explanations |
| `POST /adrs` `{analysis_id}` | Detected decision points and reconstructed ADRs |
| `POST /documentation` `{analysis_id}` | Generated documentation |
| `GET /history/snapshot/{idx}?analysis_id=` | The architecture at a history snapshot, from the temporal graph |
| `POST /ask` `{question, history}` | Q&A answer, routed intents, and the evidence (tool calls) behind it |
| `GET /rules/default` | The default rules YAML |

Generated artifacts are cached by repository, commit, rules, prompt version and model, so re-analyzing the same commit makes no LLM calls. Results that degraded (a section hit a rate limit) are never cached.

## Project layout

```
server.py              FastAPI app and endpoints
workspace.py           clone lifecycle, analysis ids, URL validation
parser/                Tree-sitter extractors (Python, JS, TS)
graph/                 Neo4j schema, current-state loader, history/temporal loader
layers.py              layer assignment from rules
rules/                 rules config validation, Cypher engine, in-memory evaluator, scoring
history.py             git history mining
snapshots.py           sampled snapshots, diffs, valid-time intervals
adr/                   decision-point detection, relevance scoring
agents/                LangGraph agents: drift, ADR, Q&A
qa_engine.py           Q&A tools (read-only graph queries, source access)
docs_generator.py      map-reduce documentation
llm.py                 Bedrock/Groq client, retries, key rotation, usage accounting
cache.py               artifact cache
static/index.html      the web UI (plain HTML/JS)
eval/                  evaluation scripts and results
tests/                 pytest suite
```

## Tests

```bash
python -m pytest
```

Tests that need Neo4j are skipped when it isn't reachable. They load fixtures into the graph, which replaces whatever analysis it held — run them when you aren't demoing. LLM-dependent code is tested with fake models; `scripts/check_llm.py` checks the real providers.

## Evaluation

Scripts in `eval/` write reports to `eval/results/`:

| Script | Measures |
|---|---|
| `eval_drift.py` | Precision/recall/F1 of violation detection on generated layered projects (Python, CommonJS, TypeScript) with injected violations and decoys, and on real repositories with injected violations |
| `eval_adr.py` | Decision-point recall against repositories that keep real ADRs (masked from the tool); `--synthesize` adds reconstructions and a human scoring sheet |
| `eval_qa.py` | Intent-routing accuracy, and live answer correctness and citation validity against graph/git ground truth |
| `eval_efficiency.py` | Time per stage, LLM calls and tokens cold vs. warm cache |

Latest results:

- **Drift detection:** precision, recall and F1 of 1.0 on 150 injected violations across 15 generated projects (with 150 decoys), and on 27 violations injected into 3 real repositories. Calls written as `module.function()` aren't resolved — the imports rule still reports those dependencies (measured: imports-rule recall 1.0, calls-rule recall 0.0 for that form).
- **ADR decision points:** 46% strict / 82% temporal recall over 28 real ADRs in 3 repositories; misses are mostly decisions with no trace in code (naming conventions, Git workflow, code style). See the report for which matches land on squashed commits.
- **Efficiency:** deterministic analysis of a 50–100 file repository in 12–14 s; warm-cache repeats make zero LLM calls.
- **Q&A routing:** 100% on a 38-question development set.

## Limits

- Python, JavaScript and TypeScript only. TS/JS path aliases (`@/x`) and git submodules aren't resolved.
- Function calls are resolved for direct names, named imports and destructured `require`; calls through `module.function()` attribute access or default imports aren't.
- The temporal graph is sampled (12 snapshots by default), at module and dependency level; functions and calls exist at HEAD only.
- Reconstructed ADRs are inferences from history, labelled as such, with a capped confidence — not recovered developer intent.
- One analysis at a time; the graph holds one repository.

## Before a demo

1. Open console.neo4j.io and make sure the instance is **Running** (free instances pause after a few idle days).
2. Run `python scripts/check_llm.py` to confirm the LLM keys work.
3. Analyze your demo repositories once beforehand: their documentation, explanations and ADRs are then served from the cache instantly.
