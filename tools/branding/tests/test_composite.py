"""Unit tests for composite.py — the pure stitching function.

Run:
    python -m pytest tools/branding/tests/test_composite.py -v
    # or
    python tools/branding/tests/test_composite.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

# Allow running as a script from project root
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from tools.branding.composite import (
    composite,
    LogoTooSmallError,
    _normalize_logo_channels,
    _build_canvas,
)


DEFAULT_CFG = {
    "bandHeightRatio": 0.12,
    "bandMinHeightPx": 80,
    "bandColor": [255, 255, 255],   # white BGR
    "logoWidthRatio": 0.7,
    "logoScaleMax": 2.0,
    "logoScaleMin": 0.25,
    "logoHorizontalAlign": "center",
    "logoPaddingRatio": 0.02,
}


def make_base(H: int, W: int, fill: int = 128) -> np.ndarray:
    """Fill grey BGR base image."""
    img = np.full((H, W, 3), fill, dtype=np.uint8)
    return img


def make_logo_rgba(h: int, w: int, alpha: int = 255, color=(0, 0, 255)) -> np.ndarray:
    """BGRA logo; default is fully opaque red."""
    logo = np.zeros((h, w, 4), dtype=np.uint8)
    logo[:, :, 0] = color[0]
    logo[:, :, 1] = color[1]
    logo[:, :, 2] = color[2]
    logo[:, :, 3] = alpha
    return logo


def make_logo_bgr(h: int, w: int, color=(0, 0, 255)) -> np.ndarray:
    logo = np.zeros((h, w, 3), dtype=np.uint8)
    logo[:, :, 0] = color[0]
    logo[:, :, 1] = color[1]
    logo[:, :, 2] = color[2]
    return logo


class TestCompositeShape(unittest.TestCase):
    """Output shape and scale expectations across base sizes."""

    def test_square_1080_with_400x120_logo(self):
        base = make_base(1080, 1080)
        logo = make_logo_rgba(120, 400)
        out = composite(base, logo, DEFAULT_CFG)

        # band_h = max(80, int(1080 * 0.12)) = 129
        self.assertEqual(out.shape, (1080 + 129, 1080, 3))
        self.assertEqual(out.dtype, np.uint8)

    def test_base_larger_than_logo_scales_up(self):
        # 2000x2000 base + 400x120 logo
        # target_w = 2000 * 0.7 = 1400, scale_ideal = 3.5
        # scaleMax caps to 2.0 -> new_w = 800
        base = make_base(2000, 2000)
        logo = make_logo_rgba(120, 400)
        out = composite(base, logo, DEFAULT_CFG)

        band_h = int(2000 * 0.12)  # 240
        self.assertEqual(out.shape, (2000 + band_h, 2000, 3))

    def test_base_smaller_than_logo_scales_down(self):
        # 300x300 base + 400x120 logo
        # target_w = 300 * 0.7 = 210, scale_ideal = 0.525
        base = make_base(300, 300)
        logo = make_logo_rgba(120, 400)
        out = composite(base, logo, DEFAULT_CFG)

        # band_h = max(80, int(300 * 0.12 = 36)) = 80
        self.assertEqual(out.shape, (300 + 80, 300, 3))

    def test_base_equals_logo_width(self):
        # 400x400 base + 400x120 logo
        # target_w = 400 * 0.7 = 280, scale_ideal = 0.7
        base = make_base(400, 400)
        logo = make_logo_rgba(120, 400)
        out = composite(base, logo, DEFAULT_CFG)
        self.assertEqual(out.shape, (400 + 80, 400, 3))  # band floor 80

    def test_scale_cap_hit_with_huge_base(self):
        # 4000x4000 base + 200x60 logo
        # target_w = 2800, scale_ideal = 14 -> capped to 2.0
        base = make_base(4000, 4000)
        logo = make_logo_rgba(60, 200)
        out = composite(base, logo, DEFAULT_CFG)

        band_h = int(4000 * 0.12)  # 480
        self.assertEqual(out.shape, (4000 + band_h, 4000, 3))

    def test_raises_when_too_small(self):
        # 100x100 base + 400x120 logo
        # target_w = 70, scale_ideal = 0.175 < logoScaleMin 0.25
        base = make_base(100, 100)
        logo = make_logo_rgba(120, 400)
        with self.assertRaises(LogoTooSmallError):
            composite(base, logo, DEFAULT_CFG)

    def test_band_height_cap_limits_scale(self):
        # If band_h is small relative to logo height, height becomes the
        # binding constraint. base 10000x400 -> band_h = 80 (just from
        # ratio 0.12*400=48, floored to 80). Logo 120 tall, scale by height:
        # 80 * 0.85 / 120 = 0.567.
        base = make_base(400, 10000)
        logo = make_logo_rgba(120, 400)
        out = composite(base, logo, DEFAULT_CFG)

        self.assertEqual(out.shape[1], 10000)
        self.assertEqual(out.shape[0], 400 + 80)

    def test_horizontal_base_landscape(self):
        # 400x1200 landscape
        base = make_base(400, 1200)
        logo = make_logo_rgba(120, 400)
        out = composite(base, logo, DEFAULT_CFG)

        self.assertEqual(out.shape, (400 + 80, 1200, 3))

    def test_vertical_base_portrait(self):
        # 1200x600 portrait (phone screenshot style)
        base = make_base(1200, 600)
        logo = make_logo_rgba(120, 400)
        out = composite(base, logo, DEFAULT_CFG)

        band_h = int(1200 * 0.12)  # 144
        self.assertEqual(out.shape, (1200 + band_h, 600, 3))


class TestCompositeChannels(unittest.TestCase):
    """Logo channel normalization paths."""

    def test_grayscale_2d_logo(self):
        base = make_base(1000, 1000)
        logo_gray = np.full((80, 300), 128, dtype=np.uint8)
        out = composite(base, logo_gray, DEFAULT_CFG)

        self.assertEqual(out.ndim, 3)
        self.assertEqual(out.shape[2], 3)
        self.assertEqual(out.dtype, np.uint8)

    def test_grayscale_3d_1ch_logo(self):
        base = make_base(1000, 1000)
        logo_gray = np.full((80, 300, 1), 128, dtype=np.uint8)
        out = composite(base, logo_gray, DEFAULT_CFG)
        self.assertEqual(out.shape[2], 3)

    def test_bgr_logo_opaque(self):
        base = make_base(1000, 1000)
        logo = make_logo_bgr(100, 300, color=(0, 255, 0))  # green
        out = composite(base, logo, DEFAULT_CFG)
        self.assertEqual(out.shape[2], 3)

    def test_illegal_channel_count_raises(self):
        base = make_base(1000, 1000)
        bad_logo = np.zeros((80, 300, 2), dtype=np.uint8)
        with self.assertRaises(ValueError):
            composite(base, bad_logo, DEFAULT_CFG)

    def test_non_uint8_logo_raises(self):
        base = make_base(1000, 1000)
        bad_logo = np.zeros((80, 300, 4), dtype=np.float32)
        with self.assertRaises(ValueError):
            composite(base, bad_logo, DEFAULT_CFG)


class TestAlphaBlending(unittest.TestCase):
    """RGBA -> white background should not black out."""

    def test_white_band_stays_white_where_alpha_zero(self):
        # Fully transparent logo over white band -> band color unchanged
        base = make_base(1000, 1000, fill=0)  # black base
        transparent_logo = make_logo_rgba(100, 300, alpha=0, color=(0, 0, 255))
        out = composite(base, transparent_logo, DEFAULT_CFG)

        # The band (rows 1000..end) should be all white (255,255,255)
        band = out[1000:, :, :]
        self.assertTrue(np.all(band == 255),
                        "fully transparent logo should not alter white band")

    def test_opaque_logo_replaces_band_pixels(self):
        base = make_base(1000, 1000)
        red = make_logo_rgba(100, 300, alpha=255, color=(0, 0, 255))  # BGR = blue*0, green*0, red*255
        out = composite(base, red, DEFAULT_CFG)

        # Find a pixel in the middle of where logo should land.
        # Logo placed centered in band at y ~= 1000 + band/2 - logo_h/2
        # Easier: check at least one pixel got the logo color.
        band_region = out[1000:, :, :]
        red_pixels = np.all(band_region == [0, 0, 255], axis=-1)
        self.assertTrue(red_pixels.any(),
                        "opaque red logo should leave at least one red pixel")

    def test_half_alpha_blends(self):
        base = make_base(1000, 1000)
        half = make_logo_rgba(100, 300, alpha=128, color=(0, 0, 255))
        out = composite(base, half, DEFAULT_CFG)

        # Some pixels should be neither pure white nor pure red
        band_region = out[1000:, :, :]
        # Count pixels that are blended (not 255,255,255 and not 0,0,255)
        pure_white = np.all(band_region == 255, axis=-1)
        pure_red = np.all(band_region == [0, 0, 255], axis=-1)
        blended = ~(pure_white | pure_red)
        self.assertTrue(blended.any(),
                        "half-alpha logo should produce blended pixels")


class TestBasePreservation(unittest.TestCase):
    """Top portion of output must equal base exactly."""

    def test_base_pixels_unchanged(self):
        base = make_base(600, 800, fill=77)
        logo = make_logo_rgba(100, 300)
        out = composite(base, logo, DEFAULT_CFG)

        # Rows 0..H should be identical to base
        H = 600
        self.assertTrue(np.array_equal(out[:H, :, :], base))

    def test_base_with_alpha_drops_alpha(self):
        # 4-channel base should be handled
        base = np.zeros((500, 500, 4), dtype=np.uint8)
        base[:, :, :3] = 100
        base[:, :, 3] = 255
        logo = make_logo_rgba(80, 200)
        out = composite(base, logo, DEFAULT_CFG)

        self.assertEqual(out.shape[2], 3)
        self.assertTrue(np.all(out[:500, :, :] == 100))


class TestHorizontalAlign(unittest.TestCase):
    """Verify x offset for left/center/right."""

    def _logo_x_range(self, out: np.ndarray, H: int) -> tuple[int, int]:
        """Return (first_x, last_x) where a non-white pixel appears in the band."""
        band = out[H:, :, :]
        non_white = np.any(band != 255, axis=(0, 2))
        idxs = np.where(non_white)[0]
        if len(idxs) == 0:
            return (-1, -1)
        return (int(idxs[0]), int(idxs[-1]))

    def test_center_align(self):
        # Use a logo whose width won't be capped by band height, so we can
        # reason about centering cleanly.
        base = make_base(1000, 1000)
        logo = make_logo_rgba(40, 200, alpha=255, color=(0, 0, 255))
        cfg = {**DEFAULT_CFG, "logoHorizontalAlign": "center"}
        out = composite(base, logo, cfg)

        W = 1000
        first_x, last_x = self._logo_x_range(out, 1000)
        left_margin = first_x
        right_margin = (W - 1) - last_x
        # Centered -> left and right margins equal (± small rounding).
        self.assertLessEqual(abs(left_margin - right_margin), 2,
                             f"left={left_margin}, right={right_margin}")

    def test_left_align(self):
        base = make_base(1000, 1000)
        logo = make_logo_rgba(40, 200, alpha=255, color=(0, 0, 255))
        cfg = {**DEFAULT_CFG, "logoHorizontalAlign": "left"}
        out = composite(base, logo, cfg)
        first_x, _ = self._logo_x_range(out, 1000)
        # padding = int(1000*0.02) = 20
        self.assertGreaterEqual(first_x, 15)
        self.assertLessEqual(first_x, 25)

    def test_right_align(self):
        base = make_base(1000, 1000)
        logo = make_logo_rgba(40, 200, alpha=255, color=(0, 0, 255))
        cfg = {**DEFAULT_CFG, "logoHorizontalAlign": "right"}
        out = composite(base, logo, cfg)
        _, last_x = self._logo_x_range(out, 1000)
        right_margin = 999 - last_x
        self.assertGreaterEqual(right_margin, 15)
        self.assertLessEqual(right_margin, 25)


class TestInterpolationChoice(unittest.TestCase):
    """Indirect check: scale > 1 should use CUBIC, scale < 1 should use AREA.
    We cannot introspect the cv2 call directly, but we can verify both paths
    produce non-degenerate output.
    """

    def test_upscale_path_produces_output(self):
        base = make_base(3000, 3000)  # forces upscale
        logo = make_logo_rgba(60, 200)  # small logo, will upscale
        out = composite(base, logo, DEFAULT_CFG)
        self.assertEqual(out.shape[1], 3000)

    def test_downscale_path_produces_output(self):
        base = make_base(400, 400)  # small -> logo shrinks
        logo = make_logo_rgba(120, 400)
        out = composite(base, logo, DEFAULT_CFG)
        self.assertEqual(out.shape[1], 400)


class TestBuildCanvas(unittest.TestCase):
    def test_invalid_band_color(self):
        with self.assertRaises(ValueError):
            _build_canvas(100, 100, 20, [255, 255])  # only 2 elements

    def test_fill_color_applied(self):
        c = _build_canvas(100, 100, 20, [10, 20, 30])
        # Everything initially set to color; check one pixel
        self.assertEqual(tuple(c[0, 0]), (10, 20, 30))


class TestNormalizeLogoChannels(unittest.TestCase):
    def test_2d_to_3ch(self):
        g = np.zeros((50, 80), dtype=np.uint8)
        out = _normalize_logo_channels(g)
        self.assertEqual(out.ndim, 3)
        self.assertEqual(out.shape[2], 3)

    def test_4ch_preserved(self):
        rgba = np.zeros((50, 80, 4), dtype=np.uint8)
        out = _normalize_logo_channels(rgba)
        self.assertEqual(out.shape[2], 4)


if __name__ == "__main__":
    unittest.main()
