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
import re
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
    if cfg.get("outputMaxWidth") is not None:
        try:
            max_w = int(cfg["outputMaxWidth"])
        except (TypeError, ValueError):
            raise ValueError(
                f"outputMaxWidth must be a positive int, got {cfg['outputMaxWidth']!r}"
            )
        if max_w <= 0:
            raise ValueError(f"outputMaxWidth must be positive, got {max_w}")
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
    ocr_engine: Optional[object] = None


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
# Foreign company footer detection (OCR bounding-box based)
# ---------------------------------------------------------------------------

FOREIGN_FOOTER_PATTERNS = [
    re.compile(r"(?:TEL|FAX|電話|傳真)", re.IGNORECASE),
    re.compile(r"\(?\d{2,3}\)?[\s\-]?\d{3,4}[\s\-]?\d{4}"),
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"旅行社"),
    re.compile(r"品保|交觀"),
]

_FOOTER_OCR_ENGINE = None
_FOOTER_OCR_UNAVAILABLE = False


def _get_footer_ocr_engine():
    global _FOOTER_OCR_ENGINE, _FOOTER_OCR_UNAVAILABLE
    if _FOOTER_OCR_UNAVAILABLE:
        return None
    if _FOOTER_OCR_ENGINE is None:
        try:
            from tools.common.rapidocr_adapter import create_rapidocr
            _FOOTER_OCR_ENGINE = create_rapidocr()
        except (ImportError, FileNotFoundError, ValueError, RuntimeError, OSError) as e:
            _FOOTER_OCR_UNAVAILABLE = True
            logger.debug("RapidOCR not available, foreign footer OCR disabled: %s", e)
            return None
    return _FOOTER_OCR_ENGINE


def set_footer_ocr_engine(engine) -> None:
    """Share an already-loaded RapidOCR engine for foreign-footer detection.

    filter.py loads RapidOCR for classification; passing that engine here lets
    the inline branding path's footer detection reuse it instead of loading a
    second copy of the model into the same process. No-op on None.
    """
    global _FOOTER_OCR_ENGINE, _FOOTER_OCR_UNAVAILABLE
    if engine is not None:
        _FOOTER_OCR_ENGINE = engine
        _FOOTER_OCR_UNAVAILABLE = False


def _has_foreign_footer_text(ocr_text: str) -> bool:
    """Quick pre-check: does the full OCR text contain >=2 footer-like patterns?"""
    text = str(ocr_text or "")
    if not text:
        return False
    hits = 0
    for p in FOREIGN_FOOTER_PATTERNS:
        if p.search(text):
            hits += 1
            if hits >= 2:
                return True
    return False


def detect_foreign_footer_cut_y(
    base: np.ndarray,
    ocr_text: str,
    cfg: dict,
    ocr_engine: Optional[object] = None,
) -> Optional[int]:
    """Detect a foreign company footer via OCR bounding boxes + pattern matching.

    Only runs when the sidecar OCR text already contains footer-like patterns
    (TEL, FAX, 旅行社, URL, etc.).  Re-runs RapidOCR on the bottom 25% of the
    image to obtain bounding boxes, then uses the topmost matching box as the
    cut point.
    """
    if not cfg.get("detectForeignFooter", False):
        return None

    if not _has_foreign_footer_text(ocr_text):
        return None

    H, W = base.shape[:2]
    if H < 200 or W < 200:
        return None

    engine = ocr_engine or _get_footer_ocr_engine()
    if engine is None:
        return None

    from tools.common.rapidocr_adapter import rapidocr_with_boxes

    crop_top = int(H * 0.75)
    bottom_crop = base[crop_top:, :, :]

    try:
        raw_output = engine(bottom_crop)
    except Exception as e:
        logger.debug("footer OCR failed: %s", e)
        return None

    items = rapidocr_with_boxes(raw_output)
    if not items:
        return None

    footer_boxes: list[tuple[float, float, str]] = []
    for box, text, _conf in items:
        if any(p.search(text) for p in FOREIGN_FOOTER_PATTERNS):
            try:
                min_y = min(pt[1] for pt in box) + crop_top
                max_y = max(pt[1] for pt in box) + crop_top
            except (TypeError, IndexError, ValueError):
                continue
            footer_boxes.append((min_y, max_y, text))

    if not footer_boxes:
        return None

    all_footer_text = " ".join(t for _, _, t in footer_boxes)
    distinct_hits = sum(1 for p in FOREIGN_FOOTER_PATTERNS if p.search(all_footer_text))
    if distinct_hits < 2:
        return None

    cut_y = int(min(b[0] for b in footer_boxes))

    crop_margin = max(5, min(15, int(round(H * 0.005))))
    cut_y = max(1, cut_y - crop_margin)

    removed = H - cut_y
    if removed < int(H * 0.03) or removed > int(H * 0.25):
        return None

    return cut_y


# ---------------------------------------------------------------------------
# Empty (content-free) colored bottom band detection
# ---------------------------------------------------------------------------

def detect_blank_bottom_band_cut_y(base: np.ndarray, cfg: dict) -> Optional[int]:
    """Return y where a content-free, same-color bottom band should be cut off.

    Unlike detect_old_cta_cut_y (which removes a *white* CTA box holding text
    like 「請洽查詢」), this targets a bottom band of ANY solid color that holds
    NO content at all — e.g. the empty teal/blue margin many DM templates leave
    below the last line of text — so the brand band sits directly under the
    content instead of below a wasted empty strip.

    Safety: the scan walks up from the bottom and stops at the first row that
    carries content (text/photo), so disclaimer fine print such as
    「含稅不含小費」 is never swallowed — only genuinely-empty rows below it are
    removed. Composed in stitch_one so it never reduces a CTA/foreign cut, so a
    「請洽查詢」 box still gets covered. Gated by cfg["detectBlankColorFooter"].
    """
    if not cfg.get("detectBlankColorFooter", False):
        return None

    H, W = base.shape[:2]
    if H < 200 or W < 200:
        return None

    content_std = float(cfg.get("blankFooterContentStd", 12.0))
    color_tol = float(cfg.get("blankFooterColorTol", 40.0))

    max_scan = max(1, int(H * 0.45))
    min_band_h = max(60, int(H * 0.04))
    anchor_h = min(max(8, int(H * 0.01)), max_scan)

    # Only the bottom max_scan rows are ever inspected, so work on that slice and
    # skip a full-image float32 copy + per-row std over rows we never read.
    # Slice-local index i maps to original row y = (H - max_scan) + i.
    y0 = H - max_scan
    b = base[y0:].astype(np.float32)
    # Per-row horizontal variation: ~0 for a solid/smooth-gradient row, high for
    # any text or photo. This is what separates "empty" from "fine print".
    row_score = b.std(axis=1).mean(axis=1)

    # The very bottom must itself be content-free; otherwise the bottom holds
    # content and we should append a fresh band rather than crop.
    if float(row_score[max_scan - anchor_h:].mean()) >= content_std:
        return None

    ref = np.median(b[max_scan - anchor_h:].reshape(-1, 3), axis=0)
    top = H
    for i in range(max_scan - 1, -1, -1):
        uniform = row_score[i] < content_std
        same_color = float(np.abs(b[i].mean(axis=0) - ref).mean()) < color_tol
        if not (uniform and same_color):
            break          # stop at the first content row — never walk past text
        top = y0 + i

    # Reject too-small (noise) and, like detect_old_cta_cut_y /
    # detect_foreign_footer_cut_y, too-large crops: a low-variance photo bottom
    # must not lose up to max_scan (45%) of real content.
    removed = H - top
    if removed < min_band_h or removed > int(H * 0.25):
        return None
    return top


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

    ocr_text = (sidecar.get("ocr") or {}).get("text", "")

    old_cta_cut_y = detect_old_cta_cut_y(base, ocr_text, ctx.cfg)
    foreign_footer_cut_y = detect_foreign_footer_cut_y(
        base, ocr_text, ctx.cfg, ocr_engine=ctx.ocr_engine,
    )

    cut_y: Optional[int] = None
    cut_reason = ""
    if old_cta_cut_y is not None and foreign_footer_cut_y is not None:
        # Take the more conservative (closer to bottom) cut to avoid
        # amplifying a false positive from either detector.
        cut_y = max(old_cta_cut_y, foreign_footer_cut_y)
        cut_reason = "CTA+foreign footer"
    elif old_cta_cut_y is not None:
        cut_y = old_cta_cut_y
        cut_reason = "old CTA footer"
    elif foreign_footer_cut_y is not None:
        cut_y = foreign_footer_cut_y
        cut_reason = "foreign footer"

    # An empty same-color band is always safe to remove. Apply it only if it
    # removes *more* than the text detectors (smaller y); never let it reduce
    # their cut, so a 「請洽查詢」/foreign box stays fully covered.
    blank_band_cut_y = detect_blank_bottom_band_cut_y(base, ctx.cfg)
    if blank_band_cut_y is not None and (cut_y is None or blank_band_cut_y < cut_y):
        cut_y = blank_band_cut_y
        cut_reason = "blank band" if not cut_reason else cut_reason + "+blank band"

    original_h_for_meta = H
    original_w_for_meta = W
    if cut_y is not None:
        logger.info(
            "crop %s: %s y=%d removed=%dpx",
            cut_reason,
            orig_img.name,
            cut_y,
            H - cut_y,
        )
        base = base[:cut_y, :, :].copy()
        H, W = base.shape[:2]

    # Cap output resolution at outputMaxWidth (if set). Source LINE images
    # are often 2480px+ wide which is wasteful for both /media/thumbnail
    # generation and final delivery — LINE Messaging API auto-compresses
    # to ~1280px on mobile clients anyway. CTA detection runs before this
    # resize so the heuristics keep their full-resolution accuracy.
    max_width = int(ctx.cfg.get("outputMaxWidth") or 0)
    if max_width and W > max_width:
        new_w = max_width
        new_h = max(1, int(round(H * (max_width / W))))
        base = cv2.resize(base, (new_w, new_h), interpolation=cv2.INTER_AREA)
        H, W = base.shape[:2]
        logger.debug("resized base to %dx%d (cap %dpx)", W, H, max_width)

    composite_cfg = ctx.cfg
    if cut_y is not None:
        composite_cfg = dict(ctx.cfg, detectExistingBottomBand=False)

    try:
        out = composite(base, ctx.logo_img, composite_cfg)
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
            "originalDimensions": {"w": int(original_w_for_meta), "h": int(original_h_for_meta)},
            "compositeBaseDimensions": {"w": int(W), "h": int(H)},
            "footerCropY": int(cut_y) if cut_y is not None else None,
            "footerCropReason": cut_reason or None,
            "footerRemovedPx": int(original_h_for_meta - cut_y) if cut_y is not None else 0,
            "bandHeightPx": int(band_h),
        },
        "configHash": ctx.config_hash,
        "config": ctx.cfg,
    }
    # tmp+replace so a crash mid-write doesn't leave a truncated JSON that
    # later breaks reindex.py. Matches the pattern in tools/common/json_store.py.
    branded_sidecar_tmp = branded_sidecar_path.with_suffix(branded_sidecar_path.suffix + ".tmp")
    try:
        with open(branded_sidecar_tmp, "w", encoding="utf-8") as f:
            json.dump(branded_sidecar, f, ensure_ascii=False, indent=2)
        branded_sidecar_tmp.replace(branded_sidecar_path)
    except OSError as e:
        logger.error("failed to write branded sidecar %s: %s",
                     branded_sidecar_path, e)
        try:
            branded_sidecar_tmp.unlink(missing_ok=True)
        except OSError:
            pass
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
    except Exception as e:
        logger.error("stitch_one error for %s: %s", sidecar_path, e)
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
