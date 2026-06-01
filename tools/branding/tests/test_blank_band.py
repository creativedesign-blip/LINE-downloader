"""Unit tests for detect_blank_bottom_band_cut_y — the empty colored-footer detector.

Run:
    python -m pytest tools/branding/tests/test_blank_band.py -v
    # or
    python tools/branding/tests/test_blank_band.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from tools.branding.brand_stitcher import detect_blank_bottom_band_cut_y

CFG_ON = {"detectBlankColorFooter": True, "blankFooterContentStd": 12, "blankFooterColorTol": 40}
TEAL = np.array([140, 190, 188], dtype=np.uint8)   # BGR


def _content(h, w):
    """Rows with high horizontal variance (stand in for text/photo)."""
    rng = np.random.RandomState(0)
    return rng.randint(0, 256, size=(h, w, 3), dtype=np.uint8)


def _solid(h, w, color):
    return np.tile(color, (h, w, 1)).astype(np.uint8)


class TestBlankBandDetector(unittest.TestCase):
    def test_crops_empty_colored_band(self):
        """A solid teal band below content is detected and cut at its top."""
        img = np.vstack([_content(800, 400), _solid(200, 400, TEAL)])
        self.assertEqual(detect_blank_bottom_band_cut_y(img, CFG_ON), 800)

    def test_does_not_swallow_fine_print(self):
        """Fine print inside the bottom region is preserved; only the empty
        rows BELOW it are removed (cut stops at the text, not above it)."""
        img = np.vstack([
            _content(900, 400),     # 0..899  main content
            _content(10, 400),      # 900..909 fine print (高 variance)
            _solid(90, 400, TEAL),  # 910..999 empty band (>= min_band_h)
        ])
        cut = detect_blank_bottom_band_cut_y(img, CFG_ON)
        self.assertEqual(cut, 910)            # cut at top of empty band
        self.assertGreater(cut, 909)          # the fine-print rows are kept

    def test_no_fire_when_band_too_thin(self):
        """An empty strip thinner than min_band_h must not trigger a crop."""
        img = np.vstack([_content(970, 400), _solid(30, 400, TEAL)])  # 30px < 4% of 1000
        self.assertIsNone(detect_blank_bottom_band_cut_y(img, CFG_ON))

    def test_no_fire_when_band_exceeds_cap(self):
        """A band larger than 25% of H is rejected (backstop against a
        low-variance photo bottom being cropped away), matching the sibling
        detectors' upper bound."""
        img = np.vstack([_content(600, 400), _solid(400, 400, TEAL)])  # 40% > 25%
        self.assertIsNone(detect_blank_bottom_band_cut_y(img, CFG_ON))

    def test_no_fire_when_bottom_has_content(self):
        """Content touching the very bottom => append a fresh band, do not crop."""
        img = _content(1000, 400)
        self.assertIsNone(detect_blank_bottom_band_cut_y(img, CFG_ON))

    def test_gradient_band_is_treated_as_empty(self):
        """A smooth vertical gradient (content-free per row) is still cropped."""
        grad = np.zeros((200, 400, 3), dtype=np.uint8)
        for i in range(200):
            grad[i, :] = (120 + i // 4, 160 + i // 6, 150 + i // 5)
        img = np.vstack([_content(800, 400), grad])
        self.assertEqual(detect_blank_bottom_band_cut_y(img, CFG_ON), 800)

    def test_disabled_by_config(self):
        img = np.vstack([_content(800, 400), _solid(200, 400, TEAL)])
        self.assertIsNone(detect_blank_bottom_band_cut_y(img, {"detectBlankColorFooter": False}))
        self.assertIsNone(detect_blank_bottom_band_cut_y(img, {}))

    def test_too_small_image(self):
        img = _solid(150, 150, TEAL)
        self.assertIsNone(detect_blank_bottom_band_cut_y(img, CFG_ON))


if __name__ == "__main__":
    unittest.main(verbosity=2)
