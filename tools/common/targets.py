"""Project-wide constants and target enumeration helpers.

Shared between tools/branding and tools/indexing so that both modules agree
on where `config/targets.json` lives and which target ids exist.
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TARGETS_PATH = PROJECT_ROOT / "config" / "targets.json"
DOWNLOADS_DIR = PROJECT_ROOT / "line-rpa" / "download"


def load_target_ids() -> list[str]:
    """Return configured target ids plus discovered downloads folders.

    The original UI-driven flow stores target ids in config/targets.json.
    The RPA/OpenClaw flow creates folders under line-rpa/download/<name>, so
    tools that process images must also discover those folders.
    """
    ids: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        if value and value not in seen:
            ids.append(value)
            seen.add(value)

    if not TARGETS_PATH.exists():
        data = {"targets": []}
    else:
        with open(TARGETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

    for target in data.get("targets", []):
        add(target.get("id"))

    if DOWNLOADS_DIR.exists():
        for child in sorted(DOWNLOADS_DIR.iterdir()):
            if child.is_dir() and not child.name.startswith((".", "_")):
                add(child.name)

    return ids


def relpath_from_root(p: Path) -> str:
    """Normalize a path to a POSIX-style string relative to PROJECT_ROOT.

    Falls back to the absolute posix form if `p` lives outside the project.
    """
    try:
        return p.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return p.as_posix()
