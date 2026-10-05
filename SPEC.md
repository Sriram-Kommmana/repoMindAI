# RepoMind AI — Project Specification

## 1. Aim of the Project

RepoMind AI aims to build an agentic platform that automatically
understands a software repository's architecture — both its current
structure and how it evolved — and uses that understanding to detect
architectural decay, reconstruct the reasoning behind past technical
decisions, and answer natural-language questions about the codebase,
grounding every AI-generated claim in verifiable evidence rather than
free-form generation.

In one sentence: give any codebase the kind of deep, historical,
architectural understanding that only a senior engineer who'd been
there since day one would normally have — and let anyone query that
understanding directly.

## 2. The Problem

Software systems evolve continuously across years and many
contributors. Three specific things degrade silently over that time:

1. **Architecture Drift** — the codebase gradually diverges from its
   intended design (a Controller starts calling the Database
   directly, bypassing the Service layer) as small, deadline-driven
   changes accumulate unnoticed.
2. **Lost Decision Rationale** — major technical decisions (why a
   dependency like Kafka was introduced, why a service was split)
   are rarely documented as formal Architecture Decision Records;
   the reasoning lives in people's heads and leaves when they do.
3. **No queryable understanding of the system** — a new engineer
   can't simply ask "what does this module do and what depends on
   it" and get a grounded, structurally-aware answer; they have to
   manually explore.

Existing AI coding tools (Copilot, Cursor, Cody) operate at the
level of a single file or function. None maintain a persistent,
structural model of the whole system, none reason over its
historical evolution, and none ground their answers in a verifiable
graph of the codebase.

## 3. Novelty

- **Temporal repository intelligence** — jointly reasoning over code
  structure *and* repository evolution, not a static snapshot.
- **Deterministic-before-generative design** — architectural facts
  (violations) are established via graph queries; AI is used only
  for explanation, prioritization, and evidence synthesis — never
  for deciding what counts as a violation.
- **Evidence/Inference/Confidence output contract** — every AI claim
  is explicitly separated into what was found (evidence), what's
  inferred (reasoning), and how confident the system is — never
  presented as unqualified fact.
- **Drift as a trend, not a report** — the health score is computed
  at multiple points across history, producing a curve that shows
  *when* architecture degraded, not just its current state.
- **One shared temporal knowledge graph** powering all three
  capabilities (drift, ADR reconstruction, and Q&A), rather than
  separate, disconnected pipelines per feature.
- **Evidence-grounded conversational Q&A** — unlike repo chatbots
  that answer from raw code text, questions are answered by
  querying the same structural/historical graph, so answers are
  traceable, not guessed.
- **Quantitative evaluation methodology** (Precision/Recall/F1,
  human-judged ADR accuracy) — not just a live demo.

## 4. Full System Pipeline (Target Architecture)

```
Git Repository
      ↓
Repository Ingestion (clone, detect languages, scope incremental diff)
      ↓
Tree-sitter Parsing → AST per file
      ↓
Static Analysis → classes, functions, imports, API routes extracted
      ↓
Temporal Knowledge Graph (Neo4j) ← Git History Mining (PyDriller + GitHub API)
      ↓                                          ↓
Architecture Analysis Engine          Historical Intelligence Engine
(deterministic rule checks →          (evidence gathering → relevance
violations → drift scoring)           scoring → correlation)
      ↓                                          ↓
              AI Reasoning Layer (LangGraph)
   (explains + prioritizes violations)   (synthesizes evidence-backed ADRs)
                        ↓
              Repository Q&A Layer
   (routes questions → graph queries / drift engine / ADR engine → answer)
                        ↓
              Evidence-Backed Reports & Answers
                        ↓
              FastAPI Backend → React Dashboard (reports + chat panel)
```

> **Note:** This is the full target architecture. See "Implementation
> Scope" sections below for what is actually being built, phase by phase.

## 5. The Knowledge Graph — the shared foundation (Target)

A **temporal** graph in Neo4j: nodes are `Module`, `Class`,
`Function`, `APIEndpoint`, `Commit`, `Developer`, `PullRequest`,
`ArchitectureRule`; relationships include `CONTAINS`, `CALLS`,
`IMPORTS`, `DEPENDS_ON`, `MODIFIED`, `AUTHORED`, `VIOLATES`.
Relationships are stored as **versioned instances** with
`valid_from_commit`/`valid_to_commit` intervals — not mutable edges
— so the graph can answer "what did this look like at any past
commit," not just "what does it look like now." All three
capabilities (Drift Detection, ADR Reconstruction, Q&A) read from
this one graph, so no capability ever reasons from a disconnected
model of the codebase.

> **Phased note:** temporal versioning is deferred — see
> Implementation Scope sections below for the phased schema.

## 6. Flagship Module 1 — Architecture Drift Detection (Target)

**How it works:** the team declares the intended architecture
pattern (e.g., Layered) and its rules as data — not inferred by an
LLM. Each rule compiles into a deterministic Cypher query (e.g.,
"find any Controller with a direct edge to a Database"). Violations
found this way are facts, not AI guesses. An LLM stage then explains
and prioritizes those violations in plain language.

**The formula:**
```
ArchitectureHealth(t) = 100 − 100 × (WeightedViolations(t) / TotalApplicableRules(t))
```
`WeightedViolations(t)` = Σ(violation count × severity weight) at
commit *t*; `TotalApplicableRules(t)` = count of rule-checks
actually evaluable at that commit. Computed across multiple commits,
this produces a **drift curve** over the repo's history. Score is
clamped to [0, 100].

**Framing to state explicitly:** this is a project-relative
indicator for tracking one repository's health across its own
history — not an absolute cross-project benchmark.

## 7. Flagship Module 2 — ADR Reconstruction (Target)

**How it works:** for a decision point (e.g., the commit where Kafka
first appears), the system gathers nearby commits/diffs/PR text,
scores each on relevance, filters out noise, and has an LLM
synthesize a structured ADR from only the high-relevance evidence.

**The formula:**
```
relevance(commit) = α·time_proximity + β·graph_proximity + γ·text_similarity
```
Three independent signals — time closeness, graph closeness, text
similarity — combined with tunable weights; only commits above
threshold reach the Synthesis Agent.

**Output contract:**
```
Evidence:    <cited commits/diffs>
Inference:   <AI's reasoning>
Confidence:  <score>
```
Never presented as a factual reconstruction of developer intent —
always evidence-backed inference with a stated confidence.

## 8. Capability 3 — Repository Q&A (Tier 2, Target)

**How it works:** a user asks a natural-language question about the
repository. A Query Understanding Agent classifies the intent and
routes it:
- **Structural** ("what depends on module X?") → direct Cypher
  query on the graph.
- **Historical** ("who last changed this, and when?") → query on
  the Commit/PR store.
- **Architectural** ("does this module violate any rules?") →
  invokes the existing Drift Detection engine.
- **Rationale** ("why was Kafka introduced?") → invokes the existing
  ADR Reconstruction engine.

An Answer Synthesis Agent then converts the structured result into a
natural-language, evidence-cited answer.

**Why this isn't "just another repo chatbot":** it doesn't reason
from raw code text — every answer is grounded in the same temporal
knowledge graph and evidence-correlation logic already built for
Drift Detection and ADR Reconstruction, so answers are traceable
back to specific graph nodes, commits, or files.

## 9. Multi-Agent Design (Target)

All three capabilities run through LangGraph state machines, not one
prompt doing everything:

- **Drift:** Rule check (deterministic) → Violation Detection
  (deterministic) → Explanation & Prioritization (LLM).
- **ADR:** Evidence Gathering → Correlation/Filtering → Synthesis
  (LLM).
- **Q&A:** Query Understanding (routing) → [Graph Query / Drift
  Engine / ADR Engine] → Answer Synthesis (LLM).

Each stage's output is a required, typed input to the next — this
interdependency, not an arbitrary agent count, is what makes the
system genuinely multi-agent rather than one agent with tools.

## 10. Full Technology Stack (Target)

| Layer | Technology |
|---|---|
| Parsing | Tree-sitter |
| Graph DB | Neo4j + Cypher |
| Graph analytics | NetworkX |
| Git mining | PyDriller + GitHub REST API |
| Agent orchestration | LangGraph + LangChain |
| LLMs | GPT-4o / Gemini Pro |
| Backend | FastAPI (Python) |
| Structured storage | PostgreSQL (commits, PRs, reports) |
| Frontend | React + TypeScript |
| Graph visualization | React Flow |
| Diagrams | Mermaid |
| Code viewer | Monaco Editor |
| Chat interface | React chat panel, calling the Q&A API endpoint |

*(Redis was considered but dropped from the core design unless a
demonstrated caching/concurrency need arises.)*

## 11. Five Major Modules (Target System Design)

1. **Ingestion & Parsing** — Tree-sitter, static analysis. **[Phase 1 — DONE]**
2. **Software Knowledge Graph** — Neo4j, temporal versioning. **[Phase 1 — DONE, current-state only]**
3. **Architecture Analysis Engine** — deterministic rules,
   violations, drift scoring. *(Priority)* **[Phase 2 — DONE]**
4. **Historical Intelligence Engine** — Git/PR mining, evidence
   correlation, ADR synthesis. *(Priority)* **[Phase 3 — DONE (Git mining slice); evidence correlation and ADR synthesis not started]**
5. **AI Reasoning & Delivery** — LangGraph orchestration (drift,
   ADR, and Q&A agents), API, dashboard with chat panel. **[Diagram export (Phase 4) in progress; everything else not started]**

## 12. Evaluation Methodology (Target)

| Capability | Test | Metrics |
|---|---|---|
| Drift Detection | Real repos (e.g., Spring PetClinic) with known refactors + hand-authored rules | Precision, Recall, F1 |
| ADR Reconstruction | Repos with real ADRs (e.g., `adr/madr`) — reconstruct and compare | Human-judged accuracy, completeness, hallucination rate |
| Repository Q&A | Sample question set per repo; check whether answers are correct and properly cited | Answer accuracy, citation correctness |
| System efficiency | Full vs. incremental analysis time, LLM call count | Wall-clock time, calls saved via caching |

## 13. Final Deliverables (Target)

- A working pipeline that ingests any Git repository and builds a
  temporal knowledge graph of its structure and history.
- A **Drift Detection report**: violation list + Architecture Health
  Score, computed across multiple points in history.
- An **ADR Reconstruction capability**: auto-generated, evidence-
  cited ADR documents for undocumented architectural decisions, each
  with an Evidence/Inference/Confidence breakdown.
- A **Repository Q&A interface**: a chat panel where users ask
  natural-language questions about the codebase and get evidence-
  grounded answers, powered by the same graph and engines.
- A **dashboard** (React) visualizing the dependency graph, drift
  trend, violations, generated ADRs, and the chat panel.
- An **evaluation report** — quantitative results against real
  repositories, not just a qualitative demo.
- A documented, extensible architecture-rule system (rules as data)
  so new patterns can be added without touching core logic.

---

## Implementation Scope — Phase 1 (Module 1 + Module 2) — COMPLETE

**Status: DONE and verified.** Kept here for reference — do not modify
this code except as explicitly directed by a later phase's scope.

### Scope simplification for Phase 1
- Language support: Python only (expand later)
- Temporal versioning: SKIPPED — current-state edges only, no
  valid_from/valid_to yet
- Git history mining: SKIPPED — became Phase 3, see below

### Node properties (Phase 1)
- `Module`: `{ path: str, language: str }`
- `Class`: `{ name: str, module_path: str }`
- `Function`: `{ name: str, signature: str, module_path: str, class_name: str | null }`

### Relationship types (Phase 1)
- `(Module)-[:CONTAINS]->(Class)`
- `(Module)-[:CONTAINS]->(Function)`
- `(Class)-[:CONTAINS]->(Function)`
- `(Function)-[:CALLS]->(Function)`
- `(Module)-[:IMPORTS]->(Module)`

### Folder structure (Phase 1)
```
repomind/
  parser/
    ast_extractor.py      # Tree-sitter parsing logic
  graph/
    schema.py              # Node/relationship constants
    loader.py               # Neo4j connection + write logic
  main.py                    # CLI entry: python main.py <repo_path>
  test_repo/                  # small sample repo for testing
  .env                          # NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
  requirements.txt
```

### Definition of Done (Phase 1) — VERIFIED
Running `python main.py ./test_repo`:
1. Parsed all `.py` files in `test_repo` ✓
2. Printed summary: "Parsed 3 files, found 2 classes, 10 functions" ✓
3. Loaded all nodes/relationships into Neo4j ✓
4. `MATCH (n) RETURN count(n)` returned 15, matching the printed
   summary (3 Module + 2 Class + 10 Function) ✓
5. 21 relationships verified: 7 CALLS, 2 IMPORTS, 12 CONTAINS ✓
6. Re-run confirmed idempotent (identical counts, no duplication) ✓

---

## Implementation Scope — Phase 2 (Module 3: Architecture Analysis Engine) — COMPLETE

**Status: DONE and verified.** Kept here for reference — do not modify
this code except as explicitly directed by a later phase's scope.

### Fixture extension (Phase 2)
Added `controller.py`, `service.py`, `database.py` to `test_repo/`:
- `handle_request` → `process_order` (controller→service, allowed)
- `process_order` → `save_record` (service→database, allowed)
- `handle_request_direct` → `save_record` (controller→database,
  deliberate violation)

### Layer assignment
Module nodes carry an optional `layer_type` property
(`controller` / `service` / `database` / `null` for untagged files).
Verified directly via `MATCH (m:Module) RETURN m.path, m.layer_type`
in Neo4j Browser — all 6 modules correctly tagged.

### Rule format (rules.yaml)
```yaml
pattern: layered
rules:
  - name: no-controller-to-db
    from_layer: controller
    to_layer: database
    allowed: false
    severity: 3
  - name: controller-to-service-allowed
    from_layer: controller
    to_layer: service
    allowed: true
    severity: 0
  - name: service-to-db-allowed
    from_layer: service
    to_layer: database
    allowed: true
    severity: 0
```

### Folder structure (Phase 2)
```
rules/
  rule_engine.py       # loads rules.yaml, compiles to Cypher, runs checks
  scoring.py             # ArchitectureHealth formula (clamped to [0,100])
check_drift.py            # CLI entry point for Phase 2
rules.yaml
```

### Definition of Done (Phase 2) — VERIFIED
Running `python check_drift.py`:
1. Loaded `rules.yaml` ✓
2. Checked all `allowed: false` rules via Cypher against the graph ✓
3. Found exactly 1 violation: `controller.py::handle_request_direct
   -> database.py::save_record` (severity 3) ✓
4. The two legitimate layered calls correctly produced NO false
   positives ✓
5. ArchitectureHealth computed and clamped to [0, 100] — printed as
   0 (was -200 before the clamping fix) ✓

**Bug caught and fixed during implementation:** the raw formula
`100 - 100*(weighted_violations/total_applicable_rules)` can go
negative or exceed 100 on small rule sets (e.g., -200 with 1 rule of
severity 3). Fixed by clamping: `max(0, min(100, score))`.

---

## Implementation Scope — Phase 3 (Module 4, minimal: Git History Mining only) — COMPLETE

**Status: DONE and verified.** Kept here for reference.

### Decision: mined the outer repo, not a synthetic test_repo history
test_repo/'s files are tracked as ordinary files inside the outer
repoMindAI repo (not a nested repo). Rather than untracking them and
creating a separate nested `.git` purely to manufacture synthetic
fixture history, PyDriller was pointed at the outer repoMindAI repo
itself, which already has real, meaningful commit history. This
satisfies the actual intent (real history to walk, real fields to
extract) more simply and avoids any structural change to a
verified, working repo.

### What was extracted (via PyDriller)
For each commit in the outer repo's history:
- commit hash (short form)
- commit message
- author name
- timestamp
- list of files modified

### Folder structure (Phase 3)
```
mine_history.py    # CLI entry point, PyDriller-based extraction
```

### Definition of Done (Phase 3) — VERIFIED
Running `python mine_history.py`:
1. Walked the outer repo's full commit history via PyDriller ✓
2. Printed each commit: hash, message, author, date, files changed ✓
3. Output cross-checked against `git log --stat` — hashes (051a119,
   ffd8f61), author, timestamps, messages, and modified files all
   matched exactly ✓
4. Summary line printed: "Mined 2 commits from ." ✓

### Explicitly out of scope for Phase 3 (unchanged)
- Evidence correlation / relevance scoring
- ADR synthesis (LLM-based)
- GitHub PR/API integration
- Any LangGraph or LLM logic
- Neo4j Commit/Developer node writes (optional per original scope,
  not built — printed output only)

---

## Implementation Scope — Phase 4 (Mermaid Diagram Export) — COMPLETE

**Status: DONE and verified.** Kept here for reference — do not modify
this code except as explicitly directed by a later phase's scope.

This is a small, self-contained addition — no new analysis, just
formatting existing graph data into a visual diagram.

### Phase 4 goal
Query the existing Neo4j graph and generate a Mermaid diagram (module
dependency graph) as output. Do NOT build: a web UI to display it, ADR
reconstruction, evidence correlation, Q&A, or any LLM/agent logic.

### What to generate
A Mermaid `flowchart` showing module-level dependencies, using the
existing `IMPORTS` relationships already in the graph:
```
flowchart TD
    app[app.py] --> models[models.py]
    app --> utils[utils.py]
    controller[controller.py] --> service[service.py]
    controller --> database[database.py]
    service --> database
```

Node labels should show the module filename. If a module has a
`layer_type` (controller/service/database), style or group those nodes
distinctly (e.g., a Mermaid subgraph per layer) so the layered
architecture is visually obvious — this directly supports the drift
detection narrative.

### Approach
1. Query Neo4j: `MATCH (m1:Module)-[:IMPORTS]->(m2:Module) RETURN m1.path, m1.layer_type, m2.path, m2.layer_type`
2. Also query all Module nodes (even ones with no IMPORTS edges) so isolated modules still appear
3. Format the results as valid Mermaid flowchart syntax
4. Write the output to a `.md` file (so it renders directly in any Markdown viewer that supports Mermaid, e.g. GitHub, VS Code preview) and also print it to the console

### New code (folder structure)
```
export_diagram.py    # CLI entry point for Phase 4
```

### Definition of Done (Phase 4)
Running `python export_diagram.py` should:
1. Query the graph for all Module nodes and IMPORTS relationships
2. Generate valid Mermaid flowchart syntax
3. Write it to `diagram_output.md`
4. Print the same Mermaid code to the console
5. Opening `diagram_output.md` in a Mermaid-capable viewer (GitHub,
   VS Code with Mermaid preview, or mermaid.live) should render a
   correct, readable module dependency diagram matching the actual
   graph structure

### Explicitly out of scope for Phase 4
- Class-level or function-level diagrams (module-level only, for now)
- A web-based interactive diagram viewer
- Automatic regeneration on every pipeline run (this is a standalone,
  on-demand export script)

### Definition of Done (Phase 4) — VERIFIED
Running `python export_diagram.py`:
1. Queried the graph for all Module nodes and IMPORTS relationships ✓
2. Generated valid Mermaid flowchart syntax ✓
3. Wrote it to `diagram_output.md` ✓
4. Printed the same Mermaid code to console ✓
5. Output matched a pre-computed expected structure exactly: 3
   layer-styled subgraphs (controller/database/service), 3 ungrouped
   nodes (app/models/utils), 5 edges, 3 classDef/class pairs ✓
6. Visually confirmed rendering in a Mermaid-capable viewer — no
   syntax errors, correct colored/framed layer boxes ✓
7. `git status` confirmed only `export_diagram.py` and
   `diagram_output.md` were added — no Phase 1-3 files touched ✓

**Post-Phase-8 enhancement — folder-level grouping (`build_mermaid`):**
the original layer-based grouping only applies to modules with a
`layer_type` — a property assigned purely by filename convention
(`controller.py`/`service.py`/`database.py`), specific to this project's
own demo fixture. A real repo using an MVC-style layout as actual
directories (`models/`, `views/`, `controllers/`) got zero grouping —
every file rendered as one flat, ungrouped node list regardless of its
real folder structure. Added a second grouping tier: a module without a
`layer_type` but with a containing folder now renders inside a Mermaid
subgraph box labeled with that folder's relative path (single-level, not
recursively nested — e.g. `src/core` is one flat box labeled `"src/core"`,
not a `src` box containing a nested `core` box); a module with neither
stays a plain top-level node, unchanged. Precedence is deliberately
layer_type first, then folder, so the existing demo fixture's output is
byte-identical to before (re-verified: same 3 layer-styled subgraphs, 3
ungrouped nodes, 5 edges, 3 classDef/class pairs). Verified against a real
23-file JS repo with genuine subdirectories (`src/`, `src/core`,
`src/modules`, `dist/`, `scripts/`, `tests/`): all six folders rendered as
correctly labeled boxes, cross-folder import edges (e.g. a test file
importing a `src/core` module) rendered correctly across box boundaries,
and the output was confirmed to render as valid SVG (no syntax errors) via
a live `mermaid.render()` call in an actual browser, not just a text-level
check.

---

## Implementation Scope — Phase 5a (URL-to-Local-Clone Wrapper) — COMPLETE

**Status: DONE and verified.** Kept here for reference — do not modify
this code except as explicitly directed by a later phase's scope.

Phase 5a is the FIRST of three planned steps toward "paste any GitHub
URL, get a live analysis": **5a (this phase) → 5b (test against real
repos, fix parsing issues) → 5c (graceful failure handling).**

### Phase 5a goal
Accept a GitHub repository URL, clone it locally, and feed that local
path into the EXISTING, UNCHANGED parsing/graph-loading pipeline
(`main.py`'s logic). No changes to `parser/`, `graph/`, `rules/`,
`check_drift.py`, `mine_history.py`, or `export_diagram.py` — this
phase only adds an acquisition step in front of what already works.

### Why this matters for the demo
The goal is: a panel member gives a real GitHub URL, and the full
pipeline (parse → load → drift check → diagram export) runs against
it live. Phase 5a is the first piece — turning a URL into a local
folder the existing pipeline can already handle.

### CLI interface
```
python analyze_repo.py <github_url>
```
Example: `python analyze_repo.py https://github.com/user/small-repo`

### Approach
1. Accept a GitHub URL as a command-line argument
2. Clone it to a temporary local directory (e.g., using `git clone`
   via `subprocess.run(...)`, or GitPython if simpler — either is
   fine, prefer whichever needs fewer new dependencies)
3. Print clear status messages as it progresses (e.g., "Cloning
   {url}...", "Clone complete, found N Python files", "Parsing...",
   "Loaded into Neo4j", "Done") — this will run live in front of a
   panel, so visible progress matters more than in earlier phases
4. Call the existing parsing + graph-loading logic (from `main.py`)
   on the cloned local path — do not duplicate or reimplement that
   logic, import and reuse it
5. Handle cleanup of the temporary clone directory in a sensible way
   (either delete it after loading into Neo4j, or leave it and print
   its path — document whichever choice is made and why)

### Explicitly out of scope for Phase 5a
- Testing against multiple different real-world repos (that's Phase
  5b — this phase only needs to prove cloning + pipeline wiring works
  on ONE small real repo as a smoke test)
- Adding error handling for parsing failures on constructs not yet
  seen (that's Phase 5c)
- Running `check_drift.py` or `export_diagram.py` automatically as
  part of this script (those remain separate commands run afterward,
  same as today — Phase 5a only handles acquisition + parsing/loading)
- GitHub API authentication for private repos (public repos only)

### Definition of Done (Phase 5a) — VERIFIED
Running `python analyze_repo.py https://github.com/kennethreitz/samplemod`:
1. Cloned the repo to a temporary local directory ✓
2. Printed clear progress messages throughout ✓
3. Successfully parsed and loaded it via the existing pipeline logic
   (refactored into a shared `run_pipeline()` function, no duplicated
   code) — 9 files, 2 classes, 5 functions, 16 nodes ✓
4. Printed a final summary matching `main.py`'s existing format ✓
5. Smoke-tested against one real repo, confirming the clone step
   works end-to-end ✓
6. `python main.py ./test_repo` re-confirmed byte-identical output
   after the refactor (6 files, 2 classes, 15 functions, 23 nodes) —
   no regression ✓

**Bug caught and fixed during implementation:** the initial cleanup
(`shutil.rmtree(temp_dir, ignore_errors=True)`) silently left the
`.git` folder behind — Windows marks some git-internal files
read-only, and `ignore_errors=True` skips the failure rather than
fixing it. Fixed with an `onerror` handler that clears the read-only
bit and retries the delete; re-confirmed the temp directory is fully
removed afterward.

---

## Implementation Scope — Phase 5b (Robustness Testing Against Real Repos) — COMPLETE

**Status: DONE and verified.** Kept here for reference — do not modify
this code except as explicitly directed by a later phase's scope.

Phase 5a is complete and verified — the URL-to-clone wrapper works,
proven against one real repo (kennethreitz/samplemod: 9 files, 2 classes,
5 functions, 16 nodes).

### Phase 5b goal
Run analyze_repo.py against SEVERAL more small, real, public Python
repos to find and fix actual parsing failures — not speculative ones.
This phase is about discovering what genuinely breaks on real-world code
that test_repo's simple fixture never exercised, then fixing each issue
as it's found.

### Explicitly different from Phase 5c
Phase 5b fixes bugs in EXISTING parsing logic when a real construct
causes an actual crash or incorrect result (e.g., a decorator confuses
the extractor, a relative import isn't resolved, an f-string with nested
expressions breaks a query). Phase 5c (separate, later) is about adding
GRACEFUL DEGRADATION for whatever still can't be parsed after 5b — i.e.,
skip-and-warn instead of crash, for the long tail of things not worth
fully supporting. Don't build 5c's skip-and-warn behavior in this phase;
if something breaks, either fix the actual parsing logic properly, or
note it as a candidate for 5c's graceful handling — don't paper over it.

### Test repos (run one at a time, fix issues as they appear before moving to the next)
Suggested small, real, structurally-varied public Python repos:
1. `https://github.com/kennethreitz/samplemod` — already tested in 5a, re-confirm as baseline
2. A small Flask app (e.g., a minimal Flask starter/tutorial repo)
3. A small CLI tool repo (argparse-based, likely has decorators)
4. A repo using relative imports within a package (a `package/__init__.py` + submodules structure)
5. (Optional, if time allows) A repo using type hints and dataclasses extensively

### Process for each repo
1. Run `python analyze_repo.py <url>`
2. If it crashes or produces obviously wrong output (e.g., 0 functions found in a repo that clearly has many), diagnose why
3. Fix the actual parsing logic in `parser/ast_extractor.py` if the fix is small and general (e.g., handling a new AST node type)
4. Re-run the SAME repo to confirm the fix worked
5. Document what broke and what the fix was (this is more evaluation/refinement material for the report)
6. Move to the next repo only after the current one is clean or the issue is explicitly deferred to Phase 5c

### Definition of Done (Phase 5b)
- Ran analyze_repo.py against at least 4 different real repos (varied structure: simple module, Flask app, CLI tool with decorators, package with relative imports)
- For each, documented: what happened, whether it worked cleanly or needed a fix, and what the fix was if any
- At least 1-2 genuine parsing bugs found and fixed in `parser/ast_extractor.py` (if the fixture-only testing so far means real bugs are likely to surface)
- After each fix, the ORIGINAL test_repo fixture is re-run to confirm no regression (`python main.py ./test_repo` still produces "Parsed 6 files, found 2 classes, 15 functions" / 23 nodes)
- A short summary table of results across all tested repos, for use in the report/demo prep

### Explicitly out of scope for Phase 5b
- Building skip-and-warn graceful degradation (that's Phase 5c)
- Testing large/complex repos (keep testing small, single-purpose repos)
- Any LLM/agent logic, ADR reconstruction, Q&A

### Definition of Done (Phase 5b) — VERIFIED

Tested against 5 real repos, 3 genuine bugs found and fixed, zero
regressions on `test_repo` after every fix:

| # | Repo | Category | Result |
|---|---|---|---|
| 1 | kennethreitz/samplemod | simple module (baseline) | Clean — 9 files, 2 classes, 5 functions, 16 nodes |
| 2 | gAmadorH/flask-hello-world | Flask app | Bug found+fixed — `@app.route(...)` wrapped functions in `decorated_definition`, silently skipped. Fixed by unwrapping. Now correctly finds 1 function. |
| 3 | takp/click-sample | CLI tool, Click decorators | Clean after the decorator fix — 7 files, 3 classes, 8 functions, 18 nodes; stacked decorators handled correctly |
| 4 | edesig/py_relative_import | package w/ relative imports | 2 bugs found+fixed — (a) relative import stems (`..a.a`) never resolved to real module paths; (b) `from X import *` wildcard imports produced zero entries regardless of relative/absolute |
| 5 | jjmalina/python-dataclasses-examples | dataclasses/type hints (optional) | Clean via the decorator fix — 10 files, 24 classes, 42 functions, 76 nodes |

**Fixes made in `parser/ast_extractor.py`:**
1. Unwrap `decorated_definition` nodes (via `child_by_field_name("definition")`) in both `_extract_file` and `_extract_class`, so decorated functions/classes are no longer silently skipped.
2. Added `_resolve_relative_module`, resolving a `relative_import` node to an absolute dotted module name using the same level-counting rule as Python's own `importlib._resolve_name`.
3. Added handling for `wildcard_import` children in `_extract_import`, so `from X import *` produces an entry allowing the module-level `IMPORTS` edge to resolve (correctly excluded from `CALLS` resolution, since there's no fixed symbol name to track).

Every fix was re-verified against the repo that triggered it, and `python main.py ./test_repo` was re-run after each fix, confirming the exact original output (6 files, 2 classes, 15 functions, 23 nodes) every time. No speculative try/except or skip-and-warn behavior was added.

---

## Implementation Scope — Phase 6 (JavaScript + TypeScript Support) — COMPLETE

**Status: DONE and verified.** Kept here for reference — do not modify
this code except as explicitly directed by a later phase's scope.

This phase extended language support beyond Python, following the same
proven process as Phase 5b: build, test against real repos, fix genuine
bugs, verify no regression.

### Phase 6 goal
Add JavaScript and TypeScript parsing support so the existing pipeline
(knowledge graph, drift detection, Git mining, diagram export) works
unmodified on JS/TS repos — not just Python. Java is explicitly deferred
to a separate, later phase.

### Why the rest of the pipeline needs ZERO changes
`graph/loader.py`, `rules/rule_engine.py`, `check_drift.py`,
`mine_history.py`, and `export_diagram.py` all operate on the graph's
schema (Module/Class/Function nodes, CONTAINS/CALLS/IMPORTS edges) —
they don't know or care what source language produced that data. As
long as the JS/TS extractor produces the SAME output shape Python's
extractor does, nothing downstream needs to change.

### Approach
1. **File language detection**: route by extension — `.py` → existing
   Python extractor, `.js`/`.jsx` → new JS extractor, `.ts`/`.tsx` →
   new TS extractor.
2. **JavaScript extractor** (new): use `tree-sitter-javascript`. Map
   its node types to the same output shape:
   - `function_declaration`, `arrow_function`, `function_expression` → Function
   - `class_declaration` → Class
   - `import_statement` / CommonJS `require(...)` calls → Imports
   - Call expressions → Calls
3. **Test JS against 2-3 real small JS repos** before starting TS —
   same process as Phase 5b: run, diagnose failures/wrong counts, fix
   root causes in the new JS extractor, re-verify, re-check Python
   regression via `test_repo`.
4. **TypeScript extractor** (new, after JS is verified): use
   `tree-sitter-typescript`. Reuse JS extraction logic where grammars
   overlap (TS is largely JS-compatible for functions/classes/calls);
   add handling for TS-specific constructs (interfaces, type aliases,
   decorators-with-types) only as needed based on real test failures —
   not speculatively.
5. **Test TS against 1-2 real small TS repos**, same fix-and-verify
   cycle.
6. **After every single change**, re-run `python main.py ./test_repo`
   and confirm the Python-only baseline is unchanged (6 files, 2
   classes, 15 functions, 23 nodes) — mandatory, not optional.

### Test repos
JS candidates (small, real, structurally simple — find via search,
verify file count is small before running):
1. A small vanilla JS utility library or CLI tool
2. A minimal Express.js app (tests `require`/`module.exports` patterns)
3. (Optional) A small React component library (tests JSX + ES module imports)

TS candidates:
1. A small TypeScript utility library
2. A minimal TS Express/Node app (tests interfaces + typed imports)

### New code (folder structure)
```
parser/
  ast_extractor.py       # existing Python extractor, UNCHANGED except for the language-routing dispatch
  js_extractor.py          # new — JavaScript extraction logic
  ts_extractor.py           # new — TypeScript extraction logic (may import/reuse js_extractor internals)
```

### Definition of Done (Phase 6)
- JavaScript: tested against 2-3 real repos, genuine bugs documented
  and fixed, output shape matches what `graph/loader.py` already
  expects (verified by successfully loading into Neo4j and querying
  the resulting graph)
- TypeScript: tested against 1-2 real repos, same verification
- After ALL changes: `python main.py ./test_repo` still produces the
  exact original Python-only output — zero regression
- `check_drift.py` and `export_diagram.py` both run successfully
  (unmodified) against a JS or TS repo's loaded graph, proving the
  downstream pipeline is genuinely language-agnostic
- A results table (same format as Phase 5b's) documenting each test
  repo and outcome, for direct use in the report

### Explicitly out of scope for Phase 6
- Java support (separate, later phase)
- Any LLM/agent logic
- Speculative handling for JS/TS constructs not actually encountered
  in real test repos
- Temporal versioning, FastAPI/dashboard work

### Definition of Done (Phase 6) — VERIFIED

Architecture: `parser/ast_extractor.py`'s `parse_repo` is now a thin
dispatcher merging results from the renamed (otherwise untouched)
Python extractor plus new `parser/js_extractor.py` and
`parser/ts_extractor.py` — all three produce the identical
`{modules, classes, functions, calls, imports}` shape, so
`graph/loader.py`, `rules/`, `check_drift.py`, `export_diagram.py`,
`main.py`, and `analyze_repo.py` needed ZERO changes.

Tested against 6 real repos (4 JS + 2 TS), 1 genuine bug found and
fixed, zero Python regressions throughout:

| # | Repo | Language | Result |
|---|---|---|---|
| — | (hand-written smoke test) | JS | Bug found+fixed — `const { a, b } = require('./mod')` (destructured require) wasn't detected as an import; only bare `require(...)` statements were. Added `_extract_declared_requires`. |
| 1 | render-examples/express-hello-world | JS | Clean — 1 file, 0 classes/0 functions (genuinely correct — only inline route handlers, no named functions, same "don't extract anonymous callbacks" philosophy as Python) |
| 2 | lam0819/MicroUI | JS | Clean — real classes, 147 functions, 173 nodes; verified correct classes, IMPORTS, and CALLS |
| 3 | zagaris/express-api | JS | Clean — 7 files, 2 functions; verified the destructured-require fix against a real directory-resolution case (`{ errorHandler } = require('./middlewares')` → resolved to `middlewares/index.js`) |
| 4 (optional) | aakashns/simple-component-library | JS/JSX | Clean — arrow-function JSX components correctly extracted, destructured imports didn't break parsing |
| 5 | mjgs/minimal-express-typescript | TS | Clean — same inline-handler pattern as repo 1, correctly 0 top-level named functions |
| 6 | GeekyAnts/express-typescript | TS | Clean — decorator-heavy controller classes extracted correctly, interfaces correctly ignored, IMPORTS/CALLS semantically accurate |

**Cross-language proof (Definition-of-Done requirement):** loaded a TS
repo's graph, then ran `check_drift.py` (→ "No violations found.
ArchitectureHealth = 100") and `export_diagram.py` (→ valid Mermaid
with correctly sanitized TS paths) completely UNMODIFIED — proving the
downstream pipeline is genuinely language-agnostic, not just that
parsing works.

**Regression:** `python main.py ./test_repo` was re-run after every
single change and produced the exact original output (6 files, 2
classes, 15 functions, 23 nodes) every time.

---

## Implementation Scope — Phase 7 (Minimal Web Interface for Demo)

**Phases 1-4, 5a, 5b, and 6 are complete and verified.** This phase is
a thin UI wrapper — it exposes existing, already-verified logic through
a browser instead of the CLI. No new analysis logic, no AI.

### Phase 7 goal
Let someone paste a GitHub URL into a web page and see the full
analysis (parse summary, drift violations, health score, dependency
diagram) rendered visually, live — for tomorrow's demo.

### Why this is fast to build
Every piece of actual work already exists and is verified: cloning
(`analyze_repo.py`), parsing+loading (the shared `run_pipeline`/
dispatcher logic), drift checking (`rules/rule_engine.py` +
`rules/scoring.py`), and diagram generation (`export_diagram.py`).
This phase only wires those together behind one API endpoint and
renders the result in a browser — no new analysis code.

### API contract
```
POST /analyze
Body: {"repo_url": "https://github.com/user/repo"}

Response:
{
  "files_parsed": 6,
  "classes_found": 2,
  "functions_found": 15,
  "nodes_loaded": 23,
  "violations": [
    {"rule": "no-controller-to-db", "severity": 3,
     "caller": "controller.py::handle_request_direct",
     "callee": "database.py::save_record"}
  ],
  "health_score": 0,
  "mermaid_diagram": "flowchart TD\n    ..."
}
```

### Page layout
- A text input for the GitHub URL, a submit button
- A loading indicator while the analysis runs (cloning + parsing a
  real repo takes real time — don't leave the page blank/frozen)
- After results arrive, render in order: parse summary (as simple
  text/stats), violations list (or "No violations found" + the health
  score), then the Mermaid diagram (rendered via the Mermaid.js CDN
  script's `mermaid.render()`/`mermaid.init()`)
- Basic, clean styling — readable, not polished. No frameworks.

### Definition of Done (Phase 7)
1. `POST /analyze` with a real GitHub URL returns the JSON contract
   above, matching what the CLI tools already produce for the same
   repo
2. The HTML page successfully calls the endpoint and renders all four
   result sections (summary, violations, health score, diagram)
3. The rendered Mermaid diagram visually matches what
   `export_diagram.py` produces for the same repo when run via CLI
4. Tested end-to-end in an actual browser against at least one real
   repo (not just test_repo) — a live demo dry run, not just an API
   test
5. No changes to any existing pipeline file's logic — only new
   FastAPI route code and the new static HTML/JS file

### Explicitly out of scope for Phase 7
- Authentication, persistence beyond the existing Neo4j graph
- Any frontend framework or build step
- ADR Reconstruction, Repository Q&A, or any LLM/agent logic
- Styling polish beyond basic readability
- Multiple pages or navigation

**Post-Phase-8 enhancement — neo-brutalist dark redesign:** on explicit
user request, restyled `static/index.html` from the original plain
light-mode layout to a dark, black/white/grayscale-only neo-brutalist
theme: thick white borders, hard offset drop shadows (no blur) on
sections/buttons, sharp corners (no border-radius), bold uppercase
headers (Space Grotesk) over monospace body text (JetBrains Mono, both
via Google Fonts), and a "pressed" button interaction (shadow
collapses/shifts on hover/active). Also updated `mermaid.initialize()`'s
`themeVariables` to match the dark palette, and — since backend-generated
`classDef` styles override the JS theme for layer-tagged nodes — updated
`export_diagram.py`'s `_LAYER_COLORS` from blue/green/tan to three shades
of gray, so the diagram stays monochrome end-to-end rather than showing
old accent colors on the new dark background. No structural HTML changes
and no JS logic changes beyond the Mermaid theme config — every element
id/class the existing `renderResults()` logic depends on is unchanged, so
this was a purely visual, zero-functional-risk change. Verified visually
in a live browser across all four result sections (parse summary stat
tiles, architecture drift + the "no violations" badge, the dark-themed
dependency diagram with folder subgraphs, and the rendered Markdown
documentation) against a real analyzed repo.

---

## Implementation Scope — Phase 8 (LLM-Generated Documentation, via Groq)

**Status: in progress.** Adds this project's first-ever generative
component — everything before this phase (Phases 1-7) was purely
deterministic (parsing, graph queries, rule checks, diagram formatting).

### Phase 8 goal
Given a panel-review deadline, generate a single comprehensive Markdown
documentation page (in the spirit of tools like deepwiki-open) for the
repo just analyzed, rendered in a new section of the same `static/index.html`
page used by Phase 7. Not a multi-page wiki, not a chat/Q&A interface, not
a RAG/vector-DB pipeline — those remain future work (see Capability 3 in
the target architecture above).

### Why this doesn't violate "deterministic before generative"
The model is never asked to determine facts (what exists, what violates a
rule) — those are still 100% computed by the existing Tree-sitter/Neo4j/
rule-engine pipeline, unchanged. The LLM call only receives that already-
computed structural evidence (modules, classes, functions, layers,
import/call edges, violations, health score) plus bounded raw source
excerpts, and is instructed to describe only what's present in that
evidence — never to invent architecture or decide what counts as a
violation.

### Approach
1. New `docs_generator.py`: builds a structural summary from the parsed
   `data` dict + drift-engine output (no disk I/O), separately selects a
   bounded, deterministically-ordered set of source files to read raw
   content from (layer-tagged modules first, then modules named in a
   violation, then by function/class count — capped at 20 files / 60,000
   total characters), and sends both to Groq (OpenAI-compatible API, called
   through the `openai` Python SDK pointed at Groq's base URL) with a
   system instruction requiring the output to stay grounded in the
   provided evidence. Default model: `openai/gpt-oss-120b` (OpenAI's
   open-weight 120B model, hosted on Groq's custom inference hardware).
   Automatically retries up to twice (2s delay) on transient server-side/
   rate-limit errors.
2. `server.py`'s `/analyze` handler calls `generate_documentation` before
   cleaning up the temp clone directory (so raw source is still readable),
   wrapped in `try/except` so an LLM-call failure (bad key, network,
   timeout, empty response, or a retryable error that never clears)
   degrades gracefully — the rest of the response (parse summary,
   violations, health score, diagram) still returns successfully.
3. `static/index.html` renders the returned Markdown via the `marked` CDN
   library, sanitized with `DOMPurify` before insertion (the source
   material includes an arbitrary untrusted public repo's own text, so
   the rendered output is treated as untrusted HTML, consistent with how
   every other server-derived string on this page is already escaped
   before reaching `innerHTML`).
4. Credentials (`GROQ_API_KEY`, optional `GROQ_MODEL` override) follow the
   exact same `.env` + `python-dotenv` convention already used for
   `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`.

### New code (folder structure)
```
docs_generator.py    # new — structural summary + bounded source excerpts + Groq call (with retry)
```

### Definition of Done (Phase 8)
1. `POST /analyze` against a real repo returns the unchanged Phase 7
   fields plus `documentation` (a Markdown string) and
   `documentation_error` (null on success).
2. The page renders a fourth section, "AI-Generated Documentation", below
   the diagram, with headings: Overview, Architecture & Layers,
   Module-by-Module Breakdown, Key Relationships & Dependencies, Known
   Architecture Issues.
3. The generated doc's claims are spot-checked against the same page's
   Parse Summary / Architecture Drift sections — no fabricated module/
   function/class names, and the Known Architecture Issues section
   matches the real violations list exactly.
4. Negative test: an invalid `GROQ_API_KEY` produces a populated
   `documentation_error` while the first three sections still render
   normally (graceful degradation, not a broken demo).
5. Tested end-to-end in a browser against a real public repo.
6. No changes to `parser/`, `graph/`, `rules/`, `check_drift.py`,
   `mine_history.py`, `export_diagram.py`, `main.py`, or `analyze_repo.py`
   — only `docs_generator.py` (new) and additive changes to `server.py`,
   `static/index.html`, `requirements.txt`, `.env`.

### Explicitly out of scope for Phase 8
- Multi-page wiki, navigation, or per-module documentation pages
- Chat/Q&A interface (that remains Capability 3 / Repository Q&A, unbuilt)
- RAG, embeddings, or a vector database — this phase uses bounded direct
  context (structural summary + raw source excerpts), not retrieval
- Caching/reuse of a previously generated doc across requests
- Any change to what counts as a violation, or to the health-score formula

**Bugs caught and fixed during implementation:**
1. The retired-model check: `gemini-2.5-flash` (the initial default) returned
   `404 NOT_FOUND` at runtime with a message naming its replacement; the
   default was updated to `gemini-3.6-flash` and confirmed working.
2. The model occasionally emitted LaTeX-style notation (`$\rightarrow$`) for
   relationship arrows, which `marked` doesn't render, showing as literal
   text in the UI. Fixed by adding an explicit "plain GitHub-flavored
   Markdown only, no LaTeX/math notation" rule to the system instruction;
   re-verified clean on a re-run.
3. **Silent blank documentation section on a larger real repo (19 files):**
   the Gemini call exceeded the original 25s timeout, raising
   `concurrent.futures.TimeoutError` — whose `str()` is `""` (empty) in
   Python. `server.py` faithfully passed that empty string through as
   `documentation_error`, and `static/index.html`'s `if (data.documentation_error)`
   check treated the empty string as falsy, silently hiding the error
   entirely (no error shown, no content shown). Fixed three ways: (a)
   `docs_generator.py` now catches the timeout and re-raises with an
   explicit, non-empty message; (b) `server.py` falls back to
   `type(exc).__name__` if `str(exc)` is ever empty for any exception type;
   (c) the frontend checks `data.documentation_error != null` instead of
   truthiness, so even a genuinely empty-but-present error string still
   displays. Also raised the timeout from 25s to 45s to reduce how often
   larger real repos hit it at all. Verified via a forced-timeout unit
   check (confirms a real message now) and a live 23-file/147-function repo
   (a transient Gemini 503 surfaced correctly instead of going blank).

**Provider round-trip (Gemini → OpenRouter → back to Gemini):** despite the
fixes above, Gemini continued returning transient `503 UNAVAILABLE` ("high
demand") errors during live testing ahead of the panel review — a capacity
issue on Google's side, not something fixable in this codebase. Tried
switching to OpenRouter's free-tier NVIDIA Nemotron 3.5 Lightning
(`nvidia/nemotron-3.5-lightning:free`) instead — OpenAI-compatible API via
the standard `openai` SDK, 1M-token context, and a free-tier rate limit
(20 req/min, 50-1,000 req/day) that looked more than sufficient on paper.
In practice, that free tier **never completed a single request** across
three separate tries during testing (timed out at 45s, then 90s+ due to a
separate bug — see below — then a full 150s with a correct fix in place) —
too slow/congested right now to be demo-reliable, even though the
integration itself was correct (verified via a forced-timeout unit test and
a clean error surfacing on a real 503 from a different, larger test repo).
Reverted to Gemini, keeping the timeout/error-surfacing fixes from the bugs
above, and added automatic retry (up to `MAX_RETRIES=2`, 2s delay) for
transient 503/429/UNAVAILABLE/RESOURCE_EXHAUSTED errors specifically —
Gemini was consistently fast (12-18s) whenever it wasn't hitting that one
transient condition, so a short retry is expected to mask most occurrences
without materially changing typical latency. `docs_generator.py`'s
prompt-building and structural-summary logic is entirely provider-agnostic
and needed no changes across either switch — only the client construction
and the API call itself changed each time.

**A second bug surfaced switching providers, worth recording:** the
original timeout implementation used `with ThreadPoolExecutor(...) as
pool:`, whose `__exit__` calls `shutdown(wait=True)` — this blocks until
the background thread actually finishes, even after `.result(timeout=...)`
already gave up waiting on it. This silently defeated the entire timeout
mechanism: a slow OpenRouter call still hung the request for 90s+ despite a
45s deadline, because exiting the `with` block re-blocked on the same slow
thread. Fixed by managing the executor manually
(`pool = ThreadPoolExecutor(...)` / `pool.shutdown(wait=False)` in a
`finally`) so an abandoned slow call can keep running in the background
without blocking the response. Verified via an isolated test (a simulated
30s call with a 2s timeout correctly returned in ~2s, not 30s) before
re-verifying against the real pipeline.

**Final provider switch (Gemini → Groq):** even with retry logic, Gemini
continued to fail live (persistent, not just occasional, 503s), so switched
to Groq — OpenAI-compatible API via the same `openai` SDK already used for
the OpenRouter attempt, chosen for its custom inference hardware and
reputation for low, consistent latency. The initially-assumed model name
(`llama-3.3-70b-versatile`, based on general Groq documentation) returned
`404 model_not_found` for this account — queried `client.models.list()`
directly to get the actual available model set, and selected
`openai/gpt-oss-120b` (OpenAI's open-weight 120B model) for the best
available output quality among what was actually accessible. Result: the
full `/analyze` pipeline (clone + parse + load + drift + diagram +
documentation) completed in **8.4 seconds** end-to-end against the test
repo — documentation generation itself now a small fraction of total
latency rather than the dominant cost. Generated output quality was
noticeably richer than earlier providers too: it correctly cited actual
docstrings from the source excerpts (not just signatures) and used Markdown
tables for the architecture/module breakdowns. All facts cross-checked
correctly (module/class/function names, health score, violations) with no
regression in grounding accuracy. `GEMINI_API_KEY`/`GEMINI_MODEL` were
replaced with `GROQ_API_KEY`/`GROQ_MODEL` in `.env`, and `google-genai` was
replaced with `openai` in `requirements.txt` (same package as the
OpenRouter attempt, since both are OpenAI-compatible APIs).

**Bug found on a larger real repo — request too large for Groq's free-tier
TPM limit:** a 19-file JS repo produced `413 rate_limit_exceeded — Request
too large... Limit 8000, Requested 20292` for `openai/gpt-oss-120b`
(8,000 tokens per minute on the free tier). Root cause: `_build_structural_summary`
had no overall size cap — only the call-edges list was bounded (at 300
entries, itself large enough to dominate the budget on a repo with many
function calls), while the module/class/function listing and import list
were completely unbounded. More API keys would **not** have fixed this: the
error is one oversized single request, not many small requests accumulating
against a per-minute budget — every free-tier key carries the same 8,000
TPM cap. Fixed by: tightening `MAX_FILES` (20→8), `MAX_CHARS_PER_FILE`
(4000→1500), `MAX_TOTAL_SOURCE_CHARS` (60,000→10,000), capping call edges
at 40 (from 300) with an "N more omitted" note, adding a
`MAX_STRUCTURAL_SUMMARY_CHARS` (6,000) cap on the structural summary as a
whole, adding a final `MAX_PROMPT_CHARS` (14,000) hard backstop on the
combined prompt in `build_prompt` (trims source excerpts first, since
health score/violations — reordered to the top of the structural
summary — are the more important half to keep intact under any
truncation), and setting `max_tokens=1200` on the Groq call to bound output
token usage too. Also fixed the retry logic to stop treating "request too
large" as retryable — it shares Groq's generic `rate_limit_exceeded` error
code with genuinely transient throttling, but retrying an *identical*
oversized payload after a delay fails identically every time, wasting
several seconds for no benefit; a `_NON_RETRYABLE_MARKERS` check
(matching on "reduce your message size" / "Request too large") now takes
priority over the retryable-marker check. Re-verified against the same
147-function repo that would have exceeded 20,000 tokens before (now
~4,700 estimated input tokens, comfortably under budget, succeeding in
9.7s) and against the original small test repo (no regression).

---

## Implementation Scope — Phase 8b (Map-Reduce Documentation Generation)

**Status: DONE and verified.**

### Problem
Even with the bounded-context fixes above, the single-call design fed the
model a repo-wide structural summary (itself capped) plus raw source for
only ~8 "important" files. For any repo bigger than a small demo fixture,
most files got no real source coverage, and for a large enough repo even
the structural summary got truncated — some modules never appeared in the
prompt at all. Confirmed real-world: a repo with only 19 files could still
overflow Groq's free-tier TPM cap on a single call.

### Why not RAG
Evaluated and explicitly rejected: retrieval-augmented generation narrows
scope to answer one query, which is the opposite of what "comprehensive,
whole-repo documentation" needs. Every file has to be covered, not just
the ones a similarity search judges most relevant to some artificial
"describe everything" query — there's no query that meaningfully narrows
"everything." The right fix is **map-reduce summarization**: chunk the
repo, describe each chunk in its own call, then synthesize a connective
overview from the chunk results.

### Design
- `grouping.py` (new): `group_modules()` — the same grouping precedence
  already verified for the Mermaid diagram (`export_diagram.py`'s
  `build_mermaid`): `layer_type` first, then containing folder
  (single-level), then a flat root bucket. Deliberately duplicated rather
  than imported from `export_diagram.py`, to avoid pulling the neo4j
  driver into a pure, no-I/O function.
- Each group is split into batches of at most 10 modules
  (`MAP_MAX_MODULES_PER_BATCH`). Every module in a batch gets a raw-source
  excerpt — batches are small enough that full per-batch coverage is
  affordable, which is the actual fix for the completeness bug.
- **Map phase**: one LLM call per batch, producing only a per-file
  `####`-level breakdown for that batch (not a full document). Runs with
  `MAP_MAX_CONCURRENCY=2` workers.
- **Reduce phase**: one final call synthesizing `## Overview` and
  `## Architecture & Layers` from the (much smaller, already-condensed)
  per-batch results — never sees raw source.
- **`## Known Architecture Issues` and `## Key Relationships &
  Dependencies` are now 100% deterministic Python templating, zero LLM
  involvement** — both are exhaustive structured data already available
  (violations list, health score, import/call edges); asking a model to
  reproduce them verbatim only risked paraphrase or omission for no
  benefit, for exactly the two sections that most need to be authoritative.
- **Fast path**: a repo whose modules all land in one group (rare in
  practice — even small repos usually span 2+ folders) skips map-reduce
  entirely and makes one call, at parity with the old single-call cost.
- **Cost ceiling, not a time ceiling**: `MAX_TOTAL_MAP_CALLS=40` bounds
  how many LLM calls one analysis can trigger (protects the account's
  shared per-day budget); by explicit user decision there is **no
  wall-clock cap** — a large repo takes however long it takes rather than
  returning early/partial results on a timer.
- **Every per-batch or reduce failure degrades to a clearly-marked
  deterministic fallback instead of failing the whole document.**
  `generate_documentation()` now only raises for catastrophic setup
  failure (missing `GROQ_API_KEY`); a failed batch becomes a deterministic
  module listing, a failed reduce becomes a templated overview, and both
  surface as a new `documentation_warnings` list (additive field in
  `server.py`'s response) — "some documentation" beats "no documentation
  field" for exactly the bug this redesign fixes. `static/index.html`
  surfaces these warnings in a dedicated notice above the rendered doc.

### Bugs found and fixed during implementation
1. **Real-world grounding overreach**: a batch describing `src/index.js`
   (which imports from `src/core/*.js`) went on to describe those imported
   files too, even though they weren't in *that* batch's evidence — those
   files get their own, separately-grounded section elsewhere. Fixed by
   strengthening the grounding rule to explicitly forbid describing a
   file not in the current batch's evidence, even one visibly imported in
   the source shown. Re-verified clean on the repo that triggered it.
2. **Rate-limit cooldown was a guess, not the actual window**: a fixed
   15s cooldown on a genuine 429 repeatedly retried into a still-exhausted
   per-minute token budget (observed: several batches cycling through all
   `MAX_RETRIES` attempts, each waiting 15s into a budget that hadn't
   actually reset yet, ballooning a 23-file repo's total time past two
   minutes). Groq's 429 message names the exact wait ("please try again in
   6.07s") — now parsed directly via regex and used as the cooldown
   (+1s margin), with a fixed fallback only if parsing fails. Re-verified:
   the same repo that previously stalled completed in ~90s with every
   retry succeeding on the first attempt after waiting.
3. **Per-call size was too close to the shared TPM ceiling for true
   concurrency**: two `MAP_MAX_CONCURRENCY=2` calls at the original
   11,000-char budget could together approach the account's observed
   ~8,000 TPM limit, causing frequent 429s under real concurrent load.
   Tightened `MAP_MAX_PROMPT_CHARS` (11,000→7,000) and
   `REDUCE_MAX_INPUT_CHARS` (9,000→6,000) so two concurrent calls
   comfortably fit together.
4. **Map output truncation**: one batch's real prose was cut off
   mid-sentence by `MAP_MAX_OUTPUT_TOKENS=700` on a 5-file batch. Raised
   to 1,000; not re-observed after.

### Verification
- **Unit-level** (no network calls, deterministic): `_plan_batches` with
  50 synthetic single-module groups correctly kept 40 and overflowed 10
  to `structural_only`, with total module count conserved exactly; a
  second case with one 45-module group mixed into 39 single-module groups
  correctly split that group mid-batch (10 kept, 35 overflowed) under the
  same cap. Mocked `_call_with_deadline` to inject a failure into one
  specific batch — confirmed that batch degrades to a deterministic
  listing with an honest warning while every other batch's real content
  ships unaffected, and `documentation_error` stays `None`. Same for a
  mocked reduce-call failure — confirmed the deterministic Overview
  fallback is used while all map sections and the deterministic sections
  ship normally.
- **Real-world**: `kennethreitz/samplemod` (9 files, 4 groups: docs/
  sample/ tests/ root) and `lam0819/MicroUI` (23 files, 6 groups) both
  ran the actual full map-reduce path (neither is a single-group repo) —
  confirmed **every module path appears somewhere in the final
  markdown** in both cases, the actual regression test for the bug this
  phase fixes. MicroUI's run hit real, repeated 429s from heavy same-day
  testing load and demonstrated the graceful-degradation path for real
  (one group — `src/core` — fell back to a structural listing with an
  honest `documentation_warnings` entry) rather than only in a mocked
  test.

### Explicitly out of scope
- A second-level/hierarchical reduce for repos with enough groups that
  even the per-group equal-share truncation in `_build_reduce_input`
  becomes too thin to be useful (`REDUCE_MAX_GROUPS_WITH_DETAIL=15`) —
  no real repo tested this session had enough groups to need it.
- Calibrating `MAP_MAX_CONCURRENCY`/prompt-size constants against a
  higher-tier Groq quota — current values are tuned against this
  account's observed free-tier ~8,000 TPM ceiling specifically.
- Async/background job architecture — by explicit user decision, stays
  fully synchronous within the single `POST /analyze` request/response.

### Post-verification tuning fix — real-world truncation and rate-limit collisions
The user ran a real 13-group repository (denser code than anything tested
above — multiple classes/methods per file) and reported two visible
defects: several AI-written sections cut off mid-sentence (e.g. a
constructor signature ending mid-parameter-list, a section ending on a
lone backtick), and 3 of 13 groups fell back to bare structural listings
instead of prose. Both traced to concrete, fixable causes:

1. **Output-length truncation**: `MAP_MAX_OUTPUT_TOKENS=1000` and
   `REDUCE_MAX_OUTPUT_TOKENS=900` were tuned against earlier, simpler test
   repos — a batch of up to 10 files with multiple classes/methods each
   needs more room to finish every file it starts describing, and a
   13-group reduce call needs more room to summarize all of them. Raised
   to `MAP_MAX_OUTPUT_TOKENS=1600` / `REDUCE_MAX_OUTPUT_TOKENS=1500`,
   trimming `MAP_MAX_PROMPT_CHARS` (7,000→6,000) and
   `REDUCE_MAX_INPUT_CHARS` (6,000→5,000) to compensate so total per-call
   token cost doesn't rise much. Also added an explicit "you have a
   limited response budget — wrap up your current file/section with a
   complete thought and stop, never start one you won't finish" rule to
   both the map and reduce system instructions, as a second line of
   defense against mid-sentence cutoffs regardless of the exact numeric
   budget.
2. **Concurrent-call rate-limit collisions**: `MAP_MAX_CONCURRENCY=2` meant
   two calls, each individually under the account's ~8,000 TPM ceiling,
   could still collide and exceed it together — causing more batches to
   exhaust `MAX_RETRIES` than genuinely necessary. Reduced to
   `MAP_MAX_CONCURRENCY=1` (fully serialized map calls) and raised
   `MAX_RETRIES` from 2 to 3 for additional resilience against contention
   from the account's other concurrent usage.

**Re-verified** against `lam0819/MicroUI` under the same kind of real,
observed account-wide rate-limit pressure (repeated genuine 429s in the
log, `Used` consistently 5,000-8,000 of the 8,000 TPM budget) — every
single batch now succeeded within its retry budget (`documentation_warnings: []`),
and a full manual read of the resulting document found no truncated
sentences anywhere, confirming both fixes held under real contention, not
just in a quiet account state.

### Multi-key rotation (reliability enhancement)

Groq's free-tier TPM budget is tracked per account, which is why the
tuning fix above had to serialize map calls onto one key
(`MAP_MAX_CONCURRENCY=1`) — any concurrency on a single shared budget
risked self-inflicted collisions. `GROQ_API_KEYS` (comma-separated, added
to `.env`) lets multiple independently-budgeted keys be configured;
`_load_api_keys`/`_build_clients` (new in `docs_generator.py`) build one
OpenAI client per key, falling back to the single `GROQ_API_KEY` for
backward compatibility if only one key is set.

Each map batch is assigned a key round-robin by its position in the batch
plan (`i % len(clients)`), and is pinned to that same key for its entire
retry lifetime — a per-key 429 is a transient per-minute window, and
waiting it out on the same key is simpler and safer than hopping keys
mid-retry, which would also risk masking a genuinely broken/revoked key
behind endless hopping. Effective map concurrency is computed at runtime
as `min(number of configured keys, MAP_MAX_CONCURRENCY_CAP=5)` — with
`max_workers <= len(clients)` guaranteed by construction, no two batches
running concurrently ever share a key, so concurrent calls never collide
on the same account's rate limit. The reduce call continues the same
round-robin (`len(kept) % len(clients)`) rather than always reusing key 0,
spreading its load too. The rate-limit cooldown itself also became
per-key (`cooldown_until` is now a list, one slot per key, instead of a
single shared value) so one key's throttling no longer blocks calls
scheduled on a different, unaffected key.

**Verification:** an offline test (mocked `_call_with_deadline`, no
network) with 3 synthetic keys and 7 single-module batches confirmed
correct round-robin assignment (A, B, C, A, B, C, A) and the reduce call
correctly landing on the next key in sequence (B); a single-key fallback
test confirmed `GROQ_API_KEY`-only `.env` files keep working unchanged.
A live end-to-end run against the project's own `test_repo` fixture (6
files, 4 groups) with 2 real Groq keys completed in 5.6s with both keys
genuinely used across the 4 map calls + 1 reduce call (`key[1], key[0],
key[0], key[1], key[0]`), zero warnings, zero failed batches.