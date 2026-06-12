from __future__ import annotations

import unittest

from tools.sync.transform import build_dataset


class TransformTests(unittest.TestCase):
    def test_travel_rows_transform_to_crm_rows(self):
        travel = {
            "itineraries": [
                {
                    "sidecar_path": "line-rpa/download/a/travel/one.jpg.json",
                    "image_path": "line-rpa/download/a/travel/one.jpg",
                    "branded_path": "line-rpa/download/a/branded/one_branded.jpg",
                    "image_sha256": "sourcehash",
                    "image_phash": "phash",
                    "source_time": "2026-06-01T00:00:00Z",
                    "indexed_at": "2026-06-01T00:01:00Z",
                }
            ],
            "itinerary_plans": [
                {
                    "plan_id": "line-rpa/download/a/travel/one.jpg.json#plan:1",
                    "sidecar_path": "line-rpa/download/a/travel/one.jpg.json",
                    "branded_path": "line-rpa/download/a/branded/one_branded.jpg",
                    "group_name": "grp",
                    "title": "Japan Hokkaido 5 days",
                    "raw_text": "raw",
                    "country_csv": ",日本,",
                    "region_csv": ",北海道,",
                    "features_csv": ",賞楓,",
                    "months_csv": ",8,",
                    "price_from": 46800,
                    "duration_days": 5,
                    "indexed_at": "2026-06-01T00:01:00Z",
                }
            ],
            "itinerary_departures": [
                {
                    "departure_id": "dep1",
                    "plan_id": "line-rpa/download/a/travel/one.jpg.json#plan:1",
                    "sidecar_path": "line-rpa/download/a/travel/one.jpg.json",
                    "departure_date": "2026-08-23",
                    "date_text": "08/23",
                    "month": 8,
                    "day": 23,
                    "weekday": 0,
                    "price_from": 46800,
                    "duration_days": 5,
                    "indexed_at": "2026-06-01T00:01:00Z",
                }
            ],
        }
        upload = {
            "upload_folders": [],
            "uploaded_images": [],
            "uploaded_image_search_index": [],
            "manual_tags": [],
        }

        dataset = build_dataset(travel, upload)

        self.assertEqual(len(dataset.assets), 1)
        self.assertEqual(len(dataset.itineraries), 1)
        self.assertEqual(len(dataset.departures), 1)
        self.assertEqual(dataset.assets[0]["source_kind"], "travel_index")
        self.assertEqual(dataset.itineraries[0]["price_from_twd"], 46800)
        self.assertIn("北海道", dataset.itineraries[0]["destination_text"])
        token_keys = {(row["token_type"], row["normalized_token"]) for row in dataset.search_tokens}
        self.assertIn(("country", "日本"), token_keys)
        self.assertIn(("region", "北海道"), token_keys)
        self.assertIn(("month", "8"), token_keys)
        self.assertIn(("duration", "5"), token_keys)

    def test_upload_catalog_rows_transform_to_crm_rows(self):
        travel = {"itineraries": [], "itinerary_plans": [], "itinerary_departures": []}
        upload = {
            "upload_folders": [
                {
                    "id": 10,
                    "folder_slug": "upload_test",
                    "display_name": "manual batch",
                    "note": "",
                    "source": "upload",
                    "status": "done",
                    "current_step": "complete",
                    "image_count": 1,
                    "line_groups": "[]",
                    "captured_at": None,
                    "job_id": None,
                    "archived_at": None,
                    "archived_by": None,
                    "delete_after": None,
                    "created_at": "2026-06-01T00:00:00Z",
                    "updated_at": "2026-06-01T00:01:00Z",
                }
            ],
            "uploaded_images": [
                {
                    "id": 7,
                    "folder_id": 10,
                    "original_filename": "manual.jpg",
                    "stored_path": "line-rpa/download/upload_test/inbox/manual.jpg",
                    "sha256": "hash",
                    "display_name": "manual title",
                    "uploaded_at": "2026-06-01T00:00:00Z",
                    "archived_at": None,
                }
            ],
            "uploaded_image_search_index": [
                {
                    "image_id": 7,
                    "folder_id": 10,
                    "search_text": "Japan Hokkaido",
                    "raw_text": "Japan Hokkaido raw",
                    "country_csv": ",日本,",
                    "region_csv": ",北海道,",
                    "months_csv": ",8,",
                    "features_csv": ",手動,",
                    "price_from": 38800,
                    "duration_days": 5,
                    "sidecar_path": "line-rpa/download/upload_test/travel/manual.jpg.json",
                    "image_path": "line-rpa/download/upload_test/travel/manual.jpg",
                    "branded_path": "line-rpa/download/upload_test/branded/manual.jpg",
                    "source_time": "2026-06-01T00:00:00Z",
                    "indexed_at": "2026-06-01T00:01:00Z",
                }
            ],
            "manual_tags": [
                {
                    "id": 99,
                    "image_id": 7,
                    "tag": "主打",
                    "note": "",
                    "created_by": "web",
                    "created_at": "2026-06-01T00:02:00Z",
                }
            ],
        }

        dataset = build_dataset(travel, upload)

        self.assertEqual(len(dataset.upload_folders), 1)
        self.assertEqual(len(dataset.assets), 1)
        self.assertEqual(len(dataset.itineraries), 1)
        self.assertEqual(len(dataset.manual_tags), 1)
        self.assertEqual(dataset.assets[0]["asset_id"], "upload_catalog:image:7")
        self.assertEqual(dataset.itineraries[0]["source_kind"], "upload_catalog")
        token_keys = {(row["token_type"], row["normalized_token"]) for row in dataset.search_tokens}
        self.assertIn(("manual_tag", "主打"), token_keys)


if __name__ == "__main__":
    unittest.main()
