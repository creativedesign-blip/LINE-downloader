"""Unit tests for io_utils.py — unicode-safe image I/O.

Covers the critical regression vector: the project path contains Chinese
characters (e.g. "大都會"), and cv2.imread/imwrite silently fail on such
paths on Windows. These tests pin down the correct behaviour.

Run:
    python -m pytest tools/branding/tests/test_io_utils.py -v
    # or
    python tools/branding/tests/test_io_utils.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from tools.branding.io_utils import imread_unicode, imwrite_unicode


class TestImreadUnicode(unittest.TestCase):
    """Read side: Chinese paths, corrupt files, missing files."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # Build a Chinese subdirectory inside the tempdir (the tempdir itself
        # is ASCII on most systems but the subdir forces non-ASCII in the path).
        self.chinese_dir = Path(self._tmp.name) / "中文路徑_測試"
        self.chinese_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_sample_png(self, name: str, shape=(30, 40, 3)) -> Path:
        """Write a small PNG directly via cv2.imencode + file.write to avoid
        cv2.imwrite's own Unicode bug during setup."""
        img = np.full(shape, 200, dtype=np.uint8)
        ok, buf = cv2.imencode(".png", img)
        assert ok
        p = self.chinese_dir / name
        with open(p, "wb") as f:
            f.write(buf.tobytes())
        return p

    def test_reads_png_from_chinese_path(self):
        p = self._write_sample_png("sample.png")
        img = imread_unicode(p, cv2.IMREAD_COLOR)
        self.assertIsNotNone(img, "Chinese path PNG should be readable")
        self.assertEqual(img.shape, (30, 40, 3))
        self.assertEqual(img.dtype, np.uint8)

    def test_reads_rgba_with_unchanged_flag(self):
        # Build a 4-channel PNG
        rgba = np.zeros((20, 20, 4), dtype=np.uint8)
        rgba[:, :, 3] = 128
        ok, buf = cv2.imencode(".png", rgba)
        assert ok
        p = self.chinese_dir / "rgba.png"
        with open(p, "wb") as f:
            f.write(buf.tobytes())

        img = imread_unicode(p, cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(img)
        self.assertEqual(img.shape, (20, 20, 4))

    def test_missing_file_returns_none(self):
        img = imread_unicode(self.chinese_dir / "does_not_exist.png")
        self.assertIsNone(img)

    def test_missing_chinese_directory_returns_none(self):
        img = imread_unicode(self.chinese_dir / "不存在的子資料夾" / "x.png")
        self.assertIsNone(img)

    def test_empty_file_returns_none(self):
        p = self.chinese_dir / "empty.png"
        p.write_bytes(b"")
        self.assertIsNone(imread_unicode(p))

    def test_corrupt_bytes_returns_none(self):
        p = self.chinese_dir / "garbage.png"
        p.write_bytes(b"not an image at all")
        self.assertIsNone(imread_unicode(p))

    def test_accepts_path_objects(self):
        p = self._write_sample_png("path_obj.png")
        self.assertIsNotNone(imread_unicode(Path(p)))


class TestImwriteUnicode(unittest.TestCase):
    """Write side: Chinese paths, auto-mkdir, formats."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.chinese_dir = Path(self._tmp.name) / "中文路徑_寫入"
        self.chinese_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _sample_bgr(self) -> np.ndarray:
        img = np.zeros((50, 60, 3), dtype=np.uint8)
        img[:, :, 0] = 255  # all blue in BGR
        return img

    def test_writes_jpg_to_chinese_path(self):
        out = self.chinese_dir / "思偉達.jpg"
        self.assertTrue(imwrite_unicode(out, self._sample_bgr(), ext=".jpg", quality=90))
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)

    def test_writes_png_to_chinese_path(self):
        out = self.chinese_dir / "旅行社.png"
        self.assertTrue(imwrite_unicode(out, self._sample_bgr(), ext=".png"))
        self.assertTrue(out.exists())

    def test_auto_creates_parent_directories(self):
        # Deep nested chinese path that doesn't exist yet
        out = self.chinese_dir / "深" / "深" / "深" / "a.jpg"
        self.assertFalse(out.parent.exists())
        self.assertTrue(imwrite_unicode(out, self._sample_bgr()))
        self.assertTrue(out.exists())

    def test_unknown_extension_still_attempts_encode(self):
        # cv2.imencode may fail on unknown extensions; we just want no crash.
        out = self.chinese_dir / "weird.xyz"
        result = imwrite_unicode(out, self._sample_bgr(), ext=".xyz")
        # Either success or graceful False — but definitely no exception
        self.assertIsInstance(result, bool)

    def test_uint8_rgba_writes_to_png(self):
        rgba = np.zeros((30, 30, 4), dtype=np.uint8)
        rgba[:, :, 2] = 255
        rgba[:, :, 3] = 200
        out = self.chinese_dir / "透明.png"
        self.assertTrue(imwrite_unicode(out, rgba, ext=".png"))
        self.assertTrue(out.exists())


class TestRoundTrip(unittest.TestCase):
    """write then read must preserve pixel content (within codec loss)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.chinese_dir = Path(self._tmp.name) / "中文_往返"
        self.chinese_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_png_roundtrip_is_lossless(self):
        original = np.random.randint(0, 256, (40, 50, 3), dtype=np.uint8)
        out = self.chinese_dir / "roundtrip.png"
        self.assertTrue(imwrite_unicode(out, original, ext=".png"))

        decoded = imread_unicode(out, cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.shape, original.shape)
        # PNG is lossless — bytes should be identical
        self.assertTrue(np.array_equal(decoded, original))

    def test_jpg_roundtrip_preserves_shape(self):
        original = np.full((40, 50, 3), 128, dtype=np.uint8)
        out = self.chinese_dir / "roundtrip.jpg"
        self.assertTrue(imwrite_unicode(out, original, ext=".jpg", quality=95))

        decoded = imread_unicode(out, cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.shape, original.shape)
        # JPEG is lossy — allow ±5 per channel for a uniform image
        self.assertTrue(np.all(np.abs(decoded.astype(int) - original.astype(int)) <= 5))

    def test_rgba_png_roundtrip_preserves_alpha(self):
        original = np.zeros((30, 30, 4), dtype=np.uint8)
        original[:, :, 0] = 100
        original[:, :, 1] = 150
        original[:, :, 2] = 200
        original[:, :, 3] = 128  # semi-transparent
        out = self.chinese_dir / "alpha.png"
        self.assertTrue(imwrite_unicode(out, original, ext=".png"))

        decoded = imread_unicode(out, cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.shape, (30, 30, 4))
        self.assertTrue(np.array_equal(decoded, original),
                        "alpha channel should survive PNG roundtrip")


class TestRealProjectPath(unittest.TestCase):
    """Smoke test: the real project path contains '大都會' — make sure
    imread_unicode works on it (if the actual metro sample exists)."""

    def test_reads_real_metro_sample_if_present(self):
        sample = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "downloads" / "metro" / "travel"
            / "line_2026-04-21T19-14-32_0001_perf.jpg"
        )
        if not sample.exists():
            self.skipTest(f"metro sample not present at {sample}")
        img = imread_unicode(sample, cv2.IMREAD_COLOR)
        self.assertIsNotNone(img,
                             f"failed to read real Chinese path: {sample}")
        self.assertEqual(img.ndim, 3)


if __name__ == "__main__":
    unittest.main()
