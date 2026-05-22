import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_MODULE_PATH = PROJECT_ROOT / "travel-agent-interface" / "openclaw_web.py"


spec = importlib.util.spec_from_file_location("openclaw_web_for_system_tag_tests", WEB_MODULE_PATH)
openclaw_web = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(openclaw_web)


class SystemTagMergeTests(unittest.TestCase):
    def test_same_sha_system_tags_are_merged_and_deduplicated(self):
        payloads = [
            {
                "countries": ["紐西蘭"],
                "regions": ["南島"],
                "features": ["高山火車"],
                "months": [8],
            },
            {
                "countries": ["紐西蘭"],
                "regions": ["皇后鎮"],
                "features": ["高山火車", "冰河"],
                "months": [8, 9],
            },
        ]

        with patch.object(openclaw_web, "_same_sha_sidecar_payloads", return_value=payloads):
            tags = openclaw_web._system_tags_for_same_sha_image(1)

        self.assertEqual(
            [tag["tag"] for tag in tags],
            ["紐西蘭", "南島", "高山火車", "8月", "皇后鎮", "冰河", "9月"],
        )

    def test_same_sha_sidecar_query_fields_are_merged(self):
        payloads = [
            {"countries": ["紐西蘭"], "regions": ["南島"], "months": [8], "duration_days": 8},
            {"countries": ["紐西蘭"], "regions": ["皇后鎮"], "months": [8, 9], "price_from": 99900},
        ]

        fields = openclaw_web._merge_sidecar_query_fields(payloads)

        self.assertEqual(fields["countries"], ["紐西蘭"])
        self.assertEqual(fields["regions"], ["南島", "皇后鎮"])
        self.assertEqual(fields["months"], [8, 9])
        self.assertEqual(fields["duration_days"], 8)
        self.assertEqual(fields["price_from"], 99900)


if __name__ == "__main__":
    unittest.main()
