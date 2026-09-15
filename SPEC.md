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

---

## Implementation Scope — Phase 5a (URL-to-Local-Clone Wrapper)

**Phases 1-4 are complete and verified.** Phase 5a is the FIRST of three
planned steps toward "paste any GitHub URL, get a live analysis":
**5a (this phase) → 5b (test against real repos, fix parsing issues) →
5c (graceful failure handling).** Do not attempt 5b or 5c in this phase
— keep this strictly to cloning + wiring into the existing pipeline.

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

### Definition of Done (Phase 5a)
Running `python analyze_repo.py <a real small public GitHub repo URL>`
should:
1. Clone the repo to a temporary local directory
2. Print clear progress messages throughout
3. Successfully parse and load it into Neo4j using the existing
   pipeline logic (no duplicated parsing code)
4. Print a final summary matching `main.py`'s existing summary format
   (files/classes/functions parsed, node count loaded)
5. As a smoke test, this should be run against at least ONE real
   small public repo (not just test_repo) to confirm the clone step
   itself works end-to-end — full robustness testing across multiple
   repos is Phase 5b, not required here