"""Deterministic module grouping for documentation generation.

Shares the same grouping precedence as export_diagram.py's build_mermaid
(layer_type first, then containing folder, then a flat root bucket) but is
NOT imported from that module, to avoid pulling in the neo4j driver
dependency (export_diagram.py imports GraphDatabase at module scope) for a
pure, no-I/O function. export_diagram.py itself is intentionally left
unrefactored — this duplication is deliberate, not an oversight; migrating
it to share this module is a candidate follow-up, not part of this change.
"""
import os
from collections import OrderedDict


def group_modules(modules: list) -> "OrderedDict[str, list]":
    """Groups module dicts (each needs at least "path" and "layer_type")
    by, in precedence order:
      1. layer_type, if set (key: "layer:<name>", groups sorted by name)
      2. containing folder, if any (key: "folder:<path>", single-level —
         "src/core" is one flat bucket, not nested under "src")
      3. everything else falls into one flat "root" bucket

    Returns an OrderedDict with deterministic key order: layer groups
    (sorted), then folder groups (sorted), then "root" last — included
    only if non-empty.
    """
    layered = {}
    foldered = {}
    root = []

    for m in modules:
        layer = m.get("layer_type")
        if layer:
            layered.setdefault(layer, []).append(m)
            continue
        folder = os.path.dirname(m["path"])
        if folder:
            foldered.setdefault(folder, []).append(m)
        else:
            root.append(m)

    result = OrderedDict()
    for layer in sorted(layered):
        result[f"layer:{layer}"] = layered[layer]
    for folder in sorted(foldered):
        result[f"folder:{folder}"] = foldered[folder]
    if root:
        result["root"] = root
    return result
