from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.indexing.index_db import TravelIndex
from tools.indexing.reindex import index_one


class TestReindexSecondPassProducts(unittest.TestCase):
    def test_indexes_codex_second_pass_products_as_plans(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "sample.png"
            sidecar = root / "sample.png.json"
            image.write_bytes(b"image")
            sidecar.write_text(
                json.dumps(
                    {
                        "ocr": {
                            "text": "日本東京 5天 NT$49,800",
                            "classification": "travel",
                            "imageSha256": "abc",
                        },
                        "secondPassOcr": {
                            "provider": "codex",
                            "status": "enriched",
                            "products": [
                                {
                                    "title": "東京五日",
                                    "country": "日本",
                                    "regions": ["東京"],
                                    "duration_days": 5,
                                    "price_from": 49800,
                                    "departures": ["2026-06-20"],
                                    "evidence": ["日本東京", "5天", "49,800"],
                                    "confidence": "high",
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with TravelIndex(":memory:") as index:
                index.upsert_plan(
                    plan_id=f"{sidecar.as_posix()}#stale",
                    sidecar_path=sidecar.as_posix(),
                    image_path=image.as_posix(),
                    plan_no=99,
                    title="stale",
                )
                self.assertEqual(index_one(sidecar, index), "indexed")
                self.assertEqual(index.plan_count(), 1)
                self.assertEqual(index.departure_count(), 1)
                plan = index.conn.execute("SELECT title, price_from, duration_days FROM itinerary_plans").fetchone()

        self.assertEqual(tuple(plan), ("東京五日", 49800, 5))


if __name__ == "__main__":
    unittest.main()
