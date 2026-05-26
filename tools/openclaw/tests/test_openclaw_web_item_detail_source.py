import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_MODULE_PATH = PROJECT_ROOT / "travel-agent-interface" / "openclaw_web.py"


spec = importlib.util.spec_from_file_location("openclaw_web_for_item_detail_source_tests", WEB_MODULE_PATH)
openclaw_web = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(openclaw_web)


class ItemDetailSourceTests(unittest.TestCase):
    def test_line_auto_upload_catalog_folder_uses_image_group_source(self):
        source_kind, source_label = openclaw_web._upload_detail_source(
            {
                "source": "line-auto",
                "line_groups": ["Group A", "Group B"],
                "display_name": "LINE auto 2026-05-26",
                "folder_slug": "line_auto_20260526_090002_Group_A_Group_B",
            },
            "line-rpa/download/line_auto_20260526_090002_Group_A_Group_B/inbox/Group B_0001_line_20260526_090042_543161.png",
        )

        self.assertEqual(source_kind, "line-auto")
        self.assertEqual(source_label, "Group B")

    def test_line_auto_upload_catalog_folder_falls_back_to_group_list(self):
        source_kind, source_label = openclaw_web._upload_detail_source(
            {
                "source": "line-auto",
                "line_groups": ["Group A", "Group B"],
                "display_name": "LINE auto 2026-05-26",
                "folder_slug": "line_auto_20260526_090002_Group_A_Group_B",
            }
        )

        self.assertEqual(source_kind, "line-auto")
        self.assertEqual(source_label, "Group A / Group B")

    def test_manual_upload_folder_uses_upload_source(self):
        source_kind, source_label = openclaw_web._upload_detail_source(
            {
                "source": "upload",
                "line_groups": [],
                "display_name": "May campaign",
                "folder_slug": "upload_20260526_090002_May_campaign",
            }
        )

        self.assertEqual(source_kind, "upload")
        self.assertEqual(source_label, "May campaign")

    def test_upload_source_without_catalog_image_id_falls_back_to_sidecar_detail(self):
        class EmptyCatalogConnection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, *args, **kwargs):
                return self

            def fetchone(self):
                return None

        with (
            patch.object(openclaw_web.sqlite3, "connect", return_value=EmptyCatalogConnection()),
            patch.object(openclaw_web, "_line_item_detail", return_value={"ok": True}) as line_detail,
        ):
            detail = openclaw_web._query_item_detail({
                "source": ["upload"],
                "sidecar_path": ["line-rpa/download/upload_old/travel/old.jpg.json"],
            })

            self.assertEqual(detail, {"ok": True})
            line_detail.assert_called_once_with(
                "line-rpa/download/upload_old/travel/old.jpg.json",
                {
                    "source": ["upload"],
                    "sidecar_path": ["line-rpa/download/upload_old/travel/old.jpg.json"],
                },
            )

    def test_filter_archived_upload_items_hides_archived_folder_rows(self):
        payload = {
            "count": 3,
            "items": [
                {"target_id": "upload_archived", "sidecar_path": "archived.jpg.json"},
                {"target_id": "upload_active", "sidecar_path": "active.jpg.json"},
                {"target_id": "line_group", "sidecar_path": "line.jpg.json"},
            ],
        }
        with patch.object(openclaw_web, "_archived_upload_folder_slugs", return_value={"upload_archived"}):
            filtered = openclaw_web._filter_archived_upload_items(payload)

        self.assertEqual(filtered["count"], 2)
        self.assertEqual(
            [item["sidecar_path"] for item in filtered["items"]],
            ["active.jpg.json", "line.jpg.json"],
        )

    def test_dedupe_payload_images_uses_image_sha(self):
        payload = {
            "count": 3,
            "items": [
                {"image_sha256": "same-sha", "sidecar_path": "newer.jpg.json"},
                {"image_sha256": "same-sha", "sidecar_path": "older.jpg.json"},
                {"image_sha256": "other-sha", "sidecar_path": "other.jpg.json"},
            ],
        }

        with patch.object(openclaw_web, "_image_sha_lookup") as sha_lookup:
            deduped = openclaw_web._dedupe_payload_images(payload)

        self.assertEqual(deduped["count"], 2)
        self.assertEqual(
            [item["sidecar_path"] for item in deduped["items"]],
            ["newer.jpg.json", "other.jpg.json"],
        )
        sha_lookup.assert_not_called()

    def test_dedupe_payload_images_uses_sha_lookup_for_paths(self):
        payload = {
            "count": 3,
            "items": [
                {"sidecar_path": "newer.jpg.json"},
                {"sidecar_path": "older.jpg.json"},
                {"sidecar_path": "other.jpg.json"},
            ],
        }

        with patch.object(
            openclaw_web,
            "_image_sha_lookup",
            return_value={
                "path:newer.jpg.json": "same-sha",
                "path:older.jpg.json": "same-sha",
                "path:other.jpg.json": "other-sha",
            },
        ):
            deduped = openclaw_web._dedupe_payload_images(payload)

        self.assertEqual(deduped["count"], 2)
        self.assertEqual(
            [item["sidecar_path"] for item in deduped["items"]],
            ["newer.jpg.json", "other.jpg.json"],
        )


if __name__ == "__main__":
    unittest.main()
