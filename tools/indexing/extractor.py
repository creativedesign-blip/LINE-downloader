"""Pure extractors: OCR text -> structured fields.

Four vocab-based extractors (country / airline / region / features) share
a cached loader and substring matcher. Three regex-based extractors
(months / price_from / duration) each have their own grammar.

All functions are pure — no side effects beyond a module-level vocab cache.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


_VOCAB_DIR = Path(__file__).parent / "vocab"
_VOCAB_CACHES: dict[str, list[str]] = {}

# OCR on traditional-Chinese images occasionally emits simplified glyphs
# (e.g. '中华航空' instead of '中華航空'). Normalize before substring match
# so vocab files can stay traditional-only.
_SIMPLIFIED_TO_TRADITIONAL = str.maketrans({
    "华": "華", "荣": "榮", "国": "國", "岛": "島", "韩": "韓",
    "亚": "亞", "欧": "歐", "义": "義", "宾": "賓", "发": "發",
    "体": "體", "馆": "館", "汉": "漢", "经": "經", "览": "覽",
    "艺": "藝", "会": "會", "场": "場", "处": "處", "产": "產",
    "东": "東", "长": "長", "广": "廣", "门": "門", "气": "氣",
    "声": "聲", "鲁": "魯", "卢": "盧", "兰": "蘭", "济": "濟",
    "飞": "飛", "边": "邊", "乐": "樂", "头": "頭", "车": "車",
    "点": "點", "话": "話", "风": "風", "园": "園", "员": "員",
    "问": "問", "时": "時", "间": "間", "样": "樣", "热": "熱",
    "专": "專", "实": "實", "为": "為", "丽": "麗", "鲜": "鮮",
    "达": "達", "节": "節", "观": "觀", "铁": "鐵", "号": "號",
    "岭": "嶺", "历": "歷", "湾": "灣", "务": "務",
    "线": "線", "访": "訪", "过": "過", "里": "裡", "师": "師",
    "张": "張", "龙": "龍", "马": "馬", "鱼": "魚", "鸟": "鳥",
    "杰": "傑", "乔": "喬", "凯": "凱", "维": "維", "赛": "賽",
})


def _normalize(text: str) -> str:
    """Map simplified glyphs to traditional so vocab stays traditional-only."""
    return text.translate(_SIMPLIFIED_TO_TRADITIONAL) if text else text


def _get_vocab(filename: str) -> list[str]:
    """Load a vocab file once; cache sorted by length desc so longer names
    take precedence (e.g. '馬來西亞' before '馬')."""
    if filename not in _VOCAB_CACHES:
        path = _VOCAB_DIR / filename
        entries: list[str] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    entries.append(line)
        _VOCAB_CACHES[filename] = sorted(entries, key=len, reverse=True)
    return _VOCAB_CACHES[filename]


def _match_vocab(text: str, vocab: list[str]) -> list[str]:
    """Return all vocab entries that appear as substrings of text, in
    first-occurrence order, no duplicates. Text is normalized simplified
    -> traditional before matching."""
    if not text:
        return []
    text = _normalize(text)
    found: list[str] = []
    seen: set[str] = set()
    for entry in vocab:
        if entry in text and entry not in seen:
            found.append(entry)
            seen.add(entry)
    return found


def extract_country(text: str) -> list[str]:
    """Country names found as substrings of text (vocab/countries.txt)."""
    return _match_vocab(text, _get_vocab("countries.txt"))


def extract_airline(text: str) -> list[str]:
    """Airline names (vocab/airlines.txt)."""
    return _match_vocab(text, _get_vocab("airlines.txt"))


def extract_region(text: str) -> list[str]:
    """Sub-region / city names (vocab/regions.txt) — '九州', '荷比盧', '京都'…"""
    return _match_vocab(text, _get_vocab("regions.txt"))


def extract_features(text: str) -> list[str]:
    """Trip highlight / promotion keywords (vocab/features.txt) —
    '賞櫻', '無購物站', '一泊三食'…"""
    return _match_vocab(text, _get_vocab("features.txt"))


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------

_FULL_DATE_RE = re.compile(r"20\d{2}[\/\-\.](\d{1,2})[\/\-\.]\d{1,2}")
_RANGE_RE = re.compile(r"(\d{1,2})\/\d{1,2}\s*[~～\-—]\s*(\d{1,2})\/\d{1,2}")
_MONTH_SLASH_RE = re.compile(r"(?<![\d/])(\d{1,2})\/\d{1,2}(?:\.\d{1,2})*")
_MONTH_NUM_CH_RE = re.compile(r"(\d{1,2})月")
_MONTH_NAME_CH_RE = re.compile(r"(十[一二]|[一二三四五六七八九十])月")

_MONTH_CH_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}


def _add_if_month(found: set[int], value: int) -> None:
    if 1 <= value <= 12:
        found.add(value)


def extract_months(text: str) -> list[int]:
    """Parse date mentions and return the set of month integers (1–12).

    Handles:
      - full date: 2026/05/30, 2026-05-30
      - range:     05/05~12/30 (expands to {5,6,7,...,12})
      - m/d list:  5/19.26 -> {5}
      - '5月' / '05月' / chinese: '五月', '十二月'
    """
    if not text:
        return []

    found: set[int] = set()

    for m in _FULL_DATE_RE.finditer(text):
        _add_if_month(found, int(m.group(1)))

    for m in _RANGE_RE.finditer(text):
        start = int(m.group(1))
        end = int(m.group(2))
        if not (1 <= start <= 12 and 1 <= end <= 12):
            continue
        if start <= end:
            for mo in range(start, end + 1):
                found.add(mo)
        else:
            for mo in range(start, 13):
                found.add(mo)
            for mo in range(1, end + 1):
                found.add(mo)

    for m in _MONTH_SLASH_RE.finditer(text):
        _add_if_month(found, int(m.group(1)))

    for m in _MONTH_NUM_CH_RE.finditer(text):
        _add_if_month(found, int(m.group(1)))

    for m in _MONTH_NAME_CH_RE.finditer(text):
        ch = m.group(1)
        if ch in _MONTH_CH_MAP:
            found.add(_MONTH_CH_MAP[ch])

    return sorted(found)


# ---------------------------------------------------------------------------
# Price
# ---------------------------------------------------------------------------

_PRICE_QI_RE = re.compile(
    r"(\d[\d,]{2,})\s*(?:元|NT\$|\$)?\s*(?:起|含稅簽起|元起|元\/人起|元\/人)"
)
_PRICE_WAN_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[~～\-]\s*(\d+(?:\.\d+)?)\s*[wW萬]"
)
_PRICE_WAN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[wW萬]")
_PRICE_DOLLAR_RE = re.compile(r"(?:NT\$|\$)\s*(\d[\d,]{2,})")


def extract_price_from(text: str) -> Optional[int]:
    """Parse all price mentions and return the minimum in TWD.

    Recognises:
      - 129900起 / 39900元起/人 / 24988 含稅簽起
      - 2~4w / 3萬 / 2.5w     (multiplied by 10000)
      - $29,900 / NT$15,888
    Returns None when no valid price is found.
    """
    if not text:
        return None

    prices: list[int] = []

    def add(n: int) -> None:
        if 1000 <= n <= 99_999_999:
            prices.append(n)

    for m in _PRICE_QI_RE.finditer(text):
        add(int(m.group(1).replace(",", "")))

    for m in _PRICE_WAN_RANGE_RE.finditer(text):
        add(int(float(m.group(1)) * 10000))
        add(int(float(m.group(2)) * 10000))

    for m in _PRICE_WAN_RE.finditer(text):
        add(int(float(m.group(1)) * 10000))

    for m in _PRICE_DOLLAR_RE.finditer(text):
        add(int(m.group(1).replace(",", "")))

    return min(prices) if prices else None


# ---------------------------------------------------------------------------
# Duration (days)
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"(\d+)\s*[天日](?:遊|程)?")


def extract_duration(text: str) -> Optional[int]:
    """Parse trip duration in days. Returns the max found integer (1–60).

    Handles: '12天11夜', '5天4夜', '8日遊', '10日', '15天'.
    """
    if not text:
        return None
    days = [
        int(m.group(1))
        for m in _DURATION_RE.finditer(text)
        if 1 <= int(m.group(1)) <= 60
    ]
    return max(days) if days else None
