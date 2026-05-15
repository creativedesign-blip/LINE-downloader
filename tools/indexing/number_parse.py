"""Shared numeric parsing helpers for Chinese travel queries."""

from __future__ import annotations

import re
from typing import Optional


CHINESE_DIGITS = {
    "零": 0, "〇": 0,
    "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

NUMBER_PATTERN = r"(\d+(?:\.\d+)?|[零〇一二兩两三四五六七八九十]{1,4})"
PRICE_UNIT_PATTERN = r"(萬|万|w|W|k|K)?"


def parse_number(value: object) -> Optional[float]:
    """Parse Arabic or simple Chinese numerals up to 99."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass

    if text in CHINESE_DIGITS:
        return float(CHINESE_DIGITS[text])

    if text.startswith("十"):
        tail = text[1:]
        return float(10 + (CHINESE_DIGITS.get(tail, 0) if tail else 0))

    if "十" in text:
        head, tail = text.split("十", 1)
        tens = CHINESE_DIGITS.get(head)
        if tens is None:
            return None
        return float(tens * 10 + (CHINESE_DIGITS.get(tail, 0) if tail else 0))

    return None


def parse_int(value: object) -> Optional[int]:
    parsed = parse_number(value)
    if parsed is None:
        return None
    if parsed != int(parsed):
        return None
    return int(parsed)


def parse_price_amount(value: object, unit: str | None = None) -> Optional[int]:
    amount = parse_number(value)
    if amount is None:
        return None

    if unit in {"萬", "万", "w", "W"}:
        amount *= 10000
    elif unit in {"k", "K"}:
        amount *= 1000
    elif amount < 300:
        amount *= 10000

    if amount < 300:
        return None
    return int(amount)


def _parse_price_digits(value: object) -> Optional[int]:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return None
    amount = int(digits)
    if 5000 <= amount <= 9_999_999:
        return amount
    return None


def parse_price_bounds(text: str) -> tuple[Optional[int], Optional[int]]:
    """Parse natural budget expressions into (min_price, max_price).

    Examples:
      三萬到五萬 -> (30000, 50000)
      2.5萬以內 -> (None, 25000)
      預算30000 -> (None, 30000)
    """
    compact = re.sub(r"\s+", "", text or "")
    number = NUMBER_PATTERN
    unit = PRICE_UNIT_PATTERN

    range_match = re.search(rf"{number}{unit}(?:到|至|~|～|-|－){number}{unit}", compact)
    if range_match:
        low_unit = range_match.group(2) or range_match.group(4)
        high_unit = range_match.group(4) or range_match.group(2)
        low = parse_price_amount(range_match.group(1), low_unit)
        high = parse_price_amount(range_match.group(3), high_unit)
        if low is not None and high is not None:
            return min(low, high), max(low, high)

    max_match = re.search(rf"(?:預算|價格|團費)?{number}{unit}(?:以內|內|以下|下|封頂|不超過|左右)", compact)
    if max_match:
        return None, parse_price_amount(max_match.group(1), max_match.group(2))

    min_match = re.search(rf"(?:預算|價格|團費)?{number}{unit}(?:以上|起|起跳|至少)", compact)
    if min_match:
        return parse_price_amount(min_match.group(1), min_match.group(2)), None

    context_match = re.search(rf"(?:預算|價格|團費){number}{unit}", compact)
    if context_match:
        return None, parse_price_amount(context_match.group(1), context_match.group(2))

    unit_match = re.search(rf"{number}(萬|万|w|W|k|K)", compact)
    if unit_match:
        return None, parse_price_amount(unit_match.group(1), unit_match.group(2))

    currency_match = re.search(
        r"(?:NT\$|NTD|TWD|\$)(\d{1,3}(?:[,，]\d{3})+|\d{4,7})",
        compact,
        re.I,
    )
    if currency_match:
        price = _parse_price_digits(currency_match.group(1))
        if price is not None:
            return price, price

    yuan_match = re.search(r"(\d{1,3}(?:[,，]\d{3})+|\d{4,7})元", compact)
    if yuan_match:
        price = _parse_price_digits(yuan_match.group(1))
        if price is not None:
            return price, price

    bare_price_match = re.search(r"(?<![\d/.-])(\d{5,6})(?![\d/.-])", compact)
    if bare_price_match:
        price = _parse_price_digits(bare_price_match.group(1))
        if price is not None:
            return price, price

    return None, None
