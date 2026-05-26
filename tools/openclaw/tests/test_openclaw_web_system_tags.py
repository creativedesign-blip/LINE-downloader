import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_MODULE_PATH = PROJECT_ROOT / "travel-agent-interface" / "openclaw_web.py"


spec = importlib.util.spec_from_file_location("openclaw_web_for_system_tag_tests", WEB_MODULE_PATH)
openclaw_web = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(openclaw_web)


class SystemTagMergeTests(unittest.TestCase):
    def test_system_tags_use_only_current_image_sidecar(self):
        payload = {
            "countries": ["紐西蘭"],
            "regions": ["南島"],
            "features": ["高山火車"],
            "months": [8],
        }

        with patch.object(openclaw_web, "_sidecar_payload_for_image", return_value=payload):
            tags = openclaw_web._system_tags_for_same_sha_image(1, Path("current.jpg"))

        self.assertEqual(
            [tag["tag"] for tag in tags],
            ["紐西蘭", "南島", "高山火車", "8月"],
        )

    def test_same_sha_sidecar_query_fields_are_merged(self):
        payloads = [
            {"countries": ["紐西蘭"], "regions": ["南島"], "months": [8], "duration_days": 8},
            {"countries": ["紐西蘭"], "regions": ["皇后鎮"], "months": [8, 9], "price_from": 99900},
        ]

        fields = openclaw_web._merge_sidecar_query_fields(payloads)

        self.assertEqual(fields["countries"], ["紐西蘭"])
        self.assertEqual(fields["regions"], ["南島", "皇后鎮"])
        self.assertEqual(fields["months"], [8, 9])
        self.assertEqual(fields["duration_days"], 8)
        self.assertEqual(fields["price_from"], 99900)

    def test_search_index_uses_only_current_image_sidecar(self):
        current_path = openclaw_web.PROJECT_ROOT / "tmp" / "current.jpg"
        image = {
            "id": 7,
            "folder_id": 3,
            "stored_path": "tmp/current.jpg",
            "original_filename": "current.jpg",
            "display_name": "",
            "reference_text": "",
            "manual_note": "",
            "sha256": "same-sha",
            "ocr_tags_override": [],
            "archived_at": None,
            "uploaded_at": "2026-05-26T00:00:00Z",
        }
        folder = {
            "id": 3,
            "display_name": "測試資料夾",
            "folder_slug": "upload_test",
            "archived_at": None,
        }
        payload = {
            "countries": ["越南"],
            "regions": ["富國島"],
            "features": ["郵輪"],
            "months": [6],
            "ocr": {"text": "越南 富國島"},
        }

        with (
            patch.object(openclaw_web, "_upload_image_record", return_value=(image, folder)),
            patch.object(openclaw_web, "_find_current_image_path", return_value=current_path),
            patch.object(openclaw_web, "_sidecar_payload_for_image", return_value=payload),
            patch.object(openclaw_web, "_same_sha_sidecar_payloads", side_effect=AssertionError("same-sha sidecars should not be merged")),
            patch.object(openclaw_web, "_manual_tags_for_images", return_value={}),
            patch.object(openclaw_web, "_branded_image_lookup", return_value=({}, {})),
            patch.object(openclaw_web, "upsert_image_search_index") as upsert,
        ):
            openclaw_web._refresh_upload_search_index_for_image(7)

        _, kwargs = upsert.call_args
        self.assertEqual(kwargs["countries"], ["越南"])
        self.assertEqual(kwargs["regions"], ["富國島"])
        self.assertIn("郵輪", kwargs["features"])
        self.assertIn("越南 富國島", kwargs["raw_text"])


if __name__ == "__main__":
    unittest.main()
