from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.indexing.second_pass_ocr import (
    call_codex_vision_structured,
    candidate_priority,
    has_split_duration_marker,
    needs_second_pass,
    refresh_first_pass_annotations,
    refresh_sidecar_with_codex_vision,
    validate_structured_output,
)



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


    def test_missing_duration_alone_does_not_need_second_pass(self):
        text = "Early bird notice"
        ok, reasons = needs_second_pass(text)

        self.assertFalse(ok)
        self.assertEqual(reasons, [])

    def test_missing_duration_with_itinerary_hint_is_not_enough_alone(self):
        text = "日本東京行程 出發日 06/20 團費 NT$49,800"
        ok, reasons = needs_second_pass(text)

        self.assertFalse(ok)
        self.assertEqual(reasons, [])

    def test_missing_price_only_when_price_context_exists(self):
        ok, reasons = needs_second_pass("日本東京 5天 行程")
        self.assertFalse(ok)
        self.assertNotIn("missing_price", reasons)

        ok, reasons = needs_second_pass("日本東京 5天 行程 團費請洽")
        self.assertFalse(ok)
        self.assertEqual(reasons, [])

    def test_missing_region_needs_two_context_signals(self):
        ok, reasons = needs_second_pass("日本 5天 06/20 NT$49,800")

        self.assertFalse(ok)
        self.assertEqual(reasons, [])

    def test_multiple_missing_fields_together_are_candidate(self):
        ok, reasons = needs_second_pass("日本行程 出發日 06/20 團費請洽")

        self.assertTrue(ok)
        self.assertIn("missing_duration", reasons)
        self.assertIn("missing_price", reasons)

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
            ["split.json", "multi.json", "duration.json", "price.json", "region.json"],
        )


class TestSecondPassOcrCache(unittest.TestCase):
    def test_refresh_first_pass_annotations_writes_candidate_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sample.png"
            sidecar = Path(tmp) / "sample.png.json"
            image.write_bytes(b"image")
            text = """?正
5???交?啁?敶勗?
47,800
07/12,07/23,08/18,08/20
敹恍???52,800
07/02,07/09"""
            sidecar.write_text(
                json.dumps({"ocr": {"text": text}}),
                encoding="utf-8",
            )

            summary, candidate = refresh_first_pass_annotations(
                sidecar,
                json.loads(sidecar.read_text(encoding="utf-8")),
            )

            saved = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(saved["domain"], "travel")
            self.assertEqual(saved["schemaVersion"], 1)
            self.assertEqual(saved["firstPassSummary"], summary)
            self.assertEqual(saved["secondPassCandidate"], candidate)
            self.assertTrue(saved["secondPassCandidate"]["needed"])
            self.assertIn("multi_plan_layout", saved["secondPassCandidate"]["reasons"])

    def test_codex_vision_records_structured_products(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sample.png"
            sidecar = Path(tmp) / "sample.png.json"
            image.write_bytes(b"image")
            sidecar.write_text(json.dumps({"ocr": {"text": "日本東京 5天 NT$49,800"}}), encoding="utf-8")
            raw = {
                "products": [
                    {
                        "title": "日本東京",
                        "country": "日本",
                        "regions": ["東京"],
                        "duration_days": 5,
                        "price_from": 49800,
                        "departures": ["2026-06-20"],
                        "evidence": ["日本東京", "5天", "49,800"],
                        "confidence": "high",
                    }
                ],
                "warnings": [],
            }

            with patch("tools.indexing.second_pass_ocr.call_codex_vision_structured", return_value=raw):
                result = refresh_sidecar_with_codex_vision(sidecar, reasons=["multi_plan_layout"])

            saved = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(result.provider, "codex")
            self.assertEqual(result.status, "enriched")
            self.assertEqual(result.after["plan_count"], 1)
            self.assertEqual(saved["secondPassOcr"]["provider"], "codex")
            self.assertEqual(saved["secondPassOcr"]["engine"], "codex-exec")
            self.assertEqual(saved["secondPassOcr"]["products"][0]["price_from"], 49800)

    def test_call_codex_vision_structured_uses_image_and_output_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sample.png"
            image.write_bytes(b"image")
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                output_path = Path(command[command.index("--output-last-message") + 1])
                output_path.write_text(json.dumps({"products": [], "warnings": []}), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch("tools.indexing.second_pass_ocr.subprocess.run", side_effect=fake_run):
                result = call_codex_vision_structured(
                    image,
                    "OCR text",
                    codex_command="codex",
                    codex_model="gpt-test",
                    timeout_seconds=123,
                )

            self.assertEqual(result, {"products": [], "warnings": []})
            self.assertIn("--image", calls[0])
            self.assertIn(str(image), calls[0])
            self.assertIn("--output-schema", calls[0])
            self.assertIn("--model", calls[0])


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
