from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.domains.travel.migrate_sidecars import migrate_sidecar


class TestTravelSidecarMigration(unittest.TestCase):
    def test_migrates_travel_sidecar_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sample.png"
            sidecar = Path(tmp) / "sample.png.json"
            image.write_bytes(b"image")
            sidecar.write_text(
                json.dumps({"ocr": {"classification": "travel", "text": "日本 5天 49,800"}}),
                encoding="utf-8",
            )

            result = migrate_sidecar(sidecar)

            saved = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(result.status, "updated")
            self.assertEqual(saved["domain"], "travel")
            self.assertEqual(saved["schemaVersion"], 1)
            self.assertIn("firstPassSummary", saved)
            self.assertIn("secondPassCandidate", saved)

    def test_skips_non_travel_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sample.png"
            sidecar = Path(tmp) / "sample.png.json"
            image.write_bytes(b"image")
            sidecar.write_text(
                json.dumps({"ocr": {"classification": "other", "text": "hello"}}),
                encoding="utf-8",
            )

            result = migrate_sidecar(sidecar)

            saved = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(result.status, "skipped")
            self.assertNotIn("domain", saved)


if __name__ == "__main__":
    unittest.main()
