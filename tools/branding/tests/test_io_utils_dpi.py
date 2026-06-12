"""Unit tests for imwrite_unicode DPI embedding.

Run:
    python -m pytest tools/branding/tests/test_io_utils_dpi.py -v
    # or
    python tools/branding/tests/test_io_utils_dpi.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

# Allow running as a script from project root
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from PIL import Image

from tools.branding.io_utils import imwrite_unicode


class TestImwriteDpi(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_jpeg_embeds_dpi_and_keeps_size(self):
        img = np.full((20, 30, 3), 200, dtype=np.uint8)  # H=20, W=30, BGR
        out = self.tmp / "x.jpg"
        self.assertTrue(imwrite_unicode(out, img, ext=".jpg", quality=90, dpi=150))
        with Image.open(out) as im:
            self.assertEqual(im.size, (30, 20))  # PIL is (W, H)
            dpi = tuple(round(v) for v in im.info.get("dpi", (0, 0)))
            self.assertEqual(dpi, (150, 150))

    def test_png_embeds_dpi(self):
        img = np.full((10, 10, 3), 100, dtype=np.uint8)
        out = self.tmp / "x.png"
        self.assertTrue(imwrite_unicode(out, img, ext=".png", dpi=150))
        with Image.open(out) as im:
            dpi = tuple(round(v) for v in im.info.get("dpi", (0, 0)))
            self.assertEqual(dpi, (150, 150))

    def test_no_dpi_path_still_writes(self):
        img = np.full((10, 10, 3), 100, dtype=np.uint8)
        out = self.tmp / "y.jpg"
        self.assertTrue(imwrite_unicode(out, img, ext=".jpg"))
        self.assertTrue(out.exists())

    def test_unicode_path_with_dpi(self):
        img = np.full((12, 12, 3), 128, dtype=np.uint8)
        out = self.tmp / "大都會_測試.jpg"  # non-ASCII path
        self.assertTrue(imwrite_unicode(out, img, ext=".jpg", quality=88, dpi=150))
        self.assertTrue(out.exists())
        with Image.open(out) as im:
            dpi = tuple(round(v) for v in im.info.get("dpi", (0, 0)))
            self.assertEqual(dpi, (150, 150))


if __name__ == "__main__":
    unittest.main()
