# Engineering Method - LINE Downloader System

這份文件整理本專案的工程化落地方法論。目的不是只讓腳本能跑，而是讓整套系統可以穩定維運、可追蹤、可重構、可人工介入，並避免模組之間互相打架。

## 核心目標

系統設計目標：

```text
可穩定執行
可追蹤問題
可控制執行成本
可逐步擴充
可人工介入
可工程化落地
```

一句話原則：

```text
先把流程切開，讓每個模組只做一件事；
不穩定的先完成，耗資源的後處理；
能自動判斷的自動處理，不確定的交給 review；
所有 index 都可重建，所有刪除都要人工確認；
先求穩定，再談效率。
```

---

## 1. 系統分階段，不混在一起

當前流程分成：

```text
階段 1：LINE RPA 下載
階段 2：OCR / 分類
階段 3：review 人工確認
階段 4：Logo 拼接
階段 5：index / sync
階段 6：跨群組去重
階段 7：最終查詢 / 確認 / 發送
```

設計依據：

```text
容易壞的事情獨立跑
耗資源的事情獨立跑
需要人工判斷的事情獨立跑
會寫資料庫/共用檔案的事情獨立控管
```

不要把 RPA、OCR、資料庫、人工確認、發送全部塞在同一個黑盒流程裡。

---

## 2. RPA 只負責下載

RPA 最脆弱，因為它依賴：

```text
LINE 視窗
滑鼠位置
座標
登入狀態
螢幕解析度
等待時間
```

所以 RPA 只負責：

```text
打開 LINE
搜尋群組
進入照片/影片頁
下載圖片
遇到已下載過的舊圖時停止
```

RPA 不負責：

```text
OCR
分類
Logo 拼接
跨群組去重
發送圖片
刪除候選資料
```

方法論：

```text
UI automation 只負責把資料抓回來，不負責理解資料。
```

---

## 3. 先下載完所有群組，再做後處理

目前多群組流程：

```text
階段 1：先下載完所有群組
群組 A 下載
群組 B 下載
群組 C 下載
...

階段 2：再逐群組 pipeline
群組 A OCR / 分類 / Logo / index / sync
群組 B OCR / 分類 / Logo / index / sync
群組 C OCR / 分類 / Logo / index / sync
...
```

這比「下載一群 → OCR 一群 → 再下載下一群」更穩。

原因：

```text
LINE 操作不中斷
RPA 更穩定
OCR 慢不影響下載流程
問題更容易定位
執行成本更可控
```

方法論：

```text
先完成外部不穩定任務，再處理內部可控任務。
```

---

## 4. 目前不做平行化

20 個群組也暫時不平行。

原因：

```text
LINE RPA 只能控制一個視窗
PaddleOCR 吃 CPU/RAM
image_index.json 是共用檔案
travel_index.db 是共用資料庫
平行 log 會交錯，debug 變困難
流程還在穩定期
```

方法論：

```text
系統沒穩之前，不要為了速度犧牲可控性。
```

未來若要安全平行化，必須先有：

```text
任務佇列
檔案鎖
DB 鎖
retry
超時控制
狀態紀錄
可追蹤 log
```

且可平行的應該只限於：

```text
OCR 讀取
pHash 計算
圖片分析
```

不可隨便平行：

```text
搬檔
刪檔
寫 image_index.json
寫 travel_index.db
final reindex
```

---

## 5. 資料夾代表狀態

資料夾語意：

```text
line-rpa/download/<group>/          原始下載暫存
line-rpa/download/<group>/travel/   已確認旅遊圖
line-rpa/download/<group>/other/    非旅遊圖
line-rpa/download/<group>/review/   需要人工確認
line-rpa/download/<group>/branded/  加 Logo 後成品
```

方法論：

```text
資料夾不是只是放檔案，而是代表資料狀態。
```

規則：

```text
travel/  可進入 Logo 拼接與查詢索引
other/   不參與旅遊發送
review/  不可自動發送，必須人工確認
branded/ 衍生圖，不是原始下載圖
```

---

## 6. 原始資料與衍生資料分開

原始圖與衍生圖不可混用。

`image_index.json` 只追蹤原始下載圖片：

```text
掃描 travel/
掃描 other/
掃描 review/
不掃 branded/
```

原因：

```text
branded/ 是加 Logo 後的衍生圖
不能拿來判斷 LINE 原圖是否已下載
```

方法論：

```text
原始資料、處理結果、衍生輸出，要分層保存。
```

---

## 7. image_index.json 是可同步的下載歷史

`line-rpa/download/image_index.json` 是中央下載歷史索引，按群組分開記錄 sha256：

```json
{
  "群組A": ["sha256..."],
  "群組B": ["sha256..."]
}
```

用途：

```text
每張下載後計算 sha256
比對該群組已下載 hash
遇到第一張已下載過的舊圖就停止該群組下載
```

pipeline 結束後要 sync：

```text
掃描 travel/ other/ review/
重新計算現存圖片 sha256
更新 image_index.json 該群組紀錄
```

方法論：

```text
任何 index 都可能失真，所以要有重建/同步機制。
```

---

## 8. review 是安全閥

分類結果分三種：

```text
travel = 明確旅遊圖
other  = 明確非旅遊圖
review = 不確定，需要人工確認
```

review 流程：

```text
pipeline JSON 輸出 review_images
OpenClaw 將 review 圖片給使用者確認
使用者判斷 travel / other
```

確認後：

```text
如果 travel：
review/ → travel/
自動 Logo 拼接
自動 reindex
自動 sync image_index.json

如果 other：
review/ → other/
自動 sync image_index.json
```

方法論：

```text
不確定的資料不要硬判斷，要進 review。
```

---

## 9. review 完成後才做跨群組去重

跨群組去重觸發條件：

```text
所有群組下載完成
所有成功群組 pipeline 完成
review_images 為空，或 review 已全部確認完成
```

然後才執行：

```text
彙總 branded/
pHash 視覺相似檢查
讀既有 OCR sidecar / travel_index.db
文案相似度 / 商品重複檢查
產生 duplicate candidates
使用者確認保留/移除
final reindex travel_index.db
```

原因：

```text
review 中可能有應該進 travel/branded 的圖片
如果太早做跨群組去重，會漏掉這些圖片
```

方法論：

```text
下游彙總任務，要等上游狀態收斂後再執行。
```

---

## 10. 跨群組去重不重複 OCR

單群組 pipeline 已經做過 OCR 並寫入 sidecar JSON：

```text
xxx.jpg.json
ocr.text
ocr.classification
ocr.reason
ocr.hits
```

跨群組去重階段不應重新 OCR。

資料來源優先：

```text
1. travel_index.db
2. travel/*.jpg.json / branded sidecar
```

方法論：

```text
已經算過的昂貴結果要重用，不要重複計算。
```

---

## 11. duplicate 不自動刪

跨群組去重只產生候選：

```text
duplicate candidates
```

不自動刪除。

使用者確認後才：

```text
標記移除
移到 duplicate/
或排除於 final index
```

建議優先「標記/排除」而不是直接刪檔。

方法論：

```text
高風險決策只做輔助判斷，不做自動破壞。
```

---

## 12. travel_index.db 是可重建查詢索引

`travel_index.db` 保存目前可查詢、可使用的 branded 結果。

初版：

```text
所有 branded 結果
```

去重確認後：

```text
final reindex
→ 最終可用 branded 結果
```

`travel_index.db` 不應是唯一狀態來源。

流程狀態來源應包括：

```text
資料夾位置
sidecar JSON
image_index.json
duplicate review 記錄
```

方法論：

```text
查詢索引應該可重建，不應該承擔所有流程狀態。
```

---

## 13. 模組邊界

目前模組責任：

```text
line-rpa/line_image_downloader.py
只管 LINE 下載

filter/filter.py
只管 OCR 分類

tools/branding/brand_stitcher.py
只管 Logo 拼接

tools/indexing/reindex.py
只管建立 travel_index.db

tools/pipeline/process_downloads.py
只管串接固定流程

review handler
只管人工確認後的搬移與後續觸發

duplicate handler
只管跨群組重複候選與確認
```

方法論：

```text
一個模組只負責一種責任。
模組之間用檔案、JSON、DB 傳狀態，不要互相偷做對方的事。
```

---

## 14. 每個步驟都要可驗證

工程化不是相信流程，而是讓流程可驗證。

每個步驟應該能回答：

```text
跑了嗎？
跑哪個群組？
成功幾張？
失敗幾張？
review 幾張？
index 是否更新？
是否可以重跑？
```

可驗證方式：

```text
py_compile
unit tests
dry-run
log
pipeline JSON
status command
```

---

## 15. 重構判斷準則

重構任何系統前，先問：

```text
1. 這是外部不穩定操作，還是內部可控處理？
2. 它應該同步跑，還是等上一步完成？
3. 它會不會寫共用資料？
4. 如果中斷，可以從哪裡恢復？
5. 它的輸入/輸出是否明確？
6. 它的結果能不能重建？
7. 它失敗時會不會影響其他模組？
8. 有沒有需要人工確認的灰色區？
9. 有沒有不該自動刪除的資料？
10. 是否有 log / JSON / DB 可以追蹤？
```

如果答案不清楚，代表還不適合自動化。

---

## Current Execution Policy

目前專案執行政策：

```text
不平行
先下載完所有群組
再逐群組 pipeline
review 未完成前不做跨群組去重
跨群組去重不重複 OCR
duplicate 不自動刪
travel_index.db 最後可重建
優先使用既有腳本，不開 ad-hoc 流程
```
