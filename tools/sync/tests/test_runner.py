from __future__ import annotations

import unittest

from tools.sync.models import AssetMedia, MediaResult, SyncDataset
from tools.sync.runner import apply_media_results, write_dataset


class RunnerTests(unittest.TestCase):
    def test_apply_media_results_copies_url_to_related_rows(self):
        dataset = SyncDataset(
            assets=[
                {
                    "asset_id": "asset1",
                    "crm_media_id": None,
                    "crm_media_url": None,
                    "public_image_url": None,
                    "crm_media_status": "pending",
                }
            ],
            itineraries=[
                {
                    "itinerary_id": "it1",
                    "asset_id": "asset1",
                    "crm_media_url": None,
                    "public_image_url": None,
                }
            ],
            departures=[
                {
                    "departure_id": "dep1",
                    "asset_id": "asset1",
                    "crm_media_url": None,
                    "public_image_url": None,
                }
            ],
            search_tokens=[],
            upload_folders=[],
            manual_tags=[],
            media=[
                AssetMedia(
                    asset_id="asset1",
                    source_kind="travel_index",
                    source_path="x.jpg",
                    file_path=None,
                )
            ],
            warnings=[],
        )

        apply_media_results(
            dataset,
            {
                "asset1": MediaResult(
                    media_id="m1",
                    url="https://crm.example.test/m1.jpg",
                    sha256="abc",
                )
            },
        )

        self.assertEqual(dataset.assets[0]["crm_media_id"], "m1")
        self.assertEqual(dataset.assets[0]["public_image_url"], "https://crm.example.test/m1.jpg")
        self.assertEqual(dataset.itineraries[0]["public_image_url"], "https://crm.example.test/m1.jpg")
        self.assertEqual(dataset.departures[0]["public_image_url"], "https://crm.example.test/m1.jpg")

    def test_write_dataset_commits_one_transaction_and_reconciles_stale_rows(self):
        dataset = SyncDataset(
            assets=[{"asset_id": "asset1", "source_kind": "travel_index"}],
            itineraries=[{"itinerary_id": "it1", "source_kind": "travel_index"}],
            departures=[{"departure_id": "dep1", "source_kind": "travel_index"}],
            search_tokens=[
                {
                    "itinerary_id": "it1",
                    "asset_id": "asset1",
                    "source_kind": "travel_index",
                    "token_type": "country",
                    "token_value": "Japan",
                    "normalized_token": "Japan",
                    "source_field": "country_csv",
                    "confidence": 1.0,
                    "weight": 4,
                }
            ],
            upload_folders=[{"folder_id": 7}],
            manual_tags=[{"tag_id": 9}],
            media=[],
            warnings=[],
        )
        writer = RecordingWriter()

        counts = write_dataset(dataset, writer)

        self.assertTrue(writer.committed)
        self.assertFalse(writer.rolled_back)
        self.assertIn(("begin",), writer.calls)
        self.assertIn(("commit",), writer.calls)
        self.assertIn(("replace_search_tokens", 1), writer.calls)
        self.assertIn(("mark_missing_inactive", "crm_assets", "travel_index", ("asset1",)), writer.calls)
        self.assertIn(("delete_missing", "crm_manual_tags", ("9",)), writer.calls)
        self.assertEqual(counts["crm_search_tokens"], 1)

    def test_write_dataset_rolls_back_on_failure(self):
        dataset = SyncDataset(
            assets=[{"asset_id": "asset1", "source_kind": "travel_index"}],
            itineraries=[],
            departures=[],
            search_tokens=[],
            upload_folders=[],
            manual_tags=[],
            media=[],
            warnings=[],
        )
        writer = RecordingWriter(fail_table="crm_assets")

        with self.assertRaises(RuntimeError):
            write_dataset(dataset, writer)

        self.assertFalse(writer.committed)
        self.assertTrue(writer.rolled_back)
        self.assertIn(("rollback",), writer.calls)


class RecordingWriter:
    def __init__(self, fail_table: str | None = None) -> None:
        self.fail_table = fail_table
        self.calls: list[tuple] = []
        self.committed = False
        self.rolled_back = False

    def begin(self) -> None:
        self.calls.append(("begin",))

    def commit(self) -> None:
        self.calls.append(("commit",))
        self.committed = True

    def rollback(self) -> None:
        self.calls.append(("rollback",))
        self.rolled_back = True

    def upsert_many(self, table: str, rows: list[dict]) -> int:
        self.calls.append(("upsert_many", table, len(rows)))
        if table == self.fail_table:
            raise RuntimeError(f"failed {table}")
        return len(rows)

    def replace_search_tokens(self, rows: list[dict]) -> int:
        self.calls.append(("replace_search_tokens", len(rows)))
        return len(rows)

    def mark_missing_inactive(self, table: str, source_kind: str, current_keys: set[str], updated_at: str) -> int:
        self.calls.append(("mark_missing_inactive", table, source_kind, tuple(sorted(current_keys))))
        return 0

    def delete_missing(self, table: str, current_keys: set[str]) -> int:
        self.calls.append(("delete_missing", table, tuple(sorted(current_keys))))
        return 0


if __name__ == "__main__":
    unittest.main()
