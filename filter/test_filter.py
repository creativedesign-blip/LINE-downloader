from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent / "filter.py"
SPEC = importlib.util.spec_from_file_location("line_filter", MODULE_PATH)
filter_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(filter_module)


class TestAssumeTravel(unittest.TestCase):
    def test_learned_rule_classifies_as_travel(self):
        original_rules = list(filter_module.LEARNED_TRAVEL_RULES)
        try:
            filter_module.LEARNED_TRAVEL_RULES = ["火星團"]
            classification, reason, hits = filter_module.classify_text("火星團")
        finally:
            filter_module.LEARNED_TRAVEL_RULES = original_rules

        self.assertEqual(classification, "travel")
        self.assertEqual(reason, "learned×1")
        self.assertEqual(hits, "火星團")

    def test_assume_travel_routes_review_to_travel(self):
        classification, reason = filter_module.apply_assume_travel(
            "review",
            "weak1",
            assume_travel=True,
        )

        self.assertEqual(classification, "travel")
        self.assertEqual(reason, "assume-travel:review")

    def test_assume_travel_routes_other_to_travel(self):
        classification, reason = filter_module.apply_assume_travel(
            "other",
            "empty",
            assume_travel=True,
        )

        self.assertEqual(classification, "travel")
        self.assertEqual(reason, "assume-travel:other")

    def test_assume_travel_leaves_travel_unchanged(self):
        classification, reason = filter_module.apply_assume_travel(
            "travel",
            "strong1",
            assume_travel=True,
        )

        self.assertEqual(classification, "travel")
        self.assertEqual(reason, "strong1")

    def test_default_behavior_is_unchanged(self):
        classification, reason = filter_module.apply_assume_travel(
            "review",
            "weak1",
            assume_travel=False,
        )

        self.assertEqual(classification, "review")
        self.assertEqual(reason, "weak1")


if __name__ == "__main__":
    unittest.main()
