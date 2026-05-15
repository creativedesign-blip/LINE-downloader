from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from tools.indexing.index_db import TravelIndex
from tools.common.targets import DOWNLOADS_DIR, PROJECT_ROOT
from tools.openclaw.operations import (
    check_duplicates,
    processing_status,
    query_itineraries,
    query_latest_results,
    record_duplicate_review,
)


def insert_row(index: TravelIndex, sidecar: str, **overrides):
    data = {
        "sidecar_path": sidecar,
        "image_path": sidecar[:-5],
        "target_id": "source-a",
        "group_name": "Source A",
        "branded_path": sidecar.replace("/travel/", "/branded/")[:-5],
        "countries": ["泰國"],
        "months": [7],
        "price_from": 39900,
        "airlines": ["中華航空"],
        "regions": ["曼谷"],
        "duration_days": 5,
        "features": ["無購物站"],
        "source_time": "2026-04-30T08:00:00Z",
    }
    data.update(overrides)
    index.upsert(**data)


def insert_plan(index: TravelIndex, sidecar: str, plan_no: int, price_from: int, **overrides):
    data = {
        "plan_id": f"{sidecar}#plan:{plan_no}",
        "sidecar_path": sidecar,
        "image_path": sidecar[:-5],
        "branded_path": sidecar.replace("/travel/", "/branded/")[:-5],
        "target_id": "source-a",
        "group_name": "Source A",
        "plan_no": plan_no,
        "title": f"Plan {plan_no}",
        "raw_text": f"Plan {plan_no} {price_from}",
        "countries": ["瘜啣?"],
        "regions": ["?潸健"],
        "months": [7],
        "price_from": price_from,
        "duration_days": 5,
    }
    data.update(overrides)
    index.upsert_plan(**data)


class TestOpenClawOperations(unittest.TestCase):
    def setUp(self):
        test_name = self._testMethodName.replace("/", "_").replace("\\", "_")
        self.tmp_path = PROJECT_ROOT / ".test-openclaw" / test_name
        shutil.rmtree(self.tmp_path, ignore_errors=True)
        self.tmp_path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.tmp_path / "travel_index.db"
        with TravelIndex(self.db_path) as index:
            insert_row(
                index,
                "line-rpa/download/source-a/travel/a.jpg.json",
                target_id="source-a",
                group_name="Source A",
                source_time="2026-04-30T08:00:00Z",
            )
            insert_row(
                index,
                "line-rpa/download/source-b/travel/b.jpg.json",
                target_id="source-b",
                group_name="Source B",
                price_from=41000,
                source_time="2026-04-30T09:00:00Z",
            )
            insert_row(
                index,
                "line-rpa/download/source-c/travel/c.jpg.json",
                target_id="source-c",
                group_name="Source C",
                countries=["日本"],
                months=[4],
                regions=["東京"],
                price_from=69900,
                source_time="2026-04-29T09:00:00Z",
            )
            insert_plan(index, "line-rpa/download/source-a/travel/a.jpg.json", 1, 39900)
            insert_plan(index, "line-rpa/download/source-a/travel/a.jpg.json", 2, 49900)
            insert_plan(index, "line-rpa/download/source-b/travel/b.jpg.json", 1, 41000)

    def tearDown(self):
        shutil.rmtree(self.tmp_path, ignore_errors=True)

    def test_query_latest_results(self):
        result = query_latest_results(self.db_path, limit=2)
        self.assertEqual(result["count"], 2)
        self.assertIn("branded_path", result["items"][0])
        self.assertIn("plan_prices", result["items"][0])
        self.assertEqual(result["items"][0]["countries"], ["泰國"])

    def test_query_itineraries_by_country_month_price(self):
        result = query_itineraries(
            self.db_path,
            countries=["泰國"],
            months=[7],
            price_min=30000,
            price_max=45000,
        )
        self.assertEqual(result["count"], 2)
        self.assertEqual(
            {item["target_id"] for item in result["items"]},
            {"source-a", "source-b"},
        )

    def test_query_itineraries_by_duration_and_feature(self):
        result = query_itineraries(
            self.db_path,
            features=["無購物站"],
            duration_days=5,
            target_id="source-a",
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["target_id"], "source-a")

    def test_query_price_range_matches_plan_price(self):
        result = query_itineraries(
            self.db_path,
            months=[7],
            price_min=48000,
            price_max=51000,
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["target_id"], "source-a")
        self.assertEqual(result["items"][0]["plan_prices"], [39900, 49900])
        self.assertEqual(result["items"][0]["price_to"], 49900)

    def test_check_duplicates_across_sources(self):
        result = check_duplicates(self.db_path)
        self.assertEqual(result["count"], 1)
        group = result["groups"][0]
        self.assertEqual(group["count"], 2)
        self.assertEqual(set(group["sources"]), {"source-a", "source-b"})
        self.assertEqual(group["match"]["countries"], ["泰國"])
        self.assertEqual(group["match"]["months"], [7])

    def test_record_duplicate_review(self):
        review_path = self.tmp_path / "reviews.json"
        result = record_duplicate_review(
            "dup_1",
            ["line-rpa/download/source-a/travel/a.jpg.json"],
            review_path,
            archived_sidecar_paths=["line-rpa/download/source-b/travel/b.jpg.json"],
            reviewer="employee",
        )
        self.assertTrue(result["ok"])
        saved = json.loads(review_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["reviews"][0]["group_id"], "dup_1")
        self.assertEqual(saved["reviews"][0]["reviewer"], "employee")
        self.assertEqual(
            saved["reviews"][0]["archived_sidecar_paths"],
            ["line-rpa/download/source-b/travel/b.jpg.json"],
        )

    def test_archived_duplicate_hidden_from_queries(self):
        review_path = self.tmp_path / "reviews.json"
        duplicate_group_id = check_duplicates(self.db_path)["groups"][0]["group_id"]
        record_duplicate_review(
            duplicate_group_id,
            ["line-rpa/download/source-a/travel/a.jpg.json"],
            review_path,
            archived_sidecar_paths=["line-rpa/download/source-b/travel/b.jpg.json"],
        )

        self.assertEqual(check_duplicates(self.db_path, review_path=review_path)["count"], 0)
        self.assertEqual(
            check_duplicates(self.db_path, review_path=review_path, include_reviewed=True)["count"],
            1,
        )

        query = query_itineraries(
            self.db_path,
            months=[7],
            limit=10,
            review_path=review_path,
        )
        self.assertEqual({item["target_id"] for item in query["items"]}, {"source-a"})

        query_all = query_itineraries(
            self.db_path,
            months=[7],
            limit=10,
            include_archived=True,
            review_path=review_path,
        )
        self.assertEqual({item["target_id"] for item in query_all["items"]}, {"source-a", "source-b"})

        latest = query_latest_results(self.db_path, limit=10, review_path=review_path)
        self.assertNotIn("source-b", {item["target_id"] for item in latest["items"]})

    def test_processing_status_counts_folders_and_index(self):
        target_dir = DOWNLOADS_DIR / "__status_test__"
        try:
            shutil.rmtree(target_dir, ignore_errors=True)
            (target_dir / "travel").mkdir(parents=True)
            (target_dir / "branded").mkdir()
            (target_dir / "error").mkdir()
            (target_dir / "travel" / "a.jpg").write_bytes(b"x")
            (target_dir / "branded" / "a_branded.jpg").write_bytes(b"x")
            (target_dir / "error" / "bad.jpg").write_bytes(b"x")
            with TravelIndex(self.db_path) as index:
                insert_row(
                    index,
                    "line-rpa/download/__status_test__/travel/a.jpg.json",
                    target_id="__status_test__",
                )
            result = processing_status(self.db_path, target_id="__status_test__")
            self.assertEqual(result["count"], 1)
            item = result["items"][0]
            self.assertEqual(item["travel_count"], 1)
            self.assertEqual(item["branded_count"], 1)
            self.assertEqual(item["error_count"], 1)
            self.assertEqual(item["indexed_count"], 1)
            self.assertEqual(result["pipeline"]["label"], "LINE圖片處理中")
            self.assertTrue(result["pipeline"]["line_fetched_done"])
            self.assertTrue(result["pipeline"]["ocr_done"])
            self.assertTrue(result["pipeline"]["composed_done"])
            self.assertFalse(result["pipeline"]["is_complete"])
        finally:
            shutil.rmtree(target_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
