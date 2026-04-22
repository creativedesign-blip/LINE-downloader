"""
PaddleOCR 3.x 圖片過濾 — 判定「旅遊行程簡介」vs「非旅遊」
流程：
  OCR 抽取文字 → 比對 travel_keywords.txt
  強信號命中任 1 個 → 旅遊相關
  否則 弱信號+金額/日期 bonus ≥ MIN_WEAK_HITS → 旅遊相關
  都不滿足 → 非旅遊
  OCR/搬移失敗 → 錯誤/
執行：
  單次：python filter.py
  監看：python filter.py --watch
"""
import os
import sys
import re
import time
import json
import shutil
import argparse
from datetime import datetime, timezone
from pathlib import Path


def sidecar_path(img_path: Path) -> Path:
    return img_path.with_suffix(img_path.suffix + '.json')


def load_sidecar(img_path: Path) -> dict:
    sp = sidecar_path(img_path)
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_sidecar(img_path: Path, data: dict) -> None:
    sp = sidecar_path(img_path)
    sp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def move_with_sidecar(src: Path, dest: Path) -> None:
    shutil.move(str(src), str(dest))
    src_side = sidecar_path(src)
    if src_side.exists():
        dest_side = sidecar_path(dest)
        try:
            shutil.move(str(src_side), str(dest_side))
        except Exception:
            pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

os.environ.setdefault('FLAGS_use_mkldnn', 'false')          # 關掉 oneDNN 避開 PIR bug
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')

try:
    from paddleocr import PaddleOCR
    import numpy as np
    import cv2
except ImportError as e:
    print(f"[錯誤] 套件缺少：{e}。請先執行 filter/install.bat")
    sys.exit(1)


def imread_unicode(path: Path):
    """Windows 中文路徑安全讀取 → 回傳 numpy BGR 陣列"""
    with open(path, 'rb') as f:
        buf = f.read()
    arr = np.frombuffer(buf, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cv2.imdecode 失敗（格式不支援或檔案損壞）")
    return img

# ============== 設定 ==============
DEFAULT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = DEFAULT_ROOT
DEFAULT_TRAVEL_DIR = DEFAULT_ROOT / 'travel'
DEFAULT_OTHER_DIR = DEFAULT_ROOT / 'other'
DEFAULT_ERROR_DIR = DEFAULT_ROOT / 'error'
DEFAULT_MIN_WEAK_HITS = 2
KEYWORDS_FILE = Path(__file__).resolve().parent / 'travel_keywords.txt'
SUPPORTED_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
WATCH_POLL_SEC = 2.0
STABLE_WAIT_SEC = 1.0


def load_keywords(path: Path):
    """解析 travel_keywords.txt → (strong_list, weak_list)
    語法：以 [STRONG]/[WEAK] 分章節；# 開頭為註解；一行一個關鍵字"""
    if not path.exists():
        raise FileNotFoundError(f"找不到關鍵字檔：{path}")
    strong, weak = [], []
    section = None
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        up = line.upper()
        if up == '[STRONG]':
            section = strong
            continue
        if up == '[WEAK]':
            section = weak
            continue
        if section is not None:
            section.append(line)
    if not strong and not weak:
        raise ValueError(f"{path} 未解析出任何關鍵字（檢查 [STRONG]/[WEAK] 標記）")
    return strong, weak


STRONG_KEYWORDS, WEAK_KEYWORDS = load_keywords(KEYWORDS_FILE)
MONEY_RE = re.compile(r'(NT\$|NTD|TWD|USD|JPY|¥|\$|元|萬)\s*[\d,]+|[\d,]+\s*元')
DATE_RE = re.compile(r'\d+\s*天\s*\d+\s*夜|\d+\s*日\s*\d+\s*夜|第\s*\d+\s*天')

def parse_args():
    parser = argparse.ArgumentParser(description='PaddleOCR travel-image classifier')
    parser.add_argument('--input-dir', type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument('--travel-dir', type=Path, default=DEFAULT_TRAVEL_DIR)
    parser.add_argument('--other-dir', type=Path, default=DEFAULT_OTHER_DIR)
    parser.add_argument('--error-dir', type=Path, default=DEFAULT_ERROR_DIR)
    parser.add_argument('--min-weak-hits', type=int, default=DEFAULT_MIN_WEAK_HITS)
    parser.add_argument('--watch', action='store_true')
    return parser.parse_args()


ARGS = parse_args()
INPUT_DIR = ARGS.input_dir.resolve()
TRAVEL_DIR = ARGS.travel_dir.resolve()
OTHER_DIR = ARGS.other_dir.resolve()
ERROR_DIR = ARGS.error_dir.resolve()
MIN_WEAK_HITS = ARGS.min_weak_hits
WATCH = ARGS.watch

TRAVEL_DIR.mkdir(parents=True, exist_ok=True)
OTHER_DIR.mkdir(parents=True, exist_ok=True)
ERROR_DIR.mkdir(parents=True, exist_ok=True)


def list_pending():
    return [
        f for f in INPUT_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
    ]


def unique_path(dest_dir: Path, name: str) -> Path:
    target = dest_dir / name
    if not target.exists():
        return target
    stem, suf = target.stem, target.suffix
    k = 1
    while (dest_dir / f"{stem}_{k}{suf}").exists():
        k += 1
    return dest_dir / f"{stem}_{k}{suf}"


def extract_text(ocr, img_path: Path) -> str:
    # 用 unicode-safe 方式讀檔 → numpy array → PaddleOCR
    img = imread_unicode(img_path)
    try:
        result = ocr.predict(input=img)
    except Exception as e:
        raise RuntimeError(f"predict 失敗：{e}")
    if not result:
        return ''
    lines = []
    for item in result:
        if isinstance(item, dict):
            texts = item.get('rec_texts') or []
            if isinstance(texts, (list, tuple)):
                lines.extend(str(t) for t in texts if t)
    return '\n'.join(lines)


OCR_INSTANCE = None


def get_ocr():
    global OCR_INSTANCE
    if OCR_INSTANCE is None:
        print("載入 PaddleOCR 模型（首次會下載，之後用快取）…")
        OCR_INSTANCE = PaddleOCR(
            lang='ch',
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )
        print("模型就緒\n")
    return OCR_INSTANCE


def classify_text(text: str):
    """回傳 (is_travel, reason, hits_display)
    規則：強信號任一命中 → True；否則弱信號+金額/日期 bonus ≥ MIN_WEAK_HITS → True"""
    if not text:
        return False, 'empty', ''
    strong = [kw for kw in STRONG_KEYWORDS if kw in text]
    weak = [kw for kw in WEAK_KEYWORDS if kw in text]
    bonus = []
    if MONEY_RE.search(text):
        bonus.append('<金額>')
    if DATE_RE.search(text):
        bonus.append('<日期>')

    if strong:
        reason = f"強×{len(strong)}"
    else:
        reason = f"弱×{len(weak)}+{len(bonus)}"
    is_travel = bool(strong) or (len(weak) + len(bonus) >= MIN_WEAK_HITS)
    all_hits = strong + weak + bonus
    hits_display = ','.join(all_hits[:5]) + (' …' if len(all_hits) > 5 else '')
    return is_travel, reason, hits_display


def update_sidecar_with_ocr(img_path: Path, *, classification: str, text: str = '',
                            reason: str = '', hits: str = '', error: str = '') -> None:
    side = load_sidecar(img_path)
    ocr_block = side.get('ocr') or {}
    ocr_block['classifiedAt'] = utc_now_iso()
    ocr_block['classification'] = classification
    if text:
        ocr_block['text'] = text
    if reason:
        ocr_block['reason'] = reason
    if hits:
        ocr_block['hits'] = hits
    if error:
        ocr_block['error'] = error
    side['ocr'] = ocr_block
    try:
        save_sidecar(img_path, side)
    except Exception as save_err:
        print(f"  [警告] sidecar 寫入失敗 {img_path.name}: {save_err}")


def process_one(ocr, img_path: Path):
    # 先檢查檔案是否還在——另一個 classifier 行程（例如 UI server 內部的）可能已經搬走
    if not img_path.exists():
        return 'skip'
    try:
        text = extract_text(ocr, img_path)
    except Exception as e:
        if not img_path.exists():
            return 'skip'
        update_sidecar_with_ocr(img_path, classification='error', error=str(e))
        try:
            err_path = unique_path(ERROR_DIR, img_path.name)
            move_with_sidecar(img_path, err_path)
        except FileNotFoundError:
            # 另一個行程搬走了，清掉我們剛寫的 sidecar 避免 orphan
            try: sidecar_path(img_path).unlink()
            except FileNotFoundError: pass
            return 'skip'
        except Exception as move_err:
            print(f"  [錯誤] {img_path.name}: {e}（搬移失敗 {move_err}）")
            return 'err'
        print(f"  [錯誤] {img_path.name}: {e}  → 錯誤/")
        return 'err'

    is_travel, reason, hits_display = classify_text(text)
    dest = TRAVEL_DIR if is_travel else OTHER_DIR
    classification = 'travel' if is_travel else 'other'
    if not img_path.exists():
        return 'skip'
    update_sidecar_with_ocr(
        img_path,
        classification=classification,
        text=text,
        reason=reason,
        hits=hits_display,
    )
    try:
        new_path = unique_path(dest, img_path.name)
        move_with_sidecar(img_path, new_path)
    except FileNotFoundError:
        try: sidecar_path(img_path).unlink()
        except FileNotFoundError: pass
        return 'skip'
    except Exception as move_err:
        print(f"  [錯誤] {img_path.name}: 搬移失敗 {move_err}")
        return 'err'
    flag = '[旅遊]' if is_travel else '[  -  ]'
    print(f"  {flag} {reason:<8} {img_path.name}  {hits_display}")
    return classification


def wait_stable(path: Path) -> bool:
    # 檔案若最近 mtime 都停了 300ms 且 size 穩定就認定完成寫入
    try:
        st1 = path.stat()
    except FileNotFoundError:
        return False
    if st1.st_size == 0:
        return False
    time.sleep(0.3)
    try:
        st2 = path.stat()
    except FileNotFoundError:
        return False
    return st2.st_size == st1.st_size and st2.st_mtime == st1.st_mtime


print("=" * 60)
print("  PaddleOCR 3.x 圖片過濾 — 旅遊相關" + ("（監看模式）" if WATCH else ""))
print("=" * 60)
print(f"  根目錄：{INPUT_DIR}")
print(f"  旅遊相關 → {TRAVEL_DIR.name}/")
print(f"  非旅遊   → {OTHER_DIR.name}/")
print(f"  錯誤檔   → {ERROR_DIR.name}/")
print(f"  關鍵字：強信號 {len(STRONG_KEYWORDS)} 個（任一即過）/ 弱信號 {len(WEAK_KEYWORDS)} 個（需 >={MIN_WEAK_HITS}，含金額/日期 bonus）")
print()

if not WATCH:
    files = list_pending()
    if not files:
        print("根目錄沒有待過濾的圖片。")
        sys.exit(0)
    print(f"找到 {len(files)} 張，開始處理\n")
    stats = {'travel': 0, 'other': 0, 'err': 0, 'skip': 0}
    for i, f in enumerate(files, 1):
        print(f"  [{i:3d}/{len(files)}]", end=' ')
        stats[process_one(get_ocr(), f)] += 1
    print()
    print(f"完成：{stats['travel']} 旅遊相關 / {stats['other']} 非旅遊 / {stats['err']} 錯誤 / {stats['skip']} 略過(另一行程已處理)")
    sys.exit(0)

print("監看中：新進根目錄的圖片會自動分類")
print("按 Ctrl+C 結束\n")
processed = set()
total = {'travel': 0, 'other': 0, 'err': 0, 'skip': 0}
try:
    while True:
        for f in list_pending():
            if f in processed:
                continue
            if not wait_stable(f):
                continue
            total[process_one(get_ocr(), f)] += 1
            processed.add(f)
        processed = {p for p in processed if p.exists()}
        time.sleep(WATCH_POLL_SEC)
except KeyboardInterrupt:
    print("\n手動結束")

print()
print("=" * 60)
print(f"  累計：{total['travel']} 旅遊相關 / {total['other']} 非旅遊 / {total['err']} 錯誤")
print("=" * 60)
