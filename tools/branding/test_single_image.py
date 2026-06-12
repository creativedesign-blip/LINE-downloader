"""Ad-hoc single-image branding test.

Runs the same footer-detection + composite pipeline stitch_one() uses, but on an
arbitrary image file (no sidecar). OCR text is obtained inline so the CTA/foreign
/blank-band footer detectors behave exactly as in production.

Usage:
    python tools/branding/test_single_image.py <input_image> <output_image>
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.branding.brand_stitcher import (
    load_config,
    DEFAULT_CONFIG_PATH,
    detect_old_cta_cut_y,
    detect_foreign_footer_cut_y,
    detect_blank_bottom_band_cut_y,
)
from tools.branding.composite import composite, LogoTooSmallError
from tools.branding.io_utils import imread_unicode, imwrite_unicode
from tools.common.targets import PROJECT_ROOT


def get_ocr_text(base) -> str:
    try:
        from tools.common.rapidocr_adapter import create_rapidocr
        engine = create_rapidocr()
    except Exception as e:
        print(f"[ocr] RapidOCR unavailable ({e}); footer text detection disabled")
        return ""
    try:
        raw = engine(base)
    except Exception as e:
        print(f"[ocr] OCR run failed: {e}")
        return ""
    # rapidocr returns (boxes, texts, scores) or list-of-[box,text,score]
    texts = []
    try:
        from tools.common.rapidocr_adapter import rapidocr_with_boxes
        for _box, text, _conf in rapidocr_with_boxes(raw):
            texts.append(text)
    except Exception:
        pass
    return " ".join(texts)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    in_path = Path(sys.argv[1]).resolve()
    out_path = Path(sys.argv[2]).resolve()

    cfg = load_config(DEFAULT_CONFIG_PATH)
    logo_path = (PROJECT_ROOT / cfg["logoPath"]).resolve()
    logo_img = imread_unicode(logo_path, cv2.IMREAD_UNCHANGED)
    if logo_img is None:
        print(f"failed to load logo: {logo_path}")
        return 1

    base = imread_unicode(in_path, cv2.IMREAD_COLOR)
    if base is None:
        print(f"failed to load input image: {in_path}")
        return 1

    H, W = base.shape[:2]
    print(f"[in] {in_path.name} {W}x{H}, logo {logo_img.shape[1]}x{logo_img.shape[0]}")

    ocr_text = get_ocr_text(base)
    print(f"[ocr] {len(ocr_text)} chars")

    old_cta = detect_old_cta_cut_y(base, ocr_text, cfg)
    foreign = detect_foreign_footer_cut_y(base, ocr_text, cfg)

    cut_y = None
    reason = ""
    if old_cta is not None and foreign is not None:
        cut_y = max(old_cta, foreign); reason = "CTA+foreign"
    elif old_cta is not None:
        cut_y = old_cta; reason = "old CTA"
    elif foreign is not None:
        cut_y = foreign; reason = "foreign footer"

    blank = detect_blank_bottom_band_cut_y(base, cfg)
    if blank is not None and (cut_y is None or blank < cut_y):
        cut_y = blank
        reason = "blank band" if not reason else reason + "+blank band"

    if cut_y is not None:
        print(f"[crop] {reason}: y={cut_y} removed={H - cut_y}px")
        base = base[:cut_y, :, :].copy()
        H, W = base.shape[:2]
    else:
        print("[crop] none")

    target_width = int(cfg.get("outputTargetWidth") or 0)
    max_width = int(cfg.get("outputMaxWidth") or 0)
    if target_width and W != target_width:
        new_w = target_width
        new_h = max(1, int(round(H * (target_width / W))))
        interp = cv2.INTER_AREA if new_w < W else cv2.INTER_CUBIC
        base = cv2.resize(base, (new_w, new_h), interpolation=interp)
        H, W = base.shape[:2]
        print(f"[resize] -> {W}x{H} (target {target_width})")
    elif max_width and W > max_width:
        new_w = max_width
        new_h = max(1, int(round(H * (max_width / W))))
        base = cv2.resize(base, (new_w, new_h), interpolation=cv2.INTER_AREA)
        H, W = base.shape[:2]
        print(f"[resize] -> {W}x{H} (cap {max_width})")

    composite_cfg = cfg
    if cut_y is not None:
        composite_cfg = dict(cfg, detectExistingBottomBand=False)

    try:
        out = composite(base, logo_img, composite_cfg)
    except LogoTooSmallError as e:
        print(f"[skip] logo too small: {e}")
        return 1

    ext = out_path.suffix or ".jpg"
    output_dpi = int(cfg.get("outputDpi") or 0) or None
    if not imwrite_unicode(out_path, out, ext=ext, quality=int(cfg["outputQuality"]), dpi=output_dpi):
        print(f"failed to write: {out_path}")
        return 1

    print(f"[out] {out_path}  {out.shape[1]}x{out.shape[0]}  band={out.shape[0]-H}px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
