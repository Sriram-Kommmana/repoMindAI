# ADR reconstruction evaluation

Repositories that maintain real Architecture Decision Records are used as ground truth. Their ADR folders are masked from detection and from reconstruction evidence.

## Decision-point recall

| Repository | Commits | Real ADRs | Detected points | Strict recall | Temporal recall | Strict recall (UI top-8) | Distinct points matched | Matches on bulk/squash commits | Precision proxy |
|---|---|---|---|---|---|---|---|---|---|
| thomvaill/log4brains | 146 | 19 | 19 | 0.579 | 0.789 | 0.579 | 2 | 10 | 0.105 |
| mrwilson/adr-viewer | 108 | 6 | 9 | 0.167 | 1.0 | 0.167 | 1 | 0 | 0.111 |
| constructorfleet/mcp-plex | 238 | 3 | 11 | 0.333 | 0.667 | 0.0 | 1 | 0 | 0.091 |
| **All** |  | 28 |  | 0.464 | 0.821 |  |  |  |  |

A match on a bulk commit (100+ files, typically a squash or initial import) is weaker evidence: several ADRs can map to the same squashed decision point, which the 'distinct points matched' column shows.

**Strict**: a detected decision point within ±30 days that shares a topic word with the ADR title. **Temporal**: any detected point within ±30 days. **Precision proxy**: detected points matching some ADR — most real decisions never get an ADR, so this is a lower bound, not precision.

### thomvaill/log4brains

| ADR date | Real ADR | Matched decision point | Shared words |
|---|---|---|---|
| 2020-09-24 | Use Markdown Architectural Decision Records | Initial technology stack: chai (testing), jest (testing), joi (validation / schemas), next (web framework), nodemon (server / runtime), react (frontend framework) (2020-09-25) | markdown |
| 2020-09-25 | Multi-packages architecture in a monorepo with Yarn and Lerna | Initial technology stack: chai (testing), jest (testing), joi (validation / schemas), next (web framework), nodemon (server / runtime), react (frontend framework) (2020-09-25) | lerna, yarn |
| 2020-09-25 | Use Prettier-ESLint Airbnb for the code style | Initial technology stack: chai (testing), jest (testing), joi (validation / schemas), next (web framework), nodemon (server / runtime), react (frontend framework) (2020-09-25) | airbnb, lint, prettier |
| 2020-09-25 | Use Next.js for Static Site Generation | Initial technology stack: chai (testing), jest (testing), joi (validation / schemas), next (web framework), nodemon (server / runtime), react (frontend framework) (2020-09-25) | next |
| 2020-09-26 | Use the ADR number as its unique ID | — (something detected nearby) |  |
| 2020-09-26 | React file structure organized by feature | Initial technology stack: chai (testing), jest (testing), joi (validation / schemas), next (web framework), nodemon (server / runtime), react (frontend framework) (2020-09-25) | file, react |
| 2020-09-27 | Avoid default exports | — (something detected nearby) |  |
| 2020-09-27 | Avoid React.FC type | Initial technology stack: chai (testing), jest (testing), joi (validation / schemas), next (web framework), nodemon (server / runtime), react (frontend framework) (2020-09-25) | react |
| 2020-09-27 | Use React hooks | Initial technology stack: chai (testing), jest (testing), joi (validation / schemas), next (web framework), nodemon (server / runtime), react (frontend framework) (2020-09-25) | hooks, react |
| 2020-10-02 | Use Explicit Architecture and DDD for the core API | Initial technology stack: chai (testing), jest (testing), joi (validation / schemas), next (web framework), nodemon (server / runtime), react (frontend framework) (2020-09-25) | core |
| 2020-10-03 | Markdown parsing is part of the domain | Initial technology stack: chai (testing), jest (testing), joi (validation / schemas), next (web framework), nodemon (server / runtime), react (frontend framework) (2020-09-25) | markdown |
| 2020-10-07 | Next.js persistent layout pattern | Initial technology stack: chai (testing), jest (testing), joi (validation / schemas), next (web framework), nodemon (server / runtime), react (frontend framework) (2020-09-25) | next |
| 2020-10-16 | Use the ADR slug as its unique ID | — (something detected nearby) |  |
| 2020-10-26 | The core API is responsible for enhancing the ADR markdown body with MDX | — |  |
| 2020-10-27 | ADR link resolver in the domain | — |  |
| 2020-11-03 | Use Lunr for search | — |  |
| 2021-01-13 | Distribute Log4brains as a global NPM package | Initial technology stack: @log4brains/cli, @log4brains/cli-common, @log4brains/init, @log4brains/web, chalk (2021-01-13) | brains, distribute, global, log, npm, package |
| 2024-09-26 | Transition to Simplified Git Flow | — |  |
| 2024-12-17 | Switch back to GitHub Flow, but keeping the automated beta releases | — (something detected nearby) |  |

### mrwilson/adr-viewer

| ADR date | Real ADR | Matched decision point | Shared words |
|---|---|---|---|
| 2018-09-02 | Record architecture decisions | — (something detected nearby) |  |
| 2018-09-02 | Expose command line interface | Adopt click (2018-09-02) | interface |
| 2018-09-09 | Use same colour for all headers | — (something detected nearby) |  |
| 2018-09-09 | Distinguish superseded records with colour | — (something detected nearby) |  |
| 2018-09-09 | Distinguish amendments to records with colour | — (something detected nearby) |  |
| 2018-09-10 | Accessibility as a first-class concern | — (something detected nearby) |  |

### constructorfleet/mcp-plex

| ADR date | Real ADR | Matched decision point | Shared words |
|---|---|---|---|
| 2025-10-05 | Adopt Architecture Decision Records | — (something detected nearby) |  |
| 2025-10-05 | Loader Multi-Worker Pipeline | Adopt coverage (2025-10-04) | loader |
| 2026-07-04 | Allow SSE and Streamable HTTP to Coexist in One Process | — |  |

## Relevance-weight sensitivity

Evidence selected for the matched decision points under different α (time) / β (graph) / γ (text) weights, compared with the default by Jaccard overlap.

**thomvaill/log4brains**

| Weights | Mean evidence commits | Mean Jaccard vs default |
|---|---|---|
| default (0.3/0.45/0.25) | 2.5 | 1.0 |
| time-heavy (0.6/0.2/0.2) | 6.5 | 0.615 |
| graph-heavy (0.15/0.7/0.15) | 2.0 | 0.875 |
| text-heavy (0.15/0.25/0.6) | 1.0 | 0.625 |
| equal (1/3 each) | 3.0 | 0.9 |

**mrwilson/adr-viewer**

| Weights | Mean evidence commits | Mean Jaccard vs default |
|---|---|---|
| default (0.3/0.45/0.25) | 3.0 | 1.0 |
| time-heavy (0.6/0.2/0.2) | 12.0 | 0.25 |
| graph-heavy (0.15/0.7/0.15) | 3.0 | 1.0 |
| text-heavy (0.15/0.25/0.6) | 2.0 | 0.667 |
| equal (1/3 each) | 5.0 | 0.6 |

**constructorfleet/mcp-plex**

| Weights | Mean evidence commits | Mean Jaccard vs default |
|---|---|---|
| default (0.3/0.45/0.25) | 12.0 | 1.0 |
| time-heavy (0.6/0.2/0.2) | 12.0 | 0.714 |
| graph-heavy (0.15/0.7/0.15) | 12.0 | 0.6 |
| text-heavy (0.15/0.25/0.6) | 4.0 | 0.333 |
| equal (1/3 each) | 12.0 | 0.846 |

## Reconstruction (LLM)

_Not run in this report (use `--synthesize`)._

## Limits

- Only decisions that leave a trace in code history are detectable (dependency, infrastructure, structure, rule changes). ADRs about process, documentation or UI conventions have no such trace.
- Topic matching uses title words, so a correct detection described with different words counts as a miss.

_Generated 2026-10-05 11:30 UTC by `eval/eval_adr.py`._
