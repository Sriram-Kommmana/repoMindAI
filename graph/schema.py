"""Node labels and relationship type constants for the Phase 1 graph schema.

Phase 1 uses current-state edges only — no valid_from_commit/valid_to_commit
temporal versioning yet (see CLAUDE.md / SPEC.md Implementation Scope).
"""

MODULE = "Module"
CLASS = "Class"
FUNCTION = "Function"

CONTAINS = "CONTAINS"
CALLS = "CALLS"
IMPORTS = "IMPORTS"
