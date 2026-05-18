"""Backfill travel domain metadata into existing sidecars."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from tools.branding.io_utils import image_of_sidecar, save_sidecar
from tools.common.targets import load_target_ids, relpath_from_root
from tools.domains.travel.policy import apply_sidecar_metadata
from tools.indexing.reindex import collect_travel_sidecars


@dataclass(frozen=True)
class MigrationResult:
    sidecar_path: str
    status: str
    reason: str = ""


@dataclass(frozen=True)
class MigrationSummary:
    scanned: int
    updated: int
    fresh: int
    skipped: int
    errors: int
    elapsed_sec: float


def load_sidecar(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def ocr_text(sidecar: dict) -> str:
    ocr = sidecar.get("ocr") or {}
    return str(ocr.get("text") or "")


def migrate_sidecar(path: Path, *, dry_run: bool = False) -> MigrationResult:
    rel = relpath_from_root(path)
    try:
        sidecar = load_sidecar(path)
    except (OSError, json.JSONDecodeError) as exc:
        return MigrationResult(rel, "error", str(exc))

    ocr = sidecar.get("ocr") or {}
    if ocr.get("classification") in {"other", "error"}:
        return MigrationResult(rel, "skipped", "non_travel_classification")

    text = ocr_text(sidecar)
    updated = apply_sidecar_metadata(sidecar, text)
    if updated == sidecar:
        return MigrationResult(rel, "fresh")

    if not dry_run:
        save_sidecar(image_of_sidecar(path), updated)
    return MigrationResult(rel, "updated")


def migrate_sidecars(paths: list[Path], *, dry_run: bool = False) -> tuple[list[MigrationResult], MigrationSummary]:
    started = time.perf_counter()
    results = [migrate_sidecar(path, dry_run=dry_run) for path in paths]
    summary = MigrationSummary(
        scanned=len(paths),
        updated=sum(1 for item in results if item.status == "updated"),
        fresh=sum(1 for item in results if item.status == "fresh"),
        skipped=sum(1 for item in results if item.status == "skipped"),
        errors=sum(1 for item in results if item.status == "error"),
        elapsed_sec=round(time.perf_counter() - started, 3),
    )
    return results, summary


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill travel domain metadata into sidecars.")
    parser.add_argument("sidecars", nargs="*", type=Path, help="specific sidecar JSON files to migrate")
    parser.add_argument("--target", action="append", dest="targets", help="target id to scan; repeatable")
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing sidecars")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON summary")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    paths = list(args.sidecars)
    if not paths:
        target_ids = args.targets if args.targets else load_target_ids()
        paths = collect_travel_sidecars(target_ids)

    results, summary = migrate_sidecars(paths, dry_run=bool(args.dry_run))
    payload = {
        "summary": asdict(summary),
        "results": [asdict(item) for item in results],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        mode = "dry-run" if args.dry_run else "write"
        print(
            "[travel-sidecar-migrate] "
            f"mode={mode} scanned={summary.scanned} updated={summary.updated} "
            f"fresh={summary.fresh} skipped={summary.skipped} errors={summary.errors} "
            f"elapsed={summary.elapsed_sec:.1f}s"
        )
        for item in results:
            if item.status in {"updated", "error"}:
                suffix = f" ({item.reason})" if item.reason else ""
                print(f"  {item.status}: {item.sidecar_path}{suffix}")
    return 0 if summary.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
