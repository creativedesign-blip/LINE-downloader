"""Unit tests for index_db.py — SQLite wrapper."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from tools.indexing.index_db import SCHEMA_VERSION, TravelIndex


def make_index() -> TravelIndex:
    return TravelIndex(":memory:")


def base_row(sidecar_path="downloads/metro/travel/a.jpg.json", **overrides):
    row = {
        "sidecar_path": sidecar_path,
        "image_path": sidecar_path[:-5],
        "target_id": "metro",
        "group_name": "思偉達",
        "branded_path": None,
        "countries": ["日本"],
        "months": [5],
        "price_from": 39900,
        "airlines": ["中華航空"],
        "regions": ["東京"],
        "duration_days": 5,
        "features": ["賞櫻"],
        "source_time": "2026-04-20T10:00:00Z",
    }
    row.update(overrides)
    return row


class TestSchema(unittest.TestCase):
    def test_creates_table(self):
        idx = make_index()
        self.assertEqual(idx.count(), 0)
        idx.close()

    def test_reinit_idempotent(self):
        idx = make_index()
        idx.upsert(**base_row())
        idx.close()
        # Re-init on a persistent path would preserve data; in-memory would not.
        # Here we just check the second init doesn't raise:
        TravelIndex(":memory:").close()


class TestUpsert(unittest.TestCase):
    def test_insert_increments_count(self):
        with make_index() as idx:
            idx.upsert(**base_row())
            self.assertEqual(idx.count(), 1)

    def test_upsert_same_key_replaces(self):
        with make_index() as idx:
            idx.upsert(**base_row(price_from=29900))
            idx.upsert(**base_row(price_from=19900))
            self.assertEqual(idx.count(), 1)
            rows = idx.query()
            self.assertEqual(rows[0]["price_from"], 19900)

    def test_csv_wrapping(self):
        with make_index() as idx:
            idx.upsert(**base_row(countries=["日本", "韓國"], months=[5, 11]))
            rows = idx.query()
            # Leading/trailing commas for exact-token match safety
            self.assertEqual(rows[0]["country_csv"], ",日本,韓國,")
            self.assertEqual(rows[0]["months_csv"], ",5,11,")

    def test_empty_collections_become_null(self):
        with make_index() as idx:
            idx.upsert(**base_row(countries=[], months=[], price_from=None))
            rows = idx.query()
            self.assertIsNone(rows[0]["country_csv"])
            self.assertIsNone(rows[0]["months_csv"])
            self.assertIsNone(rows[0]["price_from"])


class TestQuery(unittest.TestCase):
    def setUp(self):
        self.idx = make_index()
        self.idx.upsert(**base_row(
            sidecar_path="downloads/metro/travel/jp.jpg.json",
            countries=["日本"], months=[4, 5], price_from=35000,
        ))
        self.idx.upsert(**base_row(
            sidecar_path="downloads/metro/travel/kr.jpg.json",
            countries=["韓國"], months=[5, 6], price_from=25000,
        ))
        self.idx.upsert(**base_row(
            sidecar_path="downloads/metro/travel/th.jpg.json",
            countries=["泰國"], months=[1, 11, 12], price_from=18000,
        ))
        self.idx.upsert(**base_row(
            sidecar_path="downloads/other/travel/europe.jpg.json",
            target_id="other",
            countries=["荷蘭", "比利時"], months=[5, 6, 7], price_from=129900,
        ))

    def tearDown(self):
        self.idx.close()

    def test_no_filter_returns_all(self):
        self.assertEqual(len(self.idx.query()), 4)

    def test_filter_by_country(self):
        rows = self.idx.query(countries=["日本"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["country_csv"], ",日本,")

    def test_filter_by_countries_or(self):
        rows = self.idx.query(countries=["日本", "韓國"])
        self.assertEqual(len(rows), 2)

    def test_filter_by_month(self):
        rows = self.idx.query(months=[5])
        self.assertEqual(len(rows), 3)

    def test_filter_month_no_substring_collision(self):
        # months_csv for 'th.jpg.json' is ',1,11,12,'
        # Querying for month 1 must NOT accidentally match '11' or '12'.
        rows = self.idx.query(months=[1])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["country_csv"], ",泰國,")

    def test_filter_price_range(self):
        rows = self.idx.query(price_min=20000, price_max=40000)
        prices = {r["price_from"] for r in rows}
        self.assertEqual(prices, {35000, 25000})

    def test_combined_filters(self):
        rows = self.idx.query(countries=["日本", "韓國"], months=[5], price_max=30000)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["country_csv"], ",韓國,")

    def test_filter_by_target(self):
        rows = self.idx.query(target_id="other")
        self.assertEqual(len(rows), 1)

    def test_limit(self):
        rows = self.idx.query(limit=2)
        self.assertEqual(len(rows), 2)


class TestExtendedFields(unittest.TestCase):
    """Schema v2 columns: airline_csv, region_csv, duration_days, features_csv."""

    def test_csv_wrapping_new_fields(self):
        with make_index() as idx:
            idx.upsert(**base_row(
                airlines=["中華航空", "長榮航空"],
                regions=["東京", "大阪"],
                features=["賞櫻", "一泊三食"],
            ))
            row = idx.query()[0]
            self.assertEqual(row["airline_csv"], ",中華航空,長榮航空,")
            self.assertEqual(row["region_csv"], ",東京,大阪,")
            self.assertEqual(row["features_csv"], ",賞櫻,一泊三食,")

    def test_duration_days_stored(self):
        with make_index() as idx:
            idx.upsert(**base_row(duration_days=12))
            self.assertEqual(idx.query()[0]["duration_days"], 12)

    def test_filter_by_airline(self):
        with make_index() as idx:
            idx.upsert(**base_row(
                sidecar_path="a.json", airlines=["中華航空"]
            ))
            idx.upsert(**base_row(
                sidecar_path="b.json", airlines=["長榮航空"]
            ))
            idx.upsert(**base_row(
                sidecar_path="c.json", airlines=["國泰航空"]
            ))
            rows = idx.query(airlines=["中華航空", "長榮航空"])
            self.assertEqual(len(rows), 2)

    def test_filter_by_region(self):
        with make_index() as idx:
            idx.upsert(**base_row(sidecar_path="a.json", regions=["北海道"]))
            idx.upsert(**base_row(sidecar_path="b.json", regions=["沖繩"]))
            rows = idx.query(regions=["北海道"])
            self.assertEqual(len(rows), 1)

    def test_filter_by_duration_exact(self):
        with make_index() as idx:
            idx.upsert(**base_row(sidecar_path="a.json", duration_days=5))
            idx.upsert(**base_row(sidecar_path="b.json", duration_days=8))
            idx.upsert(**base_row(sidecar_path="c.json", duration_days=12))
            rows = idx.query(duration_days=8)
            self.assertEqual(len(rows), 1)

    def test_filter_by_duration_range(self):
        with make_index() as idx:
            idx.upsert(**base_row(sidecar_path="a.json", duration_days=3))
            idx.upsert(**base_row(sidecar_path="b.json", duration_days=7))
            idx.upsert(**base_row(sidecar_path="c.json", duration_days=14))
            rows = idx.query(duration_min=5, duration_max=10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["duration_days"], 7)

    def test_filter_by_features(self):
        with make_index() as idx:
            idx.upsert(**base_row(sidecar_path="a.json", features=["賞櫻"]))
            idx.upsert(**base_row(sidecar_path="b.json", features=["賞楓"]))
            rows = idx.query(features=["賞櫻"])
            self.assertEqual(len(rows), 1)


class TestMigration(unittest.TestCase):
    """PRAGMA user_version-based migration logic."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_migrate.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_fresh_db_gets_current_schema(self):
        with TravelIndex(self.db_path) as idx:
            self.assertEqual(idx.count(), 0)
        conn = sqlite3.connect(self.db_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        self.assertEqual(version, SCHEMA_VERSION)

    def test_stale_version_migrates_when_allowed(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            "CREATE TABLE itineraries (x INTEGER); "
            "INSERT INTO itineraries VALUES (1); "
            "PRAGMA user_version = 999;"
        )
        conn.commit()
        conn.close()

        with TravelIndex(self.db_path, migrate=True) as idx:
            self.assertEqual(idx.count(), 0)

        conn = sqlite3.connect(self.db_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        self.assertEqual(version, SCHEMA_VERSION)

    def test_stale_version_raises_when_migrate_false(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            "CREATE TABLE itineraries (x INTEGER); "
            "PRAGMA user_version = 999;"
        )
        conn.commit()
        conn.close()

        with self.assertRaises(RuntimeError) as ctx:
            TravelIndex(self.db_path, migrate=False)
        self.assertIn("schema version", str(ctx.exception))

    def test_fresh_db_allowed_with_migrate_false(self):
        with TravelIndex(self.db_path, migrate=False) as idx:
            self.assertEqual(idx.count(), 0)

    def test_matching_version_preserves_data(self):
        with TravelIndex(self.db_path) as idx:
            idx.upsert(**base_row())
            self.assertEqual(idx.count(), 1)

        with TravelIndex(self.db_path) as idx:
            self.assertEqual(idx.count(), 1)


class TestDelete(unittest.TestCase):
    def test_delete_removes_row(self):
        with make_index() as idx:
            idx.upsert(**base_row())
            self.assertEqual(idx.count(), 1)
            idx.delete("downloads/metro/travel/a.jpg.json")
            self.assertEqual(idx.count(), 0)

    def test_delete_nonexistent_is_noop(self):
        with make_index() as idx:
            idx.delete("never-existed")
            self.assertEqual(idx.count(), 0)


class TestClear(unittest.TestCase):
    def test_clear_empties_table(self):
        with make_index() as idx:
            for i in range(5):
                idx.upsert(**base_row(
                    sidecar_path=f"downloads/metro/travel/a{i}.jpg.json"
                ))
            self.assertEqual(idx.count(), 5)
            idx.clear()
            self.assertEqual(idx.count(), 0)


class TestFreshness(unittest.TestCase):
    def test_get_freshness_returns_none_for_unknown(self):
        with make_index() as idx:
            self.assertIsNone(idx.get_freshness("never-indexed.jpg.json"))

    def test_upsert_records_mtime_and_version(self):
        with make_index() as idx:
            idx.upsert(**base_row(), sidecar_mtime=1234.5, extractor_version="v2")
            f = idx.get_freshness("downloads/metro/travel/a.jpg.json")
            self.assertEqual(f, {"sidecar_mtime": 1234.5, "extractor_version": "v2"})

    def test_list_sidecar_paths_scopes_to_targets(self):
        with make_index() as idx:
            idx.upsert(**base_row(
                sidecar_path="downloads/metro/travel/a.jpg.json", target_id="metro",
            ))
            idx.upsert(**base_row(
                sidecar_path="downloads/agoda/travel/b.jpg.json", target_id="agoda",
            ))
            metro_only = idx.list_sidecar_paths(["metro"])
            self.assertEqual(metro_only, {"downloads/metro/travel/a.jpg.json"})
            both = idx.list_sidecar_paths(["metro", "agoda"])
            self.assertEqual(len(both), 2)
            all_paths = idx.list_sidecar_paths()
            self.assertEqual(len(all_paths), 2)


if __name__ == "__main__":
    unittest.main()
