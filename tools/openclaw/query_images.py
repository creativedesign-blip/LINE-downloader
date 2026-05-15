"""Fast local image search for OpenClaw travel products.

Reads cached OCR text from sidecars. It never runs OCR, so queries should be
near-instant after `tools/indexing/ocr_enrich.py` has run. Matching images are
copied to line-rpa/selected and optionally copied to the Windows clipboard.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.branding.io_utils import image_of_sidecar
from tools.common.targets import DOWNLOADS_DIR, PROJECT_ROOT, load_target_ids, relpath_from_root
from tools.indexing.extractor import extract_months, extract_price_from
from tools.indexing.number_parse import parse_price_bounds

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
DEFAULT_SELECTED_DIR = PROJECT_ROOT / "line-rpa" / "selected"
CLIPBOARD_SCRIPT = PROJECT_ROOT / "tools" / "openclaw" / "copy_files_to_clipboard.ps1"

DOMESTIC_KEYWORDS = [
    "台灣", "臺灣", "澎湖", "金門", "馬祖", "綠島", "蘭嶼", "小琉球", "琉球",
    "花蓮", "花東", "台東", "臺東", "宜蘭", "蘭陽", "礁溪", "南投", "溪頭",
    "杉林溪", "嘉義", "阿里山", "墾丁", "高雄", "台南", "臺南", "台中", "臺中",
    "台北", "臺北", "新北", "桃園", "新竹", "苗栗", "屏東", "基隆", "太平山",
]
OVERSEAS_KEYWORDS = [
    "韓國", "日本", "越南", "歐洲", "中國", "香港", "澳門", "港澳", "郵輪", "北海道",
    "東京", "大阪", "九州", "沖繩", "首爾", "釜山", "峴港", "河內", "胡志明",
    "曼谷", "新加坡", "馬來西亞", "澳洲", "紐西蘭", "洛陽", "鄭州", "郑州",
    "開封", "少林寺", "雲臺山", "郭亮村", "清州", "Cheongju", "Seoul",
]
SOUTH_TAIWAN = ["南臺灣", "南台灣", "高雄", "台南", "臺南", "屏東", "墾丁", "小琉球", "琉球", "嘉義", "阿里山", "北港", "朝天宮", "美人洞", "山豬溝", "烏鬼洞"]


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def collect_sidecars(target: Optional[str] = None) -> list[Path]:
    target_ids = [target] if target else load_target_ids()
    out: list[Path] = []
    for tid in target_ids:
        travel_dir = DOWNLOADS_DIR / tid / "travel"
        if not travel_dir.exists():
            continue
        for sc in sorted(travel_dir.glob("*.*.json")):
            try:
                if image_of_sidecar(sc).suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
                    out.append(sc)
            except Exception:
                pass
    return out


def find_branded(orig_image: Path) -> Optional[Path]:
    branded_dir = orig_image.parent.parent / "branded"
    for suffix in (".jpg", ".jpeg", ".png", orig_image.suffix):
        candidate = branded_dir / f"{orig_image.stem}_branded{suffix}"
        if candidate.exists():
            return candidate
    return None


def parse_date_window(query: str) -> Optional[tuple[tuple[int, int], tuple[int, int]]]:
    m = re.search(r"(\d{1,2})/(\d{1,2})\s*[~～\-到至]\s*(?:(\d{1,2})/)?(\d{1,2})", query)
    if m:
        m1, d1 = int(m.group(1)), int(m.group(2))
        m2, d2 = int(m.group(3) or m1), int(m.group(4))
        return (m1, d1), (m2, d2)
    m = re.search(r"(\d{1,2})\s*月", query)
    if m:
        mo = int(m.group(1))
        return (mo, 1), (mo, 31)
    return None


def extract_product_prices(text: str) -> list[int]:
    """Extract likely product/fare prices, avoiding insurance/tip/surcharge numbers."""
    normalized = (text or "").replace(",", "")
    compact = _compact(text).replace(",", "")
    prices: list[int] = []
    bad_context = ["保險", "保险", "醫療", "医疗", "醫疗", "医疗险", "醫療险", "小費", "小费", "加價", "加价", "車齡", "车龄", "行政手續"]
    good_context = ["考察價", "團費", "团费", "現金價", "现金价", "心動價", "售價", "元起", "元 起", "起/人", "起／人", "元起人", "含税", "含稅"]

    for m in re.finditer(r"(?<![\d/])(\d{4,6})(?![\d/])", normalized):
        n = int(m.group(1))
        if not (1000 <= n <= 300000):
            continue
        ctx_before = normalized[max(0, m.start() - 10): m.start()]
        ctx_after = normalized[m.end(): m.end() + 12]
        ctx = ctx_before + normalized[m.start():m.end()] + ctx_after
        has_good = any(g in ctx for g in good_context)
        has_good_after = any(g in ctx_after for g in ["元起", "元 起", "起/人", "起／人", "元起人", "含税", "含稅"])
        # If bad words appear before the number, accept only when the number
        # itself is immediately followed by a fare marker (e.g. 6999 元起),
        # not when it is a surcharge like NTD2000.
        if any(b in ctx_before for b in bad_context) and not has_good_after:
            continue
        if has_good:
            prices.append(n)

    for m in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[萬wW](?!\w)", compact):
        ctx = compact[max(0, m.start() - 18): m.end() + 18]
        if any(b in ctx for b in bad_context):
            continue
        if not any(g in ctx for g in good_context):
            continue
        n = int(float(m.group(1)) * 10000)
        if 1000 <= n <= 300000:
            prices.append(n)

    # Fallback to the older extractor for normal small product fares only.
    fallback = extract_price_from(text)
    if fallback is not None and 1000 <= fallback < 100000:
        bad = False
        for m in re.finditer(re.escape(str(fallback)), normalized):
            ctx = normalized[max(0, m.start() - 18): m.end() + 18]
            if any(b in ctx for b in bad_context):
                bad = True
        if not bad:
            prices.append(fallback)

    return sorted(set(prices))


def extract_dates(text: str) -> list[tuple[int, int]]:
    compact = _compact(text)
    dates: list[tuple[int, int]] = []
    for m in re.finditer(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", compact):
        mo, day = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= day <= 31:
            dates.append((mo, day))
    for m in re.finditer(r"(?<!\d)(\d{1,2})/(\d{1,2})(?:\.(\d{1,2}))+", compact):
        mo = int(m.group(1))
        if 1 <= mo <= 12:
            for day_s in [m.group(2), *re.findall(r"\.(\d{1,2})", m.group(0))]:
                day = int(day_s)
                if 1 <= day <= 31:
                    dates.append((mo, day))
    seen=set(); out=[]
    for d in dates:
        if d not in seen:
            seen.add(d); out.append(d)
    return out


def in_window(date: tuple[int, int], window: tuple[tuple[int, int], tuple[int, int]]) -> bool:
    return window[0] <= date <= window[1]


def query_matches(query: str, text: str) -> tuple[bool, list[str]]:
    raw_query = (query or "").lower().replace("查圖:", "").replace("查圖：", "")
    cq = _compact(raw_query)
    ct = _compact(text)
    ctl = ct.lower()
    reasons: list[str] = []

    if any(k in cq for k in ["國內", "台灣", "臺灣"]):
        domestic = [k for k in DOMESTIC_KEYWORDS if k in ct]
        overseas = [k for k in OVERSEAS_KEYWORDS if k.lower() in ctl]
        if not domestic or overseas:
            return False, []
        reasons.extend(domestic[:5])

    if any(k in cq for k in ["國外", "海外"]):
        overseas = [k for k in OVERSEAS_KEYWORDS if k.lower() in ctl]
        if not overseas:
            return False, []
        reasons.extend(overseas[:5])

    if any(k in cq for k in ["南臺灣", "南台灣", "南部"]):
        hits = [k for k in SOUTH_TAIWAN if k in ct]
        if not hits:
            return False, []
        # Avoid treating departure cities as south-Taiwan products, e.g. 金門
        # product departing from 高雄.
        if "金門" in ct and set(hits).issubset({"高雄", "台中", "臺中"}):
            return False, []
        reasons.extend(hits[:5])

    date_window = parse_date_window(query)
    if date_window:
        dates = extract_dates(text)
        matched_dates = [f"{m}/{d}" for m, d in dates if in_window((m, d), date_window)]
        if not matched_dates:
            return False, []
        reasons.extend(matched_dates[:8])

    price_min, price_max = parse_price_bounds(query)
    if price_min is not None or price_max is not None:
        prices = extract_product_prices(text)
        if not prices:
            return False, []
        matched_prices = [
            p for p in prices
            if (price_min is None or p >= price_min)
            and (price_max is None or p <= price_max)
        ]
        if not matched_prices:
            return False, []
        reasons.extend(str(p) for p in matched_prices[:5])

    stop = {"查圖", "幫我", "找", "有沒有", "產品", "行程", "方案", "的", "我想", "想找", "有哪些", "可以", "出團", "能出團", "現在"}
    token_source = re.sub(r"\d{1,2}/\d{1,2}\s*[~～\-到至]\s*(?:\d{1,2}/)?\d{1,2}", " ", raw_query)
    token_source = re.sub(r"\d+(?:\.\d+)?\s*[~-～至到]\s*\d+(?:\.\d+)?\s*萬?", " ", token_source)
    token_source = token_source.replace("能出團的產品", " ").replace("能出團", " ")
    tokens = [t for t in re.split(r"[\s,，:：]+", token_source) if t and t not in stop]
    special_words = {"國內", "國外", "海外", "台灣", "臺灣", "南臺灣", "南台灣", "南部"}
    plain_tokens = [t for t in tokens if t not in special_words and not re.search(r"\d", t)]
    # For natural language queries, require at least one meaningful non-filter token if present.
    meaningful = [t for t in plain_tokens if len(t) >= 2]
    if meaningful:
        hits = [t for t in meaningful if t in ctl]
        # If structured filters already matched (date/budget/domestic/etc.),
        # ignore leftover conversational words such as「的產品」instead of
        # failing an otherwise valid query.
        if not hits and not reasons:
            return False, []
        reasons.extend(hits)

    return bool(reasons) or not (date_window or price_min or price_max), reasons


def copy_to_clipboard(files: list[Path]) -> None:
    if not files:
        return
    ps = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if not ps.exists() or not CLIPBOARD_SCRIPT.exists():
        return
    def wslpath(p: Path) -> str:
        return subprocess.check_output(["wslpath", "-w", str(p)], text=True).strip()
    subprocess.run([str(ps), "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", wslpath(CLIPBOARD_SCRIPT), *[wslpath(p) for p in files]], check=True)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fast query cached OCR sidecars and optionally copy results to clipboard.")
    p.add_argument("query", nargs="+", help="search query text")
    p.add_argument("--target")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--copy-clipboard", action="store_true")
    p.add_argument("--selected-dir", default=str(DEFAULT_SELECTED_DIR))
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    query = " ".join(args.query)
    matches: list[dict] = []
    for sc in collect_sidecars(args.target):
        side = _load_json(sc)
        text = ((side.get("ocr") or {}).get("text") or "")
        ok, reasons = query_matches(query, text)
        if not ok:
            continue
        orig = image_of_sidecar(sc)
        branded = find_branded(orig) or orig
        matches.append({
            "file": branded.name,
            "sidecar": relpath_from_root(sc),
            "image_path": relpath_from_root(branded),
            "reasons": reasons,
            "text_preview": text[:300].replace("\n", " "),
        })
        if len(matches) >= args.limit:
            break

    selected_files: list[Path] = []
    if matches and args.copy_clipboard:
        selected = Path(args.selected_dir)
        selected.mkdir(parents=True, exist_ok=True)
        for old in selected.glob("*"):
            if old.is_file():
                old.unlink()
        for m in matches:
            src = PROJECT_ROOT / m["image_path"]
            dst = selected / src.name
            shutil.copy2(src, dst)
            m["selected_path"] = str(dst)
            selected_files.append(dst)
        copy_to_clipboard(selected_files)

    print(json.dumps({"count": len(matches), "matches": matches}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
