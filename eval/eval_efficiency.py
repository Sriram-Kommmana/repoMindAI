"""Efficiency evaluation: time per pipeline stage, LLM calls and tokens per
generative feature on a cold cache, and the same features again on a warm
cache (same commit, and a fresh re-analysis of it) — which should make zero
LLM calls.

Usage: python eval/eval_efficiency.py [repo_url ...]
"""
import sys
import tempfile
import time

from common import table, write_report

import cache
import llm

DEFAULT_REPOS = ["https://github.com/lam0819/MicroUI", "https://github.com/nsidnev/fastapi-realworld-example-app"]
FEATURES = [("violations", "/violations/explain"), ("decisions", "/adrs"), ("documentation", "/documentation")]


def _calls():
    usage = llm.usage_snapshot()
    return (sum(u["calls"] for u in usage.values()),
            sum(u["prompt_tokens"] + u["completion_tokens"] for u in usage.values()))


def run_features(client, analysis_id, has_violations):
    out = {}
    for name, path in FEATURES:
        if name == "violations" and not has_violations:
            out[name] = {"seconds": 0.0, "calls": 0, "tokens": 0, "skipped": True}
            continue
        c0, t0, start = *_calls(), time.time()
        resp = client.post(path, json={"analysis_id": analysis_id})
        resp.raise_for_status()
        body = resp.json()
        c1, t1 = _calls()
        warnings = body.get("documentation_warnings") if name == "documentation" else body.get("warnings")
        out[name] = {"seconds": round(time.time() - start, 1), "calls": c1 - c0, "tokens": t1 - t0,
                     "degraded": bool(warnings)}
    return out


def main():
    from fastapi.testclient import TestClient
    import server

    repos = sys.argv[1:] or DEFAULT_REPOS
    cache.CACHE_DIR = tempfile.mkdtemp(prefix="repomind_evalcache_")   # start cold
    results = []
    with TestClient(server.app) as client:
        for url in repos:
            first = client.post("/analyze", json={"repo_url": url})
            first.raise_for_status()
            a = first.json()
            print(f"{url}: analyzed in {a['seconds']}s {a['timings']}")
            cold = run_features(client, a["analysis_id"], bool(a["violations"]))
            warm_same = run_features(client, a["analysis_id"], bool(a["violations"]))
            again = client.post("/analyze", json={"repo_url": url}).json()
            warm_reanalysis = run_features(client, again["analysis_id"], bool(again["violations"]))
            results.append({"repo": url, "files": a["files_parsed"], "commits": a["history"]["commits"],
                            "analysis_seconds": a["seconds"], "timings": a["timings"],
                            "reanalysis_seconds": again["seconds"], "cold": cold, "warm_same": warm_same,
                            "warm_reanalysis": warm_reanalysis})
            print(f"  cold {cold}\n  warm {warm_same}\n  re-analysis {warm_reanalysis}")

    md = ["# Efficiency evaluation", "",
          f"LLM provider: {llm.describe('docs')['provider']} ({llm.describe('docs')['model']}). "
          "Cold = empty cache; warm = the same features requested again, and after re-analyzing the same commit.", ""]
    for r in results:
        md += [f"## {r['repo'].replace('https://github.com/', '')}", "",
               f"{r['files']} source files, {r['commits']} commits. Deterministic analysis: **{r['analysis_seconds']}s** "
               f"(re-analysis {r['reanalysis_seconds']}s).", "",
               table(["Stage", "Seconds"], [[k.replace("_", " "), v] for k, v in r["timings"].items()]), "",
               table(["Feature", "Cold seconds", "Cold LLM calls", "Cold tokens", "Cold result", "Warm calls",
                      "Warm calls after re-analysis"],
                     [[name, r["cold"][name]["seconds"], r["cold"][name]["calls"], r["cold"][name]["tokens"],
                       "skipped (no violations)" if r["cold"][name].get("skipped") else
                       "partial (rate-limited, not cached)" if r["cold"][name].get("degraded") else "complete",
                       r["warm_same"][name]["calls"], r["warm_reanalysis"][name]["calls"]] for name, _ in FEATURES]), ""]
    total_cold = sum(r["cold"][n]["calls"] for r in results for n, _ in FEATURES)
    total_warm = sum(r["warm_same"][n]["calls"] + r["warm_reanalysis"][n]["calls"] for r in results for n, _ in FEATURES)
    md += ["## Summary", "", f"Cold runs made **{total_cold}** LLM calls; the warm repeats made **{total_warm}**. "
           "The cache key covers repository, commit, rules, prompt version and provider/model, so any of those "
           "changing regenerates. A partial result (some sections hit the rate limit and fell back) is never cached, "
           "so a warm repeat after a partial cold run regenerates it once — that is the only case where warm calls "
           "are non-zero.", "",
           "Wall-clock time for cold generative features depends mostly on the provider's rate limit (Groq's free "
           "tier allows about 8,000 tokens per minute per key), not on RepoMind's own processing."]
    print(write_report("efficiency", "\n".join(md), {"results": results}))


if __name__ == "__main__":
    main()
