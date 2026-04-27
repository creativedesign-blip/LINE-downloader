"""
將 scripts/00-all-in-one.js 的最新內容注入 readme.html 的
<script id="__line_dl_src__" type="text/plain"> ... </script> 區塊。

用途：避免「改了 JS 忘了同步 HTML」。開發期手動跑 `python scripts/sync-html.py` 同步。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_FILE = ROOT / "scripts" / "00-all-in-one.js"
HTML_FILE = ROOT / "readme.html"

if not JS_FILE.exists():
    print(f"[ERROR] 找不到 {JS_FILE}")
    sys.exit(1)
if not HTML_FILE.exists():
    print(f"[ERROR] 找不到 {HTML_FILE}")
    sys.exit(1)

js = JS_FILE.read_text(encoding="utf-8")
html = HTML_FILE.read_text(encoding="utf-8")

pattern = re.compile(
    r'(<script id="__line_dl_src__" type="text/plain">)(.*?)(</script>)',
    re.DOTALL,
)
m = pattern.search(html)
if not m:
    print("[ERROR] 找不到 <script id=\"__line_dl_src__\"> 區塊")
    sys.exit(1)

if m.group(2) == js:
    print(f"[OK] HTML 已是最新 ({len(js):,} chars)")
    sys.exit(0)

new_html = html[: m.start(2)] + js + html[m.end(2) :]
HTML_FILE.write_text(new_html, encoding="utf-8")
print(f"[OK] HTML 已同步 ({len(js):,} chars 注入)")
