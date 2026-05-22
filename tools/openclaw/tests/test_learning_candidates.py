from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.openclaw import learning_candidates


class LearningCandidateTests(unittest.TestCase):
    def test_candidate_rule_texts_prefers_structured_travel_fields(self):
        sidecar = {
            "firstPassSummary": {
                "countries": ["德國", "捷克"],
                "regions": ["布拉格"],
            },
            "ocr": {"hits": "<日期>,早鳥"},
        }

        self.assertEqual(
            learning_candidates.candidate_rule_texts(sidecar),
            ["德國", "捷克", "布拉格", "早鳥"],
        )

    def test_record_assume_travel_candidates_upserts_seen_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "learning.db"
            image = Path(tmp) / "line-rpa" / "download" / "upload_test" / "travel" / "sample.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"image")
            sidecar = {
                "firstPassSummary": {"countries": ["德國"], "regions": []},
                "ocr": {"hits": "<日期>"},
            }

            first = learning_candidates.record_assume_travel_candidates(
                image,
                sidecar,
                original_classification="review",
                original_reason="weak0+1",
                db_path=db_path,
            )
            second = learning_candidates.record_assume_travel_candidates(
                image,
                sidecar,
                original_classification="review",
                original_reason="weak0+1",
                db_path=db_path,
            )

            self.assertEqual(len(first), 1)
            self.assertEqual(second[0]["rule_text"], "德國")
            self.assertEqual(second[0]["seen_count"], 2)

    def test_approve_syncs_approved_rules_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "learning.db"
            rules_path = Path(tmp) / "rules.json"
            row = learning_candidates.upsert_candidate(
                "德國",
                sample_image_path=Path(tmp) / "sample.jpg",
                sample_folder="upload_test",
                original_classification="other",
                original_reason="empty",
                db_path=db_path,
            )

            approved = learning_candidates.set_candidate_status(
                row["id"],
                "approved",
                db_path=db_path,
                approved_rules_path=rules_path,
            )

            payload = json.loads(rules_path.read_text(encoding="utf-8"))
            self.assertEqual(approved["status"], "approved")
            self.assertEqual(payload["rules"][0]["rule_text"], "德國")

    def test_report_includes_pending_and_reconsidered_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "learning.db"
            pending = learning_candidates.upsert_candidate(
                "德國",
                sample_image_path=Path(tmp) / "a.jpg",
                sample_folder="upload_test",
                original_classification="review",
                original_reason="weak0+1",
                db_path=db_path,
            )
            rejected = learning_candidates.upsert_candidate(
                "捷克",
                sample_image_path=Path(tmp) / "b.jpg",
                sample_folder="upload_test",
                original_classification="other",
                original_reason="empty",
                db_path=db_path,
            )
            learning_candidates.set_candidate_status(
                rejected["id"],
                "rejected",
                db_path=db_path,
                approved_rules_path=Path(tmp) / "rules.json",
            )
            for _ in range(learning_candidates.RECONSIDER_SEEN_COUNT - 1):
                learning_candidates.upsert_candidate(
                    "捷克",
                    sample_image_path=Path(tmp) / "b.jpg",
                    sample_folder="upload_test",
                    original_classification="other",
                    original_reason="empty",
                    db_path=db_path,
                )

            rows = learning_candidates.list_candidates(db_path=db_path)
            report = learning_candidates.render_report(rows)

            self.assertEqual({row["id"] for row in rows}, {pending["id"], rejected["id"]})
            self.assertIn("德國", report)
            self.assertIn("捷克", report)


if __name__ == "__main__":
    unittest.main()
