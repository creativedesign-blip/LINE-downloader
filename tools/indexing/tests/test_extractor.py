"""Unit tests for extractor.py — pure text-to-fields functions.

Run:
    python -m unittest tools.indexing.tests.test_extractor -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from tools.indexing.extractor import (
    extract_airline,
    extract_country,
    extract_duration,
    extract_features,
    extract_months,
    extract_price_from,
    extract_region,
)


class TestExtractCountry(unittest.TestCase):
    def test_single_country(self):
        self.assertEqual(extract_country("日本五天四夜"), ["日本"])

    def test_multiple_countries(self):
        result = extract_country("荷比盧三國：荷蘭、比利時、盧森堡")
        self.assertIn("荷蘭", result)
        self.assertIn("比利時", result)
        self.assertIn("盧森堡", result)

    def test_no_duplicates(self):
        result = extract_country("日本東京 日本大阪 日本京都")
        self.assertEqual(result.count("日本"), 1)

    def test_empty_text(self):
        self.assertEqual(extract_country(""), [])

    def test_no_match(self):
        self.assertEqual(extract_country("台北市信義區"), ["台灣"]) if "台灣" in extract_country("台北市信義區") else None
        # '台北' doesn't include '台灣' so this should be empty:
        self.assertEqual(extract_country("市中心購物美食"), [])

    def test_region_not_false_positive(self):
        # '西班牙牛排' should match '西班牙'
        self.assertIn("西班牙", extract_country("西班牙牛排"))

    def test_long_name_priority(self):
        # '馬來西亞' should match even though '馬' (shorter) isn't in vocab.
        # But we're just testing that 馬來西亞 matches correctly.
        self.assertIn("馬來西亞", extract_country("馬來西亞沙巴自由行"))


class TestExtractMonths(unittest.TestCase):
    def test_full_date(self):
        self.assertEqual(extract_months("2026/05/30 出發"), [5])

    def test_full_date_dash(self):
        self.assertEqual(extract_months("2026-11-15"), [11])

    def test_m_slash_d_list(self):
        self.assertEqual(extract_months("5/19.26 梯次"), [5])

    def test_multiple_dates_comma(self):
        result = extract_months("4/7、5/9 兩梯次")
        self.assertIn(4, result)
        self.assertIn(5, result)

    def test_range_expands(self):
        # 05/05~12/30 should expand to months 5..12
        result = extract_months("活動期間 05/05~12/30")
        self.assertEqual(result, [5, 6, 7, 8, 9, 10, 11, 12])

    def test_chinese_month(self):
        result = extract_months("五月出發、六月也有")
        self.assertIn(5, result)
        self.assertIn(6, result)

    def test_chinese_twelve(self):
        self.assertIn(12, extract_months("十二月寒假"))

    def test_chinese_eleven(self):
        self.assertIn(11, extract_months("十一月秋意"))

    def test_numeric_chinese(self):
        self.assertIn(7, extract_months("7月暑假出遊"))

    def test_out_of_range_rejected(self):
        # 13月 or 0月 should be dropped
        self.assertEqual(extract_months("13月 0月"), [])

    def test_empty_text(self):
        self.assertEqual(extract_months(""), [])

    def test_no_duplicates(self):
        result = extract_months("5/1 5/2 5月 2026/05/30")
        self.assertEqual(result.count(5), 1)

    def test_range_cross_year(self):
        # 12/1~2/28 should expand to {12,1,2}
        result = extract_months("冬季 12/1~2/28")
        self.assertIn(12, result)
        self.assertIn(1, result)
        self.assertIn(2, result)
        self.assertNotIn(6, result)


class TestExtractPriceFrom(unittest.TestCase):
    def test_qi_suffix(self):
        self.assertEqual(extract_price_from("團費 129900起"), 129900)

    def test_yuan_qi_per_person(self):
        self.assertEqual(extract_price_from("39900元起/人"), 39900)

    def test_tax_included(self):
        self.assertEqual(extract_price_from("24988 含稅簽起"), 24988)

    def test_wan_unit(self):
        # 2~4w should yield both 20000 and 40000 → min 20000
        self.assertEqual(extract_price_from("預算 2~4w"), 20000)

    def test_wan_decimal(self):
        self.assertEqual(extract_price_from("2.5w 起"), 25000)

    def test_chinese_wan(self):
        self.assertEqual(extract_price_from("3萬"), 30000)

    def test_dollar_prefix(self):
        self.assertEqual(extract_price_from("$29,900"), 29900)

    def test_nt_dollar(self):
        self.assertEqual(extract_price_from("NT$15,888"), 15888)

    def test_multiple_prices_takes_min(self):
        self.assertEqual(
            extract_price_from("原價 34888 優惠 24988起"), 24988
        )

    def test_no_price(self):
        self.assertIsNone(extract_price_from("行程精彩無比"))

    def test_empty(self):
        self.assertIsNone(extract_price_from(""))

    def test_comma_thousands(self):
        self.assertEqual(extract_price_from("129,900起"), 129900)


class TestExtractAirline(unittest.TestCase):
    def test_hua_hang(self):
        self.assertIn("中華航空", extract_airline("中華航空直飛東京"))

    def test_multiple(self):
        result = extract_airline("長榮航空、星宇航空雙選")
        self.assertIn("長榮航空", result)
        self.assertIn("星宇航空", result)

    def test_longer_before_shorter(self):
        # '中華航空' should be picked up as full name, not just '華航'
        result = extract_airline("中華航空直飛")
        self.assertIn("中華航空", result)

    def test_no_match(self):
        self.assertEqual(extract_airline("飯店早餐"), [])

    def test_empty(self):
        self.assertEqual(extract_airline(""), [])


class TestExtractRegion(unittest.TestCase):
    def test_japanese_region(self):
        result = extract_region("北海道賞雪之旅")
        self.assertIn("北海道", result)

    def test_compound_region(self):
        result = extract_region("荷比盧精華")
        self.assertIn("荷比盧", result)

    def test_city(self):
        result = extract_region("東京大阪雙城")
        self.assertIn("東京", result)
        self.assertIn("大阪", result)

    def test_no_match(self):
        self.assertEqual(extract_region("早鳥優惠"), [])


class TestExtractDuration(unittest.TestCase):
    def test_days_and_nights(self):
        self.assertEqual(extract_duration("12天11夜行程"), 12)

    def test_5d4n(self):
        self.assertEqual(extract_duration("5天4夜輕旅行"), 5)

    def test_nichi_ri(self):
        self.assertEqual(extract_duration("8日遊"), 8)

    def test_plain_ri(self):
        self.assertEqual(extract_duration("10日"), 10)

    def test_picks_max(self):
        # '12天' and '11夜' — we pick 12 via 天 match.
        self.assertEqual(extract_duration("12天11夜"), 12)

    def test_out_of_range_rejected(self):
        # '100 天' gets filtered; '2 天' should be ok though.
        self.assertEqual(extract_duration("100 天"), None)

    def test_no_duration(self):
        self.assertIsNone(extract_duration("賞花美食"))

    def test_empty(self):
        self.assertIsNone(extract_duration(""))


class TestExtractFeatures(unittest.TestCase):
    def test_seasonal(self):
        self.assertIn("賞櫻", extract_features("賞櫻名所"))

    def test_promotion(self):
        result = extract_features("早鳥優惠 無購物站")
        self.assertIn("早鳥優惠", result)
        self.assertIn("無購物站", result)

    def test_multiple_categories(self):
        result = extract_features("賞楓名湯一泊三食")
        self.assertIn("賞楓", result)
        self.assertIn("一泊三食", result)

    def test_no_match(self):
        self.assertEqual(extract_features("第五天抵達"), [])


class TestCombinedRealistic(unittest.TestCase):
    """Sanity checks against realistic OCR-like strings."""

    def test_hollnd_itinerary(self):
        text = (
            "中華航空直飛\n"
            "風采荷比盧 古董蒸氣火車12天\n"
            "荷蘭乳酪工廠、比利時巧克力、盧森堡古堡\n"
            "早鳥優惠前10位報名繳訂金，每人優惠3,000元！\n"
            "出發日期：5/19.26、6/2.16.30、7/14.28、8/11.25、9/8.22、10/6.13\n"
            "$129,900起"
        )

        self.assertIn("荷蘭", extract_country(text))
        self.assertIn("比利時", extract_country(text))
        self.assertIn("盧森堡", extract_country(text))
        self.assertEqual(set(extract_months(text)), {5, 6, 7, 8, 9, 10})
        self.assertEqual(extract_price_from(text), 129900)
        self.assertIn("中華航空", extract_airline(text))
        self.assertIn("荷比盧", extract_region(text))
        self.assertEqual(extract_duration(text), 12)
        self.assertIn("早鳥優惠", extract_features(text))


if __name__ == "__main__":
    unittest.main()
