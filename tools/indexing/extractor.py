"""Pure extractors: OCR text -> structured fields.

Four vocab-based extractors (country / airline / region / features) share
a cached loader and substring matcher. Three regex-based extractors
(months / price_from / duration) each have their own grammar.

All functions are pure — no side effects beyond a module-level vocab cache.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Optional

from tools.indexing.number_parse import parse_int


_VOCAB_DIR = Path(__file__).parent / "vocab"
_VOCAB_CACHES: dict[str, list[str]] = {}
_COUNTRY_HINTS_CACHE: dict[str, list[str]] | None = None

# OCR on traditional-Chinese images occasionally emits simplified glyphs
# (e.g. '中华航空' instead of '中華航空'). Normalize before substring match
# so vocab files can stay traditional-only.
_SIMPLIFIED_TO_TRADITIONAL = str.maketrans({
    "华": "華", "荣": "榮", "国": "國", "岛": "島", "韩": "韓",
    "亚": "亞", "欧": "歐", "义": "義", "宾": "賓", "发": "發",
    "体": "體", "馆": "館", "汉": "漢", "经": "經", "览": "覽",
    "艺": "藝", "会": "會", "场": "場", "处": "處", "产": "產",
    "东": "東", "长": "長", "广": "廣", "门": "門", "关": "關", "関": "關", "气": "氣",
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

_COMMON_OCR_TO_TRADITIONAL = str.maketrans({
    "亚": "亞", "国": "國", "岛": "島", "冲": "沖", "税": "稅",
    "馆": "館", "宫": "宮", "丽": "麗", "马": "馬", "兰": "蘭",
    "卢": "盧", "游": "遊", "车": "車", "赛": "賽", "专": "專",
    "场": "場", "爱": "愛", "绿": "綠", "导": "導", "关": "關", "関": "關",
})


def _normalize(text: str) -> str:
    """Map simplified glyphs to traditional so vocab stays traditional-only."""
    return (
        text.translate(_SIMPLIFIED_TO_TRADITIONAL).translate(_COMMON_OCR_TO_TRADITIONAL)
        if text else text
    )


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


def _get_country_hints() -> dict[str, list[str]]:
    global _COUNTRY_HINTS_CACHE
    if _COUNTRY_HINTS_CACHE is not None:
        return _COUNTRY_HINTS_CACHE
    path = _VOCAB_DIR / "country_hints.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    hints: dict[str, list[str]] = {}
    if isinstance(data, dict):
        for country, values in data.items():
            if not isinstance(country, str) or not isinstance(values, list):
                continue
            cleaned = [str(value).strip() for value in values if str(value).strip()]
            if cleaned:
                hints[country] = sorted(set(cleaned), key=len, reverse=True)
    _COUNTRY_HINTS_CACHE = hints
    return hints


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


def _infer_country_from_hints(text: str) -> list[str]:
    if not text:
        return []
    normalized = _normalize(text)
    normalized_lower = normalized.lower()
    matches: list[tuple[int, int, int, str]] = []
    for order, (country, keywords) in enumerate(_get_country_hints().items()):
        best_index: int | None = None
        best_len = 0
        for keyword in keywords:
            normalized_keyword = _normalize(keyword)
            haystack = normalized_lower if normalized_keyword.isascii() else normalized
            needle = normalized_keyword.lower() if normalized_keyword.isascii() else normalized_keyword
            index = haystack.find(needle)
            if index >= 0 and (best_index is None or index < best_index):
                best_index = index
                best_len = len(needle)
        if best_index is not None:
            matches.append((best_index, -best_len, order, country))
    matches.sort()
    countries: list[str] = []
    seen: set[str] = set()
    for _index, _length, _order, country in matches:
        if country not in seen:
            countries.append(country)
            seen.add(country)
    return countries


_REGION_COUNTRY_HINTS = {
    "北海道": "日本", "札幌": "日本", "小樽": "日本", "函館": "日本",
    "登別": "日本", "洞爺湖": "日本", "富良野": "日本", "美瑛": "日本",
    "旭川": "日本", "東京": "日本", "大阪": "日本", "京都": "日本",
    "奈良": "日本", "神戶": "日本", "名古屋": "日本", "橫濱": "日本",
    "福岡": "日本", "沖繩": "日本", "九州": "日本", "關西": "日本",
    "關東": "日本", "東北": "日本", "本州": "日本", "四國": "日本",
    "北陸": "日本", "京阪神": "日本", "京阪": "日本", "近畿": "日本",
    "富士山": "日本", "箱根": "日本", "鎌倉": "日本", "日光": "日本",
    "輕井澤": "日本", "河口湖": "日本", "靜岡": "日本", "山梨": "日本",
    "長野": "日本", "高山": "日本", "金澤": "日本", "姬路": "日本",
    "岡山": "日本", "廣島": "日本", "宮島": "日本", "鳥取": "日本",
    "松江": "日本", "高松": "日本", "鹿兒島": "日本",
    # "松山" intentionally absent: ambiguous between 台北松山機場 (departure
    # airport — appears in nearly every Taiwan domestic / outbound DM as
    # "松山出發") and 日本愛媛松山市. Mapping to 日本 caused Taiwan-trip
    # DM (e.g. "松山出發 馬祖雙島") to be tagged country=[日本, 台灣]
    # via region inference. Genuine 松山市 trips fall through to
    # country_hints.json, which already lists Japan markers like 沖繩 /
    # JUNGLIA / 美麗海 — pure "松山市" only DM is virtually nonexistent.
    "熊本": "日本", "宮崎": "日本", "別府": "日本",
    "立山黑部": "日本", "白川鄉": "日本",
    "首爾": "韓國", "釜山": "韓國", "濟州": "韓國", "濟州島": "韓國",
    "江原道": "韓國", "仁川": "韓國", "清州": "韓國", "大邱": "韓國",
    "慶州": "韓國", "全州": "韓國", "雪嶽山": "韓國",
    "北京": "中國", "上海": "中國", "廣州": "中國", "深圳": "中國",
    "杭州": "中國", "蘇州": "中國", "成都": "中國", "重慶": "中國",
    "香港": "香港", "澳門": "澳門",
    "台北": "台灣", "新北": "台灣", "桃園": "台灣", "新竹": "台灣",
    "台中": "台灣", "台南": "台灣", "高雄": "台灣", "花蓮": "台灣",
    "台東": "台灣", "宜蘭": "台灣", "南投": "台灣", "墾丁": "台灣",
    "阿里山": "台灣", "日月潭": "台灣", "瑞穗": "台灣", "綠島": "台灣",
    "蘭嶼": "台灣", "金門": "台灣", "馬祖": "台灣", "澎湖": "台灣",
    "曼谷": "泰國", "清邁": "泰國", "普吉": "泰國", "芭達雅": "泰國",
    "芭堤雅": "泰國", "華欣": "泰國",
    "峴港": "越南", "河內": "越南", "胡志明": "越南", "富國島": "越南",
    "會安": "越南", "芽莊": "越南", "大叻": "越南", "美奈": "越南",
    "吉隆坡": "馬來西亞", "沙巴": "馬來西亞", "檳城": "馬來西亞",
    "馬六甲": "馬來西亞", "蘭卡威": "馬來西亞", "新山": "馬來西亞",
    "峇里島": "印尼", "巴厘島": "印尼", "雅加達": "印尼",
    "日惹": "印尼", "泗水": "印尼", "萬隆": "印尼",
    "宿霧": "菲律賓", "長灘島": "菲律賓", "馬尼拉": "菲律賓",
    "薄荷島": "菲律賓",
    "吳哥窟": "柬埔寨", "暹粒": "柬埔寨", "金邊": "柬埔寨",
    "仰光": "緬甸", "新加坡": "新加坡",
    "杜拜": "阿聯", "阿布達比": "阿聯",
    "阿姆斯特丹": "荷蘭", "布魯塞爾": "比利時", "巴黎": "法國",
    "法蘭克福": "德國", "慕尼黑": "德國", "柏林": "德國", "倫敦": "英國",
    "羅馬": "義大利", "米蘭": "義大利", "威尼斯": "義大利",
    "佛羅倫斯": "義大利", "拿坡里": "義大利", "龐貝": "義大利",
    "巴塞隆納": "西班牙", "馬德里": "西班牙",
    "里斯本": "葡萄牙", "波多": "葡萄牙",
    "蘇黎世": "瑞士", "琉森": "瑞士", "因特拉肯": "瑞士", "維也納": "奧地利",
    "布拉格": "捷克", "布達佩斯": "匈牙利", "雅典": "希臘",
    "哥本哈根": "丹麥", "斯德哥爾摩": "瑞典", "赫爾辛基": "芬蘭",
    "雷克雅維克": "冰島", "伊斯坦堡": "土耳其", "卡帕多奇亞": "土耳其",
    "杜布羅夫尼克": "克羅埃西亞", "札格雷布": "克羅埃西亞",
    "盧比安納": "斯洛維尼亞",
    "雪梨": "澳洲", "墨爾本": "澳洲", "布里斯本": "澳洲", "布裡斯本": "澳洲",
    "黃金海岸": "澳洲", "凱恩斯": "澳洲", "伯斯": "澳洲", "阿德雷德": "澳洲",
    "奧克蘭": "紐西蘭", "皇后鎮": "紐西蘭", "基督城": "紐西蘭",
    "紐約": "美國", "洛杉磯": "美國", "舊金山": "美國", "拉斯維加斯": "美國",
    "西雅圖": "美國", "波士頓": "美國", "華盛頓": "美國", "奧蘭多": "美國",
    "芝加哥": "美國", "夏威夷": "美國",
    "溫哥華": "加拿大", "多倫多": "加拿大", "洛磯山": "加拿大",
    "班夫": "加拿大", "魁北克": "加拿大",
    "坎昆": "墨西哥", "開羅": "埃及", "尼羅河": "埃及",
    "馬拉喀什": "摩洛哥", "卡薩布蘭卡": "摩洛哥",
    "約翰尼斯堡": "南非", "開普敦": "南非",
    "奈洛比": "肯亞", "塞倫蓋提": "坦尚尼亞",
}

_COUNTRY_TEXT_HINTS = [
    (re.compile(r"\bJAPAN\b", re.I), ["日本"]),
    (re.compile(r"\bKOREA\b", re.I), ["韓國"]),
    (re.compile(r"\bAUSTRALIA\b", re.I), ["澳洲"]),
    (re.compile(r"\bBALI\b", re.I), ["印尼"]),
    (re.compile(r"法比荷"), ["法國", "比利時", "荷蘭"]),
    (re.compile(r"西葡"), ["西班牙", "葡萄牙"]),
    (re.compile(r"突尼西亞|突尼斯|笑尼西亞|北非"), ["突尼西亞"]),
    (re.compile(r"峇里島|巴里島|岩里島|婆羅浮屠"), ["印尼"]),
]


def extract_country(text: str) -> list[str]:
    """Country names found as substrings of text (vocab/countries.txt)."""
    normalized = _normalize(text)
    countries = _match_vocab(normalized, _get_vocab("countries.txt"))
    countries.extend(
        country
        for pattern, matched in _COUNTRY_TEXT_HINTS
        if pattern.search(normalized)
        for country in matched
        if country not in countries
    )
    if countries:
        return countries

    inferred: list[str] = []
    seen: set[str] = set()
    for region in _match_vocab(text, _get_vocab("regions.txt")):
        country = _REGION_COUNTRY_HINTS.get(region)
        if country and country not in seen:
            inferred.append(country)
            seen.add(country)
    if inferred:
        return inferred

    return _infer_country_from_hints(normalized)


def _is_probable_price(n: int) -> bool:
    """Reject OCR dates/years while keeping normal travel DM prices."""
    return 5000 <= n <= 99_999_999


def normalize_price_digits(raw: str) -> Optional[int]:
    """Clean an OCR price token and handle day-label + price merges.

    Some DM layouts place a large "5日" badge immediately before a price.
    OCR can merge it into tokens such as "519.888" for the actual price
    "19,888".  When a 6-digit token starts with a plausible day count and the
    remaining 5 digits are a normal travel price, prefer the 5-digit price.
    """
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    if len(digits) == 6 and digits[0] in "3456789":
        tail = int(digits[1:])
        if 10_000 <= tail <= 99_999:
            return tail
    return int(digits)


def extract_airline(text: str) -> list[str]:
    """Airline names (vocab/airlines.txt)."""
    return _match_vocab(text, _get_vocab("airlines.txt"))


# Landmark / sub-region keywords that strongly imply a canonical region
# tag. Use only highly-specific terms that are unlikely to appear outside
# their region (avoid generic ones like "AEONMALL" or "PARCOCITY" that
# exist in many places). Mainly catches OCR-mangled cases — e.g.
# "美麗海水族館" survives OCR but the literal "沖繩" character often gets
# read as just "冲" and lost — so the row would never match a "沖繩"
# query without this expansion.
_LANDMARK_REGION_HINTS = {
    "沖繩": ["美麗海", "美丽海", "玉泉洞", "琉球", "古宇利", "瀨長島",
             "濑長岛", "OKINAWA", "Okinawa", "okinawa"],
}


def extract_region(text: str) -> list[str]:
    """Sub-region / city names (vocab/regions.txt) — '九州', '荷比盧', '京都'…

    Also synthesises canonical regions from well-known landmarks
    (_LANDMARK_REGION_HINTS) so a DM whose OCR lost the literal
    region name still gets the region tag — e.g. "美麗海水族館 + 玉泉洞"
    -> 沖繩 even when "沖繩" itself didn't survive OCR.
    """
    direct = _match_vocab(text, _get_vocab("regions.txt"))
    for region, landmarks in _LANDMARK_REGION_HINTS.items():
        if region in direct:
            continue
        if any(landmark in text for landmark in landmarks):
            direct.append(region)
    return direct


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
_PRICE_DOT_THOUSANDS_RE = re.compile(
    r"(?<![\d.])(\d{1,3}(?:\.\d{3})+)(?![\d.])"
    r"(?=[\s\S]{0,30}(?:含稅|含税|起|原價))"
)
_PRICE_CONTEXT_RE = re.compile(
    r"(?<![\d/])(\d{1,3}(?:[,，]\d{3})|\d{4,6})(?![\d/])(?=[\s\S]{0,30}(?:含稅|含税|起|元))"
)


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
        if _is_probable_price(n):
            prices.append(n)

    for m in _PRICE_QI_RE.finditer(text):
        price = normalize_price_digits(m.group(1))
        if price is not None:
            add(price)

    for m in _PRICE_WAN_RANGE_RE.finditer(text):
        add(int(float(m.group(1)) * 10000))
        add(int(float(m.group(2)) * 10000))

    for m in _PRICE_WAN_RE.finditer(text):
        add(int(float(m.group(1)) * 10000))

    for m in _PRICE_DOLLAR_RE.finditer(text):
        price = normalize_price_digits(m.group(1))
        if price is not None:
            add(price)

    for m in _PRICE_DOT_THOUSANDS_RE.finditer(text):
        price = normalize_price_digits(m.group(1))
        if price is not None:
            add(price)

    for m in _PRICE_CONTEXT_RE.finditer(text):
        context = text[max(0, m.start() - 12): min(len(text), m.end() + 30)]
        if any(bad in context for bad in ["優惠", "訂金", "小費", "加價", "加收", "自費"]):
            continue
        price = normalize_price_digits(m.group(1))
        if price is not None:
            add(price)

    return min(prices) if prices else None


# ---------------------------------------------------------------------------
# Duration (days)
# ---------------------------------------------------------------------------

_DURATION_PLUS_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[+＋]\s*(\d{1,2})\s*[天日](?:遊|程)?")
_DURATION_RE = re.compile(r"(\d+)\s*[天日](?:遊|程)?")
_DURATION_CH_RE = re.compile(r"([一二兩三四五六七八九十]{1,3})\s*[天日](?:遊|程)?")


def extract_duration(text: str) -> Optional[int]:
    """Parse trip duration in days. Returns the max found integer (1–30).

    Handles: '12天11夜', '5天4夜', '5+1日', '8日遊', '10日', '15天'.
    """
    if not text:
        return None
    days: list[int] = []
    for m in _DURATION_PLUS_RE.finditer(text):
        total = sum(int(part) for part in m.groups())
        if 1 <= total <= 30:
            days.append(total)
    days.extend(
        int(m.group(1))
        for m in _DURATION_RE.finditer(text)
        if 1 <= int(m.group(1)) <= 30
    )
    for m in _DURATION_CH_RE.finditer(text):
        value = parse_int(m.group(1))
        if value is not None and 1 <= value <= 30:
            days.append(value)
    return max(days) if days else None
