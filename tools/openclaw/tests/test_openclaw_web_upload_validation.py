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


class UploadRecoveryStateTests(unittest.TestCase):
    def test_running_folder_without_lock_is_recoverable(self):
        folder = {
            "id": 10,
            "status": "running",
            "current_step": "ocr",
            "step_statuses": {"ocr": "running"},
            "updated_at": "2000-01-01T00:00:00Z",
        }

        with patch.object(openclaw_web, "_is_recent_run_lock", return_value=False):
            recovery = openclaw_web._folder_recovery_state(folder)

        self.assertTrue(recovery["stale"])
        self.assertTrue(recovery["can_retry"])
        self.assertTrue(recovery["can_archive"])
        self.assertTrue(recovery["can_delete_images"])
        self.assertEqual(recovery["stuck_step"], "ocr")

    def test_running_folder_with_lock_is_not_recoverable(self):
        folder = {
            "id": 10,
            "status": "running",
            "current_step": "ocr",
            "step_statuses": {"ocr": "running"},
            "updated_at": openclaw_web._utc_now_iso(),
        }

        with patch.object(openclaw_web, "_is_recent_run_lock", return_value=True):
            recovery = openclaw_web._folder_recovery_state(folder)

        self.assertFalse(recovery["stale"])
        self.assertFalse(recovery["can_retry"])
        self.assertFalse(recovery["can_archive"])
        self.assertFalse(recovery["can_delete_images"])

    def test_stale_folder_can_be_archived(self):
        folder = {
            "id": 10,
            "status": "running",
            "current_step": "compose",
            "image_count": 2,
            "recovery": {"can_archive": True},
        }

        allowed, reason = openclaw_web._folder_can_be_archived(folder)

        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_normal_running_folder_blocks_image_archive(self):
        with patch.object(
            openclaw_web,
            "_folder_with_runtime_status",
            return_value={"status": "running", "recovery": {"stale": False}},
        ):
            allowed, reason = openclaw_web._image_can_be_archived({"id": 10})

        self.assertFalse(allowed)
        self.assertIn("正常處理中", reason)


if __name__ == "__main__":
    unittest.main()
