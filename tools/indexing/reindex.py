"""Batch CLI to (re)build the travel itinerary SQLite index.

Reads every `line-rpa/download/<targetId>/travel/*.json` sidecar with
classification='travel', runs the three extractors, detects whether a
branded version exists, and upserts one row per sidecar.

Default mode wipes the table and rebuilds from scratch — cheap enough for
the expected data volume (~thousands of rows).

Usage:
    python tools/indexing/reindex.py
    python tools/indexing/reindex.py --target metro
    python tools/indexing/reindex.py --dry-run -v
    python tools/indexing/reindex.py --db /tmp/test.db
"""

from __future__ import annotations

import argparse
import atexit
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable, Literal, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.branding.io_utils import image_of_sidecar
from tools.common.targets import DOWNLOADS_DIR, PROJECT_ROOT, load_target_ids, relpath_from_root
from tools.indexing.extractor import (
    extract_airline,
    extract_country,
    extract_duration,
    extract_features,
    extract_months,
    extract_price_from,
    extract_region,
)
from tools.indexing.index_db import TravelIndex
from tools.indexing.plan_extractor import extract_plans

Result = Literal["indexed", "skipped", "error", "fresh"]


DEFAULT_DB_PATH = PROJECT_ROOT / "config" / "travel_index.db"
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

# Bump this when extractor logic / vocab semantically changes; existing rows
# with a stale extractor_version will be re-extracted on the next reindex
# even if their sidecar mtime is unchanged.
EXTRACTOR_VERSION = "1"

logger = logging.getLogger("indexing")


def collect_travel_sidecars(target_ids: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for tid in target_ids:
        travel_dir = DOWNLOADS_DIR / tid / "travel"
        if not travel_dir.exists():
            continue
        for sidecar in sorted(travel_dir.glob("*.*.json")):
            if image_of_sidecar(sidecar).suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
                out.append(sidecar)
    return out


def _find_branded(orig_image: Path) -> Optional[Path]:
    """Given a travel image path, return the matching branded image path
    if it exists, else None."""
    branded_dir = orig_image.parent.parent / "branded"
    for suffix in (".jpg", ".jpeg", ".png", orig_image.suffix):
        candidate = branded_dir / f"{orig_image.stem}_branded{suffix}"
        if candidate.exists():
            return candidate
    return None


def index_one(sidecar_path: Path, index: TravelIndex,
              sidecar_mtime: Optional[float] = None) -> Result:
    """Parse one sidecar and upsert a row."""
    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            sidecar = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("broken sidecar %s: %s", sidecar_path.name, e)
        return "error"

    ocr = sidecar.get("ocr") or {}
    if ocr.get("classification") != "travel":
        logger.debug("skip non-travel: %s", sidecar_path.name)
        return "skipped"

    text = ocr.get("text") or ""
    source = sidecar.get("source") or {}
    orig_img = image_of_sidecar(sidecar_path)
    fallback_target_id = orig_img.parent.parent.name if orig_img.parent.name == "travel" else None
    target_id = source.get("targetId") or fallback_target_id
    group_name = source.get("groupName") or target_id

    countries = extract_country(text)
    months = extract_months(text)
    price_from = extract_price_from(text)
    airlines = extract_airline(text)
    regions = extract_region(text)
    duration_days = extract_duration(text)
    features = extract_features(text)
    branded = _find_branded(orig_img)

    index.upsert(
        sidecar_path=relpath_from_root(sidecar_path),
        image_path=relpath_from_root(orig_img),
        target_id=target_id,
        group_name=group_name,
        branded_path=relpath_from_root(branded) if branded else None,
        countries=countries,
        months=months,
        price_from=price_from,
        airlines=airlines,
        regions=regions,
        duration_days=duration_days,
        features=features,
        source_time=sidecar.get("savedAt"),
        sidecar_mtime=sidecar_mtime,
        extractor_version=EXTRACTOR_VERSION,
    )
    sidecar_rel = relpath_from_root(sidecar_path)
    image_rel = relpath_from_root(orig_img)
    branded_rel = relpath_from_root(branded) if branded else None
    for plan in extract_plans(text):
        plan_id = f"{sidecar_rel}#plan:{plan.plan_no}"
        index.upsert_plan(
            plan_id=plan_id,
            sidecar_path=sidecar_rel,
            image_path=image_rel,
            branded_path=branded_rel,
            target_id=target_id,
            group_name=group_name,
            plan_no=plan.plan_no,
            title=plan.title,
            raw_text=plan.raw_text,
            countries=plan.countries or countries,
            regions=plan.regions or regions,
            airlines=plan.airlines or airlines,
            features=plan.features or features,
            months=plan.months,
            price_from=plan.price_from,
            duration_days=plan.duration_days,
        )
        for dep in plan.departures:
            dep_id = f"{plan_id}#dep:{dep.date_iso}"
            index.upsert_departure(
                departure_id=dep_id,
                plan_id=plan_id,
                sidecar_path=sidecar_rel,
                image_path=image_rel,
                branded_path=branded_rel,
                target_id=target_id,
                group_name=group_name,
                departure_date=dep.date_iso,
                date_text=dep.date_text,
                month=dep.month,
                day=dep.day,
                weekday=dep.weekday,
                price_from=plan.price_from,
                duration_days=plan.duration_days,
            )

    logger.debug(
        "indexed: %s (countries=%s months=%s price=%s duration=%s "
        "airlines=%s regions=%s features=%d branded=%s)",
        sidecar_path.name, countries, months, price_from, duration_days,
        airlines, regions, len(features), bool(branded),
    )
    return "indexed"


# ---------------------------------------------------------------------------
# Auto-init wrapper for filter.py inline integration
# ---------------------------------------------------------------------------

_AUTO_INDEX: Optional[TravelIndex] = None
_AUTO_INIT_FAILED: bool = False


def reindex_one_auto(sidecar_path: Path) -> Result:
    """Lazy-init singleton wrapper for filter.py integration.

    Opens TravelIndex with migrate=False so filter.py never silently drops
    rows when the schema changes. Never raises — returns 'error' on any
    failure so the caller's main pipeline is unaffected.
    """
    global _AUTO_INDEX, _AUTO_INIT_FAILED

    if _AUTO_INIT_FAILED:
        return "error"

    if _AUTO_INDEX is None:
        try:
            _AUTO_INDEX = TravelIndex(DEFAULT_DB_PATH, migrate=False)
        except (RuntimeError, OSError, sqlite3.Error) as e:
            _AUTO_INIT_FAILED = True
            logger.error("indexing auto-init failed: %s", e)
            return "error"
        atexit.register(_AUTO_INDEX.close)

    try:
        return index_one(Path(sidecar_path), _AUTO_INDEX)
    except (OSError, sqlite3.Error) as e:
        logger.error("index_one error for %s: %s", sidecar_path, e)
        return "error"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Incrementally (re)build the travel itinerary SQLite index."
    )
    p.add_argument("--target", metavar="ID",
                   help="only (re)index the given target id")
    p.add_argument("--dry-run", action="store_true",
                   help="list sidecars that would be indexed, touch no DB")
    p.add_argument("--force", action="store_true",
                   help="full rebuild: clear table and re-extract every sidecar "
                        "(default: skip rows whose sidecar mtime + extractor "
                        "version match the existing DB row)")
    p.add_argument("--db", metavar="PATH", default=str(DEFAULT_DB_PATH),
                   help=f"SQLite file (default: {DEFAULT_DB_PATH.name})")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="debug-level logging")
    return p.parse_args(argv)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(name)s] %(levelname)s %(message)s",
    )


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    _setup_logging(args.verbose)
    t_start = time.perf_counter()

    if args.target:
        target_ids = [args.target]
    else:
        target_ids = load_target_ids()

    sidecars = collect_travel_sidecars(target_ids)

    if args.dry_run:
        for sc in sidecars:
            logger.info("[dry-run] would index: %s", relpath_from_root(sc))
        logger.info("[indexing] dry-run: %d sidecars", len(sidecars))
        return 0

    stats = {"indexed": 0, "skipped": 0, "error": 0, "fresh": 0, "pruned": 0}
    with TravelIndex(Path(args.db)) as index:
        with index.transaction():
            if args.force:
                index.clear()

            disk_paths: set[str] = set()
            for sc in sidecars:
                rel = relpath_from_root(sc)
                disk_paths.add(rel)
                try:
                    mtime = sc.stat().st_mtime
                except OSError as e:
                    logger.warning("stat failed for %s: %s", sc.name, e)
                    stats["error"] += 1
                    continue

                if not args.force:
                    existing = index.get_freshness(rel)
                    if (existing
                            and existing.get("sidecar_mtime") == mtime
                            and existing.get("extractor_version") == EXTRACTOR_VERSION):
                        stats["fresh"] += 1
                        continue

                stats[index_one(sc, index, sidecar_mtime=mtime)] += 1

            # Prune rows for sidecars no longer on disk (only within targets
            # we actually scanned this run, so unrelated targets are untouched).
            for rel in index.list_sidecar_paths(target_ids) - disk_paths:
                index.delete(rel)
                stats["pruned"] += 1

        total_in_db = index.count()
        total_plans = index.plan_count()
        total_departures = index.departure_count()

    elapsed = time.perf_counter() - t_start
    logger.info(
        "[indexing] indexed=%d fresh=%d pruned=%d skipped=%d errors=%d "
        "in_db=%d plans=%d departures=%d elapsed=%.1fs",
        stats["indexed"], stats["fresh"], stats["pruned"], stats["skipped"],
        stats["error"], total_in_db, total_plans, total_departures, elapsed,
    )
    return 0 if stats["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
