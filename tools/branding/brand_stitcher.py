"""Batch CLI + single-image API for stitching the company logo onto travel images.

Reads the classified images under `downloads/<targetId>/travel/`, overlays the
logo defined in `config/branding.json`, and writes the result to
`downloads/<targetId>/branded/` along with a branded sidecar JSON.

Idempotent: tracks a 3-tuple key (logo sha256, config hash, image mtime).
If none changed since the last stitch, the image is skipped.

Usage
-----
    python tools/branding/brand_stitcher.py                   # batch all targets
    python tools/branding/brand_stitcher.py --target metro    # one target
    python tools/branding/brand_stitcher.py --file <sidecar>  # one sidecar
    python tools/branding/brand_stitcher.py --dry-run -v      # preview
    python tools/branding/brand_stitcher.py --force           # rebuild all
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Optional

import cv2
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.branding.composite import composite, LogoTooSmallError
from tools.branding.io_utils import (
    image_of_sidecar,
    imread_unicode,
    imwrite_unicode,
    sidecar_of,
)
from tools.common.targets import PROJECT_ROOT, load_target_ids, relpath_from_root


DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "branding.json"
BRANDED_SIDECAR_VERSION = 1

logger = logging.getLogger("branding")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REQUIRED_KEYS = (
    "logoPath",
    "bandHeightRatio",
    "bandMinHeightPx",
    "bandColor",
    "logoWidthRatio",
    "logoScaleMax",
    "logoScaleMin",
    "minLogoPixelWidthRequired",
    "logoHorizontalAlign",
    "logoPaddingRatio",
    "outputFormat",
    "outputQuality",
)


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    missing = [k for k in REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"config missing keys: {missing}")
    if cfg["logoHorizontalAlign"] not in ("left", "center", "right"):
        raise ValueError(
            f"logoHorizontalAlign must be left|center|right, "
            f"got {cfg['logoHorizontalAlign']!r}"
        )
    if cfg["outputFormat"].lower() not in ("jpg", "jpeg", "png"):
        raise ValueError(
            f"outputFormat must be jpg|jpeg|png, got {cfg['outputFormat']!r}"
        )
    return cfg


def hash_config(cfg: dict) -> str:
    canonical = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Context passed to stitch_one
# ---------------------------------------------------------------------------

@dataclass
class StitchContext:
    cfg: dict
    logo_img: np.ndarray
    logo_path: Path
    logo_hash: str
    config_hash: str
    force: bool = False
    dry_run: bool = False


Result = Literal["processed", "skipped", "error"]


# ---------------------------------------------------------------------------
# Per-image pipeline
# ---------------------------------------------------------------------------

def stitch_one(sidecar_path: Path, ctx: StitchContext) -> Result:
    """Stitch a single travel sidecar's image. Returns one of: processed/skipped/error."""
    sidecar_path = Path(sidecar_path).resolve()

    if sidecar_path.suffix.lower() != ".json":
        logger.error("not a sidecar (.json) file: %s", sidecar_path)
        return "error"
    if not sidecar_path.exists():
        logger.error("sidecar does not exist: %s", sidecar_path)
        return "error"

    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            sidecar = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("broken sidecar %s: %s", sidecar_path.name, e)
        return "error"

    orig_img = image_of_sidecar(sidecar_path)
    if not orig_img.exists():
        logger.error("original image missing for sidecar %s", sidecar_path.name)
        return "error"

    branded_dir = orig_img.parent.parent / "branded"
    branded_img_path = branded_dir / f"{orig_img.stem}_branded{orig_img.suffix}"
    branded_sidecar_path = sidecar_of(branded_img_path)

    orig_mtime_ms = orig_img.stat().st_mtime_ns // 1_000_000

    if not ctx.force and branded_sidecar_path.exists():
        try:
            with open(branded_sidecar_path, "r", encoding="utf-8") as f:
                prev = json.load(f)
            same_logo = prev.get("logo", {}).get("sha256") == ctx.logo_hash
            same_cfg = prev.get("configHash") == ctx.config_hash
            same_mtime = prev.get("source", {}).get("imageMtime") == orig_mtime_ms
            if same_logo and same_cfg and same_mtime:
                logger.debug("skip (idempotent): %s", orig_img.name)
                return "skipped"
            logger.info("re-stitch (keys changed): %s", orig_img.name)
        except (json.JSONDecodeError, OSError):
            logger.warning("branded sidecar unreadable, will re-stitch: %s",
                           branded_sidecar_path.name)

    if ctx.dry_run:
        logger.info("[dry-run] would stitch: %s -> %s",
                    orig_img.relative_to(PROJECT_ROOT),
                    branded_img_path.relative_to(PROJECT_ROOT))
        return "processed"

    base = imread_unicode(orig_img, cv2.IMREAD_COLOR)
    if base is None:
        logger.error("failed to read original image: %s", orig_img.name)
        return "error"

    H, W = base.shape[:2]
    if H < 50 or W < 50:
        logger.warning("base image too small (%dx%d): %s", W, H, orig_img.name)
        return "skipped"

    try:
        out = composite(base, ctx.logo_img, ctx.cfg)
    except LogoTooSmallError as e:
        logger.warning("skip (logo too small): %s — %s", orig_img.name, e)
        return "skipped"
    except (ValueError, cv2.error) as e:
        logger.error("composite failed for %s: %s", orig_img.name, e)
        return "error"

    ext = "." + ctx.cfg["outputFormat"].lower().lstrip(".")
    quality = int(ctx.cfg["outputQuality"])
    if not imwrite_unicode(branded_img_path, out, ext=ext, quality=quality):
        logger.error("failed to write branded image: %s", branded_img_path)
        return "error"

    source = sidecar.get("source", {})
    logo_h, logo_w = ctx.logo_img.shape[:2]
    band_h = out.shape[0] - H
    branded_sidecar = {
        "version": BRANDED_SIDECAR_VERSION,
        "brandedAt": _iso_now(),
        "source": {
            "sidecarPath": relpath_from_root(sidecar_path),
            "imagePath": relpath_from_root(orig_img),
            "imageMtime": orig_mtime_ms,
            "targetId": source.get("targetId"),
            "groupName": source.get("groupName"),
        },
        "logo": {
            "path": relpath_from_root(ctx.logo_path),
            "sha256": ctx.logo_hash,
            "dimensions": {"w": int(logo_w), "h": int(logo_h)},
        },
        "output": {
            "path": relpath_from_root(branded_img_path),
            "dimensions": {"w": int(out.shape[1]), "h": int(out.shape[0])},
            "originalDimensions": {"w": int(W), "h": int(H)},
            "bandHeightPx": int(band_h),
        },
        "configHash": ctx.config_hash,
        "config": ctx.cfg,
    }
    try:
        with open(branded_sidecar_path, "w", encoding="utf-8") as f:
            json.dump(branded_sidecar, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("failed to write branded sidecar %s: %s",
                     branded_sidecar_path, e)
        return "error"

    logger.info("stitched: %s", orig_img.name)
    return "processed"


# ---------------------------------------------------------------------------
# Auto-init wrapper for filter.py inline integration
# ---------------------------------------------------------------------------

_AUTO_CTX: Optional[StitchContext] = None
_AUTO_INIT_FAILED: bool = False


def _build_default_ctx() -> StitchContext:
    cfg = load_config(DEFAULT_CONFIG_PATH)
    logo_path = (PROJECT_ROOT / cfg["logoPath"]).resolve()
    if not logo_path.exists():
        raise FileNotFoundError(f"logo not found: {logo_path}")
    if logo_path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise ValueError(f"unsupported logo format: {logo_path.suffix}")
    logo_img = imread_unicode(logo_path, cv2.IMREAD_UNCHANGED)
    if logo_img is None:
        raise RuntimeError(f"failed to decode logo: {logo_path}")
    return StitchContext(
        cfg=cfg,
        logo_img=logo_img,
        logo_path=logo_path,
        logo_hash=hash_file(logo_path),
        config_hash=hash_config(cfg),
    )


def stitch_one_auto(sidecar_path: Path) -> Result:
    """Lazy-init singleton wrapper for filter.py integration.

    Never raises — returns 'error' on any failure so the caller's main
    pipeline is unaffected by branding problems.
    """
    global _AUTO_CTX, _AUTO_INIT_FAILED

    if _AUTO_INIT_FAILED:
        return "error"

    if _AUTO_CTX is None:
        try:
            _AUTO_CTX = _build_default_ctx()
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as e:
            _AUTO_INIT_FAILED = True
            logger.error("branding auto-init failed: %s", e)
            return "error"

    try:
        return stitch_one(Path(sidecar_path), _AUTO_CTX)
    except OSError as e:
        logger.error("stitch_one I/O error for %s: %s", sidecar_path, e)
        return "error"


# ---------------------------------------------------------------------------
# Collect sidecars
# ---------------------------------------------------------------------------

def collect_sidecars(target_id: Optional[str] = None) -> list[Path]:
    if target_id is not None:
        target_ids = [target_id]
    else:
        target_ids = load_target_ids()

    out: list[Path] = []
    for tid in target_ids:
        travel_dir = PROJECT_ROOT / "downloads" / tid / "travel"
        if not travel_dir.exists():
            continue
        out.extend(sorted(travel_dir.glob("*.jpg.json")))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _target_of(sidecar: Path) -> str:
    try:
        parts = sidecar.resolve().relative_to(PROJECT_ROOT).parts
        if len(parts) >= 3 and parts[0] == "downloads":
            return parts[1]
    except ValueError:
        pass
    return "?"


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(name)s] %(levelname)s %(message)s",
    )


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Stitch company logo onto classified travel images.",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--batch", action="store_true",
                   help="process all targets (default when no --target/--file)")
    g.add_argument("--target", metavar="ID",
                   help="only process the given target id (e.g. 'metro')")
    g.add_argument("--file", metavar="PATH",
                   help="only process a single sidecar (.jpg.json)")
    p.add_argument("--force", action="store_true",
                   help="ignore idempotency key, re-stitch everything")
    p.add_argument("--dry-run", action="store_true",
                   help="list what would be done, write nothing")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="debug-level logging")
    p.add_argument("--config", metavar="PATH", default=str(DEFAULT_CONFIG_PATH),
                   help="path to branding.json (default: config/branding.json)")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    _setup_logging(args.verbose)
    t_start = time.perf_counter()

    try:
        cfg = load_config(Path(args.config))
    except (FileNotFoundError, ValueError) as e:
        logger.critical("config error: %s", e)
        return 2

    logo_path = (PROJECT_ROOT / cfg["logoPath"]).resolve()
    if not logo_path.exists():
        logger.critical("logo file not found: %s", logo_path)
        return 2
    if logo_path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        logger.critical("unsupported logo format %s (only .png/.jpg allowed)",
                        logo_path.suffix)
        return 2

    logo_img = imread_unicode(logo_path, cv2.IMREAD_UNCHANGED)
    if logo_img is None:
        logger.critical("failed to decode logo: %s", logo_path)
        return 2
    if logo_img.shape[1] < int(cfg["minLogoPixelWidthRequired"]):
        logger.warning(
            "logo width %dpx < recommended %dpx; upscale may blur. "
            "Consider a higher-resolution brand.png.",
            logo_img.shape[1], int(cfg["minLogoPixelWidthRequired"]),
        )

    ctx = StitchContext(
        cfg=cfg,
        logo_img=logo_img,
        logo_path=logo_path,
        logo_hash=hash_file(logo_path),
        config_hash=hash_config(cfg),
        force=args.force,
        dry_run=args.dry_run,
    )

    if args.file:
        sidecars: Iterable[Path] = [Path(args.file)]
    else:
        sidecars = collect_sidecars(target_id=args.target)

    sidecars = list(sidecars)
    if not sidecars:
        logger.info("no sidecars to process.")
        logger.info("[branding] processed=0 skipped=0 errors=0 elapsed=0.0s")
        return 0

    stats = {"processed": 0, "skipped": 0, "error": 0}
    per_target: dict[str, dict[str, int]] = defaultdict(
        lambda: {"processed": 0, "skipped": 0, "error": 0}
    )
    for sc in sidecars:
        result = stitch_one(sc, ctx)
        stats[result] += 1
        per_target[_target_of(sc)][result] += 1

    elapsed = time.perf_counter() - t_start
    logger.info(
        "[branding] processed=%d skipped=%d errors=%d elapsed=%.1fs",
        stats["processed"], stats["skipped"], stats["error"], elapsed,
    )
    for tid, s in sorted(per_target.items()):
        total = s["processed"] + s["skipped"] + s["error"]
        logger.info("  %s: %d/%d (processed/total), skipped=%d, errors=%d",
                    tid, s["processed"], total, s["skipped"], s["error"])

    return 0 if stats["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
