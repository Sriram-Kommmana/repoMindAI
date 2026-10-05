"""Repository Q&A evaluation.

Part A (offline, no LLM): intent-routing accuracy on a hand-labelled set of
questions phrased in different ways.

Part B (live): for each repository, questions are generated from templates
with ground truth taken directly from the graph and the git history, asked
through /ask, and scored on:
  - correctness: list answers by entity precision/recall (correct when both
    are >= 0.8), single facts by containment;
  - citation validity: every file, function or commit the answer cites must
    exist AND appear in that answer's own recorded tool results;
  - routing: whether the template's intent was among the routed intents.

Usage: python eval/eval_qa.py [--no-live] [repo_url_or_path ...]
"""
import argparse
import os
import re
import tempfile

from common import table, write_report

import qa_engine
from agents.qa_graph import route_intents

# ------------------------------------------------------------------ part A

ROUTING_SET = [
    ("What does src/app.py do?", "structural"),
    ("Which modules import the database module?", "structural"),
    ("Where is the login function defined?", "structural"),
    ("List the classes in models.py", "structural"),
    ("What functions does the user service expose?", "structural"),
    ("Show me the code for handle_request", "structural"),
    ("Which files would break if I change utils.py?", "structural"),
    ("What is the entry point of this app?", "structural"),
    ("How many functions are in the repository?", "structural"),
    ("How is the code organized into folders?", "structural"),
    ("Are there any layering violations?", "architectural"),
    ("What is the architecture health score?", "architectural"),
    ("Does any controller talk to the database directly?", "architectural"),
    ("Is the separation of concerns respected?", "architectural"),
    ("Which rules are being broken?", "architectural"),
    ("Is there tight coupling between modules?", "architectural"),
    ("Does the service layer get bypassed anywhere?", "architectural"),
    ("How clean is the design of this project?", "architectural"),
    ("Who wrote auth.py?", "historical"),
    ("When was the cache module added?", "historical"),
    ("What changed recently?", "historical"),
    ("Who are the main contributors?", "historical"),
    ("How many commits touched the controller?", "historical"),
    ("Show me the history of database.py", "historical"),
    ("What did commit 1a2b3c4 change?", "historical"),
    ("How did the number of modules evolve over time?", "historical"),
    ("Who last modified the routes?", "historical"),
    ("How has the architecture health changed over time?", "historical"),
    ("Why was Redis introduced?", "rationale"),
    ("Why did they choose Express?", "rationale"),
    ("What was the reasoning behind adding Docker?", "rationale"),
    ("Why does the project use joi instead of @hapi/joi?", "rationale"),
    ("What motivated the switch to TypeScript?", "rationale"),
    ("What trade-offs led to splitting the services folder?", "rationale"),
    ("Explain the decision to adopt Alembic.", "rationale"),
    ("What were the major architectural decisions?", "rationale"),
    ("Why is there a repositories layer?", "rationale"),
    ("What is the rationale for using environment variables for config?", "rationale"),
]


def routing_accuracy() -> dict:
    rows, hits, exact = [], 0, 0
    for question, expected in ROUTING_SET:
        routed = route_intents(question)
        hit = expected in routed
        hits += hit
        exact += routed == [expected]
        rows.append({"question": question, "expected": expected, "routed": routed, "hit": hit})
    n = len(ROUTING_SET)
    return {"n": n, "accuracy": round(hits / n, 3), "exact": round(exact / n, 3),
            "misses": [r for r in rows if not r["hit"]], "rows": rows}


# ------------------------------------------------------------------ part B: ground truth

def ground_truth(session, analysis: dict) -> list:
    """Template questions for the analyzed repository, with answers from the graph."""
    qs = []
    run = lambda query, **kw: session.run(query, **kw).data()
    modules = {r["p"] for r in run("MATCH (m:Module) RETURN m.path AS p")}

    top = run("MATCH (m:Module)<-[:IMPORTS]-(x:Module) RETURN m.path AS m, collect(x.path) AS importers "
              "ORDER BY size(importers) DESC, m LIMIT 1")
    if top:
        qs.append({"intent": "structural", "kind": "set", "question": f"Which modules import `{top[0]['m']}`?",
                   "expected": set(top[0]["importers"]), "subject": top[0]["m"]})
    fan_out = run("MATCH (m:Module)-[:IMPORTS]->(x:Module) WITH m, collect(x.path) AS deps WHERE size(deps) >= 2 "
                  "RETURN m.path AS m, deps ORDER BY size(deps) DESC, m LIMIT 1")
    if fan_out:
        qs.append({"intent": "structural", "kind": "set", "question": f"Which modules does `{fan_out[0]['m']}` import?",
                   "expected": set(fan_out[0]["deps"]), "subject": fan_out[0]["m"]})
    called = run("MATCH (f:Function)<-[:CALLS]-(g:Function) WITH f, collect(DISTINCT g.name) AS callers "
                 "RETURN f.name AS f, f.module_path AS m, callers ORDER BY size(callers) DESC, f LIMIT 1")
    if called:
        qs.append({"intent": "structural", "kind": "names",
                   "question": f"Which functions call `{called[0]['f']}` (defined in `{called[0]['m']}`)?",
                   "expected": set(called[0]["callers"]), "subject": called[0]["f"]})

    violators = {v["caller"].split("::")[0] for v in analysis["violations"]}
    qs.append({"intent": "architectural", "kind": "set" if violators else "none",
               "question": "Are there any architecture violations? List the modules that contain them.",
               "expected": violators, "subject": None})
    health = analysis["health_score"]
    qs.append({"intent": "architectural", "kind": "number", "question": "What is the current architecture health score?",
               "expected": health, "subject": None})

    authors = run("MATCH (d:Developer)-[:AUTHORED]->(c:Commit) RETURN d.name AS name, count(c) AS n "
                  "ORDER BY n DESC, name LIMIT 1")
    if authors:
        qs.append({"intent": "historical", "kind": "text", "question": "Who has made the most commits?",
                   "expected": authors[0]["name"], "subject": None})
    busiest = run("MATCH (c:Commit)-[:MODIFIED]->(m:Module) WITH m, count(c) AS n "
                  "RETURN m.path AS p, n ORDER BY n DESC, p LIMIT 1")
    if busiest:
        p = busiest[0]["p"]
        qs.append({"intent": "historical", "kind": "number", "question": f"How many commits changed `{p}`?",
                   "expected": busiest[0]["n"], "subject": p})
        last = run("MATCH (d:Developer)-[:AUTHORED]->(c:Commit)-[:MODIFIED]->(:Module {path: $p}) "
                   "RETURN d.name AS who, c.short AS short ORDER BY c.timestamp DESC LIMIT 1", p=p)[0]
        qs.append({"intent": "historical", "kind": "text", "question": f"Who last changed `{p}`, and in which commit?",
                   "expected": last["short"], "subject": p, "also": last["who"]})
    intro = run("MATCH (m:Module) WHERE m.introduced_at IS NOT NULL RETURN m.path AS p, m.introduced_at AS at "
                "ORDER BY m.introduced_at DESC, p LIMIT 1")
    if intro:
        qs.append({"intent": "historical", "kind": "text", "question": f"When was `{intro[0]['p']}` first added?",
                   "expected": intro[0]["at"][:10], "subject": intro[0]["p"]})

    decisions = analysis.get("_decisions") or []
    dep = next((d for d in decisions if d["kind"] in ("dependency_change", "dependency_replace") and d["packages"]), None)
    if dep:
        qs.append({"intent": "rationale", "kind": "cites", "question": f"Why was {dep['packages'][0]} adopted?",
                   "expected": dep["short"], "subject": dep["packages"][0]})
    elif decisions:
        qs.append({"intent": "rationale", "kind": "cites",
                   "question": f"Why was this decision made: {decisions[0]['subject']}?",
                   "expected": decisions[0]["short"], "subject": None})
    for q in qs:
        q["modules"] = modules
    return qs


# ------------------------------------------------------------------ part B: scoring

_BACKTICK = re.compile(r"`([^`\n]{2,200})`")
_HEX = re.compile(r"\b([0-9a-f]{7,12})\b")
_NUM = re.compile(r"\d+(?:\.\d+)?")


def mentioned_paths(answer: str, modules: set) -> set:
    found = {m for m in modules if m in answer}
    basenames = {}
    for m in modules:
        basenames.setdefault(os.path.basename(m), []).append(m)
    for token in _BACKTICK.findall(answer):
        token = token.split(":")[0].strip()
        if token in basenames and len(basenames[token]) == 1:
            found.add(basenames[token][0])
    return found


def score(q: dict, answer: str) -> dict:
    lower = answer.lower()
    if q["kind"] in ("set", "names"):
        if q["kind"] == "set":
            got = mentioned_paths(answer, q["modules"]) - {q["subject"]}
        else:
            got = {n for n in q["expected"] | set(re.findall(r"\b[A-Za-z_]\w+\b", answer)) if re.search(rf"\b{re.escape(n)}\b", answer)}
            got &= q["expected"] | {n for n in re.findall(r"`([A-Za-z_]\w*)`", answer)}
        expected = q["expected"]
        tp = len(got & expected)
        precision = tp / len(got) if got else (1.0 if not expected else 0.0)
        recall = tp / len(expected) if expected else 1.0
        return {"precision": round(precision, 3), "recall": round(recall, 3), "correct": precision >= 0.8 and recall >= 0.8}
    if q["kind"] == "none":
        says_none = bool(re.search(r"\b(no|zero|none|0)\b[^.]*\bviolation", lower) or "no violations" in lower)
        return {"correct": says_none}
    if q["kind"] == "number":
        if q["expected"] is None:
            return {"correct": bool(re.search(r"not (be )?scored|n/?a|cannot be|no rule", lower))}
        values = {float(x) for x in _NUM.findall(answer)}
        return {"correct": any(abs(v - float(q["expected"])) < 0.051 for v in values)}
    if q["kind"] == "text":
        ok = str(q["expected"]).lower() in lower
        if q.get("also"):
            ok = ok and q["also"].lower() in lower
        return {"correct": ok}
    cited = q["expected"].lower() in lower
    hedged = bool(re.search(r"infer|likely|appears|suggest|probabl|reconstruct", lower))
    return {"correct": cited and hedged, "cited_decision_commit": cited, "marked_as_inferred": hedged}


def citation_validity(answer: str, tool_text: str, modules: set, commits: set, functions: set) -> dict:
    tokens = set(_BACKTICK.findall(answer)) | set(_HEX.findall(answer.lower()))
    checked, valid = 0, 0
    for token in tokens:
        token = token.strip()
        base = token.split("::")[0].split(":L")[0]
        kind = None
        if "::" in token or base in modules or re.search(r"\.(py|js|jsx|ts|tsx)$", base):
            kind = "path"
        elif re.fullmatch(r"[0-9a-f]{7,12}", token.lower()):
            kind = "commit"
        elif token in functions:
            kind = "function"
        if not kind:
            continue
        checked += 1
        exists = (base in modules) if kind == "path" else (token.lower()[:7] in commits) if kind == "commit" else True
        seen = base in tool_text or token.lower()[:7] in tool_text.lower()
        valid += exists and seen
    return {"checked": checked, "valid": valid}


def run_live(client, target: str) -> dict:
    from agents.adr_graph import decisions_for
    import workspace

    resp = client.post("/analyze", json={"repo_url": target})
    resp.raise_for_status()
    analysis = resp.json()
    with workspace.use(analysis["analysis_id"]) as ws:
        analysis["_decisions"] = decisions_for(ws)
    session = qa_engine.shared_driver().session()
    try:
        questions = ground_truth(session, analysis)
        commits = {r["s"] for r in session.run("MATCH (c:Commit) RETURN c.short AS s").data()}
        functions = {r["n"] for r in session.run("MATCH (f:Function) RETURN DISTINCT f.name AS n").data()}
    finally:
        session.close()

    results = []
    original = qa_engine._run_tool
    for q in questions:
        recorded = []

        def recording(session, sources, name, raw_args, _orig=original, _rec=recorded):
            text, args, summary = _orig(session, sources, name, raw_args)
            _rec.append(text)
            return text, args, summary
        qa_engine._run_tool = recording
        try:
            answer = client.post("/ask", json={"question": q["question"]}).json()
        finally:
            qa_engine._run_tool = original
        if answer.get("error"):
            results.append({"question": q["question"], "intent": q["intent"], "error": answer["error"], "correct": False})
            continue
        s = score(q, answer["answer"])
        cites = citation_validity(answer["answer"], "\n".join(recorded), q["modules"], commits, functions)
        results.append({"question": q["question"], "intent": q["intent"], "routed": answer["intents"],
                        "routed_ok": q["intent"] in answer["intents"], "tools": [e["tool"] for e in answer["evidence"]],
                        **s, **{f"citations_{k}": v for k, v in cites.items()}, "answer": answer["answer"]})
        print(f"  [{'OK ' if s['correct'] else 'BAD'}] {q['question']}")
    return {"target": target, "results": results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-live", action="store_true")
    ap.add_argument("targets", nargs="*")
    args = ap.parse_args()

    routing = routing_accuracy()
    print(f"routing accuracy {routing['accuracy']} (exact {routing['exact']}) on {routing['n']} questions")

    live = []
    if not args.no_live:
        from fastapi.testclient import TestClient
        from fixtures.make_history_repo import make_history_repo
        import server
        os.environ["REPOMIND_ALLOW_LOCAL_REPOS"] = "1"
        targets = args.targets or [make_history_repo(os.path.join(tempfile.mkdtemp(prefix="repomind_evalqa_"), "repo")),
                                   "https://github.com/hagopj13/node-express-boilerplate",
                                   "https://github.com/nsidnev/fastapi-realworld-example-app"]
        with TestClient(server.app) as client:
            for target in targets:
                print(target)
                live.append(run_live(client, target))

    md = ["# Repository Q&A evaluation", "", "## A. Intent routing (offline)", "",
          f"{routing['n']} hand-labelled questions. A question counts as routed correctly when its labelled intent is "
          f"among the routed intents (the router may add more, which only widens the tools offered).", "",
          f"**Routing accuracy: {routing['accuracy']}** (exactly one intent and the right one: {routing['exact']}).", "",
          "This set was used while developing the router (it surfaced two keyword gaps, 'directly' and 'reasoning', "
          "which were fixed), so it is a development-set score, not a held-out one.", ""]
    if routing["misses"]:
        md += ["Misrouted:", "", table(["Question", "Expected", "Routed"],
                                       [[m["question"], m["expected"], ", ".join(m["routed"])] for m in routing["misses"]]), ""]
    rows_all = [r for t in live for r in t["results"]]
    if live:
        by_intent = {}
        for r in rows_all:
            b = by_intent.setdefault(r["intent"], {"n": 0, "correct": 0, "routed": 0, "checked": 0, "valid": 0})
            b["n"] += 1
            b["correct"] += r.get("correct", False)
            b["routed"] += r.get("routed_ok", False)
            b["checked"] += r.get("citations_checked", 0)
            b["valid"] += r.get("citations_valid", 0)
        total = {k: sum(b[k] for b in by_intent.values()) for k in ("n", "correct", "routed", "checked", "valid")}
        pct = lambda a, b: f"{a}/{b} ({round(100 * a / b)}%)" if b else "–"
        md += ["## B. Live answers with graph and git ground truth", "",
               "Questions are generated per repository from templates; the expected answers come from Cypher queries "
               "on the graph and from the mined history, not from the model. Citations count as valid only if the cited "
               "file, function or commit exists and appears in that answer's own tool results.", "",
               table(["Intent", "Questions", "Correct", "Routed correctly", "Valid citations"],
                     [[i, b["n"], pct(b["correct"], b["n"]), pct(b["routed"], b["n"]), pct(b["valid"], b["checked"])]
                      for i, b in sorted(by_intent.items())]
                     + [["**All**", total["n"], pct(total["correct"], total["n"]), pct(total["routed"], total["n"]),
                         pct(total["valid"], total["checked"])]]), ""]
        for t in live:
            md += [f"### {t['target'] if t['target'].startswith('http') else 'scripted history fixture'}", "",
                   table(["Question", "Intent", "Correct", "Precision", "Recall", "Citations valid"],
                         [[r["question"], r["intent"], "yes" if r.get("correct") else ("error" if r.get("error") else "no"),
                           r.get("precision", ""), r.get("recall", ""),
                           f"{r.get('citations_valid', 0)}/{r.get('citations_checked', 0)}"] for r in t["results"]]), ""]
        md += ["Single runs at temperature 0.2; answers can vary between runs. Full answers are in `qa.json`."]
    print(write_report("qa", "\n".join(md), {"routing": routing, "live": [
        {**t, "results": [{k: v for k, v in r.items()} for r in t["results"]]} for t in live]}))


if __name__ == "__main__":
    main()
