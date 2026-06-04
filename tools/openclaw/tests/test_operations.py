from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from tools.indexing.index_db import TravelIndex
from tools.common.targets import DOWNLOADS_DIR, PROJECT_ROOT
from tools.openclaw.operations import (
    auto_resolve_image_duplicates,
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


def insert_departure(index: TravelIndex, sidecar: str, *, departure_date: str,
                     price_from: int, duration_days: int = 5,
                     target_id: str = "source-a", group_name: str = "Source A",
                     plan_no: int = 1):
    index.upsert_departure(
        departure_id=f"{sidecar}#dep:{departure_date}",
        plan_id=f"{sidecar}#plan:{plan_no}",
        sidecar_path=sidecar,
        image_path=sidecar[:-5],
        target_id=target_id,
        group_name=group_name,
        departure_date=departure_date,
        month=int(departure_date[5:7]),
        day=int(departure_date[8:10]),
        weekday=0,
        price_from=price_from,
        duration_days=duration_days,
    )


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
            # a and b are the same deal: same destination, departure date,
            # duration and exact price (per-departure price, not the image min).
            insert_departure(
                index, "line-rpa/download/source-a/travel/a.jpg.json",
                departure_date="2026-08-23", price_from=20900, duration_days=5,
                target_id="source-a", group_name="Source A",
            )
            insert_departure(
                index, "line-rpa/download/source-b/travel/b.jpg.json",
                departure_date="2026-08-23", price_from=20900, duration_days=5,
                target_id="source-b", group_name="Source B",
            )

    def tearDown(self):
        shutil.rmtree(self.tmp_path, ignore_errors=True)

    def test_query_latest_results(self):
        result = query_latest_results(self.db_path, limit=2)
        self.assertEqual(result["count"], 2)
        self.assertIn("branded_path", result["items"][0])
        self.assertIn("plan_prices", result["items"][0])
        self.assertEqual(result["items"][0]["countries"], ["泰國"])

    def test_query_latest_results_dedupes_by_image_sha256(self):
        with TravelIndex(self.db_path) as index:
            insert_row(
                index,
                "line-rpa/download/source-old/travel/old.jpg.json",
                target_id="source-old",
                group_name="Source Old",
                image_sha256="same-image",
                source_time="2026-04-30T07:00:00Z",
            )
            insert_row(
                index,
                "line-rpa/download/source-new/travel/new.jpg.json",
                target_id="source-new",
                group_name="Source New",
                image_sha256="same-image",
                source_time="2026-04-30T10:00:00Z",
            )

        result = query_latest_results(self.db_path, limit=10)
        same_image_items = [
            item for item in result["items"]
            if item["sidecar_path"] in {
                "line-rpa/download/source-old/travel/old.jpg.json",
                "line-rpa/download/source-new/travel/new.jpg.json",
            }
        ]

        self.assertEqual(len(same_image_items), 1)
        self.assertEqual(same_image_items[0]["target_id"], "source-new")

    def test_query_latest_results_keeps_older_duplicate_when_latest_is_archived(self):
        older_sidecar = "line-rpa/download/source-old/travel/old-keep.jpg.json"
        newer_sidecar = "line-rpa/download/source-new/travel/new-archived.jpg.json"
        with TravelIndex(self.db_path) as index:
            insert_row(
                index,
                older_sidecar,
                target_id="source-old",
                group_name="Source Old",
                image_sha256="same-archived-image",
                source_time="2026-04-30T07:00:00Z",
            )
            insert_row(
                index,
                newer_sidecar,
                target_id="source-new",
                group_name="Source New",
                image_sha256="same-archived-image",
                source_time="2026-04-30T10:00:00Z",
            )
        review_path = self.tmp_path / "reviews.json"
        record_duplicate_review(
            "same-archived-image",
            [older_sidecar],
            review_path,
            archived_sidecar_paths=[newer_sidecar],
        )

        result = query_latest_results(self.db_path, limit=10, review_path=review_path)
        same_image_items = [
            item for item in result["items"]
            if item["sidecar_path"] in {older_sidecar, newer_sidecar}
        ]

        self.assertEqual(len(same_image_items), 1)
        self.assertEqual(same_image_items[0]["sidecar_path"], older_sidecar)

    def test_query_latest_results_overfetches_after_dedupe(self):
        with TravelIndex(self.db_path) as index:
            for number in range(110):
                insert_row(
                    index,
                    f"line-rpa/download/source-dup/travel/dup-{number}.jpg.json",
                    target_id=f"source-dup-{number}",
                    group_name="Source Dup",
                    image_sha256="same-overfetch-image",
                    source_time="2026-04-30T10:00:00Z",
                )

        result = query_latest_results(self.db_path, limit=2)

        self.assertEqual(result["count"], 2)
        self.assertEqual(
            len([
                item for item in result["items"]
                if str(item["sidecar_path"]).startswith("line-rpa/download/source-dup/")
            ]),
            1,
        )

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
        self.assertEqual(group["match"]["departure_date"], "2026-08-23")
        self.assertEqual(group["match"]["duration_days"], 5)
        self.assertEqual(group["match"]["price_from"], 20900)

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

    def test_check_duplicates_flags_identical_image_as_certain(self):
        # Two sources sharing the same image_sha256 but otherwise unrelated
        # metadata must still be caught as a certain duplicate.
        with TravelIndex(self.db_path) as index:
            insert_row(
                index,
                "line-rpa/download/source-x/travel/x.jpg.json",
                target_id="source-x",
                group_name="Source X",
                countries=["越南"],
                months=[11],
                regions=["峴港"],
                price_from=22900,
                image_sha256="shared-image-hash",
            )
            insert_row(
                index,
                "line-rpa/download/source-y/travel/y.jpg.json",
                target_id="source-y",
                group_name="Source Y",
                countries=["越南"],
                months=[12],
                regions=["富國島"],
                price_from=88000,
                duration_days=8,
                image_sha256="shared-image-hash",
            )
        groups = check_duplicates(self.db_path)["groups"]
        certain = [g for g in groups if g["match_type"] == "image_sha256"]
        self.assertEqual(len(certain), 1)
        self.assertEqual(certain[0]["confidence"], "certain")
        self.assertEqual(certain[0]["count"], 2)
        self.assertEqual(certain[0]["match"]["image_sha256"], "shared-image-hash")
        self.assertEqual(set(certain[0]["sources"]), {"source-x", "source-y"})

    def test_check_duplicates_requires_same_price_for_offer(self):
        # The offer signature includes the exact price: same destination,
        # departure date and duration but different prices are different deals
        # and must NOT group.
        with TravelIndex(self.db_path) as index:
            for tid, price in (("source-p", 38000), ("source-q", 80000)):
                sidecar = f"line-rpa/download/{tid}/travel/{tid}.jpg.json"
                insert_row(
                    index, sidecar, target_id=tid, group_name=tid,
                    countries=["韓國"], months=[9], regions=["首爾"],
                )
                insert_departure(
                    index, sidecar, departure_date="2026-09-01",
                    price_from=price, duration_days=5, target_id=tid, group_name=tid,
                )
        korea = [
            g for g in check_duplicates(self.db_path)["groups"]
            if g["match"].get("countries") == ["韓國"]
        ]
        self.assertEqual(korea, [])

    def test_auto_resolve_image_duplicates_removes_image_tier_from_review(self):
        # Image-tier duplicates are confident enough to resolve without a human:
        # auto keep-one logically archives the extras, and they no longer show
        # up in the (metadata-only) human review list.
        review_path = self.tmp_path / "reviews.json"
        with TravelIndex(self.db_path) as index:
            insert_row(
                index,
                "line-rpa/download/src-ia/travel/img-a.jpg.json",
                target_id="src-ia",
                group_name="Image A",
                countries=["日本"],
                months=[3],
                regions=["東京"],
                image_sha256="img-dup",
            )
            insert_row(
                index,
                "line-rpa/download/src-ib/travel/img-b.jpg.json",
                target_id="src-ib",
                group_name="Image B",
                countries=["日本"],
                months=[3],
                regions=["東京"],
                image_sha256="img-dup",
            )
        summary = auto_resolve_image_duplicates(self.db_path, review_path=review_path)
        self.assertEqual(summary["resolved_groups"], 1)
        self.assertEqual(summary["archived_images"], 1)
        after = check_duplicates(self.db_path, review_path=review_path)["groups"]
        self.assertEqual([g for g in after if g["match_type"] == "image_sha256"], [])

    def test_auto_resolve_keeps_branded_copy(self):
        # Keep the copy that actually has a branded image, even if the plain
        # copy is otherwise a tiebreak winner — has_branded reflects the real
        # branded column, not the image_path display fallback.
        review_path = self.tmp_path / "reviews.json"
        branded = "line-rpa/download/src-keep/travel/keep.jpg.json"
        plain = "line-rpa/download/src-arch/travel/arch.jpg.json"
        with TravelIndex(self.db_path) as index:
            insert_row(
                index, branded, target_id="src-keep", group_name="K",
                countries=["日本"], months=[3], regions=["東京"], image_sha256="brand-dup",
            )
            insert_row(
                index, plain, target_id="src-arch", group_name="A",
                countries=["日本"], months=[3], regions=["東京"], image_sha256="brand-dup",
                branded_path=None,
            )
        auto_resolve_image_duplicates(self.db_path, review_path=review_path)
        entry = json.loads(review_path.read_text(encoding="utf-8"))["reviews"][0]
        self.assertEqual(entry["kept_sidecar_path"], branded)
        self.assertEqual(entry["archived_sidecar_paths"], [plain])

    def test_check_duplicates_include_certain_false_drops_sha_tier(self):
        # The review surface passes include_certain=False: sha-identical groups
        # (already collapsed by the query layer) are dropped, while phash and
        # metadata tiers remain.
        with TravelIndex(self.db_path) as index:
            insert_row(
                index,
                "line-rpa/download/src-ja/travel/ja.jpg.json",
                target_id="src-ja",
                group_name="JA",
                countries=["日本"],
                months=[3],
                regions=["東京"],
                image_sha256="rev-dup",
            )
            insert_row(
                index,
                "line-rpa/download/src-jb/travel/jb.jpg.json",
                target_id="src-jb",
                group_name="JB",
                countries=["日本"],
                months=[3],
                regions=["東京"],
                image_sha256="rev-dup",
            )
        review_view = check_duplicates(self.db_path, include_certain=False)["groups"]
        self.assertEqual([g for g in review_view if g["match_type"] == "image_sha256"], [])
        # setUp's a/b offer group is metadata and must still be present.
        self.assertTrue(any(g["match_type"] == "metadata" for g in review_view))
        # The default still surfaces the certain tier.
        default_view = check_duplicates(self.db_path)["groups"]
        self.assertTrue(any(g["match_type"] == "image_sha256" for g in default_view))

    def test_same_source_near_image_does_not_block_cross_source_offer(self):
        # A near-phash pair within ONE source is source-filtered (never shown),
        # so it must NOT claim its members — otherwise A's genuine cross-source
        # offer duplicate with C would be missed.
        with TravelIndex(self.db_path) as index:
            insert_row(
                index, "line-rpa/download/src-1/travel/a.jpg.json",
                target_id="src-1", group_name="S1", countries=["越南"], months=[8],
                regions=["峴港"], image_sha256="sha-A", image_phash="ffffffffffffffff",
            )
            insert_row(
                index, "line-rpa/download/src-1/travel/b.jpg.json",
                target_id="src-1", group_name="S1", countries=["越南"], months=[8],
                regions=["峴港"], image_sha256="sha-B", image_phash="fffffffffffffffe",
            )
            insert_row(
                index, "line-rpa/download/src-2/travel/c.jpg.json",
                target_id="src-2", group_name="S2", countries=["越南"], months=[8],
                regions=["峴港"], image_sha256="sha-C", image_phash="0000000000000000",
            )
            insert_departure(
                index, "line-rpa/download/src-1/travel/a.jpg.json",
                departure_date="2026-08-23", price_from=20900, duration_days=5,
                target_id="src-1", group_name="S1",
            )
            insert_departure(
                index, "line-rpa/download/src-2/travel/c.jpg.json",
                departure_date="2026-08-23", price_from=20900, duration_days=5,
                target_id="src-2", group_name="S2",
            )
        offers = [
            g for g in check_duplicates(self.db_path)["groups"]
            if g["match"].get("countries") == ["越南"]
            and g["match"].get("departure_date") == "2026-08-23"
        ]
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["count"], 2)
        self.assertEqual(set(offers[0]["sources"]), {"src-1", "src-2"})

    def test_check_duplicates_month_fallback_without_departures(self):
        # No extracted departure → fall back to month level: same destination +
        # month + duration + exact price groups; a different price does not.
        with TravelIndex(self.db_path) as index:
            for tid, price in (("source-v1", 25000), ("source-v2", 25000), ("source-v3", 30000)):
                insert_row(
                    index, f"line-rpa/download/{tid}/travel/{tid}.jpg.json",
                    target_id=tid, group_name=tid,
                    countries=["越南"], months=[10], regions=["峴港"], price_from=price,
                )
        vietnam = [
            g for g in check_duplicates(self.db_path)["groups"]
            if g["match"].get("countries") == ["越南"]
        ]
        self.assertEqual(len(vietnam), 1)
        self.assertEqual(vietnam[0]["count"], 2)
        self.assertEqual(vietnam[0]["match"]["months"], [10])
        self.assertEqual(vietnam[0]["match"]["price_from"], 25000)
        self.assertNotIn("departure_date", vietnam[0]["match"])

    def test_check_duplicates_country_order_does_not_split_group(self):
        # Same multi-country product listed in different token order must stay
        # in one group thanks to normalized (sorted) keys.
        with TravelIndex(self.db_path) as index:
            insert_row(
                index,
                "line-rpa/download/source-m/travel/m.jpg.json",
                target_id="source-m",
                group_name="Source M",
                countries=["日本", "韓國"],
                months=[5],
                regions=["大阪", "首爾"],
            )
            insert_row(
                index,
                "line-rpa/download/source-n/travel/n.jpg.json",
                target_id="source-n",
                group_name="Source N",
                countries=["韓國", "日本"],
                months=[5],
                regions=["首爾", "大阪"],
            )
            insert_departure(
                index, "line-rpa/download/source-m/travel/m.jpg.json",
                departure_date="2026-05-10", price_from=55000, duration_days=5,
                target_id="source-m", group_name="Source M",
            )
            insert_departure(
                index, "line-rpa/download/source-n/travel/n.jpg.json",
                departure_date="2026-05-10", price_from=55000, duration_days=5,
                target_id="source-n", group_name="Source N",
            )
        groups = check_duplicates(self.db_path)["groups"]
        combo = [g for g in groups if set(g["match"].get("countries", [])) == {"日本", "韓國"}]
        self.assertEqual(len(combo), 1)
        self.assertEqual(combo[0]["count"], 2)

    def test_review_survives_group_id_drift(self):
        # A review recorded against the current group_id should keep hiding the
        # same items even if the group_id later changes (e.g. key formula tweak),
        # because the members are covered by the reviewed path set.
        review_path = self.tmp_path / "reviews.json"
        record_duplicate_review(
            "stale-group-id-that-no-longer-matches",
            ["line-rpa/download/source-a/travel/a.jpg.json"],
            review_path,
            archived_sidecar_paths=["line-rpa/download/source-b/travel/b.jpg.json"],
        )
        self.assertEqual(check_duplicates(self.db_path, review_path=review_path)["count"], 0)
        self.assertEqual(
            check_duplicates(self.db_path, review_path=review_path, include_reviewed=True)["count"],
            1,
        )

    def test_ignore_review_survives_group_id_drift(self):
        # An "ignore" review now records every member path, so it keeps hiding
        # the group even when the group_id no longer matches.
        review_path = self.tmp_path / "reviews.json"
        record_duplicate_review(
            "stale-id-after-key-change",
            [
                "line-rpa/download/source-a/travel/a.jpg.json",
                "line-rpa/download/source-b/travel/b.jpg.json",
            ],
            review_path,
            action="ignore",
        )
        self.assertEqual(check_duplicates(self.db_path, review_path=review_path)["count"], 0)

    def test_check_duplicates_collapses_same_source_identical_rows(self):
        # The same file re-indexed under two sidecars in ONE source is a re-index
        # artifact, not a reviewable duplicate: it must not surface on its own,
        # and a genuine second source still forms a 2-source certain group.
        with TravelIndex(self.db_path) as index:
            insert_row(
                index,
                "line-rpa/download/source-dup/travel/first.jpg.json",
                target_id="source-dup",
                group_name="Dup Source",
                countries=["馬來西亞"],
                months=[8],
                regions=["吉隆坡"],
                image_sha256="collapse-sha",
            )
            insert_row(
                index,
                "line-rpa/download/source-dup/travel/second.jpg.json",
                target_id="source-dup",
                group_name="Dup Source",
                countries=["馬來西亞"],
                months=[8],
                regions=["吉隆坡"],
                image_sha256="collapse-sha",
            )
        # Same source only → collapsed away, nothing to review.
        my_groups = [
            g for g in check_duplicates(self.db_path, include_same_source=True)["groups"]
            if g["match"].get("countries") == ["馬來西亞"]
        ]
        self.assertEqual(my_groups, [])
        # Add a second source with the same image → one 2-source certain group.
        with TravelIndex(self.db_path) as index:
            insert_row(
                index,
                "line-rpa/download/source-other/travel/third.jpg.json",
                target_id="source-other",
                group_name="Other Source",
                countries=["馬來西亞"],
                months=[8],
                regions=["吉隆坡"],
                image_sha256="collapse-sha",
            )
        groups = [
            g for g in check_duplicates(self.db_path)["groups"]
            if g["match"].get("countries") == ["馬來西亞"]
        ]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["match_type"], "image_sha256")
        self.assertEqual(groups[0]["count"], 2)
        self.assertEqual(set(groups[0]["sources"]), {"source-dup", "source-other"})

    def test_check_duplicates_flags_near_duplicate_by_phash(self):
        # Same picture re-encoded: sha256 differs, but the perceptual hashes are
        # 1 bit apart, so it must surface as a "near" duplicate.
        with TravelIndex(self.db_path) as index:
            insert_row(
                index,
                "line-rpa/download/source-na/travel/na.jpg.json",
                target_id="source-na",
                group_name="Near A",
                countries=["寮國"],
                months=[3],
                regions=["永珍"],
                image_sha256="sha-near-a",
                image_phash="ffffffffffffffff",
            )
            insert_row(
                index,
                "line-rpa/download/source-nb/travel/nb.jpg.json",
                target_id="source-nb",
                group_name="Near B",
                countries=["寮國"],
                months=[3],
                regions=["永珍"],
                image_sha256="sha-near-b",
                image_phash="fffffffffffffffe",
            )
        groups = check_duplicates(self.db_path)["groups"]
        near = [g for g in groups if g["match_type"] == "image_phash"]
        self.assertEqual(len(near), 1)
        self.assertEqual(near[0]["confidence"], "near")
        self.assertEqual(near[0]["count"], 2)
        self.assertEqual(set(near[0]["sources"]), {"source-na", "source-nb"})
        # The metadata phase must not re-report the same pair.
        laos_meta = [
            g for g in groups
            if g["match_type"] == "metadata" and g["match"].get("countries") == ["寮國"]
        ]
        self.assertEqual(laos_meta, [])

    def test_exact_sha_not_double_reported_as_phash_near(self):
        # Byte-identical images (same sha) with near phashes must appear once,
        # as a certain (image_sha256) group — never also as a phash-near group.
        with TravelIndex(self.db_path) as index:
            insert_row(
                index,
                "line-rpa/download/source-ea/travel/ea.jpg.json",
                target_id="source-ea",
                group_name="Exact A",
                countries=["柬埔寨"],
                months=[2],
                regions=["金邊"],
                image_sha256="same-sha-x",
                image_phash="aaaaaaaaaaaaaaaa",
            )
            insert_row(
                index,
                "line-rpa/download/source-eb/travel/eb.jpg.json",
                target_id="source-eb",
                group_name="Exact B",
                countries=["柬埔寨"],
                months=[2],
                regions=["金邊"],
                image_sha256="same-sha-x",
                image_phash="aaaaaaaaaaaaaaab",
            )
        cambodia = [
            g for g in check_duplicates(self.db_path)["groups"]
            if g["match"].get("countries") == ["柬埔寨"]
        ]
        self.assertEqual(len(cambodia), 1)
        self.assertEqual(cambodia[0]["match_type"], "image_sha256")

    def test_check_duplicates_splits_by_duration(self):
        # Duration is part of the offer signature: same destination, date and
        # price but a different trip length is a different deal. Two 5-day
        # offers group; the 8-day one stays separate.
        with TravelIndex(self.db_path) as index:
            for idx, days in enumerate((5, 5, 8)):
                tid = f"source-sg-{idx}"
                sidecar = f"line-rpa/download/{tid}/travel/sg-{idx}.jpg.json"
                insert_row(
                    index, sidecar, target_id=tid, group_name=tid,
                    countries=["新加坡"], months=[6], regions=["市區"],
                )
                insert_departure(
                    index, sidecar, departure_date="2026-06-15",
                    price_from=30000, duration_days=days, target_id=tid, group_name=tid,
                )
        groups = [
            g for g in check_duplicates(self.db_path)["groups"]
            if g["match"].get("countries") == ["新加坡"]
        ]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 2)
        self.assertEqual(groups[0]["match"]["duration_days"], 5)

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
