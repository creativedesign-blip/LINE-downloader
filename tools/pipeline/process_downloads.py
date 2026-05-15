"""Run the fixed RPA image-processing pipeline.

Pipeline contract:
  line-rpa/download/<target>/
    -> OCR classify via filter/filter.py
    -> keep travel images in line-rpa/download/<target>/travel/
    -> keep non-travel images in line-rpa/download/<target>/other/
    -> stitch config/brand.png into line-rpa/download/<target>/branded/
    -> rebuild config/travel_index.db

  line-rpa/download/<target>/inbox/ is also supported for compatibility.

This script intentionally reuses the existing OCR, branding, and indexing
modules instead of reimplementing their logic. It is the stable command that
OpenClaw or an RPA scheduler should call after images are downloaded.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.common.image_seen import file_sha256
from tools.common.json_store import load_json_dict, save_json_dict
from tools.common.targets import DOWNLOADS_DIR, PROJECT_ROOT, load_target_ids, relpath_from_root


FILTER_SCRIPT = PROJECT_ROOT / "filter" / "filter.py"
BRANDING_SCRIPT = PROJECT_ROOT / "tools" / "branding" / "brand_stitcher.py"
OCR_ENRICH_SCRIPT = PROJECT_ROOT / "tools" / "indexing" / "ocr_enrich.py"
SECOND_PASS_OCR_SCRIPT = PROJECT_ROOT / "tools" / "indexing" / "second_pass_ocr.py"
REINDEX_SCRIPT = PROJECT_ROOT / "tools" / "indexing" / "reindex.py"
DEFAULT_SECOND_PASS_LIMIT = 0

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
IMAGE_INDEX_PATH = DOWNLOADS_DIR / "image_index.json"
IMAGE_INDEX_SYNC_DIRS = ("travel", "other", "review")
# Sidecar cache so sync_image_index_for_targets doesn't re-hash every file
# on every pipeline run; keyed by repo-relative posix path.
HASH_CACHE_PATH = DOWNLOADS_DIR / ".image_hash_cache.json"


@dataclass
class StepResult:
    name: str
    command: list[str]
    exit_code: int
    elapsed_sec: float


@dataclass
class PipelineResult:
    target_ids: list[str]
    dry_run: bool
    steps: list[StepResult]
    exit_code: int
    review_images: dict[str, list[str]]


def discover_target_ids(target: Optional[str] = None) -> list[str]:
    if target:
        return [target]
    return load_target_ids()


def has_pending_images(input_dir: Path) -> bool:
    if not input_dir.exists():
        return False
    return any(
        item.is_file() and item.suffix.lower() in SUPPORTED_EXT
        for item in input_dir.iterdir()
    )


def load_image_index(path: Path = IMAGE_INDEX_PATH) -> dict[str, list[str]]:
    raw = load_json_dict(path)
    return {
        target_id: [str(value) for value in hashes]
        for target_id, hashes in raw.items()
        if isinstance(target_id, str) and isinstance(hashes, list)
    }


def save_image_index(index: dict[str, list[str]], path: Path = IMAGE_INDEX_PATH) -> None:
    save_json_dict(path, index)


def collect_images_in_folder(target_id: str, folder_name: str) -> list[Path]:
    folder = DOWNLOADS_DIR / target_id / folder_name
    if not folder.exists():
        return []
    return [
        item for item in sorted(folder.iterdir())
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXT
    ]


def collect_index_images(target_id: str) -> list[Path]:
    images: list[Path] = []
    for folder_name in IMAGE_INDEX_SYNC_DIRS:
        images.extend(collect_images_in_folder(target_id, folder_name))
    return images


def collect_review_images(target_ids: list[str]) -> dict[str, list[str]]:
    review: dict[str, list[str]] = {}
    for target_id in target_ids:
        paths = collect_images_in_folder(target_id, "review")
        if paths:
            review[target_id] = [relpath_from_root(path) for path in paths]
    return review


def load_hash_cache(path: Path = HASH_CACHE_PATH) -> dict[str, dict]:
    """{rel_posix_path: {"mtime": float, "size": int, "sha256": str}}."""
    return load_json_dict(path)


def save_hash_cache(cache: dict[str, dict], path: Path = HASH_CACHE_PATH) -> None:
    save_json_dict(path, cache)


def _cached_digest(entry: Optional[dict], st: object) -> Optional[str]:
    """Return the cached SHA256 if (mtime, size, sha256) all match, else None."""
    if not entry:
        return None
    if entry.get("mtime") != getattr(st, "st_mtime", None):
        return None
    if entry.get("size") != getattr(st, "st_size", None):
        return None
    return entry.get("sha256") or None


def sync_image_index_for_targets(
    target_ids: list[str],
    index_path: Path = IMAGE_INDEX_PATH,
    cache_path: Path = HASH_CACHE_PATH,
) -> StepResult:
    """Refresh image_index.json for `target_ids`, reusing cached SHA256
    digests when (mtime, size) match. Cache entries belonging to non-synced
    targets are passed through; entries for synced targets that no longer
    have a file on disk are dropped (natural prune)."""
    started = time.perf_counter()
    index = load_image_index(index_path)
    old_cache = load_hash_cache(cache_path)
    new_cache: dict[str, dict] = {}
    cache_hits = 0
    cache_misses = 0
    errors: list[str] = []

    # Derive prefixes from DOWNLOADS_DIR rather than hardcoding
    # "line-rpa/download/<tid>/" — the cache passthrough rule (drop entries
    # under synced targets that vanished on disk) breaks silently if the
    # downloads folder ever moves and the literal goes stale.
    target_path_prefixes = tuple(
        relpath_from_root(DOWNLOADS_DIR / tid) + "/" for tid in target_ids
    )

    for target_id in target_ids:
        hashes: set[str] = set()
        for image_path in collect_index_images(target_id):
            rel = relpath_from_root(image_path)
            try:
                st = image_path.stat()
            except OSError as exc:
                errors.append(f"{image_path}: {exc}")
                continue
            digest = _cached_digest(old_cache.get(rel), st)
            if digest is not None:
                cache_hits += 1
            else:
                try:
                    digest = file_sha256(image_path)
                except OSError as exc:
                    errors.append(f"{image_path}: {exc}")
                    continue
                cache_misses += 1
            new_cache[rel] = {"mtime": st.st_mtime, "size": st.st_size, "sha256": digest}
            hashes.add(digest)
        index[target_id] = sorted(hashes)

    # Carry over cache entries for targets we did NOT sync this run, so a
    # per-target invocation doesn't wipe the cache for everyone else.
    for rel, entry in old_cache.items():
        if rel in new_cache or rel.startswith(target_path_prefixes):
            continue
        new_cache[rel] = entry

    if not errors:
        save_image_index(index, index_path)
        save_hash_cache(new_cache, cache_path)
    elapsed = time.perf_counter() - started
    command = [
        "internal:sync-image-index",
        "--folders",
        ",".join(IMAGE_INDEX_SYNC_DIRS),
        "--targets",
        ",".join(target_ids),
        "--cache-hits",
        str(cache_hits),
        "--cache-misses",
        str(cache_misses),
    ]
    if errors:
        command.extend(["--errors", "; ".join(errors[:5])])
    return StepResult(
        name="sync-image-index",
        command=command,
        exit_code=1 if errors else 0,
        elapsed_sec=round(elapsed, 3),
    )


def run_step(name: str, command: list[str]) -> StepResult:
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=PROJECT_ROOT)
    elapsed = time.perf_counter() - started
    return StepResult(
        name=name,
        command=command,
        exit_code=int(completed.returncode),
        elapsed_sec=round(elapsed, 3),
    )


def targets_with_pending_images(target_ids: list[str]) -> list[str]:
    """Targets whose group root or inbox/ holds at least one image to filter."""
    pending: list[str] = []
    for target_id in target_ids:
        base = DOWNLOADS_DIR / target_id
        if has_pending_images(base) or has_pending_images(base / "inbox"):
            pending.append(target_id)
    return pending


def build_commands(args: argparse.Namespace, target_ids: list[str]) -> list[tuple[str, list[str]]]:
    """Build one shared subprocess per stage instead of one per target.

    Earlier versions spawned filter/ocr_enrich/branding once per target,
    which forced OCR and PIL/cv2/branding config to reload N times.
    The downstream scripts now accept repeatable --target so a single
    process can iterate over all targets with one model load.
    """
    commands: list[tuple[str, list[str]]] = []

    if not args.skip_ocr:
        pending_targets = targets_with_pending_images(target_ids)
        if pending_targets:
            cmd = [args.python, str(FILTER_SCRIPT)]
            for target_id in pending_targets:
                cmd.extend(["--target", target_id])
            commands.append(("ocr:all", cmd))

    if not args.skip_branding and target_ids:
        # brand_stitcher.py with no --target processes every indexed target
        # in one process; cheaper than N spawns each loading PIL/cv2/logo.
        cmd = [args.python, str(BRANDING_SCRIPT)]
        if args.force_branding:
            cmd.append("--force")
        commands.append(("branding:all", cmd))

    if not args.skip_ocr_enrich and target_ids:
        cmd = [args.python, str(OCR_ENRICH_SCRIPT)]
        for target_id in target_ids:
            cmd.extend(["--target", target_id])
        commands.append(("ocr-enrich:all", cmd))

    if getattr(args, "second_pass_ocr", False) and target_ids:
        second_pass_limit = getattr(args, "second_pass_limit", DEFAULT_SECOND_PASS_LIMIT)
        cmd = [
            args.python,
            str(SECOND_PASS_OCR_SCRIPT),
            "--provider",
            "paddle-ocr",
            "--limit",
            str(second_pass_limit),
        ]
        for target_id in target_ids:
            cmd.extend(["--target", target_id])
        commands.append(("second-pass-ocr:all", cmd))

    if not args.skip_index and target_ids:
        commands.append(("index:all", [args.python, str(REINDEX_SCRIPT)]))

    return commands


def print_human_summary(result: PipelineResult) -> None:
    targets = ", ".join(result.target_ids) if result.target_ids else "(none)"
    print(f"[pipeline] targets: {targets}")
    if result.dry_run:
        print("[pipeline] dry run, no commands executed")
    for step in result.steps:
        cmd = " ".join(step.command)
        print(
            f"[pipeline] {step.name}: exit={step.exit_code} "
            f"elapsed={step.elapsed_sec:.1f}s"
        )
        print(f"  {cmd}")
    if result.review_images:
        total_review = sum(len(paths) for paths in result.review_images.values())
        print(f"[pipeline] review_images={total_review}")
        for target_id, paths in result.review_images.items():
            print(f"  {target_id}: {len(paths)}")
    print(f"[pipeline] exit_code={result.exit_code}")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OCR -> travel filter -> branding -> travel_index.db.",
    )
    parser.add_argument("--target", help="only process line-rpa/download/<target>")
    parser.add_argument("--python", default=sys.executable or "python",
                        help="Python executable for child scripts")
    parser.add_argument("--skip-ocr", action="store_true",
                        help="skip OCR/classification")
    parser.add_argument("--skip-branding", action="store_true",
                        help="skip brand stitching")
    parser.add_argument("--skip-index", action="store_true",
                        help="skip travel_index.db rebuild")
    parser.add_argument("--skip-ocr-enrich", action="store_true",
                        help="skip cached OCR enrichment for travel sidecars")
    parser.add_argument("--second-pass-ocr", action="store_true",
                        help="rerun PaddleOCR only for suspicious travel sidecars before indexing")
    parser.add_argument("--second-pass-limit", type=int, default=DEFAULT_SECOND_PASS_LIMIT,
                        help="maximum suspicious sidecars to refresh per run; default 0 processes all")
    parser.add_argument("--force-branding", action="store_true",
                        help="rebuild branded images even if unchanged")
    parser.add_argument("--dry-run", action="store_true",
                        help="print planned commands without running them")
    parser.add_argument("--json", action="store_true",
                        help="print machine-readable JSON summary")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    target_ids = discover_target_ids(args.target)
    commands = build_commands(args, target_ids)

    steps: list[StepResult] = []
    exit_code = 0
    if args.dry_run:
        steps = [
            StepResult(name=name, command=command, exit_code=0, elapsed_sec=0.0)
            for name, command in commands
        ]
    else:
        for name, command in commands:
            step = run_step(name, command)
            steps.append(step)
            if step.exit_code != 0:
                exit_code = step.exit_code
                break
        if exit_code == 0 and target_ids:
            step = sync_image_index_for_targets(target_ids)
            steps.append(step)
            if step.exit_code != 0:
                exit_code = step.exit_code

    result = PipelineResult(
        target_ids=target_ids,
        dry_run=bool(args.dry_run),
        steps=steps,
        exit_code=exit_code,
        review_images=collect_review_images(target_ids),
    )

    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print_human_summary(result)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
