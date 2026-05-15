from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.common.image_seen import file_sha256
from tools.indexing.second_pass_ocr import (
    candidate_priority,
    has_split_duration_marker,
    needs_second_pass,
    refresh_sidecar_with_paddle_ocr,
    validate_structured_output,
)


class FakeOcrEngine:
    def __init__(self):
        self.calls = 0

    def __call__(self, _image_input):
        self.calls += 1
        return [(None, "日本 5天 49,800")], None


class TestSecondPassCandidates(unittest.TestCase):
    def test_suspicious_multi_plan_dm_is_candidate(self):
        text = """關西
5日
日本環球影城
47,800
07/12,07/23,08/18,08/20
快速通關券
52,800
07/02,07/09"""
        ok, reasons = needs_second_pass(text)
        self.assertTrue(ok)
        self.assertIn("multi_plan_layout", reasons)

    def test_simple_clear_dm_does_not_need_second_pass(self):
        text = "日本 立山黑部 5天 49,800 06/20"
        ok, reasons = needs_second_pass(text)
        self.assertFalse(ok)
        self.assertEqual(reasons, [])

    def test_split_duration_marker_requires_duration_prefix(self):
        self.assertTrue(has_split_duration_marker("關西 5\n日 日本 49,800"))
        self.assertTrue(has_split_duration_marker("關西 5\n天 日本 49,800"))
        self.assertFalse(has_split_duration_marker("關西\n日本 5日 49,800"))


    def test_prioritizes_duration_and_price_candidates_first(self):
        rows = [
            (Path("multi.json"), ["multi_plan_layout"]),
            (Path("region.json"), ["missing_region"]),
            (Path("price.json"), ["missing_price"]),
            (Path("duration.json"), ["missing_duration"]),
            (Path("split.json"), ["split_duration_marker"]),
        ]

        ordered = sorted(rows, key=candidate_priority)

        self.assertEqual(
            [path.name for path, _reasons in ordered],
            ["duration.json", "price.json", "split.json", "region.json", "multi.json"],
        )


class TestSecondPassOcrCache(unittest.TestCase):
    def test_skips_when_second_pass_cache_matches_image_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sample.png"
            sidecar = Path(tmp) / "sample.png.json"
            image.write_bytes(b"image")
            digest = file_sha256(image)
            sidecar.write_text(
                json.dumps({
                    "ocr": {"text": "日本 5天 49,800", "imageSha256": digest},
                    "secondPassOcr": {
                        "provider": "paddle-ocr",
                        "imageSha256": digest,
                        "status": "enriched",
                    },
                }),
                encoding="utf-8",
            )

            engine = FakeOcrEngine()
            result = refresh_sidecar_with_paddle_ocr(engine, sidecar, reasons=["missing_region"])

            self.assertEqual(result.status, "skipped_second_pass_cache")
            self.assertEqual(engine.calls, 0)

    def test_records_second_pass_status_after_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sample.png"
            sidecar = Path(tmp) / "sample.png.json"
            image.write_bytes(b"image")
            sidecar.write_text(json.dumps({"ocr": {"text": ""}}), encoding="utf-8")

            engine = FakeOcrEngine()
            result = refresh_sidecar_with_paddle_ocr(engine, sidecar, reasons=["missing_region"])

            saved = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(result.status, "enriched")
            self.assertEqual(engine.calls, 1)
            self.assertEqual(saved["secondPassOcr"]["provider"], "paddle-ocr")
            self.assertEqual(saved["secondPassOcr"]["reasons"], ["missing_region"])
            self.assertEqual(saved["ocr"]["engine"], "paddleocr")


class TestSecondPassValidation(unittest.TestCase):
    def test_accepts_grounded_product(self):
        source = "關西 5日 日本環球影城 47,800 07/12,07/23"
        raw = {
            "products": [
                {
                    "title": "關西 5日 日本環球影城",
                    "country": "日本",
                    "regions": ["關西"],
                    "duration_days": 5,
                    "price_from": 47800,
                    "departures": ["2026-07-12", "2026-07-23"],
                    "evidence": ["關西", "5日", "47,800", "07/12,07/23"],
                    "confidence": "high",
                }
            ],
            "warnings": [],
        }
        products, warnings = validate_structured_output(raw, source)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].duration_days, 5)
        self.assertEqual(products[0].price_from, 47800)
        self.assertEqual(warnings, [])

    def test_rejects_ungrounded_evidence(self):
        source = "關西 5日 日本環球影城 47,800"
        raw = {
            "products": [
                {
                    "title": "關西 5日 日本環球影城",
                    "country": "日本",
                    "regions": ["關西"],
                    "duration_days": 5,
                    "price_from": 47800,
                    "departures": [],
                    "evidence": ["不存在的飯店"],
                    "confidence": "high",
                }
            ],
            "warnings": [],
        }
        products, warnings = validate_structured_output(raw, source)
        self.assertEqual(products, [])
        self.assertTrue(any("evidence_not_in_ocr" in warning for warning in warnings))

    def test_normalizes_invalid_numbers_to_none(self):
        source = "日本 99日 999"
        raw = {
            "products": [
                {
                    "title": "日本",
                    "country": "日本",
                    "regions": [],
                    "duration_days": 99,
                    "price_from": 999,
                    "departures": ["not-a-date"],
                    "evidence": ["日本"],
                    "confidence": "medium",
                }
            ],
            "warnings": [],
        }
        products, warnings = validate_structured_output(raw, source)
        self.assertEqual(len(products), 1)
        self.assertIsNone(products[0].duration_days)
        self.assertIsNone(products[0].price_from)
        self.assertEqual(products[0].departures, [])
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
