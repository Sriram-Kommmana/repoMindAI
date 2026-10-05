"""Assigns each module to an architectural layer from the rules' `layers`
section (pure, no I/O).

Precedence, most explicit first:
  1. glob: matched against the full path — deliberate per-repo overrides
  2. file: matched against the file name, e.g. controller.py, *.service.ts
  3. dir:  matched against folder names from the innermost outward, so
     app/services/db/session.py is "db", not "services"
Within each step, layers are tried in the order the rules list them.
Modules matching the `ignore` patterns (tests, by default) get no layer:
they legitimately import every layer. Matching is case-insensitive fnmatch.
"""
import fnmatch


def _matches(value: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(value.lower(), pattern.lower())


def is_ignored(path: str, ignore: list) -> bool:
    parts = path.split("/")
    for p in ignore or []:
        if "glob" in p and _matches(path, p["glob"]):
            return True
        if "file" in p and _matches(parts[-1], p["file"]):
            return True
        if "dir" in p and any(_matches(folder, p["dir"]) for folder in parts[:-1]):
            return True
    return False


def classify(path: str, layers_config: dict, ignore: list = None):
    if not layers_config or is_ignored(path, ignore):
        return None
    parts = path.split("/")
    filename, folders = parts[-1], parts[:-1]

    for kind, candidates in (("glob", [path]), ("file", [filename]), ("dir", list(reversed(folders)))):
        for candidate in candidates:
            for layer, patterns in layers_config.items():
                for p in patterns:
                    if kind in p and _matches(candidate, p[kind]):
                        return layer
    return None


def apply_layers(data: dict, rules: dict) -> None:
    """Overwrites each module's layer_type in place. A rules document without
    a layers section keeps the parser's own filename-based layers."""
    layers_config = rules.get("layers")
    if not layers_config:
        return
    ignore = rules.get("ignore", [])
    for module in data["modules"]:
        module["layer_type"] = classify(module["path"], layers_config, ignore)
