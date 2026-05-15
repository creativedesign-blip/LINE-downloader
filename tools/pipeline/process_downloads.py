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
from tools.common.targets import DOWNLOADS_DIR, PROJECT_ROOT, load_target_ids


FILTER_SCRIPT = PROJECT_ROOT / "filter" / "filter.py"
BRANDING_SCRIPT = PROJECT_ROOT / "tools" / "branding" / "brand_stitcher.py"
OCR_ENRICH_SCRIPT = PROJECT_ROOT / "tools" / "indexing" / "ocr_enrich.py"
REINDEX_SCRIPT = PROJECT_ROOT / "tools" / "indexing" / "reindex.py"

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
IMAGE_INDEX_PATH = DOWNLOADS_DIR / "image_index.json"
IMAGE_INDEX_SYNC_DIRS = ("travel", "other", "review")


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
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    index: dict[str, list[str]] = {}
    for target_id, hashes in data.items():
        if isinstance(target_id, str) and isinstance(hashes, list):
            index[target_id] = [str(value) for value in hashes]
    return index


def save_image_index(index: dict[str, list[str]], path: Path = IMAGE_INDEX_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


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
            review[target_id] = [path.relative_to(PROJECT_ROOT).as_posix() for path in paths]
    return review


def sync_image_index_for_targets(
    target_ids: list[str],
    index_path: Path = IMAGE_INDEX_PATH,
) -> StepResult:
    started = time.perf_counter()
    index = load_image_index(index_path)
    errors: list[str] = []
    for target_id in target_ids:
        hashes: set[str] = set()
        for image_path in collect_index_images(target_id):
            try:
                hashes.add(file_sha256(image_path))
            except OSError as exc:
                errors.append(f"{image_path}: {exc}")
        index[target_id] = sorted(hashes)
    if not errors:
        save_image_index(index, index_path)
    elapsed = time.perf_counter() - started
    command = [
        "internal:sync-image-index",
        "--folders",
        ",".join(IMAGE_INDEX_SYNC_DIRS),
        "--targets",
        ",".join(target_ids),
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
    which forced RapidOCR and PIL/cv2/branding config to reload N times.
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
