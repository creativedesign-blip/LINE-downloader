from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.openclaw.operations import DEFAULT_DB_PATH, query_latest_results
from tools.openclaw.upload_catalog import CATALOG_DB_PATH, query_image_search_index


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _count_rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] if row else 0)


def _duplicate_key_counts(items: list[dict[str, Any]], key_names: tuple[str, ...]) -> dict[str, int]:
    keys = []
    for item in items:
        key = ""
        for name in key_names:
            value = str(item.get(name) or "").strip()
            if value:
                key = value
                break
        if key:
            keys.append(key)
    return {key: count for key, count in Counter(keys).items() if count > 1}


def audit_upload_catalog(catalog_db: Path, sample_limit: int) -> dict[str, Any]:
    if not catalog_db.is_file():
        return {"ok": False, "error": f"missing db: {catalog_db}"}
    with _connect(catalog_db) as conn:
        raw_same_sha_groups = _count_rows(
            conn,
            """
            SELECT COUNT(*) FROM (
                SELECT i.sha256
                FROM uploaded_images i
                JOIN upload_folders f ON f.id = i.folder_id
                WHERE i.archived_at IS NULL
                  AND f.archived_at IS NULL
                  AND i.sha256 IS NOT NULL
                  AND i.sha256 <> ''
                GROUP BY i.sha256
                HAVING COUNT(*) > 1
            )
            """,
        )
        indexed_same_sha_groups = _count_rows(
            conn,
            """
            SELECT COUNT(*) FROM (
                SELECT i.sha256
                FROM uploaded_image_search_index s
                JOIN uploaded_images i ON i.id = s.image_id
                JOIN upload_folders f ON f.id = s.folder_id
                WHERE i.archived_at IS NULL
                  AND f.archived_at IS NULL
                  AND i.sha256 IS NOT NULL
                  AND i.sha256 <> ''
                GROUP BY i.sha256
                HAVING COUNT(*) > 1
            )
            """,
        )
        archived_index_rows = _count_rows(
            conn,
            """
            SELECT COUNT(*)
            FROM uploaded_image_search_index s
            JOIN uploaded_images i ON i.id = s.image_id
            JOIN upload_folders f ON f.id = s.folder_id
            WHERE i.archived_at IS NOT NULL
               OR f.archived_at IS NOT NULL
            """,
        )

    queried_items = query_image_search_index(limit=sample_limit, db_path=catalog_db)
    query_duplicate_keys = _duplicate_key_counts(queried_items, ("sha256", "sidecar_path", "image_path"))
    query_ok = not query_duplicate_keys
    raw_ok = raw_same_sha_groups == 0
    index_ok = indexed_same_sha_groups == 0 and archived_index_rows == 0
    return {
        "query_ok": query_ok,
        "raw_ok": raw_ok,
        "index_ok": index_ok,
        "raw_active_same_sha_groups": raw_same_sha_groups,
        "indexed_active_same_sha_groups": indexed_same_sha_groups,
        "archived_index_rows": archived_index_rows,
        "query_sample_count": len(queried_items),
        "query_duplicate_key_count": len(query_duplicate_keys),
        "query_duplicate_keys": query_duplicate_keys,
    }


def audit_travel_index(travel_db: Path, sample_limit: int) -> dict[str, Any]:
    if not travel_db.is_file():
        return {"ok": False, "error": f"missing db: {travel_db}"}
    with _connect(travel_db) as conn:
        raw_same_sha_groups = _count_rows(
            conn,
            """
            SELECT COUNT(*) FROM (
                SELECT image_sha256
                FROM itineraries
                WHERE image_sha256 IS NOT NULL
                  AND image_sha256 <> ''
                GROUP BY image_sha256
                HAVING COUNT(*) > 1
            )
            """,
        )
        rows = conn.execute(
            """
            SELECT image_sha256, sidecar_path, image_path, branded_path
            FROM itineraries
            WHERE image_sha256 IS NOT NULL
              AND image_sha256 <> ''
            """
        ).fetchall()
    sha_by_path = {}
    for row in rows:
        sha = str(row["image_sha256"] or "").strip()
        for key in ("sidecar_path", "image_path", "branded_path"):
            path = str(row[key] or "").strip()
            if path and sha:
                sha_by_path[path] = sha

    queried_items = query_latest_results(travel_db, limit=sample_limit).get("items") or []
    query_keys = []
    for item in queried_items:
        paths = [
            str(item.get("sidecar_path") or "").strip(),
            str(item.get("image_path") or "").strip(),
            str(item.get("branded_path") or "").strip(),
        ]
        query_keys.append(next((sha_by_path[path] for path in paths if path in sha_by_path), paths[0]))
    query_duplicate_keys = {key: count for key, count in Counter(query_keys).items() if key and count > 1}
    query_ok = not query_duplicate_keys
    raw_ok = raw_same_sha_groups == 0
    return {
        "query_ok": query_ok,
        "raw_ok": raw_ok,
        "raw_same_sha_groups": raw_same_sha_groups,
        "latest_query_sample_count": len(queried_items),
        "latest_query_duplicate_key_count": len(query_duplicate_keys),
        "latest_query_duplicate_keys": query_duplicate_keys,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit OpenClaw image dedupe state.")
    parser.add_argument("--catalog-db", type=Path, default=CATALOG_DB_PATH)
    parser.add_argument("--travel-db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args()

    report = {
        "upload_catalog": audit_upload_catalog(args.catalog_db, args.limit),
        "travel_index": audit_travel_index(args.travel_db, args.limit),
    }
    query_ok = all(section.get("query_ok") for section in report.values())
    storage_clean = (
        bool(report["upload_catalog"].get("raw_ok"))
        and bool(report["upload_catalog"].get("index_ok"))
        and bool(report["travel_index"].get("raw_ok"))
    )
    report["ok"] = query_ok
    report["ok_scope"] = "query_output"
    report["query_ok"] = query_ok
    report["storage_clean"] = storage_clean

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("dedupe query audit:", "ok" if query_ok else "failed")
        print("dedupe storage clean:", "yes" if storage_clean else "no")
    return 0 if query_ok else 1


if __name__ == "__main__":
    sys.exit(main())
