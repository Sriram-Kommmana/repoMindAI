"""RepoMind AI — Phase 4 CLI entry point: Mermaid module-dependency diagram export.

Usage: python export_diagram.py
Assumes the graph has already been loaded via `python main.py <repo_path>`.

Read-only: queries the existing Module nodes and IMPORTS relationships and
formats them as a Mermaid flowchart. No graph writes, no LLM involvement.
"""
import os
import re
import sys

from dotenv import load_dotenv
from neo4j import GraphDatabase

from graph.schema import IMPORTS, MODULE

load_dotenv()

_MODULES_QUERY = (
    f"MATCH (m:{MODULE}) "
    f"RETURN m.path AS path, m.layer_type AS layer_type "
    f"ORDER BY m.path"
)

_IMPORTS_QUERY = (
    f"MATCH (m1:{MODULE})-[:{IMPORTS}]->(m2:{MODULE}) "
    f"RETURN m1.path AS from_path, m2.path AS to_path "
    f"ORDER BY m1.path, m2.path"
)

_LAYER_COLORS = {
    # Grayscale only, for the neo-brutalist black/white/dark UI (Phase 8) —
    # different shades still keep the three layers visually distinct
    # without introducing hue.
    "controller": "fill:#2b2b2b,stroke:#f2f2f2,color:#f2f2f2",
    "service": "fill:#404040,stroke:#f2f2f2,color:#f2f2f2",
    "database": "fill:#181818,stroke:#f2f2f2,color:#f2f2f2",
}


def _get_driver():
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    return GraphDatabase.driver(uri, auth=(user, password))


def fetch_modules(session):
    return [dict(r) for r in session.run(_MODULES_QUERY)]


def fetch_imports(session):
    return [dict(r) for r in session.run(_IMPORTS_QUERY)]


def sanitize_id(path: str) -> str:
    """Deterministic, Mermaid-safe node ID derived from a module path.

    Operates on the full path (not just the basename) so paths that only
    differ by directory still sanitize to distinct IDs.
    """
    stem = path[:-3] if path.endswith(".py") else path
    return re.sub(r"[^0-9a-zA-Z_]", "_", stem)


def build_mermaid(modules: list, imports: list) -> str:
    """Pure formatter (no I/O). Returns raw `flowchart TD ...` Mermaid source.

    Grouping precedence per module: `layer_type` (the demo fixture's
    controller/service/database convention) first, since that's an
    explicit, deliberate tag — then its containing folder, so a real repo
    with an MVC-style layout (models/, views/, controllers/ as actual
    directories, which never get a layer_type — that's only assigned by
    filename, not folder name) still gets meaningful visual grouping
    instead of one flat, ungrouped node list. A module with neither stays
    a plain top-level node, exactly as before.
    """
    node_id = {m["path"]: sanitize_id(m["path"]) for m in modules}

    layered = {}
    foldered = {}
    unlayered = []
    for m in modules:
        layer = m["layer_type"]
        if layer:
            layered.setdefault(layer, []).append(m)
            continue
        folder = os.path.dirname(m["path"])
        if folder:
            foldered.setdefault(folder, []).append(m)
        else:
            unlayered.append(m)

    lines = ["flowchart TD"]

    for layer in sorted(layered):
        lines.append(f'    subgraph {layer}_layer["{layer.capitalize()}"]')
        for m in layered[layer]:
            label = os.path.basename(m["path"])
            lines.append(f'        {node_id[m["path"]]}["{label}"]')
        lines.append("    end")

    for folder in sorted(foldered):
        # "folder_" prefix keeps this subgraph id from ever colliding with a
        # module's own sanitized node id.
        lines.append(f'    subgraph folder_{sanitize_id(folder)}["{folder}"]')
        for m in foldered[folder]:
            label = os.path.basename(m["path"])
            lines.append(f'        {node_id[m["path"]]}["{label}"]')
        lines.append("    end")

    for m in unlayered:
        label = os.path.basename(m["path"])
        lines.append(f'    {node_id[m["path"]]}["{label}"]')

    if imports:
        lines.append("")
        for edge in imports:
            lines.append(f'    {node_id[edge["from_path"]]} --> {node_id[edge["to_path"]]}')

    if layered:
        lines.append("")
        for layer in sorted(layered):
            style = _LAYER_COLORS.get(layer, "fill:#2b2b2b,stroke:#f2f2f2,color:#f2f2f2")
            lines.append(f"    classDef {layer}Style {style};")
        for layer in sorted(layered):
            ids = ",".join(node_id[m["path"]] for m in layered[layer])
            lines.append(f"    class {ids} {layer}Style;")

    return "\n".join(lines)


def build_folder_mermaid(modules: list, imports: list) -> str:
    """Folder-level dependency diagram (one node per folder, edges labelled
    with the number of module imports between folders). Used for historical
    snapshots, where a full module-level diagram of a large repo would
    exceed Mermaid's text size limit."""
    def folder_of(path):
        return os.path.dirname(path) or "(root)"

    files = {}
    layers = {}
    for m in modules:
        folder = folder_of(m["path"])
        files[folder] = files.get(folder, 0) + 1
        if m.get("layer_type"):
            layers.setdefault(folder, {}).setdefault(m["layer_type"], 0)
            layers[folder][m["layer_type"]] += 1

    edges = {}
    for e in imports:
        a, b = folder_of(e["from_path"]), folder_of(e["to_path"])
        if a != b and a in files and b in files:
            edges[(a, b)] = edges.get((a, b), 0) + 1

    def node(folder):
        return "folder_" + re.sub(r"[^0-9a-zA-Z_]", "_", folder)

    lines = ["flowchart LR"]
    for folder in sorted(files):
        count = files[folder]
        lines.append(f'    {node(folder)}["{folder} ({count} file{"s" if count != 1 else ""})"]')
    for (a, b), n in sorted(edges.items()):
        lines.append(f"    {node(a)} -->|{n}| {node(b)}")

    majority = {f: max(counts, key=counts.get) for f, counts in layers.items()}
    for layer in sorted(set(majority.values())):
        style = _LAYER_COLORS.get(layer, "fill:#2b2b2b,stroke:#f2f2f2,color:#f2f2f2")
        lines.append(f"    classDef {layer}Style {style};")
        ids = ",".join(node(f) for f in sorted(majority) if majority[f] == layer)
        lines.append(f"    class {ids} {layer}Style;")
    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    driver = _get_driver()
    try:
        with driver.session() as session:
            modules = fetch_modules(session)
            imports = fetch_imports(session)
    finally:
        driver.close()

    mermaid = build_mermaid(modules, imports)
    print(mermaid)

    with open("diagram_output.md", "w", encoding="utf-8") as f:
        f.write("# Module Dependency Diagram\n\n```mermaid\n")
        f.write(mermaid)
        f.write("\n```\n")

    print(f"\nWrote diagram to diagram_output.md ({len(modules)} modules, {len(imports)} import edges)")


if __name__ == "__main__":
    main()
