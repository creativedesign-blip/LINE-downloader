from __future__ import annotations

import unittest

from tools.sync.mysql_writer import build_upsert_sql


class MySQLWriterTests(unittest.TestCase):
    def test_search_token_upsert_does_not_write_generated_hash(self):
        sql, params = build_upsert_sql(
            "crm_search_tokens",
            [
                {
                    "itinerary_id": "it1",
                    "asset_id": "asset1",
                    "source_kind": "travel_index",
                    "token_type": "country",
                    "token_value": "日本",
                    "normalized_token": "日本",
                    "source_field": "country_csv",
                    "confidence": 1.0,
                    "weight": 4,
                }
            ],
        )

        self.assertNotIn("token_uniq_hash", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertEqual(len(params), 1)
        self.assertEqual(len(params[0]), 9)

    def test_assets_upsert_has_expected_primary_key(self):
        sql, _ = build_upsert_sql(
            "crm_assets",
            [
                {
                    "asset_id": "asset1",
                    "source_kind": "travel_index",
                    "source_table": "itineraries",
                    "source_pk": "asset1",
                }
            ],
        )

        self.assertIn("INSERT INTO `crm_assets`", sql)
        self.assertNotIn("`asset_id` = VALUES(`asset_id`)", sql)


if __name__ == "__main__":
    unittest.main()
