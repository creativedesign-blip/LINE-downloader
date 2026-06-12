from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from tools.common.targets import PROJECT_ROOT, TRAVEL_INDEX_DB_PATH
from tools.openclaw.upload_catalog import CATALOG_DB_PATH
from tools.sync.models import Row


def _connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _rows(conn: sqlite3.Connection, sql: str) -> list[Row]:
    return [dict(row) for row in conn.execute(sql).fetchall()]


def read_travel_index(db_path: Path = TRAVEL_INDEX_DB_PATH) -> dict[str, list[Row]]:
    if not db_path.is_file():
        return {"itineraries": [], "itinerary_plans": [], "itinerary_departures": []}
    with closing(_connect_readonly(db_path)) as conn:
        return {
            "itineraries": _rows(conn, "SELECT * FROM itineraries")
            if _table_exists(conn, "itineraries")
            else [],
            "itinerary_plans": _rows(conn, "SELECT * FROM itinerary_plans")
            if _table_exists(conn, "itinerary_plans")
            else [],
            "itinerary_departures": _rows(conn, "SELECT * FROM itinerary_departures")
            if _table_exists(conn, "itinerary_departures")
            else [],
        }


def read_upload_catalog(db_path: Path = CATALOG_DB_PATH) -> dict[str, list[Row]]:
    if not db_path.is_file():
        return {
            "upload_folders": [],
            "uploaded_images": [],
            "uploaded_image_search_index": [],
            "manual_tags": [],
        }
    with closing(_connect_readonly(db_path)) as conn:
        folders = (
            _rows(conn, "SELECT * FROM upload_folders")
            if _table_exists(conn, "upload_folders")
            else []
        )
        images = (
            _rows(conn, "SELECT * FROM uploaded_images")
            if _table_exists(conn, "uploaded_images")
            else []
        )
        search = (
            _rows(conn, "SELECT * FROM uploaded_image_search_index")
            if _table_exists(conn, "uploaded_image_search_index")
            else []
        )
        tags = (
            _rows(conn, "SELECT * FROM manual_tags")
            if _table_exists(conn, "manual_tags")
            else []
        )
    return {
        "upload_folders": folders,
        "uploaded_images": images,
        "uploaded_image_search_index": search,
        "manual_tags": tags,
    }


def resolve_project_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path
