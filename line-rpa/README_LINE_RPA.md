# LINE PC 群組圖片下載 RPA

這個工具會讀取 `line.XLSX` 第一欄群組名稱，控制 Windows 版 LINE 前台介面，依序進入群組的「照片・影片」頁下載圖片。

## 正式外網流程

外網網頁的「手動觸發抓取+ocr+組圖」只使用這一組設定：

```text
line-rpa\config.json
line-rpa\line.XLSX
```

不要改用舊測試檔或封存檔。`config.json` 是正式來源，`line.XLSX` 是正式群組清單。

目前正式設定保留實測成功流程的 LINE 視窗位置與長寬。

一般桌面座標，也就是肉眼看到的目前 LINE 視窗：

```json
{
  "x": 0,
  "y": 53,
  "width": 1024,
  "height": 507
}
```

RPA 程式是 DPI-aware，`config.json` 裡必須保存對應的 DPI-aware 座標：

```json
"line_window": {
  "x": 0,
  "y": 80,
  "width": 1536,
  "height": 760
}
```

主要座標使用同一套成功流程設定：

```json
"search_box": [0.074, 0.162],
"first_search_result": [0.2021, 0.3471],
"chat_menu": [0.9775, 0.1538],
"viewer_download_button": [0.9206, 0.07],
"download_button": [0.9206, 0.07]
```

照片/影片視窗與圖片檢視/下載視窗也固定為成功流程大小。

照片/影片視窗一般桌面座標：

```json
{
  "x": 0,
  "y": 0,
  "width": 602,
  "height": 762
}
```

圖片檢視/下載視窗一般桌面寬度會受 LINE 視窗最小寬度限制，實測落在約 `672 x 762`。
這個圖片檢視/下載視窗大小已完成另存新檔成功測試，正式流程固定使用這組值。

RPA DPI-aware 設定：

```json
"media_window": {
  "x": 0,
  "y": 0,
  "width": 903,
  "height": 1143
},
"viewer_window": {
  "x": 0,
  "y": 0,
  "width": 1008,
  "height": 1143
}
```

正式流程會跑完整 `line.XLSX`，即使某一個群組沒有下載到新圖，也會繼續處理後面的群組：

```json
"wait_seconds": 2,
"max_no_new_download_rounds": 5,
"next_image_wait_seconds": 1.0,
"stop_on_group_failure": false
```

這是保守加速設定：降低固定等待時間，但仍保留足夠 timeout，避免 LINE 偶發卡頓時漏圖。

## 執行前

1. 確認 LINE PC 版已登入。
2. 關閉不必要的視窗，避免擋住 LINE。
3. 執行期間不要操作滑鼠與鍵盤。
4. 確認 `config.json` 裡的 `save_root` 是：

```text
.\line-rpa\download
```

## 先測試清單與日誌

這個命令不會控制 LINE，只會讀取 Excel 並建立 dry-run 日誌：

```powershell
python .\line_image_downloader.py --dry-run
```

日誌位置：

```text
.\line-rpa\download\line_download_log.xlsx
```

## 首次端到端測試

這會控制 LINE，並依照 `config.json` 的 `test_limit` 處理群組：

```powershell
python .\line_image_downloader.py
```

## 全部群組執行

第一筆確認成功後再執行全部：

```powershell
python .\line_image_downloader.py --all
```

## 座標校準

LINE PC 版介面若不同，可能需要調整 `config.json` 的 `coordinates`。座標是視窗最大化後的相對比例，格式為 `[水平比例, 垂直比例]`，範圍是 `0` 到 `1`。

主要欄位：

- `search_box`: LINE 搜尋框
- `first_search_result`: 搜尋結果第一筆
- `chat_menu`: 群組右上角三點選單
- `photos_videos_menu_item`: 「照片・影片」選項
- `first_photo_thumbnail`: 照片頁第一張圖片
- `download_button`: 圖片檢視器下載按鈕
- `next_button`: 下一張圖片按鈕
- `close_viewer`: 關閉圖片檢視器

## 注意

- 檔案已存在時不覆蓋；日誌會記為跳過。
- 腳本不處理 LINE 登入、驗證碼或帳號切換。
- 只抓照片圖片，不抓影片、檔案、連結或投票。
- 舊的測試 config / Excel 已移除，避免誤用。正式流程只保留 `config.json` 與 `line.XLSX`。
