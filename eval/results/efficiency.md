# Efficiency evaluation

LLM provider: groq (openai/gpt-oss-120b). Cold = empty cache; warm = the same features requested again, and after re-analyzing the same commit.

## lam0819/MicroUI

23 source files, 36 commits. Deterministic analysis: **12.6s** (re-analysis 11.7s).

| Stage | Seconds |
|---|---|
| clone | 1.54 |
| parse | 1.29 |
| graph load | 2.52 |
| rules | 0.62 |
| diagram | 0.5 |
| history mining | 0.06 |
| snapshots | 5.32 |
| history load | 0.77 |

| Feature | Cold seconds | Cold LLM calls | Cold tokens | Warm calls | Warm calls after re-analysis |
|---|---|---|---|---|---|
| violations | 0.0 | 0 | 0 | 0 | 0 |
| decisions | 7.5 | 1 | 3028 | 0 | 0 |
| documentation | 32.8 | 7 | 18167 | 8 | 0 |

## nsidnev/fastapi-realworld-example-app

95 source files, 208 commits. Deterministic analysis: **14.0s** (re-analysis 12.2s).

| Stage | Seconds |
|---|---|
| clone | 1.88 |
| parse | 0.44 |
| graph load | 2.58 |
| rules | 0.69 |
| diagram | 0.96 |
| history mining | 0.11 |
| snapshots | 5.89 |
| history load | 1.43 |

| Feature | Cold seconds | Cold LLM calls | Cold tokens | Warm calls | Warm calls after re-analysis |
|---|---|---|---|---|---|
| violations | 2.2 | 1 | 2211 | 0 | 0 |
| decisions | 63.9 | 8 | 19096 | 0 | 0 |
| documentation | 151.7 | 23 | 48673 | 0 | 0 |

## Summary

Cold runs made **40** LLM calls; the warm repeats made **8**. The cache key covers repository, commit, rules, prompt version and provider/model, so any of those changing regenerates; degraded (warning) results are never cached.

Wall-clock time for cold generative features depends mostly on the provider's rate limit (Groq's free tier allows about 8,000 tokens per minute per key), not on RepoMind's own processing.

_Generated 2026-10-05 10:45 UTC by `eval/eval_efficiency.py`._
