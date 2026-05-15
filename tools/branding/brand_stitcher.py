"""Batch CLI + single-image API for stitching the company logo onto travel images.

Reads classified images under `line-rpa/download/<targetId>/travel/`, overlays the
logo defined in `config/branding.json`, and writes the result to
`line-rpa/download/<targetId>/branded/` along with a branded sidecar JSON.

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
from tools.common.targets import DOWNLOADS_DIR, PROJECT_ROOT, load_target_ids, relpath_from_root


DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "branding.json"
BRANDED_SIDECAR_VERSION = 1
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

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
    "detectExistingBottomBand",
    "whiteThreshold",
    "whiteMinCoverageRatio",
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
# Old CTA footer detection/cropping
# ---------------------------------------------------------------------------

CTA_KEYWORDS = (
    "請洽",
    "请洽",
    "洽詢",
    "洽询",
    "詳情",
    "详情",
    "查詢",
    "查询",
    # Common OCR confusions seen in current LINE samples.
    "群情請洽",
    "詳情請治",
)


def _has_cta_keyword(ocr_text: str) -> bool:
    text = "".join(str(ocr_text or "").split())
    return any(k in text for k in CTA_KEYWORDS)


def detect_old_cta_cut_y(base: np.ndarray, ocr_text: str, cfg: dict) -> Optional[int]:
    """Return y where an old bottom CTA/contact box should be cut off.

    Conservative by design: current samples show true old CTA boxes contain OCR
    text like 「詳情請洽」 and have a bottom-anchored low-content white rectangle.
    White-heavy itinerary/price areas without CTA text must not be cropped.
    """
    if not _has_cta_keyword(ocr_text):
        return None

    H, W = base.shape[:2]
    if H < 200 or W < 200:
        return None

    threshold = int(cfg.get("whiteThreshold", 240))
    near_white = np.all(base >= threshold, axis=2)
    row_coverage = near_white.mean(axis=1)

    # Smooth so 「詳情請洽」 text strokes do not break the white box.
    window = max(9, min(31, (H // 90) * 2 + 1))
    smooth = np.convolve(row_coverage, np.ones(window) / float(window), mode="same")

    search_top = int(H * 0.60)
    white_threshold = 0.90 if H >= 2000 else 0.84
    gap_limit = max(6, int(H * 0.008))

    # The CTA box must be attached to, or very close to, the bottom.
    y = H - 1
    while y >= search_top and smooth[y] < white_threshold:
        y -= 1
    if H - 1 - y > max(18, int(H * 0.025)):
        return None

    bottom = y
    gap = 0
    top = y
    while y >= search_top:
        if smooth[y] >= white_threshold:
            top = y
            gap = 0
        else:
            gap += 1
            if gap > gap_limit:
                break
        y -= 1

    box_h = bottom - top + 1
    # Some suppliers use a very short one-line 「詳情請洽」 box (e.g. 九寨溝
    # sample: ~52px on a 1492px image), so keep the minimum a bit lower.
    if box_h < max(45, int(H * 0.03)) or box_h > int(H * 0.22):
        return None
    if float(smooth[top:bottom + 1].mean()) < 0.80:
        return None

    # Refine to the upper border/separator line if present.
    gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.int16)
    row_diff = np.abs(np.diff(gray, axis=0)).mean(axis=1)
    # Keep refinement close to the detected white-box top.  A larger window can
    # jump to price/table separators above the CTA box on tall itinerary sheets.
    lo = max(search_top, top - max(20, int(H * 0.006)))
    hi = min(H - 2, top + max(10, int(H * 0.006)))
    edge_y = int(lo + np.argmax(row_diff[lo:hi + 1])) if hi >= lo else top

    # The edge must be plausible; otherwise use the detected white-box top.
    cut_y = edge_y if row_diff[edge_y] >= max(18.0, row_diff[search_top:H - 1].mean() * 1.8) else top

    # Crop a little above the detected CTA top so the old box border/shadow is
    # removed too.  Keep it small to avoid eating itinerary/price content.
    crop_margin = max(5, min(12, int(round(H * 0.004))))
    cut_y = max(1, cut_y - crop_margin)

    removed = H - cut_y
    if removed < max(60, int(H * 0.04)) or removed > int(H * 0.25):
        return None
    return max(1, min(cut_y, H - 1))


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
    ext = "." + ctx.cfg["outputFormat"].lower().lstrip(".")
    branded_img_path = branded_dir / f"{orig_img.stem}_branded{ext}"
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

    old_cta_cut_y = detect_old_cta_cut_y(
        base,
        (sidecar.get("ocr") or {}).get("text", ""),
        ctx.cfg,
    )
    original_h_for_meta = H
    if old_cta_cut_y is not None:
        logger.info(
            "crop old CTA footer: %s y=%d removed=%dpx",
            orig_img.name,
            old_cta_cut_y,
            H - old_cta_cut_y,
        )
        base = base[:old_cta_cut_y, :, :].copy()
        H, W = base.shape[:2]

    try:
        out = composite(base, ctx.logo_img, ctx.cfg)
    except LogoTooSmallError as e:
        logger.warning("skip (logo too small): %s — %s", orig_img.name, e)
        return "skipped"
    except (ValueError, cv2.error) as e:
        logger.error("composite failed for %s: %s", orig_img.name, e)
        return "error"

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
            "originalDimensions": {"w": int(W), "h": int(original_h_for_meta)},
            "compositeBaseDimensions": {"w": int(W), "h": int(H)},
            "oldCtaCropY": int(old_cta_cut_y) if old_cta_cut_y is not None else None,
            "oldCtaRemovedPx": int(original_h_for_meta - old_cta_cut_y) if old_cta_cut_y is not None else 0,
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
        travel_dir = DOWNLOADS_DIR / tid / "travel"
        if not travel_dir.exists():
            continue
        for sidecar in sorted(travel_dir.glob("*.*.json")):
            if image_of_sidecar(sidecar).suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
                out.append(sidecar)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _target_of(sidecar: Path) -> str:
    try:
        parts = sidecar.resolve().relative_to(PROJECT_ROOT).parts
        if len(parts) >= 4 and parts[0] == "line-rpa" and parts[1] == "download":
            return parts[2]
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
