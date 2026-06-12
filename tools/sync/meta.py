from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from tools.common.db import open_db
from tools.common.targets import PROJECT_ROOT
from tools.sync.models import MediaResult


SYNC_META_DB = PROJECT_ROOT / "logs" / "openclaw" / "sync_meta.db"


def ensure_tables(db_path: Path = SYNC_META_DB) -> None:
    with closing(open_db(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS media_cache (
                sha256 TEXT PRIMARY KEY,
                media_id TEXT NOT NULL,
                url TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                uploaded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sync_status (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_run_at TEXT,
                last_success_at TEXT,
                last_error TEXT,
                last_error_at TEXT,
                last_counts_json TEXT
            );
            """
        )
        conn.commit()

def get_media(sha256: str, db_path: Path = SYNC_META_DB) -> MediaResult | None:
    ensure_tables(db_path)
    with closing(open_db(db_path)) as conn:
        row = conn.execute(
            "SELECT * FROM media_cache WHERE sha256 = ?",
            (sha256,),
        ).fetchone()
    if row is None:
        return None
    raw = json.loads(row["raw_json"])
    return MediaResult(
        media_id=row["media_id"],
        url=row["url"],
        sha256=row["sha256"],
        raw=raw,
        deduplicated=bool(raw.get("deduplicated")),
        size=raw.get("size"),
    )


def save_media(result: MediaResult, uploaded_at: str, db_path: Path = SYNC_META_DB) -> None:
    ensure_tables(db_path)
    with closing(open_db(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO media_cache (sha256, media_id, url, raw_json, uploaded_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sha256) DO UPDATE SET
                media_id = excluded.media_id,
                url = excluded.url,
                raw_json = excluded.raw_json,
                uploaded_at = excluded.uploaded_at
            """,
            (
                result.sha256,
                result.media_id,
                result.url,
                json.dumps(result.raw or {}, ensure_ascii=False, sort_keys=True),
                uploaded_at,
            ),
        )
        conn.commit()
