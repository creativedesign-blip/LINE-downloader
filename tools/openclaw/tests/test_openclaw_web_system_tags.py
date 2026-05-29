import importlib.util
import gc
import sqlite3
import tempfile
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

    def test_system_tag_override_rejects_new_tags(self):
        override = openclaw_web._system_tag_override_for_update(
            ["日本", "東京", "5月"],
            ["日本", "東京", "郵輪"],
        )

        self.assertEqual(override, ["日本", "東京"])

    def test_system_tag_override_can_clear_all_source_tags(self):
        override = openclaw_web._system_tag_override_for_update(
            ["日本", "東京"],
            [],
        )

        self.assertEqual(override, [openclaw_web.SYSTEM_TAGS_CLEARED_SENTINEL])

    def test_line_annotation_manual_tags_are_queryable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "travel_index.db"
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute(
                    """
                    CREATE TABLE itineraries (
                        sidecar_path TEXT,
                        image_path TEXT,
                        branded_path TEXT,
                        target_id TEXT,
                        group_name TEXT,
                        country_csv TEXT,
                        region_csv TEXT,
                        months_csv TEXT,
                        price_from INTEGER,
                        airline_csv TEXT,
                        duration_days INTEGER,
                        features_csv TEXT,
                        source_time TEXT,
                        indexed_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO itineraries (
                        sidecar_path, image_path, branded_path, target_id, group_name,
                        country_csv, region_csv, months_csv, price_from, airline_csv,
                        duration_days, features_csv, source_time, indexed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "line-rpa/download/group/travel/0001.jpg.json",
                        "line-rpa/download/group/travel/0001.jpg",
                        "line-rpa/download/group/branded/0001.jpg",
                        "group",
                        "LINE Group",
                        ",日本,",
                        ",東京,",
                        ",6,",
                        39900,
                        "",
                        5,
                        ",美食,",
                        "2026-05-26T00:00:00Z",
                        "2026-05-26T00:00:00Z",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            with (
                patch.object(openclaw_web, "DEFAULT_DB_PATH", db_path),
                patch.object(
                    openclaw_web,
                    "_read_item_annotations",
                    return_value={
                        "line:line-rpa/download/group/travel/0001.jpg.json": {
                            "manual_tags": ["神女號"],
                            "reference_text": "",
                            "manual_note": "",
                        }
                    },
                ),
            ):
                items = openclaw_web._query_line_annotation_results(
                    "神女號",
                    {"countries": [], "regions": [], "months": [], "features": []},
                    limit=10,
                )
            gc.collect()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["sidecar_path"], "line-rpa/download/group/travel/0001.jpg.json")
        self.assertIn("神女號", items[0]["features"])
        self.assertEqual(items[0]["manual_tags"], [{"id": "line-1", "tag": "神女號"}])

    def test_line_annotation_query_combines_db_filters_with_manual_terms(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "travel_index.db"
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute(
                    """
                    CREATE TABLE itineraries (
                        sidecar_path TEXT,
                        image_path TEXT,
                        branded_path TEXT,
                        target_id TEXT,
                        group_name TEXT,
                        country_csv TEXT,
                        region_csv TEXT,
                        months_csv TEXT,
                        price_from INTEGER,
                        airline_csv TEXT,
                        duration_days INTEGER,
                        features_csv TEXT,
                        source_time TEXT,
                        indexed_at TEXT
                    )
                    """
                )
                rows = [
                    (
                        "line-rpa/download/japan/travel/0001.jpg.json",
                        "line-rpa/download/japan/travel/0001.jpg",
                        "line-rpa/download/japan/branded/0001.jpg",
                        "japan",
                        "Japan Group",
                        ",Japan,",
                        ",Tokyo,",
                        ",6,",
                        39900,
                        "",
                        5,
                        ",food,",
                        "2026-05-26T00:00:00Z",
                        "2026-05-26T00:00:00Z",
                    ),
                    (
                        "line-rpa/download/korea/travel/0002.jpg.json",
                        "line-rpa/download/korea/travel/0002.jpg",
                        "line-rpa/download/korea/branded/0002.jpg",
                        "korea",
                        "Korea Group",
                        ",Korea,",
                        ",Seoul,",
                        ",6,",
                        29900,
                        "",
                        4,
                        ",food,",
                        "2026-05-26T00:00:00Z",
                        "2026-05-26T00:00:00Z",
                    ),
                ]
                conn.executemany(
                    """
                    INSERT INTO itineraries (
                        sidecar_path, image_path, branded_path, target_id, group_name,
                        country_csv, region_csv, months_csv, price_from, airline_csv,
                        duration_days, features_csv, source_time, indexed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                conn.commit()
            finally:
                conn.close()

            with (
                patch.object(openclaw_web, "DEFAULT_DB_PATH", db_path),
                patch.object(
                    openclaw_web,
                    "_read_item_annotations",
                    return_value={
                        "line:line-rpa/download/japan/travel/0001.jpg.json": {
                            "manual_tags": ["Venus"],
                            "reference_text": "",
                            "manual_note": "",
                        },
                        "line:line-rpa/download/korea/travel/0002.jpg.json": {
                            "manual_tags": ["Venus"],
                            "reference_text": "",
                            "manual_note": "",
                        },
                    },
                ),
            ):
                items = openclaw_web._query_line_annotation_results(
                    "Japan Venus",
                    {"countries": ["Japan"], "regions": [], "months": [], "features": []},
                    limit=10,
                )
            gc.collect()

        self.assertEqual([item["sidecar_path"] for item in items], [
            "line-rpa/download/japan/travel/0001.jpg.json",
        ])

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
