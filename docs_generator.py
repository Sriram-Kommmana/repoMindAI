"""RepoMind AI — Phase 8: map-reduce LLM-generated documentation (via Groq).

Deterministic-before-generative: every FACT fed to or produced for this
document (modules, classes, functions, layers, relationships, violations,
health score) comes from the already-verified parse/graph/rule-engine
output. The LLM only ever writes descriptive prose on top of those facts —
it never decides what a violation is, and as of this rewrite it is no
longer even asked to reproduce the violations list or the import/call
graph verbatim (see _build_known_issues_section /
_build_relationships_section) — those are now pure Python templating,
zero LLM involvement, zero risk of omission or paraphrase.

LLM access (provider choice, key rotation, deadlines, retries) lives in
llm.py; this module only builds prompts and assembles the document.

Architecture history: the original design sent one prompt covering the
WHOLE repo's structural summary plus a handful of "important" files' raw
source, hard-capped to fit one model call. For any repo bigger than a
small demo fixture this meant most files got no real source coverage, and
large enough repos even had their structural summary truncated — some
modules never appeared in the prompt at all. This module now does
map-reduce instead: modules are grouped (grouping.group_modules — the same
precedence already verified for the Mermaid diagram: layer_type, then
folder, then a flat root bucket), each group is described in its own
LLM call (map), and a final call synthesizes an Overview/Architecture
narrative from the per-group results (reduce). Every module is covered by
construction — nothing is dropped for losing a relevance ranking. Small
repos (the common demo case) take a single-call fast path equivalent in
cost to the old design. Every per-call failure (map or reduce) degrades to
a clearly-marked deterministic fallback rather than failing the whole
document — see `generate_documentation`'s docstring for the full contract.

Map batches run concurrently up to llm.parallelism("docs"): one per Groq key
(each key has its own rate-limit budget, and each batch is pinned to its own
key so concurrent calls never collide), or BEDROCK_MAX_CONCURRENCY on
Bedrock.
"""
import concurrent.futures
import os
import time
from collections import OrderedDict

import llm
from grouping import group_modules

# --- Chunking ---
MAP_MAX_MODULES_PER_BATCH = 10
# Cost/rate-limit ceiling on total LLM calls one analysis can trigger — NOT
# a time cap (the app intentionally has no wall-clock budget; a large repo
# may take however long it takes). Bounds how much of the account's shared
# per-day request budget one analysis can consume.
MAX_TOTAL_MAP_CALLS = 40
# Two concurrent calls on ONE Groq key can each fit its ~8,000 TPM budget and
# still blow it together (observed on a real 13-group repo), so concurrency
# never exceeds llm.parallelism("docs"), and is capped here regardless.
MAP_MAX_CONCURRENCY_CAP = 5

# --- Map phase (one call per batch of up to MAP_MAX_MODULES_PER_BATCH modules) ---
MAP_MAX_CHARS_PER_FILE = 2000
MAP_MAX_TOTAL_SOURCE_CHARS_PER_BATCH = 10000
MAP_STRUCTURAL_BUDGET_CHARS_PER_BATCH = 3000
MAP_MAX_PROMPT_CHARS = 6000  # trimmed further to make room for more
                              # output budget below without raising total
                              # per-call tokens much — see MAP_MAX_OUTPUT_TOKENS
MAP_MAX_OUTPUT_TOKENS = 1600  # raised from 1000: observed real mid-sentence
                               # cutoffs on content-dense files (multiple
                               # classes/methods per file) — a batch of up
                               # to 10 such files needs real headroom to
                               # finish every file it starts describing
MAP_MAX_CALL_EDGES = 30

# --- Reduce phase (one final call synthesizing all map results) ---
REDUCE_MAX_INPUT_CHARS = 5000
REDUCE_MAX_OUTPUT_TOKENS = 1500  # raised from 900: observed the reduce call
                                   # itself cut off mid-sentence on a
                                   # 13-group repo — more groups to
                                   # summarize needs more output room
REDUCE_MAX_GROUPS_WITH_DETAIL = 15

# --- Fast path for small repos (single call, no map/reduce) ---
SINGLE_CALL_MAX_CHARS_PER_FILE = 2500
SINGLE_CALL_MAX_TOTAL_SOURCE_CHARS = 16000
SINGLE_CALL_MAX_STRUCTURAL_CHARS = 6000
SINGLE_CALL_MAX_PROMPT_CHARS = 16000
SINGLE_CALL_MAX_OUTPUT_TOKENS = 1500
SINGLE_CALL_MAX_CALL_EDGES = 60

_GROUNDING_RULES = """- Only describe files, classes, functions, and relationships that appear in the evidence given to you. Do not invent files, functions, parameters, or behavior you cannot see.
- Describe ONLY the files explicitly listed in the structural evidence given to you in THIS request. If a file you're describing imports or references another file that is NOT in your given evidence (you may see its path in an import statement), do not describe, summarize, or guess at that other file's contents — it belongs to a different part of the document, already handled separately. Mentioning that an import exists is fine; describing what the imported file itself does is not.
- If source isn't available for a file, describe it only using its structural evidence (classes, function signatures) and do not guess at its internal behavior.
- If you are uncertain about something, say so explicitly rather than guessing.
- Write plain GitHub-flavored Markdown only. Do not use LaTeX or math notation (no `$...$`, `\\rightarrow`, or similar) — for a relationship, write plain text like "A -> B".
- You have a limited response budget. Be concise per file/section rather than exhaustive, so you finish every item with a complete sentence. If you are running low on space, wrap up your CURRENT file/section with a complete thought and stop — never start describing a new file or section you won't have room to finish."""

_MAP_SYSTEM_INSTRUCTION = f"""You are writing ONE section of a larger technical documentation document — the module-by-module description for a single group of related files from a software repository.

Everything under "STRUCTURAL EVIDENCE" was extracted deterministically by static analysis (Tree-sitter AST parsing) and a Neo4j knowledge graph — treat it as ground truth. Everything under "SOURCE EXCERPTS" is real source code read directly from the repo, possibly truncated for length.

{_GROUNDING_RULES}
- Use "####" (four hashes) as the heading level for each individual file you describe — never "##" or "###", those are reserved for the surrounding document's own structure.
- Do NOT include an overall title or heading for this group as a whole — only per-file "####" headings.
- Cover every file listed in the structural evidence, even briefly if source isn't available for it. Do not skip any.
- Do not write an introduction, conclusion, or summary — only the per-file descriptions.
"""

_REDUCE_SYSTEM_INSTRUCTION = """You are writing the opening sections of a technical documentation document for a software repository, based on per-group summaries a separate process has already written.

Everything under "REPO-WIDE FACTS" is deterministic structural data. Everything under "GROUP SUMMARIES" is condensed prose already written about each group of files — some groups may be marked "structural listing only" if a detailed description wasn't available; treat that as a known, acceptable gap, not something to apologize for or dwell on.

- Ground every claim in the facts and group summaries given to you. Do not invent files, modules, or architecture you have not been given evidence for.
- Write plain GitHub-flavored Markdown only. No LaTeX or math notation.
- Output exactly two sections, in this order: "## Overview" (a few sentences on what this repository is and how it's organized) and "## Architecture & Layers" (the major groups/layers and how they relate, drawing on the group summaries).
- Do not repeat per-file details already covered elsewhere — stay at a higher level.
- Do not include a "Known Architecture Issues" or "Key Relationships" section — those are handled elsewhere.
- You have a limited response budget. If you are running low on space while covering groups, prefer shorter mentions of remaining groups over leaving a sentence unfinished — always end on a complete thought.
"""

_SINGLE_CALL_SYSTEM_INSTRUCTION = f"""You are generating technical documentation for a software repository.

Everything under "STRUCTURAL EVIDENCE" below was extracted deterministically by static analysis (Tree-sitter AST parsing) and a Neo4j knowledge graph — treat it as ground truth. Everything under "SOURCE EXCERPTS" is real source code read directly from the repo, possibly truncated for length.

{_GROUNDING_RULES}

Output a single well-formed Markdown document with exactly these sections, in this order: ## Overview, ## Architecture & Layers, ## Module-by-Module Breakdown.
"""


def _qualified(class_name, name):
    return f"{class_name}.{name}" if class_name else name


def _health_text(health_score) -> str:
    if health_score is None:
        return "not scored (no layer-tagged dependencies for the rules to judge)"
    return f"{health_score} / 100"


def _group_display_name(group_key: str) -> str:
    if group_key.startswith("layer:"):
        return f"{group_key.split(':', 1)[1].capitalize()} Layer"
    if group_key.startswith("folder:"):
        return group_key.split(":", 1)[1]
    return "Other / Root-Level Files"


# --------------------------------------------------------------------------
# Deterministic sections — zero LLM involvement, used regardless of which
# generation path ran.
# --------------------------------------------------------------------------

def _build_known_issues_section(violations: list, health_score: float) -> str:
    lines = ["## Known Architecture Issues", "", f"**Architecture Health Score:** {_health_text(health_score)}", ""]
    if not violations:
        lines.append("No architecture violations were found.")
    else:
        lines.append("**Violations:**")
        for v in violations:
            lines.append(f'- [{v["rule"]}] severity={v["severity"]}: {v["caller"]} -> {v["callee"]}')
    return "\n".join(lines)


def _build_relationships_section(data: dict) -> str:
    lines = ["## Key Relationships & Dependencies", ""]
    if data["imports"]:
        lines.append("### Import Edges (module -> module)")
        for edge in sorted(data["imports"], key=lambda e: (e["from"], e["to"])):
            lines.append(f'- {edge["from"]} -> {edge["to"]}')
        lines.append("")
    if data["calls"]:
        lines.append("### Call Edges (function -> function)")
        for c in sorted(
            data["calls"],
            key=lambda c: (c["caller_module"], c["caller_name"], c["callee_module"], c["callee_name"]),
        ):
            caller = f'{c["caller_module"]}::{_qualified(c["caller_class"], c["caller_name"])}'
            callee = f'{c["callee_module"]}::{_qualified(c["callee_class"], c["callee_name"])}'
            lines.append(f"- {caller} -> {callee}")
        lines.append("")
    if not data["imports"] and not data["calls"]:
        lines.append("No import or call relationships were detected.")
    return "\n".join(lines).rstrip()


def _deterministic_module_listing(modules: list, data: dict) -> str:
    """Reuses the nesting logic from the structural summary, with no LLM
    involvement — used both when a map call fails and for groups that
    overflowed MAX_TOTAL_MAP_CALLS. Honestly marked, never mistaken for a
    real AI-written description."""
    module_paths = {m["path"] for m in modules}
    classes_by_module = {}
    for c in data["classes"]:
        if c["module_path"] in module_paths:
            classes_by_module.setdefault(c["module_path"], []).append(c["name"])
    functions_by_module = {}
    for f in data["functions"]:
        if f["module_path"] in module_paths:
            functions_by_module.setdefault(f["module_path"], []).append(
                _qualified(f["class_name"], f["name"])
            )

    lines = ["_Structural listing only — no AI-written description available for this section._", ""]
    for m in sorted(modules, key=lambda m: m["path"]):
        path = m["path"]
        lines.append(f"#### {path}")
        classes = sorted(classes_by_module.get(path, []))
        functions = sorted(functions_by_module.get(path, []))
        if classes:
            lines.append(f"- Classes: {', '.join(classes)}")
        if functions:
            lines.append(f"- Functions: {', '.join(functions)}")
        if not classes and not functions:
            lines.append("- (no classes or functions extracted)")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Batching
# --------------------------------------------------------------------------

def _batch_chunk(modules: list) -> list:
    modules_sorted = sorted(modules, key=lambda m: m["path"])
    return [
        modules_sorted[i:i + MAP_MAX_MODULES_PER_BATCH]
        for i in range(0, len(modules_sorted), MAP_MAX_MODULES_PER_BATCH)
    ]


def _plan_batches(groups: "OrderedDict[str, list]"):
    """Returns (kept, structural_only). `kept` is an ordered list of
    {"group_key", "modules"} batches, capped at MAX_TOTAL_MAP_CALLS total.
    `structural_only` is an OrderedDict of group_key -> modules for
    anything beyond that cap — never silently dropped."""
    kept = []
    structural_only = OrderedDict()
    total = 0
    for group_key, modules in groups.items():
        for batch_modules in _batch_chunk(modules):
            if total < MAX_TOTAL_MAP_CALLS:
                kept.append({"group_key": group_key, "modules": batch_modules})
                total += 1
            else:
                structural_only.setdefault(group_key, []).extend(batch_modules)
    return kept, structural_only


# --------------------------------------------------------------------------
# Shared prompt-building helpers (used by map, reduce, and the fast path)
# --------------------------------------------------------------------------

def _build_group_structural_summary(modules: list, data: dict, budget_chars: int, max_call_edges: int) -> str:
    module_paths = {m["path"] for m in modules}
    classes_by_module = {}
    for c in data["classes"]:
        if c["module_path"] in module_paths:
            classes_by_module.setdefault(c["module_path"], []).append(c["name"])
    functions_by_module = {}
    for f in data["functions"]:
        if f["module_path"] in module_paths:
            functions_by_module.setdefault(f["module_path"], []).append(
                _qualified(f["class_name"], f["name"])
            )

    lines = ["## Modules"]
    for m in sorted(modules, key=lambda m: m["path"]):
        path = m["path"]
        layer = f' (layer: {m["layer_type"]})' if m.get("layer_type") else ""
        lines.append(f'- {path} [{m["language"]}]{layer}')
        for cls in sorted(classes_by_module.get(path, [])):
            lines.append(f"    - class {cls}")
        for fn in sorted(functions_by_module.get(path, [])):
            lines.append(f"    - function {fn}")

    relevant_imports = [e for e in data["imports"] if e["from"] in module_paths or e["to"] in module_paths]
    if relevant_imports:
        lines.append("\n## Import edges (module -> module)")
        for edge in sorted(relevant_imports, key=lambda e: (e["from"], e["to"])):
            lines.append(f'- {edge["from"]} -> {edge["to"]}')

    relevant_calls = [
        c for c in data["calls"]
        if c["caller_module"] in module_paths or c["callee_module"] in module_paths
    ]
    if relevant_calls:
        sorted_calls = sorted(
            relevant_calls,
            key=lambda c: (c["caller_module"], c["caller_name"], c["callee_module"], c["callee_name"]),
        )
        lines.append("\n## Call edges (function -> function)")
        for c in sorted_calls[:max_call_edges]:
            caller = f'{c["caller_module"]}::{_qualified(c["caller_class"], c["caller_name"])}'
            callee = f'{c["callee_module"]}::{_qualified(c["callee_class"], c["callee_name"])}'
            lines.append(f"- {caller} -> {callee}")
        if len(sorted_calls) > max_call_edges:
            lines.append(f"... ({len(sorted_calls) - max_call_edges} more call edges omitted)")

    summary = "\n".join(lines)
    if len(summary) > budget_chars:
        summary = summary[:budget_chars] + "\n... [additional structural detail truncated]"
    return summary


def _collect_source_excerpts(repo_path: str, paths: list, max_chars_per_file: int, max_total_chars: int) -> str:
    blocks = []
    total = 0
    for rel_path in paths:
        if total >= max_total_chars:
            break
        abs_path = os.path.join(repo_path, rel_path)
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue

        remaining_budget = max_total_chars - total
        cap = min(max_chars_per_file, remaining_budget)
        truncated = len(content) > cap
        content = content[:cap]
        total += len(content)

        suffix = "\n... [truncated]" if truncated else ""
        blocks.append(f"### {rel_path}\n```\n{content}{suffix}\n```")

    return "\n\n".join(blocks)


def _build_prompt(structural_summary: str, source_excerpts: str, max_prompt_chars: int,
                   system_instruction: str, label: str = None) -> tuple:
    def _assemble(excerpts):
        prefix = f"GROUP: {label}\n\n" if label else ""
        return (
            f"{prefix}"
            "STRUCTURAL EVIDENCE\n\n"
            f"{structural_summary}\n\n"
            "SOURCE EXCERPTS\n\n"
            f"{excerpts if excerpts else '(no source excerpts available)'}"
        )

    user_content = _assemble(source_excerpts)
    if len(user_content) > max_prompt_chars:
        overhead = len(_assemble(""))
        budget = max(0, max_prompt_chars - overhead)
        trimmed = source_excerpts[:budget] + "\n... [source excerpts truncated to fit model limits]"
        user_content = _assemble(trimmed)
    return system_instruction, user_content


# --------------------------------------------------------------------------
# LLM call
# --------------------------------------------------------------------------

def _complete(system_instruction: str, user_content: str, max_tokens: int, key_slot=None) -> str:
    result = llm.chat(
        [{"role": "system", "content": system_instruction}, {"role": "user", "content": user_content}],
        purpose="docs", max_tokens=max_tokens, key_slot=key_slot,
    )
    if not result.content:
        raise ValueError("the model returned an empty response")
    return result.content


# --------------------------------------------------------------------------
# Map phase
# --------------------------------------------------------------------------

def _generate_batch_section(key_slot: int, group_key: str, modules: list, data: dict, repo_path: str) -> dict:
    """One map call. NEVER raises."""
    module_paths = [m["path"] for m in modules]
    try:
        structural_summary = _build_group_structural_summary(
            modules, data, MAP_STRUCTURAL_BUDGET_CHARS_PER_BATCH, MAP_MAX_CALL_EDGES
        )
        paths = sorted(m["path"] for m in modules)
        source_excerpts = _collect_source_excerpts(
            repo_path, paths, MAP_MAX_CHARS_PER_FILE, MAP_MAX_TOTAL_SOURCE_CHARS_PER_BATCH
        )
        system_instruction, user_content = _build_prompt(
            structural_summary, source_excerpts, MAP_MAX_PROMPT_CHARS,
            _MAP_SYSTEM_INSTRUCTION, label=_group_display_name(group_key),
        )
        markdown = _complete(system_instruction, user_content, MAP_MAX_OUTPUT_TOKENS, key_slot=key_slot)
        return {"group_key": group_key, "status": "ok", "markdown": markdown, "error": None, "module_paths": module_paths}
    except Exception as exc:
        return {
            "group_key": group_key, "status": "error", "markdown": None,
            "error": str(exc) or type(exc).__name__, "module_paths": module_paths,
        }


def _run_map_phase(kept: list, data: dict, repo_path: str, max_workers: int) -> list:
    """Runs all kept batches with `max_workers` concurrent workers, keeping
    the deterministic batch order in the result. Batch i is pinned to key
    slot i: with max_workers <= the number of keys, no two concurrent
    batches share a key's rate limit. `with ... as pool:` is fine here —
    each call's own deadline is enforced inside llm.chat."""
    results = [None] * len(kept)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_index = {
            pool.submit(_generate_batch_section, i, b["group_key"], b["modules"], data, repo_path): i
            for i, b in enumerate(kept)
        }
        for future in concurrent.futures.as_completed(future_to_index):
            results[future_to_index[future]] = future.result()
    return results


# --------------------------------------------------------------------------
# Reduce phase
# --------------------------------------------------------------------------

def _build_reduce_input(batch_results: list, structural_only: "OrderedDict[str, list]",
                         groups: "OrderedDict[str, list]", data: dict, health_score: float) -> str:
    batches_by_group = OrderedDict()
    for r in batch_results:
        batches_by_group.setdefault(r["group_key"], []).append(r)

    group_entries = []
    for group_key, modules in groups.items():
        display = _group_display_name(group_key)
        oks = [r for r in batches_by_group.get(group_key, []) if r["status"] == "ok"]
        gist = " ".join(r["markdown"].strip() for r in oks) if oks else None
        group_entries.append((display, len(modules), gist))

    lines = [
        f"Total modules: {len(data['modules'])}",
        f"Total groups: {len(groups)}",
        f"Architecture Health Score: {_health_text(health_score)}",
        "",
        "GROUP SUMMARIES",
    ]

    detailed = group_entries[:REDUCE_MAX_GROUPS_WITH_DETAIL]
    overflow = group_entries[REDUCE_MAX_GROUPS_WITH_DETAIL:]

    per_group_budget = REDUCE_MAX_INPUT_CHARS // max(1, len(detailed))
    for display, count, gist in detailed:
        if gist:
            lines.append(f"- {display} ({count} files): {gist[:per_group_budget]}")
        else:
            lines.append(f"- {display} ({count} files): [structural listing only, no prose summary available]")

    for display, count, _gist in overflow:
        lines.append(f"- {display} ({count} files)")

    return "\n".join(lines)


def _reduce(reduce_input: str) -> dict:
    """NEVER raises."""
    try:
        markdown = _complete(_REDUCE_SYSTEM_INSTRUCTION, reduce_input, REDUCE_MAX_OUTPUT_TOKENS)
        return {"status": "ok", "markdown": markdown, "error": None}
    except Exception as exc:
        return {"status": "error", "markdown": None, "error": str(exc) or type(exc).__name__}


def _deterministic_overview_fallback(data: dict, health_score: float, groups: "OrderedDict[str, list]") -> str:
    lines = [
        "## Overview", "",
        f"This repository contains {len(data['modules'])} files across {len(groups)} groups. "
        f"Architecture health score: {_health_text(health_score)}. See the Module-by-Module Breakdown "
        "below for per-file detail.",
        "", "## Architecture & Layers", "",
    ]
    for group_key, modules in groups.items():
        lines.append(f"- {_group_display_name(group_key)} ({len(modules)} files)")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Final assembly
# --------------------------------------------------------------------------

def _assemble_document(reduce_markdown: str, batch_results: list, structural_only: "OrderedDict[str, list]",
                        groups: "OrderedDict[str, list]", data: dict, violations: list, health_score: float) -> str:
    parts = [reduce_markdown.strip(), "", "## Module-by-Module Breakdown", ""]

    batches_by_group = OrderedDict()
    for r in batch_results:
        batches_by_group.setdefault(r["group_key"], []).append(r)

    for group_key, group_modules_list in groups.items():
        parts.append(f"### {_group_display_name(group_key)}")
        parts.append("")
        for r in batches_by_group.get(group_key, []):
            if r["status"] == "ok":
                parts.append(r["markdown"].strip())
            else:
                batch_modules = [m for m in group_modules_list if m["path"] in r["module_paths"]]
                parts.append(_deterministic_module_listing(batch_modules, data))
            parts.append("")
        if group_key in structural_only:
            parts.append(_deterministic_module_listing(structural_only[group_key], data))
            parts.append("")

    parts.append(_build_relationships_section(data))
    parts.append("")
    parts.append(_build_known_issues_section(violations, health_score))

    return "\n".join(parts)


# --------------------------------------------------------------------------
# Fast path (small repos — single call, no map/reduce)
# --------------------------------------------------------------------------

def _generate_single_call(modules: list, data: dict, repo_path: str) -> str:
    structural_summary = _build_group_structural_summary(
        modules, data, SINGLE_CALL_MAX_STRUCTURAL_CHARS, SINGLE_CALL_MAX_CALL_EDGES
    )
    paths = sorted(m["path"] for m in modules)
    source_excerpts = _collect_source_excerpts(
        repo_path, paths, SINGLE_CALL_MAX_CHARS_PER_FILE, SINGLE_CALL_MAX_TOTAL_SOURCE_CHARS
    )
    system_instruction, user_content = _build_prompt(
        structural_summary, source_excerpts, SINGLE_CALL_MAX_PROMPT_CHARS, _SINGLE_CALL_SYSTEM_INSTRUCTION
    )
    return _complete(system_instruction, user_content, SINGLE_CALL_MAX_OUTPUT_TOKENS)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def generate_documentation(repo_path: str, data: dict, violations: list, health_score: float) -> dict:
    """Orchestrates chunking + map + reduce (or the single-call fast path
    for small repos) into a complete documentation Markdown string.

    Returns:
        {
          "markdown": str,        # always non-empty if this returns at all
          "warnings": list[str],  # empty == fully AI-generated, no degradation
          "stats": {...},         # counts, for logging/debugging
        }

    Raises ONLY for setup-time failures where no output is possible at all
    (no LLM provider configured). Every per-batch or reduce-call failure
    degrades into `warnings` instead of propagating — "some documentation"
    beats "no documentation field".
    """
    provider = llm.describe("docs")  # raises LLMConfigError if no key is configured

    start = time.time()
    groups = group_modules(data["modules"])
    kept, structural_only = _plan_batches(groups)
    warnings = []

    if len(kept) <= 1 and not structural_only:
        modules = kept[0]["modules"] if kept else []
        try:
            body_markdown = _generate_single_call(modules, data, repo_path)
        except Exception as exc:
            body_markdown = (
                f"## Overview\n\nThis repository contains {len(data['modules'])} files. "
                f"Architecture health score: {_health_text(health_score)}.\n\n"
                f"## Architecture & Layers\n\n{_deterministic_module_listing(modules, data)}"
            )
            warnings.append(
                f"AI-written documentation could not be generated ({str(exc) or type(exc).__name__}); "
                "showing a structural listing only."
            )
        full_markdown = "\n\n".join([
            body_markdown.strip(), _build_relationships_section(data),
            _build_known_issues_section(violations, health_score),
        ])
        return {
            "markdown": full_markdown,
            "warnings": warnings,
            "stats": {
                "total_modules": len(data["modules"]), "groups": len(groups),
                "batches_kept": 1, "batches_ok": 0 if warnings else 1, "batches_failed": 1 if warnings else 0,
                "groups_structural_only": 0, "reduce_ok": None,
                "elapsed_seconds": round(time.time() - start, 2),
                "provider": provider,
            },
        }

    map_concurrency = min(provider["parallelism"], MAP_MAX_CONCURRENCY_CAP)
    batch_results = _run_map_phase(kept, data, repo_path, map_concurrency)

    batches_failed = [r for r in batch_results if r["status"] == "error"]
    if batches_failed:
        names = ", ".join(_group_display_name(r["group_key"]) for r in batches_failed)
        warnings.append(
            f"{len(batches_failed)} of {len(batch_results)} section(s) could not be AI-generated "
            f"and fall back to a structural listing: {names}."
        )
    if structural_only:
        total_overflow_modules = sum(len(v) for v in structural_only.values())
        names = ", ".join(_group_display_name(k) for k in structural_only)
        warnings.append(
            f"{len(structural_only)} group(s) ({total_overflow_modules} files) exceeded this analysis's "
            f"{MAX_TOTAL_MAP_CALLS}-call limit and are listed structurally only: {names}."
        )

    reduce_input = _build_reduce_input(batch_results, structural_only, groups, data, health_score)
    reduce_result = _reduce(reduce_input)
    if reduce_result["status"] == "ok":
        reduce_markdown = reduce_result["markdown"]
        reduce_ok = True
    else:
        reduce_markdown = _deterministic_overview_fallback(data, health_score, groups)
        reduce_ok = False
        warnings.append(
            "The Overview/Architecture summary could not be AI-generated "
            f"({reduce_result['error']}) and uses a simpler deterministic fallback."
        )

    full_markdown = _assemble_document(
        reduce_markdown, batch_results, structural_only, groups, data, violations, health_score
    )

    return {
        "markdown": full_markdown,
        "warnings": warnings,
        "stats": {
            "total_modules": len(data["modules"]), "groups": len(groups),
            "batches_kept": len(kept), "batches_ok": len(batch_results) - len(batches_failed),
            "batches_failed": len(batches_failed), "groups_structural_only": len(structural_only),
            "reduce_ok": reduce_ok, "elapsed_seconds": round(time.time() - start, 2),
            "provider": provider, "map_concurrency": map_concurrency,
        },
    }
