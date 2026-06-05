import importlib.util
import io
import tempfile
import unittest
from http import HTTPStatus
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

    def test_failed_step_makes_running_folder_recoverable(self):
        folder = {
            "id": 10,
            "status": "running",
            "current_step": "compose",
            "step_statuses": {"ocr": "success", "compose": "failed"},
            "updated_at": openclaw_web._utc_now_iso(),
        }

        with patch.object(openclaw_web, "_is_recent_run_lock", return_value=True):
            recovery = openclaw_web._folder_recovery_state(folder)

        self.assertTrue(recovery["stale"])
        self.assertTrue(recovery["can_archive"])
        self.assertTrue(recovery["can_retry"])
        self.assertTrue(recovery["can_delete_images"])
        self.assertEqual(recovery["stuck_step"], "compose")

    def test_failed_step_allows_folder_archive(self):
        folder = {
            "id": 10,
            "status": "running",
            "current_step": "ocr",
            "image_count": 2,
            "step_statuses": {"ocr": "failed"},
            "updated_at": openclaw_web._utc_now_iso(),
        }

        with patch.object(openclaw_web, "_is_recent_run_lock", return_value=True):
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

    def test_failed_image_can_be_archived_while_folder_running(self):
        with patch.object(
            openclaw_web,
            "_folder_with_runtime_status",
            return_value={"status": "running", "recovery": {"stale": False}},
        ):
            allowed, reason = openclaw_web._image_can_be_archived({"id": 10}, {"ocr_status": "failed"})

        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_recoverable_running_folder_allows_image_archive(self):
        with patch.object(
            openclaw_web,
            "_folder_with_runtime_status",
            return_value={"status": "running", "recovery": {"stale": True, "can_delete_images": True}},
        ):
            allowed, reason = openclaw_web._image_can_be_archived({"id": 10}, {"ocr_status": "pending"})

        self.assertTrue(allowed)
        self.assertEqual(reason, "")


class UploadHandlerMultipartRegressionTests(unittest.TestCase):
    """Drive the real /api/uploads/folders/{id}/images handler with a real
    multipart body and assert it answers 200, not 500.

    Regression guard for the bug where the stored-file index was computed as
    ``int(get_folder(...) or folder).get("image_count")`` — the closing paren
    was misplaced so ``int()`` received the folder *dict* and raised
    ``TypeError: int() argument must be ... not 'dict'``, which the handler's
    blanket except turned into "internal server error" on *every* upload. The
    folder here carries an ``image_count`` so the buggy expression runs.
    """

    def _make_handler(self, body: bytes, content_type: str):
        handler = openclaw_web.Handler.__new__(openclaw_web.Handler)
        handler.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.command = "POST"
        handler.path = "/api/uploads/folders/123/images"
        captured: dict = {}

        def fake_json(payload, status=HTTPStatus.OK):
            captured["payload"] = payload
            captured["status"] = status

        # Instance attributes shadow the bound methods so we don't open a socket
        # or launch the real OCR/branding/index pipeline.
        handler._json = fake_json
        handler._start_upload_pipeline = lambda folder, trigger_source="upload": {"ok": True, "started": False}
        return handler, captured

    def test_multipart_upload_returns_200_not_500(self):
        boundary = "----regression-boundary"
        png = make_png(700, 900)
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="01.png"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode("utf-8") + png + f"\r\n--{boundary}--\r\n".encode("utf-8")
        content_type = f"multipart/form-data; boundary={boundary}"

        folder = {
            "id": 123,
            "image_count": 2,
            "status": "pending",
            "current_step": "upload",
            "folder_slug": "regression-folder",
        }

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(openclaw_web, "get_folder", return_value=folder), \
                patch.object(openclaw_web, "folder_target_path", return_value=Path(tmp)), \
                patch.object(openclaw_web, "stored_path_is_registered", return_value=False), \
                patch.object(openclaw_web, "add_image", return_value={"id": 405, "original_filename": "01.png"}) as add_image_mock, \
                patch.object(openclaw_web, "_upload_image_size_requirement", return_value=(620, 50)):
            handler, captured = self._make_handler(body, content_type)
            handler._handle_uploads_post("/api/uploads/folders/123/images")

        self.assertEqual(captured["status"], HTTPStatus.OK)
        self.assertTrue(captured["payload"].get("ok"))
        self.assertEqual(len(captured["payload"].get("images") or []), 1)
        self.assertEqual(captured["payload"].get("rejected"), [])
        add_image_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
