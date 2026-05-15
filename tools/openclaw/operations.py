"""OpenClaw-facing operations over the processed travel index.

This module intentionally reads only processed data. RPA and the fixed
pipeline own downloading, OCR, branding, and indexing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8+ on this project.
    ZoneInfo = None

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.common.targets import DOWNLOADS_DIR, PROJECT_ROOT, load_target_ids, relpath_from_root
from tools.common.image_seen import first_seen_for_path, load_image_seen_log


DEFAULT_DB_PATH = PROJECT_ROOT / "config" / "travel_index.db"
DEFAULT_REVIEW_PATH = PROJECT_ROOT / "config" / "duplicate_reviews.json"
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
MIN_PLAN_PRICE = 10_000


def _load_duplicate_reviews(review_path: Path = DEFAULT_REVIEW_PATH) -> dict[str, Any]:
    try:
        data = json.loads(review_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {"version": 1, "reviews": []}
    if not isinstance(data, dict):
        data = {"version": 1, "reviews": []}
    if not isinstance(data.get("reviews"), list):
        data["reviews"] = []
    return data


def _reviewed_duplicate_group_ids(review_path: Path = DEFAULT_REVIEW_PATH) -> set[str]:
    data = _load_duplicate_reviews(review_path)
    return {
        str(entry.get("group_id"))
        for entry in data.get("reviews", [])
        if isinstance(entry, dict) and entry.get("group_id")
    }


def archived_sidecar_paths(review_path: Path = DEFAULT_REVIEW_PATH) -> set[str]:
    data = _load_duplicate_reviews(review_path)
    archived: set[str] = set()
    for entry in data.get("reviews", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("action") != "keep_one":
            continue
        for value in entry.get("archived_sidecar_paths") or []:
            if value:
                archived.add(str(value))
    return archived


def _filter_archived_items(
    items: list[dict[str, Any]],
    *,
    include_archived: bool = False,
    review_path: Path = DEFAULT_REVIEW_PATH,
) -> list[dict[str, Any]]:
    if include_archived:
        return items
    archived = archived_sidecar_paths(review_path)
    if not archived:
        return items
    return [item for item in items if str(item.get("sidecar_path") or "") not in archived]


def _parse_iso(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty datetime")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _csv_tokens(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item for item in str(value).split(",") if item]


def _row_to_public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    get = row.get if isinstance(row, dict) else row.__getitem__
    return {
        "sidecar_path": get("sidecar_path"),
        "image_path": get("image_path"),
        "branded_path": get("branded_path") or get("image_path"),
        "target_id": get("target_id"),
        "group_name": get("group_name"),
        "countries": _csv_tokens(get("country_csv")),
        "regions": _csv_tokens(get("region_csv")),
        "months": [int(v) for v in _csv_tokens(get("months_csv")) if str(v).isdigit()],
        "price_from": get("price_from"),
        "airlines": _csv_tokens(get("airline_csv")),
        "duration_days": get("duration_days"),
        "features": _csv_tokens(get("features_csv")),
        "source_time": get("source_time"),
        "indexed_at": get("indexed_at"),
    }


def _valid_plan_price(value: Any) -> Optional[int]:
    try:
        price = int(value)
    except (TypeError, ValueError):
        return None
    if price < MIN_PLAN_PRICE:
        return None
    return price


def _plan_to_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "plan_no": row["plan_no"],
        "title": row["title"],
        "price_from": row["price_from"],
        "months": [int(v) for v in _csv_tokens(row["months_csv"]) if str(v).isdigit()],
        "duration_days": row["duration_days"],
    }


def _attach_plan_summaries(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items or not _has_table(conn, "itinerary_plans"):
        return items

    sidecars = [str(item.get("sidecar_path") or "") for item in items if item.get("sidecar_path")]
    if not sidecars:
        return items

    placeholders = ",".join("?" for _ in sidecars)
    rows = conn.execute(
        "SELECT sidecar_path, plan_no, title, price_from, months_csv, duration_days "
        f"FROM itinerary_plans WHERE sidecar_path IN ({placeholders}) "
        "AND price_from IS NOT NULL ORDER BY sidecar_path, plan_no",
        sidecars,
    ).fetchall()

    plans_by_sidecar: dict[str, list[dict[str, Any]]] = {}
    prices_by_sidecar: dict[str, set[int]] = {}
    for row in rows:
        price = _valid_plan_price(row["price_from"])
        if price is None:
            continue
        sidecar = row["sidecar_path"]
        plans_by_sidecar.setdefault(sidecar, []).append(_plan_to_public(row))
        prices_by_sidecar.setdefault(sidecar, set()).add(price)

    enriched: list[dict[str, Any]] = []
    for item in items:
        sidecar = str(item.get("sidecar_path") or "")
        prices = sorted(prices_by_sidecar.get(sidecar, set()))
        copy = dict(item)
        if prices:
            copy["plan_prices"] = prices
            copy["price_to"] = max(prices)
            copy["price_count"] = len(prices)
            copy["plans"] = plans_by_sidecar.get(sidecar, [])
            if copy.get("price_from") is None:
                copy["price_from"] = min(prices)
        enriched.append(copy)
    return enriched


def _with_first_seen(item: dict[str, Any], seen_log: dict[str, dict[str, Any]]) -> dict[str, Any]:
    copy = dict(item)
    image_path = copy.get("image_path")
    if image_path:
        copy["first_seen_at"] = first_seen_for_path(PROJECT_ROOT / str(image_path), seen_log)
    else:
        copy["first_seen_at"] = None
    return copy


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _has_itineraries_table(conn: sqlite3.Connection) -> bool:
    return _has_table(conn, "itineraries")


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def query_latest_results(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    since: Optional[str] = None,
    hours: Optional[float] = None,
    today: bool = False,
    timezone_name: str = "Asia/Taipei",
    composed_only: bool = False,
    target_id: Optional[str] = None,
    limit: int = 10,
    include_archived: bool = False,
    review_path: Path = DEFAULT_REVIEW_PATH,
) -> dict[str, Any]:
    """Return latest processed itineraries ordered by indexed_at desc."""
    clauses: list[str] = []
    params: list[Any] = []

    since_dt: Optional[datetime] = None
    if since:
        since_dt = _parse_iso(since)
    elif today:
        tz = ZoneInfo(timezone_name) if ZoneInfo else timezone(timedelta(hours=8))
        local_now = datetime.now(tz)
        since_dt = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    elif hours is not None:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=float(hours))
    filter_by_first_seen = today and composed_only
    if since_dt is not None and not filter_by_first_seen:
        clauses.append("indexed_at >= ?")
        params.append(since_dt.strftime("%Y-%m-%dT%H:%M:%SZ"))

    if composed_only:
        clauses.append("branded_path IS NOT NULL AND branded_path <> ''")

    if target_id:
        clauses.append("target_id = ?")
        params.append(target_id)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql_limit = int(limit)
    if filter_by_first_seen:
        sql_limit = max(int(limit) * 5, int(limit), 500)
    elif not include_archived:
        sql_limit = max(int(limit) * 5, int(limit), 100)
    sql = (
        f"SELECT * FROM itineraries {where} "
        "ORDER BY indexed_at DESC, source_time DESC LIMIT ?"
    )
    params.append(sql_limit)

    with _connect(db_path) as conn:
        if not _has_itineraries_table(conn):
            return {
                "count": 0,
                "items": [],
                "filters": {
                    "since": since_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if since_dt else None,
                    "today": bool(today),
                    "timezone": timezone_name if today else None,
                    "composed_only": bool(composed_only),
                    "today_by": "first_seen_at_or_source_time" if filter_by_first_seen else "indexed_at" if today else None,
                    "target_id": target_id,
                    "limit": int(limit),
                },
                "warning": "travel_index.db is not initialized; run the fixed pipeline first",
            }
        rows = conn.execute(sql, params).fetchall()
        items = _attach_plan_summaries(conn, [_row_to_public(row) for row in rows])
    items = _filter_archived_items(items, include_archived=include_archived, review_path=review_path)

    seen_log = load_image_seen_log() if filter_by_first_seen else {}
    items = [
        _with_first_seen(item, seen_log) if filter_by_first_seen else item
        for item in items
    ]
    if filter_by_first_seen and since_dt is not None:
        since_text = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        def today_marker(item: dict[str, Any]) -> str:
            return str(
                item.get("first_seen_at")
                or item.get("source_time")
                or item.get("indexed_at")
                or ""
            )

        items = [
            item for item in items
            if today_marker(item) >= since_text
        ]
        items.sort(key=lambda item: (today_marker(item), str(item.get("indexed_at") or "")), reverse=True)
    items = items[:int(limit)]
    return {
        "count": len(items),
        "items": items,
        "filters": {
            "since": since_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if since_dt else None,
            "today": bool(today),
            "timezone": timezone_name if today else None,
            "composed_only": bool(composed_only),
            "today_by": "first_seen_at_or_source_time" if filter_by_first_seen else "indexed_at" if today else None,
            "target_id": target_id,
            "limit": int(limit),
            "include_archived": bool(include_archived),
        },
    }


def _add_csv_any(
    clauses: list[str],
    params: list[Any],
    column: str,
    values: Optional[list[Any]],
) -> None:
    if not values:
        return
    cleaned = [value for value in values if value is not None and str(value) != ""]
    if not cleaned:
        return
    clauses.append("(" + " OR ".join(f"{column} LIKE ?" for _ in cleaned) + ")")
    params.extend(f"%,{value},%" for value in cleaned)


def query_itineraries(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    countries: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
    months: Optional[list[int]] = None,
    airlines: Optional[list[str]] = None,
    features: Optional[list[str]] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    duration_days: Optional[int] = None,
    duration_min: Optional[int] = None,
    duration_max: Optional[int] = None,
    target_id: Optional[str] = None,
    limit: int = 10,
    include_archived: bool = False,
    review_path: Path = DEFAULT_REVIEW_PATH,
) -> dict[str, Any]:
    """Query processed itineraries by structured filters."""
    clauses: list[str] = []
    params: list[Any] = []
    _add_csv_any(clauses, params, "country_csv", countries)
    _add_csv_any(clauses, params, "region_csv", regions)
    _add_csv_any(clauses, params, "months_csv", months)
    _add_csv_any(clauses, params, "airline_csv", airlines)
    _add_csv_any(clauses, params, "features_csv", features)

    if price_min is not None or price_max is not None:
        image_price_parts: list[str] = ["price_from IS NOT NULL"]
        plan_price_parts: list[str] = [
            "p.sidecar_path = itineraries.sidecar_path",
            "p.price_from IS NOT NULL",
            "p.price_from >= ?",
        ]
        image_price_params: list[Any] = []
        plan_price_params: list[Any] = [MIN_PLAN_PRICE]
        if price_min is not None:
            image_price_parts.append("price_from >= ?")
            image_price_params.append(int(price_min))
            plan_price_parts.append("p.price_from >= ?")
            plan_price_params.append(int(price_min))
        if price_max is not None:
            image_price_parts.append("price_from <= ?")
            image_price_params.append(int(price_max))
            plan_price_parts.append("p.price_from <= ?")
            plan_price_params.append(int(price_max))
        clauses.append(
            "(("
            + " AND ".join(image_price_parts)
            + ") OR EXISTS (SELECT 1 FROM itinerary_plans p WHERE "
            + " AND ".join(plan_price_parts)
            + "))"
        )
        params.extend(image_price_params)
        params.extend(plan_price_params)
    if duration_days is not None:
        clauses.append("duration_days = ?")
        params.append(int(duration_days))
    if duration_min is not None:
        clauses.append("duration_days >= ?")
        params.append(int(duration_min))
    if duration_max is not None:
        clauses.append("duration_days <= ?")
        params.append(int(duration_max))
    if target_id:
        clauses.append("target_id = ?")
        params.append(target_id)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    # Dedup by image_sha256 — RPA-side hash dedup leaks (group rename,
    # corrupt image_index.json, etc.) sometimes land the same image bytes
    # in multiple rows. Mirror the rule from index_db.TravelIndex.query
    # so this code path doesn't surface duplicates either.
    sql = (
        f"SELECT * FROM ("
        f"  SELECT *, ROW_NUMBER() OVER ("
        f"    PARTITION BY COALESCE(image_sha256, sidecar_path) "
        f"    ORDER BY indexed_at DESC, rowid DESC"
        f"  ) AS _rn FROM itineraries {where}"
        f") WHERE _rn = 1 "
        "ORDER BY indexed_at DESC, source_time DESC LIMIT ?"
    )
    sql_limit = int(limit) if include_archived else max(int(limit) * 5, int(limit), 100)
    params.append(sql_limit)

    filters = {
        "countries": countries or [],
        "regions": regions or [],
        "months": months or [],
        "airlines": airlines or [],
        "features": features or [],
        "price_min": price_min,
        "price_max": price_max,
        "duration_days": duration_days,
        "duration_min": duration_min,
        "duration_max": duration_max,
        "target_id": target_id,
        "limit": int(limit),
        "include_archived": bool(include_archived),
    }

    with _connect(db_path) as conn:
        if not _has_itineraries_table(conn):
            return {
                "count": 0,
                "items": [],
                "filters": filters,
                "warning": "travel_index.db is not initialized; run the fixed pipeline first",
            }
        rows = conn.execute(sql, params).fetchall()
        items = _attach_plan_summaries(conn, [_row_to_public(row) for row in rows])
    items = _filter_archived_items(items, include_archived=include_archived, review_path=review_path)
    items = items[:int(limit)]
    return {
        "count": len(items),
        "items": items,
        "filters": filters,
    }


def _price_bucket(price: Any, bucket_size: int) -> Optional[int]:
    if price is None:
        return None
    try:
        return round(int(price) / bucket_size) * bucket_size
    except (TypeError, ValueError):
        return None


def _duplicate_key(item: dict[str, Any], price_bucket_size: int) -> Optional[tuple]:
    countries = tuple(item["countries"])
    months = tuple(item["months"])
    if not countries or not months:
        return None
    return (
        countries,
        tuple(item["regions"]),
        months,
        item["duration_days"],
        _price_bucket(item["price_from"], price_bucket_size),
    )


def _duplicate_group_id(key: tuple) -> str:
    payload = json.dumps(key, ensure_ascii=False, sort_keys=True, default=str)
    return "dup_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def check_duplicates(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    limit_groups: int = 20,
    price_bucket_size: int = 5000,
    include_same_source: bool = False,
    include_reviewed: bool = False,
    review_path: Path = DEFAULT_REVIEW_PATH,
) -> dict[str, Any]:
    """Find likely duplicate itinerary products across sources.

    Basic v1 rule: country + month are required; region, duration, and rounded
    price bucket strengthen the grouping. By default, groups must include more
    than one source target/group.
    """
    with _connect(db_path) as conn:
        if not _has_itineraries_table(conn):
            return {
                "count": 0,
                "groups": [],
                "rule": {
                    "required": ["countries", "months"],
                    "grouped_by": ["countries", "regions", "months", "duration_days", "price_bucket"],
                    "price_bucket_size": int(price_bucket_size),
                    "include_same_source": bool(include_same_source),
                },
                "warning": "travel_index.db is not initialized; run the fixed pipeline first",
            }
        rows = conn.execute(
            "SELECT * FROM itineraries ORDER BY indexed_at DESC"
        ).fetchall()

    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        item = _row_to_public(row)
        key = _duplicate_key(item, price_bucket_size)
        if key is None:
            continue
        groups.setdefault(key, []).append(item)

    duplicate_groups: list[dict[str, Any]] = []
    reviewed_group_ids = set() if include_reviewed else _reviewed_duplicate_group_ids(review_path)
    for key, items in groups.items():
        if len(items) < 2:
            continue
        sources = {
            item.get("target_id") or item.get("group_name") or ""
            for item in items
        }
        sources.discard("")
        if not include_same_source and len(sources) < 2:
            continue
        group_id = _duplicate_group_id(key)
        if group_id in reviewed_group_ids:
            continue
        duplicate_groups.append({
            "group_id": group_id,
            "match": {
                "countries": list(key[0]),
                "regions": list(key[1]),
                "months": list(key[2]),
                "duration_days": key[3],
                "price_bucket": key[4],
            },
            "count": len(items),
            "sources": sorted(sources),
            "items": items,
        })

    duplicate_groups.sort(key=lambda g: (g["count"], len(g["sources"])), reverse=True)
    duplicate_groups = duplicate_groups[:int(limit_groups)]
    return {
        "count": len(duplicate_groups),
        "groups": duplicate_groups,
        "rule": {
            "required": ["countries", "months"],
            "grouped_by": ["countries", "regions", "months", "duration_days", "price_bucket"],
            "price_bucket_size": int(price_bucket_size),
            "include_same_source": bool(include_same_source),
            "include_reviewed": bool(include_reviewed),
        },
    }


def _count_images(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return sum(
        1
        for item in path.iterdir()
        if item.is_file() and item.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    )


def _latest_mtime_iso(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_dir():
        return None
    latest: Optional[float] = None
    for item in path.iterdir():
        if not item.is_file():
            continue
        if latest is None or item.stat().st_mtime > latest:
            latest = item.stat().st_mtime
    if latest is None:
        return None
    return datetime.fromtimestamp(latest, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pipeline_status(items: list[dict[str, Any]]) -> dict[str, Any]:
    active_items = [
        item for item in items
        if sum(
            int(item.get(key) or 0)
            for key in (
                "inbox_count", "travel_count", "branded_count",
                "other_count", "error_count", "indexed_count",
            )
        ) > 0
    ]

    has_active = bool(active_items)
    line_fetched_done = (
        has_active and
        all(int(item.get("inbox_count") or 0) == 0 and int(item.get("travel_count") or 0) > 0 for item in active_items)
    )
    ocr_done = (
        has_active and
        all(int(item.get("indexed_count") or 0) >= int(item.get("travel_count") or 0) for item in active_items)
    )
    composed_done = (
        has_active and
        all(int(item.get("branded_count") or 0) >= int(item.get("travel_count") or 0) for item in active_items)
    )
    error_free = (
        has_active and
        all(int(item.get("error_count") or 0) == 0 for item in active_items)
    )
    completed_stages = sum([line_fetched_done, ocr_done, composed_done])
    is_complete = line_fetched_done and ocr_done and composed_done and error_free
    return {
        "label": "LINE圖片處理完成" if is_complete else "LINE圖片處理中",
        "line_fetched_done": line_fetched_done,
        "ocr_done": ocr_done,
        "composed_done": composed_done,
        "error_free": error_free,
        "is_complete": is_complete,
        "completed_stages": completed_stages,
        "total_stages": 3,
    }


def processing_status(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    target_id: Optional[str] = None,
) -> dict[str, Any]:
    """Summarize processed folder counts and indexed rows by target."""
    targets = load_target_ids()
    if target_id:
        targets = [target_id]

    indexed_counts: dict[str, int] = {}
    latest_indexed: dict[str, Optional[str]] = {}
    total_indexed = 0
    with _connect(db_path) as conn:
        if _has_itineraries_table(conn):
            for row in conn.execute(
                "SELECT target_id, COUNT(*) AS n, MAX(indexed_at) AS latest "
                "FROM itineraries GROUP BY target_id"
            ).fetchall():
                tid = row["target_id"] or ""
                indexed_counts[tid] = int(row["n"])
                latest_indexed[tid] = row["latest"]
                total_indexed += int(row["n"])

    items: list[dict[str, Any]] = []
    for tid in targets:
        base = DOWNLOADS_DIR / tid
        inbox = base / "inbox"
        travel = base / "travel"
        branded = base / "branded"
        other = base / "other"
        error = base / "error"
        items.append({
            "target_id": tid,
            "inbox_count": _count_images(inbox) + _count_images(base),
            "travel_count": _count_images(travel),
            "branded_count": _count_images(branded),
            "other_count": _count_images(other),
            "error_count": _count_images(error),
            "indexed_count": indexed_counts.get(tid, 0),
            "latest_file_time": max(
                [
                    value for value in [
                        _latest_mtime_iso(inbox),
                        _latest_mtime_iso(base),
                        _latest_mtime_iso(travel),
                        _latest_mtime_iso(branded),
                        _latest_mtime_iso(other),
                        _latest_mtime_iso(error),
                    ]
                    if value
                ],
                default=None,
            ),
            "latest_indexed_at": latest_indexed.get(tid),
        })

    payload = {
        "count": len(items),
        "total_indexed": total_indexed,
        "items": items,
        "warning": None if indexed_counts else "travel_index.db is not initialized or has no indexed rows",
    }
    payload["pipeline"] = _pipeline_status(items)
    return payload


def record_duplicate_review(
    group_id: str,
    keep_sidecar_paths: list[str],
    review_path: Path = DEFAULT_REVIEW_PATH,
    *,
    action: str = "keep_one",
    archived_sidecar_paths: Optional[list[str]] = None,
    reviewer: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Record duplicate-review choice and logical archive targets.

    This does not delete or move files. Query APIs hide archived sidecars by
    default and can be called with include_archived=True to show everything.
    """
    review_path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_duplicate_reviews(review_path)
    keep_sidecar_paths = [str(value) for value in keep_sidecar_paths if value]
    if archived_sidecar_paths is None:
        archived_sidecar_paths = []
    archived_sidecar_paths = [str(value) for value in archived_sidecar_paths if value]
    if action not in {"keep_one", "ignore"}:
        raise ValueError("action must be keep_one or ignore")

    entry = {
        "group_id": group_id,
        "action": action,
        "keep_sidecar_paths": keep_sidecar_paths,
        "kept_sidecar_path": keep_sidecar_paths[0] if keep_sidecar_paths else None,
        "archived_sidecar_paths": archived_sidecar_paths if action == "keep_one" else [],
        "reviewer": reviewer,
        "note": note,
        "reviewed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    data["reviews"].append(entry)
    review_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "review_path": relpath_from_root(review_path),
        "entry": entry,
    }


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenClaw travel index operations")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    query = sub.add_parser("query", help="query itineraries by structured filters")
    query.add_argument("--country", action="append", dest="countries", default=[])
    query.add_argument("--region", action="append", dest="regions", default=[])
    query.add_argument("--month", action="append", dest="months", type=int, default=[])
    query.add_argument("--airline", action="append", dest="airlines", default=[])
    query.add_argument("--feature", action="append", dest="features", default=[])
    query.add_argument("--price-min", type=int)
    query.add_argument("--price-max", type=int)
    query.add_argument("--duration-days", type=int)
    query.add_argument("--duration-min", type=int)
    query.add_argument("--duration-max", type=int)
    query.add_argument("--target", help="filter target_id")
    query.add_argument("--limit", type=int, default=10)

    latest = sub.add_parser("latest", help="query latest processed itineraries")
    latest.add_argument("--since", help="ISO datetime, e.g. 2026-04-30T00:00:00Z")
    latest.add_argument("--hours", type=float, help="look back N hours")
    latest.add_argument("--target", help="filter target_id")
    latest.add_argument("--limit", type=int, default=10)

    dup = sub.add_parser("duplicates", help="find likely duplicate products")
    dup.add_argument("--limit-groups", type=int, default=20)
    dup.add_argument("--price-bucket-size", type=int, default=5000)
    dup.add_argument("--include-same-source", action="store_true")
    dup.add_argument("--include-reviewed", action="store_true")

    status = sub.add_parser("status", help="summarize processing status")
    status.add_argument("--target", help="filter target_id")

    review = sub.add_parser("review-duplicate", help="record duplicate review")
    review.add_argument("--group-id", required=True)
    review.add_argument("--keep", action="append", default=[],
                        help="sidecar path to keep; repeat for multiple")
    review.add_argument("--archive", action="append", default=[],
                        help="sidecar path to logically archive; repeat for multiple")
    review.add_argument("--action", choices=["keep_one", "ignore"], default="keep_one")
    review.add_argument("--reviewer")
    review.add_argument("--note")
    review.add_argument("--review-path", default=str(DEFAULT_REVIEW_PATH))

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db)
    if args.command == "query":
        result = query_itineraries(
            db_path,
            countries=args.countries,
            regions=args.regions,
            months=args.months,
            airlines=args.airlines,
            features=args.features,
            price_min=args.price_min,
            price_max=args.price_max,
            duration_days=args.duration_days,
            duration_min=args.duration_min,
            duration_max=args.duration_max,
            target_id=args.target,
            limit=args.limit,
        )
    elif args.command == "latest":
        result = query_latest_results(
            db_path,
            since=args.since,
            hours=args.hours,
            target_id=args.target,
            limit=args.limit,
        )
    elif args.command == "duplicates":
        result = check_duplicates(
            db_path,
            limit_groups=args.limit_groups,
            price_bucket_size=args.price_bucket_size,
            include_same_source=args.include_same_source,
            include_reviewed=args.include_reviewed,
        )
    elif args.command == "status":
        result = processing_status(
            db_path,
            target_id=args.target,
        )
    elif args.command == "review-duplicate":
        result = record_duplicate_review(
            args.group_id,
            args.keep,
            Path(args.review_path),
            action=args.action,
            archived_sidecar_paths=args.archive,
            reviewer=args.reviewer,
            note=args.note,
        )
    else:
        raise AssertionError(args.command)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
