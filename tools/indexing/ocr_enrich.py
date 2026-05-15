"""Enrich travel sidecars with OCR text once, so later image searches are fast.

This is the pre-index step for the OpenClaw flow:
  travel image -> sidecar OCR text -> branding -> SQLite/search index

It uses RapidOCR because it is lightweight inside the project .venv. Existing
sidecars with OCR text are skipped unless --force is supplied.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.branding.io_utils import load_sidecar, save_sidecar
from tools.common.image_seen import file_sha256
from tools.common.targets import DOWNLOADS_DIR, load_target_ids
from tools.indexing.extractor import extract_price_from

from PIL import Image, ImageEnhance, ImageOps

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
logger = logging.getLogger("ocr-enrich")


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_images(target_id: Optional[str] = None) -> list[Path]:
    target_ids = [target_id] if target_id else load_target_ids()
    out: list[Path] = []
    for tid in target_ids:
        travel_dir = DOWNLOADS_DIR / tid / "travel"
        if not travel_dir.exists():
            continue
        for img in sorted(travel_dir.iterdir()):
            if img.is_file() and img.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
                out.append(img)
    return out


def _ocr_text(engine, image_path: Path) -> str:
    result, _ = engine(str(image_path))
    if not result:
        return ""
    lines: list[str] = []
    for item in result:
        if len(item) >= 2 and item[1]:
            lines.append(str(item[1]))
    return "\n".join(lines)


def _has_price_area_cue(text: str) -> bool:
    return any(cue in (text or "") for cue in ("含稅", "含税", "起", "元"))


def _ocr_image(engine, image: Image.Image) -> str:
    import numpy as np

    result, _ = engine(np.array(image))
    if not result:
        return ""
    lines: list[str] = []
    for item in result:
        if len(item) >= 2 and item[1]:
            lines.append(str(item[1]))
    return "\n".join(lines)


def _price_crop_candidates(image: Image.Image) -> list[tuple[str, Image.Image]]:
    width, height = image.size
    bottom45 = image.crop((0, int(height * 0.55), width, height))
    bottom35 = image.crop((0, int(height * 0.65), width, height))

    gray = ImageOps.grayscale(bottom45)
    gray = ImageEnhance.Contrast(gray).enhance(2.2)
    gray = ImageEnhance.Sharpness(gray).enhance(1.5)

    threshold = ImageOps.grayscale(bottom35)
    threshold = ImageEnhance.Contrast(threshold).enhance(2.5)
    threshold = threshold.point(lambda pixel: 255 if pixel > 170 else 0)

    return [
        ("price_bottom_gray.png", gray),
        ("price_bottom_threshold.png", threshold),
    ]


def _price_ocr_text(engine, image_path: Path, current_text: str) -> str:
    if extract_price_from(current_text):
        return ""
    if current_text and not _has_price_area_cue(current_text):
        return ""

    try:
        image = Image.open(image_path).convert("RGB")
    except Exception:
        return ""

    for _name, candidate in _price_crop_candidates(image):
        text = _ocr_image(engine, candidate)
        if extract_price_from(text):
            return text
    return ""


def enrich_one(engine, image_path: Path, *, force: bool = False) -> str:
    sidecar = load_sidecar(image_path)
    ocr = sidecar.get("ocr") or {}
    image_hash = file_sha256(image_path)

    if not force and ocr.get("text") and ocr.get("imageSha256") == image_hash:
        price_ocr = ocr.get("priceOcr") or {}
        if price_ocr.get("imageSha256") == image_hash:
            return "skipped"
        price_text = _price_ocr_text(engine, image_path, str(ocr.get("text") or ""))
        if not price_text:
            ocr["priceOcr"] = {
                "text": "",
                "engine": "rapidocr-onnxruntime",
                "imageSha256": image_hash,
                "classifiedAt": _iso_now(),
                "status": "not_found",
            }
            sidecar["ocr"] = ocr
            save_sidecar(image_path, sidecar)
            return "skipped"
        ocr["priceOcr"] = {
            "text": price_text,
            "engine": "rapidocr-onnxruntime",
            "imageSha256": image_hash,
            "classifiedAt": _iso_now(),
            "status": "found",
        }
        ocr["text"] = f"{ocr.get('text') or ''}\n{price_text}".strip()
        sidecar["ocr"] = ocr
        save_sidecar(image_path, sidecar)
        return "enriched"

    text = _ocr_text(engine, image_path)
    price_text = _price_ocr_text(engine, image_path, text)
    if price_text:
        text = f"{text}\n{price_text}".strip()
    source = sidecar.get("source") or {}
    if not source.get("targetId"):
        try:
            source["targetId"] = image_path.parent.parent.name
            source.setdefault("groupName", image_path.parent.parent.name)
        except Exception:
            pass

    ocr.update({
        "classifiedAt": _iso_now(),
        "classification": ocr.get("classification") or "travel",
        "text": text,
        "engine": "rapidocr-onnxruntime",
        "imageSha256": image_hash,
    })
    if price_text:
        ocr["priceOcr"] = {
            "text": price_text,
            "engine": "rapidocr-onnxruntime",
            "imageSha256": image_hash,
            "classifiedAt": _iso_now(),
            "status": "found",
        }
    sidecar["source"] = source
    sidecar["ocr"] = ocr
    sidecar.setdefault("savedAt", _iso_now())
    save_sidecar(image_path, sidecar)
    return "enriched"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OCR-enrich travel sidecars once for fast search.")
    p.add_argument("--target", action="append", default=None, metavar="ID",
                   help="repeatable target id; omit to process all download targets")
    p.add_argument("--force", action="store_true", help="re-OCR even when cached text exists")
    p.add_argument("--dry-run", action="store_true", help="list images only")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def collect_images_for_targets(targets: Optional[list[str]]) -> list[Path]:
    if not targets:
        return collect_images(None)
    out: list[Path] = []
    for tid in targets:
        out.extend(collect_images(tid))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="[%(name)s] %(levelname)s %(message)s")
    images = collect_images_for_targets(args.target)
    if args.dry_run:
        for img in images:
            logger.info("[dry-run] would OCR: %s", img)
        logger.info("[ocr-enrich] dry-run images=%d", len(images))
        return 0

    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as e:
        logger.critical("rapidocr-onnxruntime is not installed in this Python: %s", e)
        return 2

    engine = RapidOCR()
    stats = {"enriched": 0, "skipped": 0, "error": 0}
    for img in images:
        try:
            stats[enrich_one(engine, img, force=args.force)] += 1
        except Exception as e:
            stats["error"] += 1
            logger.error("OCR failed for %s: %s", img.name, e)
    logger.info("[ocr-enrich] enriched=%d skipped=%d errors=%d total=%d",
                stats["enriched"], stats["skipped"], stats["error"], len(images))
    return 0 if stats["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
