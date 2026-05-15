"""Atomic JSON dict load/save shared by pipeline state files.

Three places previously rolled their own (image_seen_log, image_index,
.image_hash_cache). Two were non-atomic — a Ctrl+C mid-write corrupted
the file and forced a full rebuild. Centralising the pattern here makes
the atomic tmp+replace contract a single thing to maintain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json_dict(path: Path) -> dict[str, Any]:
    """Read a JSON object from `path`. Missing or corrupt → empty dict.

    A cache miss only costs a rebuild, never correctness; never raise.
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_json_dict(
    path: Path,
    data: dict[str, Any],
    *,
    sort_keys: bool = True,
) -> None:
    """Pretty-print `data` to `path` atomically (write tmp then replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=sort_keys),
        encoding="utf-8",
    )
    tmp.replace(path)
