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
> Scope — Phase 1" below for what is actually being built right now.

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

> **Phase 1 note:** temporal versioning is deferred — see
> Implementation Scope below for the simplified Phase 1 schema.

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
this produces a **drift curve** over the repo's history.

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

1. **Ingestion & Parsing** — Tree-sitter, static analysis.
2. **Software Knowledge Graph** — Neo4j, temporal versioning.
3. **Architecture Analysis Engine** — deterministic rules,
   violations, drift scoring. *(Priority)*
4. **Historical Intelligence Engine** — Git/PR mining, evidence
   correlation, ADR synthesis. *(Priority)*
5. **AI Reasoning & Delivery** — LangGraph orchestration (drift,
   ADR, and Q&A agents), API, dashboard with chat panel.

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

## Implementation Scope — Phase 1 (Module 1 + Module 2 only)

**This is what we are actually building right now.** Everything
above this section describes the full target vision — do not build
any of it yet beyond what's scoped here.

### Phase 1 goal
Build only parsing + graph loading. Do NOT build drift detection,
ADR reconstruction, Q&A, temporal versioning, Git history mining, or
any LLM/agent logic yet.

### Scope simplification for Phase 1
- Language support: Python only (expand later)
- Temporal versioning: SKIP for now — just current-state edges, no
  valid_from/valid_to yet (add this in a later phase)
- Git history mining: SKIP for now — that's Module 4, a separate
  later phase

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

### Folder structure
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

### Definition of Done (Phase 1)
Running `python main.py ./test_repo` should:
1. Parse all `.py` files in `test_repo`
2. Print a summary: `"Parsed N files, found M classes, K functions"`
3. Load all nodes/relationships into Neo4j
4. Running `MATCH (n) RETURN count(n)` in Neo4j Browser shows the
   correct node count matching the printed summary
