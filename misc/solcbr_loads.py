"""Utilities for locating solcbr load directories on disk."""

import re
from pathlib import Path

LOADS_BASE = Path("/home/public/RND/loads/solcbr")


def strip_soltr(version: str) -> str:
    """Strip 'soltr_' prefix from a load version string."""
    return version.removeprefix("soltr_")


def load_path(version: str) -> Path | None:
    """Return the filesystem path for a load, or None if unparseable.

    Three layouts are supported:
        regular: LOADS_BASE/<X.Y.Z>/<X.Y.Z.BUILD>/   e.g. 10.25.0.202
        feature: LOADS_BASE/feature/<NAME>/<VERSION>/ e.g. 100.0SOL-144552.0.5612
        main:    LOADS_BASE/main/<VERSION>/           e.g. 100.0main.0.5554

    The type is determined by the second dotted segment: purely numeric →
    regular; 'main' → main; anything else → feature (name = second segment
    minus leading digits).
    """
    v = strip_soltr(version)
    parts = v.split(".")
    if len(parts) < 2:
        return None
    branch = re.sub(r"^\d+", "", parts[1])
    if branch == "main":
        return LOADS_BASE / "main" / v
    if branch:
        return LOADS_BASE / "feature" / branch / v
    dot = v.rfind(".")
    return LOADS_BASE / v[:dot] / v
