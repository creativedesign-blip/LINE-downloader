from __future__ import annotations

import sys
import unittest
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from tools.indexing.number_parse import parse_int, parse_number, parse_price_amount, parse_price_bounds


class TestNumberParse(unittest.TestCase):
    def test_parse_arabic_and_chinese_numbers(self):
        self.assertEqual(parse_int("5"), 5)
        self.assertEqual(parse_int("五"), 5)
        self.assertEqual(parse_int("十二"), 12)
        self.assertEqual(parse_int("二十五"), 25)
        self.assertEqual(parse_number("2.5"), 2.5)

    def test_price_amount_units(self):
        self.assertEqual(parse_price_amount("三", "萬"), 30000)
        self.assertEqual(parse_price_amount("2.5", "萬"), 25000)
        self.assertEqual(parse_price_amount("30", "k"), 30000)
        self.assertEqual(parse_price_amount("30000", None), 30000)

    def test_price_bounds(self):
        self.assertEqual(parse_price_bounds("預算三萬到五萬"), (30000, 50000))
        self.assertEqual(parse_price_bounds("2.5萬以內"), (None, 25000))
        self.assertEqual(parse_price_bounds("三萬以上"), (30000, None))
        self.assertEqual(parse_price_bounds("預算30000"), (None, 30000))
        self.assertEqual(parse_price_bounds("韓國 34500"), (34500, 34500))
        self.assertEqual(parse_price_bounds("韓國 NT$34,500"), (34500, 34500))
        self.assertEqual(parse_price_bounds("韓國 34500元"), (34500, 34500))

    def test_plain_duration_number_is_not_price(self):
        self.assertEqual(parse_price_bounds("5天四夜"), (None, None))


if __name__ == "__main__":
    unittest.main()
