"""Shared SQLite connection helper.

All callers across the project open SQLite the same way: ensure the parent
directory exists, set a Row factory, and — crucially — enable WAL + a generous
busy timeout so the web server and the RPA/indexing pipeline can touch the same
DB concurrently without hard `database is locked` failures.

WAL (journal_mode) is a persistent property of the DB file: once any connection
sets it, every later connection (even a raw sqlite3.connect) operates in WAL
mode. busy_timeout is per-connection, so it must be set on each connect.

foreign_keys is intentionally left at SQLite's default (off) to preserve the
historical behavior of callers that declare ON DELETE CASCADE but never relied
on enforcement; flipping it on is a separate, deliberate decision.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_TIMEOUT = 30.0  # seconds to wait on a locked DB before raising


def open_db(path: "str | Path", *, timeout: float = DEFAULT_TIMEOUT) -> sqlite3.Connection:
    """Open a SQLite connection with sane concurrency defaults.

    Ensures the parent dir exists, sets `sqlite3.Row` row factory, a busy
    timeout, and WAL journal mode. Returns the connection (caller owns close).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def content_deduped_itineraries_sql(where: str = "") -> str:
    """Inner SELECT keeping one `itineraries` row per image content, newest first.

    The single SQL source of the same "same image" rule as
    operations._content_key: partition by COALESCE(image_sha256, sidecar_path)
    (rows with no hash fall back to their own sidecar so they don't collapse
    together) and keep the most complete row — a row that still carries a
    perceptual hash wins over an otherwise-newer NULL-phash row, then most
    recently indexed. ``rowid DESC`` tiebreaks within one reindex transaction
    where every row shares an indexed_at second.

    Callers pass a ready ``WHERE ...`` clause (or "") and append their own outer
    ORDER BY / LIMIT — only the dedup window must stay identical across sites.
    """
    return (
        "SELECT * FROM ("
        "  SELECT *, ROW_NUMBER() OVER ("
        "    PARTITION BY COALESCE(image_sha256, sidecar_path) "
        "    ORDER BY (image_phash IS NOT NULL) DESC, indexed_at DESC, rowid DESC"
        f"  ) AS _rn FROM itineraries {where}"
        ") WHERE _rn = 1"
    )
