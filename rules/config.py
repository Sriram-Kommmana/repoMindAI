"""Loads and validates the architecture rules ("rules as data").

A rules document has an optional `layers` section (which modules belong to
which layer, by file/folder/glob pattern) and a `rules` list. It comes from
rules.yaml or, per analysis, from YAML the user pasted into the UI, so it is
validated strictly before anything uses it.
"""
import os
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

DEFAULT_RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules.yaml")
MAX_RULES_YAML_CHARS = 20_000

_LAYER_NAME = r"^[a-z][a-z_]{0,29}$"


class RulesError(ValueError):
    """The rules document is invalid; the message says what to fix."""


class LayerPattern(BaseModel):
    file: Optional[str] = Field(None, max_length=200)
    dir: Optional[str] = Field(None, max_length=200)
    glob: Optional[str] = Field(None, max_length=200)

    @model_validator(mode="after")
    def _exactly_one(self):
        given = [k for k in ("file", "dir", "glob") if getattr(self, k)]
        if len(given) != 1:
            raise ValueError("each layer pattern needs exactly one of file:, dir: or glob:")
        return self


class Rule(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    from_layer: str = Field(pattern=_LAYER_NAME)
    to_layer: str = Field(pattern=_LAYER_NAME)
    allowed: bool
    severity: int = Field(ge=0, le=10)
    edge: Literal["calls", "imports"] = "calls"


class RulesConfig(BaseModel):
    pattern: str = Field("custom", max_length=60)
    layers: dict[str, list[LayerPattern]] = Field(default_factory=dict)
    ignore: list[LayerPattern] = Field(default_factory=list, max_length=60)
    rules: list[Rule] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _consistent(self):
        import re

        if len(self.layers) > 20:
            raise ValueError("at most 20 layers")
        for name, patterns in self.layers.items():
            if not re.match(_LAYER_NAME, name):
                raise ValueError(f"layer name '{name}' must be lowercase letters/underscores (max 30)")
            if len(patterns) > 60:
                raise ValueError(f"layer '{name}' has more than 60 patterns")
        names = [r.name for r in self.rules]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"duplicate rule names: {', '.join(duplicates)}")
        if self.layers:
            for r in self.rules:
                for layer in (r.from_layer, r.to_layer):
                    if layer not in self.layers:
                        raise ValueError(f"rule '{r.name}' uses layer '{layer}', which the layers section doesn't define")
        return self


def parse_rules(text: str) -> dict:
    """Validates a YAML rules document and returns it as a plain dict (the
    shape the rule engine and evaluator consume)."""
    if len(text) > MAX_RULES_YAML_CHARS:
        raise RulesError(f"Rules YAML is too long (max {MAX_RULES_YAML_CHARS} characters).")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RulesError(f"Rules YAML could not be parsed: {exc}") from None
    if not isinstance(raw, dict):
        raise RulesError("Rules YAML must be a mapping with a 'rules' list.")
    try:
        config = RulesConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'rules'}: {e['msg']}" for e in exc.errors())
        raise RulesError(f"Invalid rules: {problems}") from None
    return config.model_dump(exclude_none=True)


def load_rules_config(text: Optional[str] = None, path: str = DEFAULT_RULES_PATH) -> dict:
    if text is None:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    return parse_rules(text)


def default_rules_text(path: str = DEFAULT_RULES_PATH) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
