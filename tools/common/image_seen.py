"""Track when an image hash was first seen by the local LINE pipeline."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tools.common.targets import DOWNLOADS_DIR, PROJECT_ROOT


IMAGE_SEEN_LOG_PATH = DOWNLOADS_DIR / "image_seen_log.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    """SHA256 hex digest of a file's bytes, streamed in 64KB chunks.

    Shared by filter/ocr_enrich/process_downloads so the cache key on the
    sidecar (imageSha256) matches byte-for-byte regardless of which stage
    computed it.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_image_seen_log(path: Path = IMAGE_SEEN_LOG_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for digest, record in data.items():
        if isinstance(digest, str) and isinstance(record, dict):
            out[digest] = dict(record)
    return out


def save_image_seen_log(log: dict[str, dict[str, Any]], path: Path = IMAGE_SEEN_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(log, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(path)


def relpath(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def record_seen_image(
    log: dict[str, dict[str, Any]],
    image_path: Path,
    *,
    target_id: Optional[str],
    first_seen_at: Optional[str] = None,
    source: str = "pipeline",
) -> tuple[bool, Optional[str]]:
    try:
        digest = file_sha256(image_path)
    except OSError:
        return False, None
    if digest in log:
        return False, digest
    log[digest] = {
        "first_seen_at": first_seen_at or utc_now_iso(),
        "target_id": target_id,
        "image_path": relpath(image_path),
        "source": source,
    }
    return True, digest


def first_seen_for_path(path: Path, log: Optional[dict[str, dict[str, Any]]] = None) -> Optional[str]:
    try:
        digest = file_sha256(path)
    except OSError:
        return None
    data = log if log is not None else load_image_seen_log()
    record = data.get(digest)
    if not isinstance(record, dict):
        return None
    value = record.get("first_seen_at")
    return str(value) if value else None
