"""Core compositing algorithm: overlay a fixed logo on a white band below base.

Pure functions — no filesystem I/O, no config reading. Callers supply the
loaded base image, loaded logo image, and a fully resolved cfg dict.

Bi-directional scaling: logo grows with base width (target = W * logoWidthRatio),
capped at logoScaleMax to avoid upscale blur, and floored at logoScaleMin
below which the output is deemed unreadable (raises LogoTooSmallError so the
caller can skip that image).
"""

from __future__ import annotations

import cv2
import numpy as np


class LogoTooSmallError(ValueError):
    """Scale fell below cfg['logoScaleMin'] — logo would be unreadable."""


def composite(
    base: np.ndarray,
    logo: np.ndarray,
    cfg: dict,
) -> np.ndarray:
    """Overlay `logo` onto a white band below `base` and return the new image.

    Args:
        base: H x W x 3 uint8 BGR. If a 4-channel BGRA is given, the alpha
            channel is dropped (base is assumed fully opaque).
        logo: h x w x {1,3,4} uint8 or h x w gray. Normalized internally.
        cfg: dict with keys:
            - bandHeightRatio (float)
            - bandMinHeightPx (int)
            - bandColor (list[int] BGR, length 3)
            - logoWidthRatio (float)
            - logoScaleMax (float)
            - logoScaleMin (float)
            - logoHorizontalAlign ("left"|"center"|"right")
            - logoPaddingRatio (float)

    Returns:
        (H + band_h) x W x 3 uint8 BGR ndarray.

    Raises:
        LogoTooSmallError: when the computed scale is below logoScaleMin,
            meaning the base image is too small to host a readable logo.
        ValueError: on malformed inputs (unsupported channel count, wrong dtype).
    """
    base = _normalize_base(base)
    logo = _normalize_logo_channels(logo)

    H, W = base.shape[:2]
    h0, w0 = logo.shape[:2]

    pad = int(W * float(cfg["logoPaddingRatio"]))
    existing_band_h = 0
    if cfg.get("detectExistingBottomBand", False):
        existing_band_h = _detect_bottom_band_height(
            base,
            threshold=int(cfg.get("whiteThreshold", 240)),
            min_coverage=float(cfg.get("whiteMinCoverageRatio", 0.96)),
        )

    available_w = max(1, W - (pad * 2))
    target_w = available_w * float(cfg["logoWidthRatio"])
    scale_ideal = target_w / w0 if w0 > 0 else 0.0
    scale_max = float(cfg["logoScaleMax"])
    scale_min = float(cfg["logoScaleMin"])

    scale = min(scale_ideal, scale_max)
    if scale < scale_min:
        raise LogoTooSmallError(
            f"scale={scale:.3f} < logoScaleMin={scale_min}; "
            f"base {W}x{H} too small for logo {w0}x{h0}"
        )

    new_h = max(1, int(round(h0 * scale)))
    new_w = max(1, int(round(w0 * scale)))

    required_band_h = max(
        int(cfg["bandMinHeightPx"]),
        int(H * float(cfg["bandHeightRatio"])),
        new_h + (pad * 2),
    )
    band_h = max(existing_band_h, required_band_h)
    added_band_h = max(0, band_h - existing_band_h)

    canvas = _build_canvas(H, W, added_band_h, cfg["bandColor"])
    canvas[0:H, 0:W] = base

    band_top = H - existing_band_h

    if (new_h, new_w) != (h0, w0):
        interp = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
        logo_r = cv2.resize(logo, (new_w, new_h), interpolation=interp)
    else:
        logo_r = logo

    if cfg["logoHorizontalAlign"] == "left":
        x = pad
    elif cfg["logoHorizontalAlign"] == "right":
        x = W - new_w - pad
    else:
        x = (W - new_w) // 2
    y = band_top + (band_h - new_h) // 2

    x = max(0, min(x, W - new_w))
    y = max(band_top, min(y, band_top + band_h - new_h))

    if logo_r.ndim == 3 and logo_r.shape[2] == 4:
        _alpha_blend_into(canvas, logo_r, x, y)
    else:
        canvas[y:y + new_h, x:x + new_w] = logo_r

    return canvas


def _normalize_base(base: np.ndarray) -> np.ndarray:
    """Ensure base is H x W x 3 uint8 BGR. Drops alpha if present."""
    if base.dtype != np.uint8:
        raise ValueError(f"base must be uint8, got {base.dtype}")
    if base.ndim == 2:
        return cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
    if base.ndim == 3:
        c = base.shape[2]
        if c == 3:
            return base
        if c == 4:
            return base[:, :, :3].copy()
        if c == 1:
            return cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
    raise ValueError(f"Unsupported base shape: {base.shape}")


def _normalize_logo_channels(logo: np.ndarray) -> np.ndarray:
    """Accept {gray 2D, gray 3D-1ch, BGR 3ch, BGRA 4ch}; keep alpha if present."""
    if logo.dtype != np.uint8:
        raise ValueError(f"logo must be uint8, got {logo.dtype}")
    if logo.ndim == 2:
        return cv2.cvtColor(logo, cv2.COLOR_GRAY2BGR)
    if logo.ndim == 3:
        c = logo.shape[2]
        if c == 1:
            return cv2.cvtColor(logo, cv2.COLOR_GRAY2BGR)
        if c == 3:
            return logo
        if c == 4:
            return logo
    raise ValueError(f"Unsupported logo shape: {logo.shape}")


def _detect_bottom_band_height(
    base: np.ndarray,
    threshold: int = 240,
    min_coverage: float = 0.96,
) -> int:
    """Return height of a bottom CTA/white band touching image bottom.

    The old implementation required every row to be almost entirely white.
    That misses common travel DM footers where a white band contains black text
    like 「請洽查詢」.  This version still anchors at the image bottom, but uses a
    rolling row-coverage score and allows short dark gaps caused by text.
    """
    H, W = base.shape[:2]
    if H <= 0 or W <= 0:
        return 0

    near_white = np.all(base >= threshold, axis=2)
    row_coverage = near_white.mean(axis=1)

    # Smooth row coverage so text strokes do not split one white footer into
    # many tiny fragments.  For config default 0.96, use ~0.88 after smoothing.
    window = max(9, min(31, H // 80 * 2 + 1))
    kernel = np.ones(window, dtype=np.float32) / float(window)
    smooth = np.convolve(row_coverage, kernel, mode="same")
    coverage_threshold = max(0.82, min(0.95, min_coverage - 0.08))

    max_scan = max(1, int(H * 0.35))
    min_band_h = max(60, int(H * 0.04))
    gap_limit = max(8, int(H * 0.015))
    anchor_h = min(max(8, int(H * 0.01)), max_scan)

    # Must be actually white/light at the very bottom; otherwise this is a
    # normal image and we should append a new logo band instead of replacing.
    if float(row_coverage[H - anchor_h:H].mean()) < coverage_threshold:
        return 0

    top_limit = H - max_scan
    gap = 0
    top = H
    for y in range(H - 1, top_limit - 1, -1):
        if smooth[y] >= coverage_threshold:
            gap = 0
            top = y
        else:
            gap += 1
            if gap > gap_limit:
                break

    band_h = H - top
    if band_h < min_band_h:
        return 0
    return band_h


def _build_canvas(
    H: int,
    W: int,
    band_h: int,
    band_color_bgr,
) -> np.ndarray:
    """Allocate (H+band_h, W, 3) uint8 filled with the band color."""
    if len(band_color_bgr) != 3:
        raise ValueError(
            f"bandColor must be a 3-element BGR list, got {band_color_bgr}"
        )
    b, g, r = (int(v) for v in band_color_bgr)
    canvas = np.empty((H + band_h, W, 3), dtype=np.uint8)
    canvas[:, :, 0] = b
    canvas[:, :, 1] = g
    canvas[:, :, 2] = r
    return canvas


def _alpha_blend_into(
    canvas: np.ndarray,
    rgba: np.ndarray,
    x: int,
    y: int,
) -> None:
    """Straight-alpha blend a BGRA logo onto the BGR canvas in place."""
    h, w = rgba.shape[:2]
    roi = canvas[y:y + h, x:x + w]

    alpha = rgba[:, :, 3:4].astype(np.float32) / 255.0
    fg = rgba[:, :, :3].astype(np.float32)
    bg = roi.astype(np.float32)

    blended = fg * alpha + bg * (1.0 - alpha)
    roi[:] = np.clip(blended, 0, 255).astype(np.uint8)
