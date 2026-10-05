"""ADR reconstruction evaluation against repositories that keep real ADRs.

Leakage control: the ADR folders are excluded from detection and from the
evidence the reconstruction sees, and commits that only touch them are
ignored — the tool never reads the answers it is scored against.

Deterministic metrics (no LLM):
  - decision-point recall: share of real ADRs with a detected decision point
    within +-30 days AND sharing at least one topic word (strict), or just
    within +-30 days (temporal);
  - decision precision proxy: share of detected decision points that match a
    real ADR (low by nature: most real decisions never get an ADR written);
  - alpha/beta/gamma sensitivity: how much the evidence selection changes
    under different relevance weights.
With --synthesize (uses the LLM): reconstructs matched decisions, reports the
validator's statistics, and writes a side-by-side rubric sheet
(adr_rubric.md) for human scoring of accuracy, completeness and
hallucination.

Usage: python eval/eval_adr.py [--synthesize] [--per-repo 5] [repo_url ...]
"""
import argparse
import os
import re
from datetime import datetime, timezone

from common import clone, remove_tree, table, write_report, RESULTS

from adr.detect import MAX_DECISIONS, detect_decisions
from adr.relevance import focus_files, score_evidence, tokens
from external_imports import modules_using, scan_repo
from history import commit_meta, git, mine_commits
from layers import apply_layers
from parser import ast_extractor
from rules.config import load_rules_config
from snapshots import build_snapshots, source_change_filter

REPOS = ["https://github.com/thomvaill/log4brains", "https://github.com/mrwilson/adr-viewer",
         "https://github.com/constructorfleet/mcp-plex"]
ADR_FILE = re.compile(r"(^|/)((docs?|documentation)/)?(adr|adrs|decisions|architecture/decisions)/[^/]+\.md$", re.I)
WINDOW_DAYS = 30
TEST_DIRS = {"test", "tests", "integration-tests", "__tests__", "fixtures", "e2e", "examples", "example", "spec"}
GENERIC = {"use", "using", "adopt", "record", "records", "architecture", "architectural", "decision", "decisions",
           "adr", "adrs", "proposal", "introduce", "initial", "technology", "stack", "module", "group", "modules"}
WEIGHTS = {"default (0.3/0.45/0.25)": (0.3, 0.45, 0.25), "time-heavy (0.6/0.2/0.2)": (0.6, 0.2, 0.2),
           "graph-heavy (0.15/0.7/0.15)": (0.15, 0.7, 0.15), "text-heavy (0.15/0.25/0.6)": (0.15, 0.25, 0.6),
           "equal (1/3 each)": (1 / 3, 1 / 3, 1 / 3)}
RULES = load_rules_config()


def parse_adrs(repo: str) -> list:
    adrs = []
    for path in git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines():
        name = path.rsplit("/", 1)[-1].lower()
        if not ADR_FILE.search(path) or name in ("readme.md", "index.md") or "template" in name:
            continue
        if any(seg.lower() in TEST_DIRS for seg in path.split("/")[:-1]):
            continue  # fixture ADRs used by the project's own tests, not real decisions
        with open(os.path.join(repo, *path.split("/")), "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        heading = next((l.lstrip("#").strip() for l in text.splitlines() if l.startswith("#")), name)
        title = re.sub(r"^(adr[-\s]*)?\d+[.:)\-\s]+", "", heading, flags=re.I).strip()
        date = None
        m = re.match(r"(\d{4})(\d{2})(\d{2})-", name) or re.match(r"(\d{4})-(\d{2})-(\d{2})", name)
        if m:
            date = "-".join(m.groups())
        if not date:
            m = re.search(r"^\s*[-*]?\s*\**date\**\s*:\s*\**\s*(\d{4}-\d{2}-\d{2})", text, re.I | re.M)
            date = m.group(1) if m else None
        if not date:
            added = git(repo, "log", "--diff-filter=A", "--follow", "--format=%aI", "--", path).split()
            date = added[-1][:10] if added else None
        body = re.sub(r"\s+", " ", text.split("\n", 1)[1] if "\n" in text else "").strip()
        adrs.append({"path": path, "title": title, "date": date, "excerpt": body[:700]})
    return sorted(adrs, key=lambda a: a["date"] or "")


def _days(a: str, b: str) -> float:
    try:
        da = datetime.fromisoformat(a[:10]).replace(tzinfo=timezone.utc)
        db = datetime.fromisoformat(b[:10]).replace(tzinfo=timezone.utc)
        return abs((da - db).days)
    except (TypeError, ValueError):
        return 10 ** 6


def topic(words: str) -> set:
    return {t for t in tokens(words) if t not in GENERIC}


def decision_topic(d: dict) -> set:
    """What the decision is about — not the commit's file list, which on a
    squashed or initial commit contains everything and matches anything."""
    packages = " ".join(d["packages"] + d.get("added", []) + d.get("removed", []))
    return topic(f"{d['subject']} {packages} {d['commit_subject']} {d.get('folder', '')}")


def match(adrs: list, decisions: list) -> list:
    rows = []
    for a in adrs:
        near = [d for d in decisions if a["date"] and _days(a["date"], d["date"] or "") <= WINDOW_DAYS]
        strict = [(len(topic(a["title"]) & decision_topic(d)), d) for d in near]
        strict = [x for x in strict if x[0] > 0]
        best = max(strict, key=lambda x: (x[0], -_days(a["date"], x[1]["date"])))[1] if strict else None
        rows.append({"adr": a, "temporal": bool(near), "strict": best,
                     "shared": sorted(topic(a["title"]) & decision_topic(best)) if best else []})
    return rows


def sensitivity(decisions: list, commits: list, usage: dict, imports: list, excluded) -> dict:
    out = {}
    base_sets = {}
    for d in decisions:
        mods = sorted({m for p in d["packages"] for m in modules_using(usage, p, d.get("ecosystem", "pypi"))})
        focus = focus_files({**d, "files": [f for f in d["files"] if not excluded(f)]}, mods, imports)
        for label, w in WEIGHTS.items():
            ev = score_evidence(d, commits, focus, weights=w, excluded=excluded)["evidence"]
            shorts = {e["commit"]["short"] for e in ev}
            if label.startswith("default"):
                base_sets[d["id"]] = shorts
            out.setdefault(label, []).append((d["id"], shorts))
    summary = {}
    for label, items in out.items():
        sizes = [len(s) for _, s in items]
        jac = [len(s & base_sets[i]) / len(s | base_sets[i]) if s | base_sets[i] else 1.0 for i, s in items]
        summary[label] = {"mean_evidence": round(sum(sizes) / len(sizes), 2) if sizes else 0,
                          "mean_jaccard_vs_default": round(sum(jac) / len(jac), 3) if jac else 0}
    return summary


def evaluate_repo(url: str, synthesize: bool, per_repo: int) -> dict:
    root = clone(url)
    try:
        adrs = parse_adrs(root)
        adr_dirs = sorted({a["path"].rsplit("/", 1)[0] for a in adrs})
        exclude = [f"{d}/*" for d in adr_dirs]

        def excluded(path):
            return any(path.startswith(d + "/") for d in adr_dirs)

        commits = mine_commits(root)["commits"]
        head = ast_extractor.parse_repo(root)
        apply_layers(head, RULES)
        by_hash = {c["hash"]: c for c in commits}
        snaps = build_snapshots(root, RULES, head, 1.0, lambda s: by_hash.get(s) or commit_meta(root, s),
                                eligible=source_change_filter(commits))
        all_decisions = detect_decisions(root, commits, snaps, exclude, limit=50)
        top = detect_decisions(root, commits, snaps, exclude, limit=MAX_DECISIONS)
        rows = match(adrs, all_decisions)
        rows_top = match(adrs, top)
        matched_ids = {r["strict"]["id"] for r in rows if r["strict"]}
        bulk_shas = {c["hash"] for c in commits if c["bulk"]}
        on_bulk = sum(1 for r in rows if r["strict"] and r["strict"]["sha"] in bulk_shas)
        usage = scan_repo(root, [m["path"] for m in head["modules"]])
        matched = [d for d in all_decisions if d["id"] in matched_ids]
        result = {
            "repo": url, "adrs": len(adrs), "adr_dirs": adr_dirs, "commits": len(commits),
            "detected": len(all_decisions),
            "strict_recall": round(sum(1 for r in rows if r["strict"]) / len(adrs), 3) if adrs else None,
            "temporal_recall": round(sum(1 for r in rows if r["temporal"]) / len(adrs), 3) if adrs else None,
            "strict_recall_top8": round(sum(1 for r in rows_top if r["strict"]) / len(adrs), 3) if adrs else None,
            "precision_proxy": round(len(matched_ids) / len(all_decisions), 3) if all_decisions else None,
            "distinct_points_matched": len(matched_ids), "matches_on_bulk_commits": on_bulk,
            "rows": [{"date": r["adr"]["date"], "title": r["adr"]["title"], "temporal": r["temporal"],
                      "match": r["strict"]["subject"] if r["strict"] else None,
                      "match_date": (r["strict"]["date"] or "")[:10] if r["strict"] else None, "shared": r["shared"]}
                     for r in rows],
            "sensitivity": sensitivity(matched[:10], commits, usage, head["imports"], excluded) if matched else {},
        }
        if synthesize and matched:
            from agents.adr_graph import reconstruct_one
            reconstructions = []
            for r in [r for r in rows if r["strict"]][:per_repo]:
                adr, warnings, _ = reconstruct_one(url, commits[-1]["hash"], root, RULES, head, commits, r["strict"],
                                                   usage, tuple(exclude))
                reconstructions.append({"real": r["adr"], "reconstructed": adr, "warnings": warnings})
            result["reconstructions"] = reconstructions
        return result
    finally:
        remove_tree(root)


def rubric(results: list) -> str:
    md = ["# ADR reconstruction — human scoring sheet", "",
          "For each pair, compare the reconstructed record with the real ADR the project wrote. The reconstruction "
          "never saw the real ADR (its folder was masked). Score: **Accuracy** 1–5 (does the reconstructed decision "
          "match the real one?), **Completeness** 1–5 (context and consequences covered?), **Hallucination** yes/no "
          "(any claim not supported by the cited evidence?). Record who scored.", ""]
    for r in results:
        for i, pair in enumerate(r.get("reconstructions", []), 1):
            real, rec = pair["real"], pair["reconstructed"]
            md += [f"## {r['repo'].replace('https://github.com/', '')} — pair {i}", "",
                   f"**Real ADR** ({real['date']}, `{real['path']}`): **{real['title']}**", "", f"> {real['excerpt']}", "",
                   f"**Reconstructed** ({(rec['date'] or '')[:10]}, {rec['status']}, confidence {rec['confidence']} "
                   f"{rec['confidence_label']}): **{rec['title']}**", "",
                   f"- Decision: {rec['decision']}", f"- Context: {rec['context']}",
                   f"- Inference: {rec['inference']}",
                   f"- Evidence: {', '.join(e['short'] for e in rec['evidence'])}", "",
                   "| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |",
                   "|---|---|---|---|---|", "|  |  |  |  |  |", ""]
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthesize", action="store_true")
    ap.add_argument("--per-repo", type=int, default=5)
    ap.add_argument("repos", nargs="*")
    args = ap.parse_args()

    results = []
    for url in args.repos or REPOS:
        print(url)
        try:
            results.append(evaluate_repo(url, args.synthesize, args.per_repo))
            r = results[-1]
            print(f"  ADRs {r['adrs']}, detected {r['detected']}, strict recall {r['strict_recall']}, "
                  f"temporal {r['temporal_recall']}, top-8 {r['strict_recall_top8']}")
        except Exception as exc:
            results.append({"repo": url, "error": str(exc)})
            print("  ERROR", exc)

    ok = [r for r in results if "error" not in r]
    total_adrs = sum(r["adrs"] for r in ok)
    strict = sum(sum(1 for row in r["rows"] if row["match"]) for r in ok)
    temporal = sum(sum(1 for row in r["rows"] if row["temporal"]) for r in ok)
    md = ["# ADR reconstruction evaluation", "",
          "Repositories that maintain real Architecture Decision Records are used as ground truth. Their ADR folders "
          "are masked from detection and from reconstruction evidence.", "",
          "## Decision-point recall", "",
          table(["Repository", "Commits", "Real ADRs", "Detected points", "Strict recall", "Temporal recall",
                 "Strict recall (UI top-8)", "Distinct points matched", "Matches on bulk/squash commits",
                 "Precision proxy"],
                [[r["repo"].replace("https://github.com/", ""), r["commits"], r["adrs"], r["detected"], r["strict_recall"],
                  r["temporal_recall"], r["strict_recall_top8"], r["distinct_points_matched"],
                  r["matches_on_bulk_commits"], r["precision_proxy"]] for r in ok]
                + [["**All**", "", total_adrs, "", round(strict / total_adrs, 3) if total_adrs else "",
                    round(temporal / total_adrs, 3) if total_adrs else "", "", "", "", ""]]), "",
          "A match on a bulk commit (100+ files, typically a squash or initial import) is weaker evidence: several "
          "ADRs can map to the same squashed decision point, which the 'distinct points matched' column shows.", "",
          "**Strict**: a detected decision point within ±30 days that shares a topic word with the ADR title. "
          "**Temporal**: any detected point within ±30 days. **Precision proxy**: detected points matching some ADR "
          "— most real decisions never get an ADR, so this is a lower bound, not precision.", ""]
    for r in ok:
        md += [f"### {r['repo'].replace('https://github.com/', '')}", "",
               table(["ADR date", "Real ADR", "Matched decision point", "Shared words"],
                     [[row["date"], row["title"], f"{row['match']} ({row['match_date']})" if row["match"] else
                       ("— (something detected nearby)" if row["temporal"] else "—"), ", ".join(row["shared"])]
                      for row in r["rows"]]), ""]
    if any(r.get("sensitivity") for r in ok):
        md += ["## Relevance-weight sensitivity", "",
               "Evidence selected for the matched decision points under different α (time) / β (graph) / γ (text) "
               "weights, compared with the default by Jaccard overlap.", ""]
        for r in ok:
            if r.get("sensitivity"):
                md += [f"**{r['repo'].replace('https://github.com/', '')}**", "",
                       table(["Weights", "Mean evidence commits", "Mean Jaccard vs default"],
                             [[k, v["mean_evidence"], v["mean_jaccard_vs_default"]] for k, v in r["sensitivity"].items()]), ""]
    recs = [p for r in ok for p in r.get("reconstructions", [])]
    if recs:
        attempts = [p["reconstructed"]["validation"].get("attempts", 0) for p in recs]
        flagged = sum(1 for p in recs if p["reconstructed"]["validation"].get("unsupported_mentions"))
        fallback = sum(1 for p in recs if p["reconstructed"].get("fallback"))
        md += ["## Reconstruction (LLM) — automatic checks", "",
               f"{len(recs)} matched decisions reconstructed. Validator retries needed: "
               f"{sum(1 for a in attempts if a > 1)}/{len(recs)}; records with unsupported mentions flagged: {flagged}; "
               f"fallbacks (no usable synthesis): {fallback}. Cited commits outside the evidence remaining after "
               f"validation: 0 by construction (they are removed or trigger a retry).", "",
               "Human scores (accuracy, completeness, hallucination) go in `adr_rubric.md`.", ""]
        with open(os.path.join(RESULTS, "adr_rubric.md"), "w", encoding="utf-8") as f:
            f.write(rubric(ok))
    else:
        md += ["## Reconstruction (LLM)", "", "_Not run in this report (use `--synthesize`)._", ""]
    md += ["## Limits", "",
           "- Only decisions that leave a trace in code history are detectable (dependency, infrastructure, structure, "
           "rule changes). ADRs about process, documentation or UI conventions have no such trace.",
           "- Topic matching uses title words, so a correct detection described with different words counts as a miss."]
    print(write_report("adr", "\n".join(md), {"results": results}))


if __name__ == "__main__":
    main()
