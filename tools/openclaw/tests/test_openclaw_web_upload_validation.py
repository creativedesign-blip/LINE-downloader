import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_MODULE_PATH = PROJECT_ROOT / "travel-agent-interface" / "openclaw_web.py"


spec = importlib.util.spec_from_file_location("openclaw_web_for_upload_tests", WEB_MODULE_PATH)
openclaw_web = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(openclaw_web)


def make_png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class UploadImageDimensionValidationTests(unittest.TestCase):
    def test_current_branding_requirement_is_620_px_wide(self):
        min_width, min_edge = openclaw_web._upload_image_size_requirement()

        self.assertEqual(min_width, 620)
        self.assertEqual(min_edge, 50)

    def test_rejects_image_narrower_than_branding_requirement(self):
        with patch.object(openclaw_web, "_upload_image_size_requirement", return_value=(620, 50)):
            error = openclaw_web._validate_upload_image_dimensions(make_png(619, 900))

        self.assertIsNotNone(error)
        self.assertIn("619x900px", error)
        self.assertIn("寬度至少 620px", error)

    def test_rejects_image_below_minimum_edge(self):
        with patch.object(openclaw_web, "_upload_image_size_requirement", return_value=(620, 50)):
            error = openclaw_web._validate_upload_image_dimensions(make_png(620, 49))

        self.assertIsNotNone(error)
        self.assertIn("620x49px", error)
        self.assertIn("至少 50px", error)

    def test_accepts_image_that_meets_branding_requirement(self):
        with patch.object(openclaw_web, "_upload_image_size_requirement", return_value=(620, 50)):
            error = openclaw_web._validate_upload_image_dimensions(make_png(620, 900))

        self.assertIsNone(error)

    def test_rejects_corrupt_image_bytes(self):
        error = openclaw_web._validate_upload_image_dimensions(b"not an image")

        self.assertEqual(error, "圖片無法讀取或格式損壞")


if __name__ == "__main__":
    unittest.main()
