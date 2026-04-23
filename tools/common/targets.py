"""Project-wide constants and target enumeration helpers.

Shared between tools/branding and tools/indexing so that both modules agree
on where `config/targets.json` lives and which target ids exist.
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TARGETS_PATH = PROJECT_ROOT / "config" / "targets.json"


def load_target_ids() -> list[str]:
    """Return all target ids from config/targets.json, or [] if unreadable."""
    if not TARGETS_PATH.exists():
        return []
    with open(TARGETS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [t["id"] for t in data.get("targets", []) if t.get("id")]


def relpath_from_root(p: Path) -> str:
    """Normalize a path to a POSIX-style string relative to PROJECT_ROOT.

    Falls back to the absolute posix form if `p` lives outside the project.
    """
    try:
        return p.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return p.as_posix()
