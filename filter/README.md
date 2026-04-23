# PaddleOCR 自動過濾「旅遊行程簡介」

針對旅行社透過 LINE 官方帳號發給客戶的**行程簡介海報**設計：
OCR 辨識圖片文字 → 比對旅遊關鍵字（行程、團費、航班、飯店、天數夜數、目的地、金額格式）→ 依命中數分類。

## 執行方式

### 主要路徑（推薦）：UI server
雙擊上層資料夾的 **`launch-ui.bat`**：自動啟動 conda `paddleocr` env + Node UI server + 瀏覽器。
在 UI 按「立即抓取」或「開始全部監控」。下載落 `downloads/<target>/inbox/` 後 classifier 自動分類到 `travel/` 或 `other/`。

### 備用路徑：獨立跑 filter.py
若 UI server 沒跑、只想對某個資料夾重跑分類：
```
python filter/filter.py --input-dir <IN> --travel-dir <TRAVEL> --other-dir <OTHER>
```

## 一次性安裝

雙擊 `install.bat`：
- 找到本機 miniconda（`%UserProfile%\miniconda3`）
- 建立獨立 conda env `paddleocr`（Python 3.11）
- `pip install paddlepaddle paddleocr`（約 500MB / 5-10 分鐘）

## 判定邏輯（強弱信號分級）

關鍵字外置於 **`travel_keywords.txt`**，分兩節：

| 類別 | 門檻 | 範例 |
|---|---|---|
| **[STRONG]** 強信號 | 命中任 **1 個** 即判旅遊 | 行程、團費、出團、航班、班機、機票、導遊、領隊、訂金、尾款、五天四夜 … |
| **[WEAK]** 弱信號 | 需 ≥ `MIN_WEAK_HITS`（預設 2）才判旅遊 | 日本、東京、飯店、美食、觀光、溫泉 …（含金額/日期 bonus） |

加上金額 regex（`NT$ / 元 / USD …`）與日期 regex（`N天N夜 / 第N天`），都計入弱信號的命中數。

## 調整規則（無需改 Python）

**編輯 `filter/travel_keywords.txt`**：
- 缺少地名 / 術語 → 直接加到對應 `[STRONG]` 或 `[WEAK]` 段
- 想把某弱詞升強 → 從 WEAK 剪下貼到 STRONG
- 想更嚴格 → 移除 STRONG 裡不確定的詞；或在 BAT 加 `--min-weak-hits 3`
- 想更寬鬆 → 加 `--min-weak-hits 1`

改完存檔，下次 filter.py 啟動就生效（模型不需重載）。

## 檔案結構

```
line官方-download/
├── launch-ui.bat            ← 主要入口（UI server）
├── readme.html              ← 引導頁
├── app.js + _legacy/src/    ← Node 核心
├── scripts/
│   ├── 00-all-in-one.js     ← 頁內注入 scanner
│   ├── launch-chrome.bat    ← 開專用 Chrome (port 9333)
│   └── sync-html.py
├── filter/
│   ├── install.bat          ← 一次性設定 conda env
│   ├── filter.py            ← OCR 分類器（支援 --watch / --input-dir）
│   ├── travel_keywords.txt  ← 關鍵字清單（[STRONG]/[WEAK]）
│   └── README.md
├── config/
│   ├── targets.json         ← target 綁定
│   └── state/<target>.json  ← 每 target 的 seenKeys
└── downloads/<target>/{inbox,travel,other}/
```

## 疑難

| 現象 | 處理 |
|---|---|
| `conda env "paddleocr" not found` | 先跑 `filter/install.bat` |
| 旅遊海報被誤判為「非旅遊」 | 看 log 實際 OCR 出什麼；缺關鍵字就加進 `travel_keywords.txt` 對應段落 |
| 模型下載卡住 | 檢查網路；模型存在 `%USERPROFILE%\.paddleocr\` |
| 中英混雜辨不全 | 改 `lang='ch'` → `'chinese_cht'`（繁中模型） |
