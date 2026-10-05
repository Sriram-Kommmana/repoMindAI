# Drift detection evaluation

Precision, recall and F1 of the deterministic rule engine with the default `rules.yaml`.

## A. Synthetic layered projects

5 generated projects per language, 8 entities each (controller, service, repository and model modules per entity). Each project gets 8 injected violations covering all four default rule types (controller→database calls and imports, service→controller, database→service, database→controller) and 10 decoys that must not be flagged (allowed_call, name_collision, string_mention, test_file, model_import).

| Language | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| Python | 50 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| JavaScript (CommonJS) | 50 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| TypeScript (ES modules) | 50 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| **All** | 150 | 0 | 0 | 1.0 | 1.0 | 1.0 |

Per rule, all languages:

| Rule | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| no-controller-imports-db | 30 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| no-controller-to-db | 30 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| no-db-imports-controller | 30 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| no-db-imports-service | 30 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| no-service-imports-controller | 30 | 0 | 0 | 1.0 | 1.0 | 1.0 |

### A2. Known unsupported call form: calls through a module attribute

Three controller→repository dependencies per language written as `module.function()` (Python `import x as m; m.f()`, CommonJS `const m = require(...); m.f()`, ES `import * as m ...; m.f()`). The call resolvers deliberately don't guess these targets.

| Language | Imports-rule recall | Calls-rule recall | False positives |
|---|---|---|---|
| Python | 1.0 | 0.0 | 0 |
| JavaScript (CommonJS) | 1.0 | 0.0 | 0 |
| TypeScript (ES modules) | 1.0 | 0.0 | 0 |

The dependency is still reported (by the imports rule) in every case; only the function-level call edge is missing, which affects the calls rule and call-level answers in Q&A.

## B. Real repositories with injected violations

Each repository is first analyzed as-is; that baseline was reviewed by hand (by the author) and is excluded from scoring. Up to 3 module imports per rule type are then appended to real files, and the repository is re-analyzed. Recall is over the injections; precision is over everything newly flagged.

| Repository | Baseline violations | Injected | Precision | Recall | F1 | Baseline unchanged |
|---|---|---|---|---|---|---|
| nsidnev/fastapi-realworld-example-app | 15 | 12 | 1.0 | 1.0 | 1.0 | yes |
| hagopj13/node-express-boilerplate | 0 | 3 | 1.0 | 1.0 | 1.0 | yes |
| w3tecch/express-typescript-boilerplate | 0 | 12 | 1.0 | 1.0 | 1.0 | yes |

## C. Graph engine vs in-memory evaluator

Compared on 3 synthetic project(s) loaded into Neo4j: identical results.

## Limits

- Synthetic projects only use constructs the resolvers support (from-imports, named ES imports, destructured `require`). Calls through `module.function()` attribute access or default imports are not resolved, so the calls rule can miss them in real code; the imports rules still catch the dependency.
- Layers come from folder and file-name patterns; a repository whose layout doesn't match the patterns needs its own `layers` section, otherwise its modules are untagged and not judged.

_Generated 2026-10-05 10:38 UTC by `eval/eval_drift.py`._
