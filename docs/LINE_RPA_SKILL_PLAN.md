# LINE RPA Skill 規劃
## 目標

把目前 LINE 圖片下載 RPA 的「操作知識」整理成 OpenClaw 可重複使用的 skill，但不要把核心 RPA 邏輯搬出 repo。

Skill 的定位是：

- 指引 agent 如何安全啟動、檢查、診斷 LINE RPA。
- 提供固定的 preflight/status helper scripts，減少每次手動查狀態的成本。
- 保留 repo 內現有 RPA、pipeline、OpenClaw Web API 作為唯一執行來源。

Skill 不應該：

- 重新實作 LINE 視窗控制、圖片下載、OCR、品牌分類或索引流程。
- 保存 LINE 視窗座標的另一份副本。
- 自動刪除圖片、lock file、job 記錄或人工審核資料。

## 建議位置

本機 OpenClaw workspace-pipeline skill 目錄：

```text
~/.openclaw/workspace-pipeline/skills/line-rpa-operations/
```

建議結構：

```text
line-rpa-operations/
  SKILL.md
  scripts/
    check_rpa_env.ps1
    collect_rpa_status.ps1
    summarize_latest_job.py
```

## Repo 邊界

核心程式繼續放在目前 repo：

```text
C:\Users\user\Desktop\LINE-downloader-main\
```

Skill 只呼叫這些既有入口：

```text
tools/openclaw/run_scheduled_line_rpa.ps1
tools/openclaw/run_uploaded_images.ps1
tools/pipeline/process_downloads.py
line-rpa/line_image_downloader.py
```

這樣做的原因：

- repo 是版本控制、測試、commit、push 的主體。
- skill 是本機 agent 操作層，適合放「怎麼操作」和「怎麼檢查」。
- 避免 RPA 邏輯散落兩份，後續修改 LINE UI 座標或流程時不會不同步。

## SKILL.md 規劃

`SKILL.md` 應包含：

- `name: line-rpa-operations`
- `description` 明確觸發場景：
  - 使用者要執行 LINE RPA。
  - 使用者要查 latest job、lock、log。
  - 使用者要診斷圖片下載、上傳圖片處理、OCR、品牌分類、索引 pipeline。
  - 使用者要校準 LINE 視窗位置或座標設定。

正文只保留必要操作規則：

- 先確認 repo path。
- RPA 前先跑 `scripts/check_rpa_env.ps1`。
- 查狀態先跑 `scripts/collect_rpa_status.ps1`。
- 需要摘要 latest job 時跑 `scripts/summarize_latest_job.py`。
- 不並行跑多個 LINE RPA。
- 不直接刪除 lock，除非已確認 PID 不存在且使用者同意。
- 不直接改動或複製 LINE 座標，座標只維護在 repo 的 `line-rpa/config.json`。

## Helper Scripts 規劃

### check_rpa_env.ps1

用途：跑 RPA 前的環境檢查。

應檢查：

- repo 路徑是否存在。
- 必要入口檔是否存在：
  - `tools/openclaw/run_scheduled_line_rpa.ps1`
  - `tools/openclaw/run_uploaded_images.ps1`
  - `tools/pipeline/process_downloads.py`
  - `line-rpa/line_image_downloader.py`
- Python 是否可用：
  - RPA Python。
  - pipeline Python。
- `line-rpa/config.json` 是否可讀且 JSON 格式正確。
- `line_exe` 指向的 LINE executable 是否存在。
- Excel path、save root、logs、data 目錄是否存在。
- `OPENCLAW_WEB_USER`、`OPENCLAW_WEB_PASSWORD` 是否已設定。
- internet mode 時，Cloudflared executable 是否存在。
- `line-rpa-scheduled.lock` 是否存在，若存在檢查 PID 是否還活著。
- `latest_job.json` 是否顯示仍在 running。
- LINE 視窗相關設定是否存在：
  - `line_window`
  - `media_window`
  - `viewer_window`
  - 下載按鈕、下一張、關閉、搜尋框、媒體視窗等座標比例 key。

這個 script 只做 read-only 檢查，不啟動 LINE，不修改 config，不刪 lock。

### collect_rpa_status.ps1

用途：快速收集目前 RPA 狀態。

應輸出：

- repo path。
- `latest_job.json` 摘要。
- lock file 是否存在。
- lock PID 是否還活著。
- 最近的 OpenClaw/RPA log 檔案：
  - `line-rpa-scheduled-*.log`
  - `uploaded-images-*.log`
  - `rpa_subprocess.log`
  - `upload_subprocess.log`
  - `web.log`
- 每個 log 的修改時間、大小、最後幾行。

這個 script 也只做 read-only 收集，不自動修復。

### summarize_latest_job.py

用途：把 `logs/openclaw/latest_job.json` 轉成容易閱讀的摘要。

應輸出：

- job id。
- trigger source。
- target id / folder id。
- status。
- running。
- pid。
- started_at / finished_at。
- return code。
- last error。
- log path。
- 每個 step 的狀態：
  - RPA download。
  - upload/image processing。
  - OCR。
  - composition。
  - index。

如果 latest job 不存在或 JSON 壞掉，應清楚輸出錯誤並回傳非 0 exit code。

## LINE 視窗座標維護原則

座標唯一來源：

```text
line-rpa/config.json
```

校準說明可放：

```text
line-rpa/RPA_WINDOW_BASELINE.md
```

Skill 裡不要保存實際座標值，只保存規則：

- 開跑前檢查座標 key 是否存在。
- 檢查 ratio 值是否為 0 到 1 之間。
- 如果 LINE UI 改版或螢幕解析度變更，回 repo 修改 `line-rpa/config.json`。
- 修改座標後用 repo 的 RPA 測試或小範圍手動 run 驗證。

## 建議實作階段

### Phase 1：只建立 skill 文件與 read-only scripts

- 建立 `line-rpa-operations/SKILL.md`。
- 建立三個 helper scripts。
- scripts 只讀資料，不改 repo，不啟動 RPA，不刪檔。
- 驗證 PowerShell parse、Python parse。

### Phase 2：接入日常操作

- 用 `check_rpa_env.ps1` 作為每次手動 RPA 前置檢查。
- 用 `collect_rpa_status.ps1` 作為錯誤診斷第一步。
- 觀察實際使用時是否還常常需要手動查其他檔案。

### Phase 3：再決定是否擴充

只有在 Phase 1/2 確認穩定後，才考慮新增：

- calibration checklist reference。
- job recovery checklist reference。
- OpenClaw Web/API troubleshooting reference。

不要一開始就做太大，避免 skill 變成另一份 README 或另一套 pipeline。

## 驗收標準

第一版完成時應符合：

- skill 可放在 `~/.openclaw/workspace-pipeline/skills/line-rpa-operations/`。
- `SKILL.md` frontmatter 合法。
- 三個 scripts 都可單獨執行或 parse。
- scripts 不做 destructive action。
- repo 內 RPA/pipeline 邏輯沒有被搬移。
- LINE 座標仍只維護在 `line-rpa/config.json`。
