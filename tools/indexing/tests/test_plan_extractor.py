from __future__ import annotations

import sys
import unittest
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from tools.indexing.plan_extractor import extract_plans


class TestPlanExtractor(unittest.TestCase):
    def test_splits_multi_price_plans_and_keeps_dates_separate(self):
        text = """
關西 5日
日本環球影城、達摩勝尾寺
07/12,07/23,08/18,08/20
47,800 含稅 起
日本環球影城快速通關、園區包場派對、大阪市區飯店
07/02,07/09
52,800 含稅 起
日本環球影城快速通關、園區包場派對、影城外圍飯店
07/02,07/04,07/09,07/11
54,800 含稅 起
"""
        plans = extract_plans(text)
        self.assertEqual(len(plans), 3)
        self.assertEqual([p.price_from for p in plans], [47800, 52800, 54800])
        self.assertIn("2026-08-18", [d.date_iso for d in plans[0].departures])
        self.assertNotIn("2026-08-18", [d.date_iso for d in plans[1].departures])
        self.assertNotIn("2026-08-18", [d.date_iso for d in plans[2].departures])

    def test_departure_weekday(self):
        plans = extract_plans("韓國 5日\n06/20\n17,900起")
        self.assertEqual(plans[0].departures[0].date_iso, "2026-06-20")
        self.assertEqual(plans[0].departures[0].weekday, 6)  # Saturday


if __name__ == "__main__":
    unittest.main()
