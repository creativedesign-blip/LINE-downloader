"""
RapidOCR image classifier for travel-related LINE downloads.
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
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
import re
import time
import shutil
import hashlib
import argparse
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.branding.io_utils import sidecar_of, load_sidecar, save_sidecar
from tools.common.rapidocr_adapter import create_rapidocr, rapidocr_lines
from tools.domains.travel.policy import apply_sidecar_metadata
from tools.openclaw.learning_candidates import (
    load_approved_rule_texts,
    record_assume_travel_candidates,
)


def move_with_sidecar(src: Path, dest: Path) -> None:
    # Move sidecar before image so a failure leaves the source folder
    # intact instead of orphaning the OCR sidecar at the src location.
    src_side = sidecar_of(src)
    dest_side = sidecar_of(dest)
    sidecar_moved = False
    if src_side.exists():
        shutil.move(str(src_side), str(dest_side))
        sidecar_moved = True
    try:
        shutil.move(str(src), str(dest))
    except Exception:
        if sidecar_moved:
            try:
                shutil.move(str(dest_side), str(src_side))
            except Exception as rollback_err:
                print(f"  [錯誤] sidecar 回滾失敗 {dest_side} -> {src_side}: {rollback_err}")
        raise


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


try:
    import numpy as np
    import cv2
except ImportError as e:
    print(f"[錯誤] 套件缺少：{e}。請先執行 filter/install.bat")
    sys.exit(1)


from tools.common.targets import DOWNLOADS_DIR


def decode_image_bytes(buf: bytes):
    """Decode raw image bytes to BGR ndarray. Raises on decode failure."""
    arr = np.frombuffer(buf, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("cv2.imdecode 失敗（格式不支援或檔案損壞）")
    return img


@dataclass(frozen=True)
class Routes:
    """Output destinations for one filter spec. Attribute names match
    the classify_text return values (travel/review/other) so process_one
    can dispatch with `getattr(routes, classification)`."""
    travel: Path
    other: Path
    review: Path
    error: Path

# ============== 設定 ==============
DEFAULT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = DEFAULT_ROOT
DEFAULT_TRAVEL_DIR = DEFAULT_ROOT / 'travel'
DEFAULT_OTHER_DIR = DEFAULT_ROOT / 'other'
DEFAULT_REVIEW_DIR = DEFAULT_ROOT / 'review'
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
LEARNED_TRAVEL_RULES = load_approved_rule_texts()
MONEY_RE = re.compile(
    r'(NT\$|NTD|TWD|USD|JPY|¥|\$|元|萬)\s*[\d,]+'
    r'|[\d,]+\s*(元|萬|起|起售)'
    r'|\b\d{1,3}(?:,\d{3})+\b'
    r'|(?<!\d)\d{4,6}\s*起(?!\d)'
)
DATE_RE = re.compile(
    r'\d+\s*天\s*\d+\s*夜'
    r'|\d+\s*日\s*\d+\s*夜'
    r'|第\s*\d+\s*天'
    r'|(?<!\d)\d{1,2}\s*(日|天)(?!\d)'
    r'|(?<!\d)\d{1,2}\s*/\s*\d{1,2}(?!\d)'
    r'|(?<!\d)\d{1,2}\s*月\s*\d{1,2}\s*日(?!\d)'
)


def normalize_ocr_text(text: str) -> str:
    """Normalize OCR text for matching.

    OCR engines sometimes insert spaces/newlines inside words, emit full-width
    digits, or mixes Simplified/Traditional variants.  Keep the original text
    for logs/indexing, but classify against this compact version to avoid false
    OTHER results for obvious travel DM images.
    """
    text = unicodedata.normalize('NFKC', text or '')
    replacements = {
        '韩国': '韓國',
        '冲绳': '沖繩',
        '冲縄': '沖繩',
        '美丽海水族馆': '美麗海水族館',
        '答里岛': '峇里島',
        '巴里島': '峇里島',
        '開囊': '開賣',  # common OCR miss for 可樂 DM「開賣」
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return re.sub(r'\s+', '', text)


def keyword_hits(keywords, raw_text: str, compact_text: str):
    hits = []
    for kw in keywords:
        norm_kw = normalize_ocr_text(kw)
        if kw in raw_text or (norm_kw and norm_kw in compact_text):
            hits.append(kw)
    return hits

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='RapidOCR travel-image classifier')
    parser.add_argument('--input-dir', type=Path, default=None,
                        help='Single-folder compatibility mode: source folder (defaults to project root).')
    parser.add_argument('--travel-dir', type=Path, default=None,
                        help='Single-folder compatibility mode: travel destination.')
    parser.add_argument('--other-dir', type=Path, default=None,
                        help='Single-folder compatibility mode: other destination.')
    parser.add_argument('--review-dir', type=Path, default=None,
                        help='Single-folder compatibility mode: review destination (uncertain hits).')
    parser.add_argument('--error-dir', type=Path, default=None,
                        help='Single-folder compatibility mode: error destination.')
    parser.add_argument('--target', action='append', default=None, metavar='ID',
                        help='Repeatable target id under line-rpa/download/<ID>/. '
                             'Mutually exclusive with --input-dir/--travel-dir/etc. '
                             'Multi-target mode shares one OCR engine load.')
    parser.add_argument('--assume-travel', action='store_true',
                        help='Treat successfully OCR-read review/other images as travel.')
    parser.add_argument('--min-weak-hits', type=int, default=DEFAULT_MIN_WEAK_HITS)
    parser.add_argument('--watch', action='store_true',
                        help='Watch mode polls a single input dir; not allowed with --target.')
    parser.add_argument('--no-auto-index', action='store_true',
                        help='Skip the inline per-image reindex of travel images. Use when a '
                             'batch reindex (index:all) runs afterwards, so the slow per-row '
                             'autocommit index pass is not duplicated. Branding still runs inline.')
    return parser.parse_args(argv)


# Mutated by main(); kept module-level so classify_text() and other helpers
# can be imported and unit-tested without re-deriving the threshold.
MIN_WEAK_HITS = DEFAULT_MIN_WEAK_HITS


def list_pending(input_dir: Path):
    return [
        f for f in input_dir.iterdir()
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


def extract_text(ocr, img) -> str:
    # img is a decoded BGR ndarray. Passing the array (rather than a path)
    # avoids re-reading the file and works around Windows codepage issues.
    try:
        result = ocr(img)
    except Exception as e:
        raise RuntimeError(f"predict 失敗：{e}")
    return '\n'.join(rapidocr_lines(result))


OCR_INSTANCE = None


def get_ocr():
    global OCR_INSTANCE
    if OCR_INSTANCE is None:
        print("載入 RapidOCR 模型…")
        OCR_INSTANCE = create_rapidocr()
        print("模型就緒\n")
    return OCR_INSTANCE


def classify_text(text: str):
    """Return (classification, reason, hits_display).

    classification ∈ {'travel', 'review', 'other'}:
      - travel: strong keyword hit, OR weak+bonus signals reach MIN_WEAK_HITS
      - review: no strong hit, but at least one weak or bonus signal
        (some travel cue is present but not enough to commit). Routed
        to review/ for human confirmation.
      - other: no signal at all.
    """
    if not text:
        return 'other', 'empty', ''
    raw_text = unicodedata.normalize('NFKC', text)
    compact_text = normalize_ocr_text(raw_text)
    learned = keyword_hits(LEARNED_TRAVEL_RULES, raw_text, compact_text)
    strong = keyword_hits(STRONG_KEYWORDS, raw_text, compact_text)
    weak = keyword_hits(WEAK_KEYWORDS, raw_text, compact_text)
    bonus = []
    if MONEY_RE.search(raw_text) or MONEY_RE.search(compact_text):
        bonus.append('<金額>')
    if DATE_RE.search(raw_text) or DATE_RE.search(compact_text):
        bonus.append('<日期>')

    weight = len(weak) + len(bonus)
    if learned:
        reason = f"learned×{len(learned)}"
    elif strong:
        reason = f"強×{len(strong)}"
    else:
        reason = f"弱×{len(weak)}+{len(bonus)}"

    if learned or strong or weight >= MIN_WEAK_HITS:
        classification = 'travel'
    elif weight >= 1:
        classification = 'review'
    else:
        classification = 'other'

    all_hits = learned + strong + weak + bonus
    hits_display = ','.join(all_hits[:5]) + (' …' if len(all_hits) > 5 else '')
    return classification, reason, hits_display


def apply_assume_travel(classification: str, reason: str, *, assume_travel: bool) -> tuple[str, str]:
    if assume_travel and classification in {'review', 'other'}:
        return 'travel', f"assume-travel:{classification}"
    return classification, reason


def update_sidecar_with_ocr(img_path: Path, *, classification: str, text: str = '',
                            reason: str = '', hits: str = '', error: str = '',
                            image_sha256: str = '',
                            original_classification: str = '',
                            original_reason: str = '',
                            assume_travel_applied: bool = False) -> None:
    side = load_sidecar(img_path)
    ocr_block = side.get('ocr') or {}
    ocr_block['classifiedAt'] = utc_now_iso()
    ocr_block['classification'] = classification
    if original_classification:
        ocr_block['originalClassification'] = original_classification
    if original_reason:
        ocr_block['originalReason'] = original_reason
    if assume_travel_applied:
        ocr_block['assumeTravelApplied'] = True
    if text:
        ocr_block['text'] = text
        # Stamp engine + image hash so ocr_enrich's cache check
        # (text + matching imageSha256) hits and skips a redundant OCR pass.
        ocr_block['engine'] = 'rapidocr-onnxruntime'
        if image_sha256:
            ocr_block['imageSha256'] = image_sha256
        if classification == 'travel':
            side = apply_sidecar_metadata(side, text)
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


def process_one(ocr, img_path: Path, *, routes: Routes, assume_travel: bool = False,
                auto_index: bool = True):
    # 先檢查檔案是否還在——另一個 classifier 行程（例如 UI server 內部的）可能已經搬走
    if not img_path.exists():
        return 'skip'
    # Read the file exactly once: hash from the buffer and decode from the
    # same bytes, so OCR sees the same image as the recorded imageSha256.
    try:
        with open(img_path, 'rb') as f:
            buf = f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return 'skip'
    if not buf:
        return 'skip'
    img_hash = hashlib.sha256(buf).hexdigest()

    try:
        img = decode_image_bytes(buf)
        text = extract_text(ocr, img)
    except Exception as e:
        if not img_path.exists():
            return 'skip'
        update_sidecar_with_ocr(img_path, classification='error', error=str(e))
        try:
            err_path = unique_path(routes.error, img_path.name)
            move_with_sidecar(img_path, err_path)
        except FileNotFoundError:
            # 另一個行程搬走了，清掉我們剛寫的 sidecar 避免 orphan
            try: sidecar_of(img_path).unlink()
            except FileNotFoundError: pass
            return 'skip'
        except Exception as move_err:
            print(f"  [錯誤] {img_path.name}: {e}（搬移失敗 {move_err}）")
            return 'err'
        print(f"  [錯誤] {img_path.name}: {e}  → 錯誤/")
        return 'err'

    classification, reason, hits_display = classify_text(text)
    original_classification = classification
    original_reason = reason
    classification, reason = apply_assume_travel(
        classification,
        reason,
        assume_travel=assume_travel,
    )
    assume_travel_applied = (
        assume_travel
        and original_classification in {'review', 'other'}
        and classification == 'travel'
    )
    dest = getattr(routes, classification)
    if not img_path.exists():
        return 'skip'
    update_sidecar_with_ocr(
        img_path,
        classification=classification,
        text=text,
        reason=reason,
        hits=hits_display,
        image_sha256=img_hash,
        original_classification=original_classification if assume_travel_applied else '',
        original_reason=original_reason if assume_travel_applied else '',
        assume_travel_applied=assume_travel_applied,
    )
    try:
        new_path = unique_path(dest, img_path.name)
        move_with_sidecar(img_path, new_path)
    except FileNotFoundError:
        try: sidecar_of(img_path).unlink()
        except FileNotFoundError: pass
        return 'skip'
    except Exception as move_err:
        print(f"  [錯誤] {img_path.name}: 搬移失敗 {move_err}")
        return 'err'
    flag_by_class = {'travel': '[旅遊]', 'review': '[待審]', 'other': '[  -  ]'}
    print(f"  {flag_by_class[classification]} {reason:<8} {img_path.name}  {hits_display}")

    if assume_travel_applied:
        try:
            sidecar = load_sidecar(new_path)
            rows = record_assume_travel_candidates(
                new_path,
                sidecar,
                original_classification=original_classification,
                original_reason=original_reason,
            )
            if rows:
                print(f"    learning candidates: {len(rows)}")
        except Exception as learning_err:
            print(f"    [warning] learning candidate record failed: {learning_err}")

    # Only auto-brand + auto-index confirmed travel images. review/ images
    # wait for human confirmation; once moved into travel/, the next
    # pipeline run picks them up via reindex/branding.
    #
    # auto_index=False (set by process_downloads when a batch index:all follows)
    # skips the inline reindex: that per-row autocommit pass is ~100x slower than
    # the batched rebuild and is fully redundant with index:all. Branding still
    # runs inline (idempotent, so the later branding:all is a cheap no-op).
    if classification == 'travel':
        sc = sidecar_of(new_path)
        from tools.branding.brand_stitcher import stitch_one_auto, set_footer_ocr_engine
        # Reuse the RapidOCR engine we already loaded for classification so the
        # branding footer detector doesn't load a second copy into this process.
        set_footer_ocr_engine(ocr)
        stitch_one_auto(sc)
        if auto_index:
            from tools.indexing.reindex import reindex_one_auto
            reindex_one_auto(sc)

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


def resolve_target_specs(args):
    """Return list of (input_dir, travel_dir, other_dir, review_dir, error_dir).

    --target mode: derives paths from line-rpa/download/<id>/{,inbox} and
    routes outputs to <id>/{travel,other,review,error}. inbox/ entry only
    emitted when it exists.

    Single-folder compatibility mode: one spec from --input-dir/--travel-dir/etc.
    with the same defaults the script has used since v1.
    """
    compatibility_dirs_provided = any([
        args.input_dir, args.travel_dir, args.other_dir, args.review_dir, args.error_dir,
    ])
    if args.target and compatibility_dirs_provided:
        raise SystemExit(
            '--target cannot be combined with --input-dir/--travel-dir/'
            '--other-dir/--review-dir/--error-dir; pick one mode.'
        )
    if args.target and args.watch:
        raise SystemExit('--watch is single-folder polling and cannot be combined with --target.')

    if args.target:
        specs: list[tuple[Path, Routes]] = []
        for tid in args.target:
            base = (DOWNLOADS_DIR / tid).resolve()
            if not base.exists():
                # Skip silently rather than mkdir-creating a phantom group folder.
                print(f"[skip] target 不存在：{base}")
                continue
            routes = Routes(
                travel=base / 'travel',
                other=base / 'other',
                review=base / 'review',
                error=base / 'error',
            )
            specs.append((base, routes))
            inbox = base / 'inbox'
            if inbox.exists():
                specs.append((inbox.resolve(), routes))
        return specs

    return [(
        (args.input_dir or DEFAULT_INPUT_DIR).resolve(),
        Routes(
            travel=(args.travel_dir or DEFAULT_TRAVEL_DIR).resolve(),
            other=(args.other_dir or DEFAULT_OTHER_DIR).resolve(),
            review=(args.review_dir or DEFAULT_REVIEW_DIR).resolve(),
            error=(args.error_dir or DEFAULT_ERROR_DIR).resolve(),
        ),
    )]


def main(argv=None) -> int:
    global MIN_WEAK_HITS
    args = parse_args(argv)
    MIN_WEAK_HITS = args.min_weak_hits

    specs = resolve_target_specs(args)

    seen_outputs = set()
    for _, routes in specs:
        for d in (routes.travel, routes.other, routes.review, routes.error):
            if d not in seen_outputs:
                d.mkdir(parents=True, exist_ok=True)
                seen_outputs.add(d)

    print("=" * 60)
    print("  RapidOCR 圖片過濾 — 旅遊相關" + ("（監看模式）" if args.watch else ""))
    print("=" * 60)
    if args.target:
        print(f"  Targets: {', '.join(args.target)} ({len(specs)} input folders)")
    else:
        in_dir, routes = specs[0]
        print(f"  根目錄：{in_dir}")
        print(f"  旅遊相關 → {routes.travel.name}/")
        print(f"  非旅遊   → {routes.other.name}/")
        print(f"  待人工審核 → {routes.review.name}/")
        print(f"  錯誤檔   → {routes.error.name}/")
    print(f"  關鍵字：強信號 {len(STRONG_KEYWORDS)} 個（任一即過）/ 弱信號 {len(WEAK_KEYWORDS)} 個（需 >={MIN_WEAK_HITS}，含金額/日期 bonus）")
    print(f"  待審區：strong=0 但有 1 個信號的圖（弱×1+0、弱×0+1）→ {DEFAULT_REVIEW_DIR.name}/")
    if args.assume_travel:
        print("  assume-travel: OCR-success review/other images route to travel/")
    print()

    if args.watch:
        in_dir, routes = specs[0]
        return _watch_loop(in_dir, routes, assume_travel=bool(args.assume_travel))

    stats = {'travel': 0, 'review': 0, 'other': 0, 'err': 0, 'skip': 0}
    any_files = False
    for in_dir, routes in specs:
        if not in_dir.exists():
            print(f"[skip] 來源不存在：{in_dir}")
            continue
        files = list_pending(in_dir)
        if not files:
            continue
        any_files = True
        print(f"[{in_dir}] 找到 {len(files)} 張，開始處理")
        for i, f in enumerate(files, 1):
            print(f"  [{i:3d}/{len(files)}]", end=' ')
            stats[process_one(get_ocr(), f, routes=routes, assume_travel=bool(args.assume_travel),
                              auto_index=not args.no_auto_index)] += 1
        print()

    if not any_files:
        print("沒有待過濾的圖片。")
        return 0
    print(f"完成：{stats['travel']} 旅遊相關 / {stats['review']} 待人工審核 / "
          f"{stats['other']} 非旅遊 / {stats['err']} 錯誤 / {stats['skip']} 略過")
    return 0


def _watch_loop(input_dir: Path, routes: Routes, *, assume_travel: bool = False) -> int:
    print("監看中：新進根目錄的圖片會自動分類")
    print("按 Ctrl+C 結束\n")
    processed = set()
    total = {'travel': 0, 'review': 0, 'other': 0, 'err': 0, 'skip': 0}
    try:
        while True:
            for f in list_pending(input_dir):
                if f in processed:
                    continue
                if not wait_stable(f):
                    continue
                total[process_one(get_ocr(), f, routes=routes, assume_travel=assume_travel)] += 1
                processed.add(f)
            processed = {p for p in processed if p.exists()}
            time.sleep(WATCH_POLL_SEC)
    except KeyboardInterrupt:
        print("\n手動結束")

    print()
    print("=" * 60)
    print(f"  累計：{total['travel']} 旅遊相關 / {total['review']} 待人工審核 / "
          f"{total['other']} 非旅遊 / {total['err']} 錯誤")
    print("=" * 60)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
