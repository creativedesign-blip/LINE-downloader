"""Sync upload-only annotations into travel_index's image_annotations table.

The travel index already holds every uploaded image's extracted fields (OCR
text, countries, regions, months, price, duration) keyed by content sha256.
The only *additional* searchable signal that lives solely in upload_catalog is
the human annotation: display name, original filename, reference text, note,
manual tags and override tags.

This module copies that annotation text into travel_index.image_annotations,
keyed by image content sha256, so the travel index can become the single
search source without losing "search by tag / note / filename". A full replace
keeps it idempotent; run it after an index sync or whenever annotations change.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.common.db import open_db
from tools.common.targets import TRAVEL_INDEX_DB_PATH
from tools.indexing.index_db import TravelIndex
from tools.openclaw.upload_catalog import CATALOG_DB_PATH


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def annotation_tokens_by_sha(catalog_db: Path = CATALOG_DB_PATH) -> dict[str, set[str]]:
    """Map content sha256 -> set of upload-only searchable tokens.

    Only non-archived images (and folders) contribute, mirroring what the
    upload search index would surface. Images sharing a sha merge their tokens.
    """
    by_sha: dict[str, set[str]] = {}
    if not Path(catalog_db).is_file():
        return by_sha
    with open_db(catalog_db) as conn:
        names = _table_names(conn)
        if "uploaded_images" not in names or "upload_folders" not in names:
            return by_sha
        image_rows = conn.execute(
            """
            SELECT i.id, i.sha256, i.display_name, i.original_filename,
                   i.reference_text, i.manual_note, i.ocr_tags_override
            FROM uploaded_images i
            JOIN upload_folders f ON f.id = i.folder_id
            WHERE i.archived_at IS NULL AND f.archived_at IS NULL
              AND i.sha256 IS NOT NULL AND i.sha256 <> ''
            """
        ).fetchall()
        tags_by_image: dict[int, list[str]] = {}
        if "manual_tags" in names:
            for image_id, tag in conn.execute("SELECT image_id, tag FROM manual_tags"):
                tags_by_image.setdefault(int(image_id), []).append(str(tag or ""))

    for row in image_rows:
        sha = str(row["sha256"]).strip()
        if not sha:
            continue
        tokens = by_sha.setdefault(sha, set())
        for value in (row["display_name"], row["original_filename"],
                      row["reference_text"], row["manual_note"]):
            text = str(value or "").strip()
            if text:
                tokens.add(text)
        try:
            for tag in json.loads(row["ocr_tags_override"] or "[]"):
                text = str(tag or "").strip()
                if text:
                    tokens.add(text)
        except (TypeError, ValueError):
            pass
        for tag in tags_by_image.get(int(row["id"]), []):
            text = tag.strip()
            if text:
                tokens.add(text)

    return {sha: tokens for sha, tokens in by_sha.items() if tokens}


def rebuild_image_annotations(
    *,
    travel_db: Path = TRAVEL_INDEX_DB_PATH,
    catalog_db: Path = CATALOG_DB_PATH,
) -> dict[str, Any]:
    """Rebuild travel_index.image_annotations from the current upload catalog."""
    by_sha = annotation_tokens_by_sha(catalog_db)
    rows = [(sha, " ".join(sorted(tokens))) for sha, tokens in by_sha.items()]
    with TravelIndex(travel_db) as index:
        written = index.replace_image_annotations(rows)
    return {"annotations": written}


def main() -> int:
    result = rebuild_image_annotations()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
