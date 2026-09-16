# RepoMind AI — Technical Documentation

This document walks through every phase of RepoMind AI as it was actually
built: what each phase implements, the files involved, and — more
importantly — the *intuition* behind why it was built that way. For the
original planning spec and Definition-of-Done checklists, see `SPEC.md`.
For current-phase working rules, see `CLAUDE.md`.

## The core idea, in one paragraph

Most AI coding tools read a file, maybe a function, and answer a question
about it. RepoMind AI instead builds a **structural model of the entire
repository first** — as a graph, not as text — and only *afterwards* lets
anything generative (an LLM) look at that model to explain it. Architecture
violations, dependency counts, and health scores are never "asked" of a
language model; they're computed by querying a graph, the same way a
database query is a fact, not an opinion. The LLM's only job, wherever it
appears, is to turn already-established facts into readable prose. This
one design decision — **deterministic before generative** — shapes every
phase below.

---

## Phase 1 — Knowledge Graph (Tree-sitter → Neo4j)

**What it does:** Parses a Python repository with Tree-sitter and writes
the result into Neo4j as a graph: `Module`, `Class`, and `Function` nodes,
connected by `CONTAINS` (module contains class/function, class contains
method), `CALLS` (function calls function), and `IMPORTS` (module imports
module) edges.

**Implementation:**
- `parser/ast_extractor.py` walks each file's Tree-sitter AST and extracts
  structural facts — not the source text itself, just *what exists*:
  function names and signatures, class names, which functions call which,
  which modules import which.
- `graph/schema.py` defines the node/relationship shape as constants, so
  the graph's structure lives in one place.
- `graph/loader.py` owns the Neo4j connection and the Cypher `MERGE`
  statements that write the extracted facts in — `MERGE` rather than
  `CREATE` so re-running the tool on the same repo doesn't duplicate nodes
  (verified idempotent: identical counts on a second run).
- `main.py` is the CLI entry point: `python main.py <repo_path>`.

**The intuition:** A codebase is fundamentally a *graph* — files depend on
files, classes contain methods, functions call each other — but most
tooling treats it as a pile of text files. Once you have it as an actual
graph in a real graph database, you can *ask* it questions with a query
language (Cypher) instead of re-parsing text every time: "what does this
module depend on?" becomes one `MATCH` clause, not a search. This graph is
also the **one shared foundation** every later phase builds on — drift
detection, diagrams, and documentation all read from this same graph
rather than each maintaining its own private understanding of the repo.

---

## Phase 2 — Architecture Drift Detection

**What it does:** Declares an intended architecture (e.g., a layered
Controller → Service → Database pattern) as data, checks the graph for
violations of it, and computes a 0–100 "Architecture Health" score.

**Implementation:**
- Module nodes carry an optional `layer_type` property
  (`controller`/`service`/`database`), currently assigned by filename
  convention in the demo fixture.
- `rules.yaml` declares each rule declaratively:
  ```yaml
  - name: no-controller-to-db
    from_layer: controller
    to_layer: database
    allowed: false
    severity: 3
  ```
- `rules/rule_engine.py` loads that YAML and compiles each `allowed: false`
  rule into a Cypher query (e.g., "find any Controller-layer function that
  calls a Database-layer function"). A match is a violation — a fact
  produced by a database query, not a guess.
- `rules/scoring.py` implements:
  ```
  ArchitectureHealth = 100 − 100 × (WeightedViolations / TotalApplicableRules)
  ```
  clamped to `[0, 100]` with `max(0, min(100, score))`.
- `check_drift.py` is the CLI entry point.

**The intuition:** Architecture drift is usually described qualitatively
("this codebase has gotten messy") with no way to measure it or track it
over time. Turning the *intended* architecture into declarative rule data,
and violations into deterministic graph queries, makes drift a **number**
you can compute, compare across commits, and trust — because a rule
violation found this way is a verifiable fact, never an LLM's opinion
about whether something "looks wrong." Rules living in a YAML file (not
hardcoded logic) also means adding a new architectural constraint is a
data change, not a code change.

**Bug found:** the raw formula can go negative or exceed 100 on a small
rule set (a single severity-3 violation against very few applicable rules
produced −200). Fixed by clamping the final score — a reminder that even a
purely deterministic formula needs its edge cases checked against real
numbers, not just the common case.

---

## Phase 3 — Git History Mining

**What it does:** Walks a repository's real commit history and extracts,
per commit: hash, message, author, timestamp, and files changed.

**Implementation:**
- `mine_history.py` uses PyDriller to walk commits and print this data.
- Rather than manufacturing a synthetic commit history for the small
  `test_repo` fixture, PyDriller was pointed at the outer RepoMindAI repo
  itself, which already has real, meaningful history — a simpler way to
  get genuine data to extract than building fake history just to have
  something to mine.

**The intuition:** A repository's *current* structure only tells you where
it ended up, not how it got there or why. Git history is the raw material
for reconstructing *decisions* (a later, still-unbuilt capability: ADR
Reconstruction) — you can't correlate "why was this dependency
introduced?" with anything if you never captured the commit-level evidence
in the first place. Phase 3 deliberately stayed narrow (extraction only,
no correlation or synthesis logic yet) — get the raw evidence pipeline
working and verified before building reasoning on top of it.

---

## Phase 4 — Mermaid Diagram Export

**What it does:** Queries the graph for modules and `IMPORTS` edges and
generates a Mermaid flowchart — a visual dependency diagram — grouping
related modules into boxes.

**Implementation:**
- `export_diagram.py`'s `build_mermaid()` queries all `Module` nodes and
  `IMPORTS` relationships, then formats them as Mermaid `flowchart TD`
  syntax, writing to `diagram_output.md` and printing to console.
- Grouping precedence (in `build_mermaid`): a module with a `layer_type`
  goes into a layer-styled subgraph first; a module with no `layer_type`
  but a containing folder goes into a subgraph labeled by that folder
  (single-level — `src/core` is one flat box, not nested under `src`);
  anything left over stays a plain top-level node.
- `_LAYER_COLORS` styles layer-tagged nodes with distinct fills so the
  layered architecture is visually obvious at a glance.

**The intuition:** A list of violations is precise but not *legible* —
seeing the actual shape of the dependency graph makes drift visceral in a
way numbers alone don't ("oh, that controller box has an arrow straight
into the database box"). The folder-grouping tier was added after
recognizing that `layer_type` is a convention specific to this project's
own demo fixture (filename-based tagging); a real repo using an MVC-style
*directory* layout (`models/`, `views/`, `controllers/`) has meaningful
grouping information too — it's just expressed as folder structure instead
of a naming convention. Reusing the same box-per-group idea for folders,
with `layer_type` taking precedence where it exists, means the diagram
stays useful on repos this project never specifically designed for.

---

## Phase 5 — URL-to-Live-Analysis, Hardened Against Real Repos

**What it does:** Accepts a GitHub URL, clones it, and feeds the clone
into the existing parsing/graph-loading pipeline — turning "here's a repo
on GitHub" into a fully loaded graph with zero manual steps.

**Implementation:**
- `analyze_repo.py`: `git clone` via `subprocess`, prints live progress
  ("Cloning...", "Parsing...", "Loaded into Neo4j", "Done"), then calls a
  shared `run_pipeline()` function refactored out of `main.py` so both the
  local-path and URL entry points run identical logic — no duplicated
  parsing code between them.
- Cleanup: `shutil.rmtree` with a custom `onerror` handler that clears
  Windows' read-only bit on `.git`-internal files before retrying the
  delete (plain `ignore_errors=True` silently left `.git` behind).
- Hardening pass (5b): tested against 5 real public repos one at a time,
  fixing genuine parser bugs as they surfaced, re-confirming the original
  `test_repo` fixture's exact output after every fix (regression check).

**Bugs found and fixed (in `parser/ast_extractor.py`):**
1. Decorated functions/classes (`@app.route(...)`) were wrapped in a
   `decorated_definition` AST node the extractor didn't unwrap — silently
   skipped entirely. Fixed by unwrapping via
   `child_by_field_name("definition")`.
2. Relative imports (`from ..a import a`) were never resolved to an
   absolute module path. Fixed with `_resolve_relative_module`, using the
   same level-counting rule Python's own import machinery uses.
3. `from X import *` wildcard imports produced zero entries. Fixed by
   handling `wildcard_import` nodes explicitly (correctly excluded from
   `CALLS` resolution, since there's no fixed symbol name to track for a
   star import).

**The intuition:** A parser that only works on one carefully-controlled
fixture proves nothing about real-world robustness. The entire point of
Phase 5b was to go looking for what breaks on code this project didn't
write — decorators, relative imports, wildcard imports are all extremely
common real-world Python that a narrow fixture simply never exercises. The
rule followed throughout: fix the actual root cause in the shared
extractor, never special-case around a symptom, and always re-verify the
original fixture still produces byte-identical output — a fix for repo #4
must never quietly break what repo #1 already proved worked.

---

## Phase 6 — JavaScript & TypeScript Support

**What it does:** Extends parsing beyond Python so the *same* downstream
pipeline (graph, rules, diagrams) works unmodified on JS/TS repos.

**Implementation:**
- `parser/ast_extractor.py`'s `parse_repo()` became a thin dispatcher: it
  routes each file by extension to the Python extractor (existing,
  untouched) or to two new modules, `parser/js_extractor.py` and
  `parser/ts_extractor.py`, using `tree-sitter-javascript` and
  `tree-sitter-typescript` respectively.
- The critical constraint: **all three extractors must produce the exact
  same output shape** — `{modules, classes, functions, calls, imports}` —
  because `graph/loader.py`, `rules/rule_engine.py`, `check_drift.py`, and
  `export_diagram.py` only ever operate on that shape. None of them know
  or care what language produced it.
- JS-specific mapping: `function_declaration`/`arrow_function` → Function,
  `class_declaration` → Class, `import_statement` and CommonJS
  `require(...)` → Imports, call expressions → Calls.
- TS extractor reuses JS logic where the grammars overlap (TS is largely
  JS-compatible for functions/classes/calls) and adds TS-specific handling
  only where a real test repo actually needed it.

**Bug found:** destructured `require` (`const { a, b } = require('./mod')`)
wasn't recognized as an import — only bare `require(...)` statements were.
Fixed by adding `_extract_declared_requires`.

**Cross-language proof:** loaded a TypeScript repo's graph, then ran
`check_drift.py` and `export_diagram.py` **completely unmodified** against
it and got correct output — direct proof that the downstream pipeline is
genuinely language-agnostic, not just that the new parsers happen to work
in isolation.

**The intuition:** The graph schema (Module/Class/Function nodes,
CONTAINS/CALLS/IMPORTS edges) was deliberately designed in Phase 1 to be a
language-neutral shape, not a Python-specific one. Phase 6 is the payoff
of that design choice: adding a second and third language required *zero*
changes to four already-verified files, because "what a function is" was
never coupled to "how Python's grammar expresses a function." This is the
same reasoning as the deterministic-before-generative principle applied
one level down — get the *shape* of the data right once, and everything
built on top of that shape stays stable as the inputs change.

---

## Phase 7 — Web Interface

**What it does:** Wraps the entire CLI pipeline behind one HTTP endpoint
and a single HTML page, so a panel member can paste a URL into a browser
instead of running commands.

**Implementation:**
- `server.py`: a FastAPI app with one route, `POST /analyze`, that calls
  `analyze_repo`'s pipeline, `rules/rule_engine.py` + `scoring.py`, and
  `export_diagram.py` — the exact same functions the CLI tools already
  call — and returns their results as one JSON payload.
- `static/index.html`: a single page (no build step, no framework) with a
  URL input, a loading indicator, and four render sections: parse summary,
  violations + health score, the Mermaid diagram, and (from Phase 8
  onward) AI-generated documentation.
- Later restyled neo-brutalist / dark / grayscale-only on request: thick
  borders, hard offset drop shadows (no blur), sharp corners, Space
  Grotesk headers over JetBrains Mono body text — purely visual, no
  structural or logic changes, verified against every result section in a
  live browser.

**The intuition:** Every actual unit of work in this phase already existed
and was already verified by Phases 1–6 — Phase 7 adds *zero* new analysis
logic. The only new problem it solves is presentation: making an
already-correct pipeline demoable to someone who isn't going to open a
terminal. Keeping it framework-free was deliberate too — a build step adds
failure surface for a one-page demo tool with no long-term frontend
ambitions at this stage.

---

## Phase 8 / 8b — AI-Generated Documentation (the generative layer)

This is the project's **first and only generative component** — everything
above is pure graph queries and rule evaluation. It's also the phase that
went through the most iteration, so it's split into what it does now, and
the path taken to get there.

### What it does today

Generates one comprehensive Markdown documentation page for the analyzed
repo — Overview, Architecture & Layers, Module-by-Module Breakdown, Key
Relationships & Dependencies, Known Architecture Issues — rendered as a
new section of the same Phase 7 page.

### Why a single LLM call didn't work

The first implementation built one structural summary of the *entire*
repo (every module/class/function/import/call edge) plus raw source for a
handful of "important" files, and sent it all in one prompt. For any repo
larger than the demo fixture, this broke down two ways: most files never
got real source coverage at all (only ~8 files were selected), and for a
large enough repo even the *structural summary* itself had to be
truncated to fit — meaning some modules never appeared in the prompt in
any form. The actual, confirmed failure: a 19-file repo needed ~20,300
tokens against an 8,000-token-per-minute budget, in a single request.

### Why not RAG (retrieval-augmented generation)

This was explicitly evaluated and rejected. RAG's whole premise is
narrowing scope: given a query, retrieve the most *relevant* chunks and
answer from those. But "write comprehensive documentation for the whole
repo" isn't a query that RAG's relevance-ranking can meaningfully narrow —
there's no principled way to decide which files are "less relevant" to
"describe everything," and any embedding-similarity ranking would
silently drop coverage of whatever it ranked low. The actual goal
("cover every file") is the opposite of what retrieval is for.

### The fix: map-reduce

- **Grouping (`grouping.py`, new):** `group_modules()` groups modules by
  `layer_type` first, then by containing folder, then a flat `root`
  bucket — deliberately reusing the exact same grouping precedence
  already verified for the Mermaid diagram, because it's already a proven
  way to carve a repo into meaningful, human-recognizable chunks.
- **Batching:** each group is split into batches of at most 10 modules
  (`MAP_MAX_MODULES_PER_BATCH`).
- **Map phase:** one LLM call per batch, describing only that batch's
  modules. Because a batch is capped at 10 modules, *every* module in it
  can get a real source excerpt — this is the actual fix for the
  completeness bug: no file loses source coverage to a repo-wide priority
  ranking, because there is no repo-wide ranking anymore, only small,
  fully-covered batches.
- **Reduce phase:** one final call synthesizes the connective Overview and
  Architecture narrative from the (much smaller) per-batch results — it
  never sees raw source at all, only already-condensed summaries.
- **Deterministic sections:** Known Architecture Issues and Key
  Relationships & Dependencies are pure Python templating now, not LLM
  output at all — both are exhaustive structured data (the violations
  list, the import/call edges) that's already 100% known, so asking a
  model to reproduce it verbatim only risks paraphrase or omission for a
  section that most needs to be authoritative.
- **Fast path:** a repo whose modules all land in a single group (rare)
  skips map-reduce and makes one call, at the same cost as the old design.
- **Graceful degradation:** `generate_documentation()` now only raises for
  catastrophic setup failure (a missing API key). A failed batch degrades
  to a deterministic structural listing; a failed reduce degrades to a
  templated overview; both surface honestly via a `documentation_warnings`
  list rather than silently vanishing or failing the whole document.
- **No wall-clock cap, by explicit design decision:** the system stays
  fully synchronous inside one `POST /analyze` request, and a large repo
  is allowed to take however long it genuinely takes rather than
  returning early/partial results on a timer. A *count*-based ceiling
  (`MAX_TOTAL_MAP_CALLS`) still exists — that's a cost/rate-limit
  safeguard against a pathological repo burning the account's shared
  daily quota, not a time limit.

### The provider journey (and why it matters)

1. **Gemini** (`google-genai` SDK) — worked, but returned persistent
   `503 UNAVAILABLE` under real load: a capacity issue on Google's side,
   not fixable in this codebase.
2. **OpenRouter's free NVIDIA Nemotron** — OpenAI-compatible, generous
   context window, rate limits that looked sufficient on paper — but never
   completed a single request across three separate tries (45s, then
   90s+, then a full 150s), too congested to be demo-reliable.
3. **Groq**, `openai/gpt-oss-120b` — the model name initially assumed from
   general documentation (`llama-3.3-70b-versatile`) 404'd for this
   specific account; querying `client.models.list()` directly surfaced
   what was actually available. Result: 8.4 seconds end-to-end for the
   full pipeline including documentation, with noticeably higher output
   quality (correctly cited real docstrings, used Markdown tables).

**Intuition:** none of docs_generator.py's prompt-building or
structural-summary logic changed across any of these three switches —
only the client construction and the API call itself. That's the payoff
of keeping the LLM call as a thin, swappable edge of the system rather
than threading provider-specific logic through the whole module.

### Two subtle bugs worth understanding

1. **The timeout that didn't time out.** The original implementation used
   `with ThreadPoolExecutor(...) as pool:`. `__exit__` calls
   `shutdown(wait=True)`, which blocks until the background thread
   actually finishes — even after `.result(timeout=...)` already gave up
   waiting on it. A 45-second deadline was therefore not really a
   deadline: exiting the `with` block re-blocked on the same slow call,
   producing 90+ second hangs. Fixed by managing the executor manually
   (`pool.shutdown(wait=False)` in a `finally` block) so an abandoned slow
   call can keep running in the background without blocking the response.
   This is a general Python gotcha, not specific to LLM calls — it recurred
   in a second code path during later testing and was fixed the same way.

2. **The error that showed nothing.** `concurrent.futures.TimeoutError`'s
   `str()` is `""` — empty. The server passed that empty string through as
   `documentation_error`, and the frontend's `if (data.documentation_error)`
   check treated an empty string as falsy — so a genuine timeout produced
   a completely blank section with no error and no content, the worst
   possible failure mode (silent, not just ungraceful). Fixed on three
   layers at once: an explicit non-empty message where the timeout is
   raised, a `str(exc) or type(exc).__name__` fallback on the server, and
   an `!= null` check (not truthiness) on the frontend — belt-and-suspenders
   because any one layer alone would have masked the bug again the next
   time a different exception happened to stringify oddly.

### Real-world rate-limit tuning

Groq's free tier is an account-wide shared budget (~8,000 tokens/minute,
observed empirically). Two rounds of tuning were needed against real,
not simulated, load:

- **Cooldown accuracy:** a fixed 15-second cooldown after a `429` was a
  guess, not the real reset window — retries kept firing into a budget
  that hadn't actually recovered yet. Fixed by parsing Groq's own error
  text (`"please try again in 6.07s"`) via regex and using that exact
  value (+1s margin) as the cooldown, shared across concurrent workers via
  a locked timestamp.
- **Concurrency vs. collisions:** running 2 batches concurrently meant two
  individually-fine-sized calls could still exceed the shared budget
  together. Reduced concurrency to 1 (fully serialized map calls) and
  raised the retry count from 2 to 3 for additional resilience — verified
  under genuine repeated 429s from real account load that every batch
  still eventually succeeded, with zero mid-sentence truncation across a
  full manual read of the output.

**Intuition throughout Phase 8/8b:** every fix here follows from taking
the account's *actual*, measured limits seriously rather than trusting a
provider's documented numbers or a guessed constant — the same
evidence-over-assumption instinct that drives the rest of the project's
design, just applied to infrastructure instead of architecture.

---

## The thread connecting all eight phases

Each phase either **establishes a fact deterministically** (parsing,
graph, rules, git history) or **presents an already-established fact**
(diagrams, the web UI) or, in exactly one case, **explains established
facts in prose** (documentation) — and even that one generative phase is
explicitly forbidden from inventing structure it wasn't handed. Nothing in
this system ever asks a language model "is this a violation?" or "does
this dependency exist?" — those are always graph queries. That boundary is
what keeps the system's claims checkable: every number and every
relationship mentioned anywhere in the UI traces back to a Cypher query
against real parsed code, not to something a model decided sounded right.
