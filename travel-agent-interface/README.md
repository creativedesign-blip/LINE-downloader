# Travel Agent Interface

這個資料夾提供大都會旅遊的對外聊天介面。前端使用
`travel-agent-interface.jsx`，後端由 `openclaw_web.py` 轉接 Agent
旅遊索引資料。

## 啟動方式

在同一台電腦本機或同網路使用：

```powershell
cd C:\Users\user\Desktop\LINE-downloader-main\travel-agent-interface
.\start-public.ps1
```

對外網使用 Cloudflare Tunnel：

```powershell
cd C:\Users\user\Desktop\LINE-downloader-main\travel-agent-interface
.\start-internet.ps1
```

啟動後終端機會顯示 `https://...trycloudflare.com`，把那個網址給外部使用者即可。
Quick Tunnel 的網址不是永久網址；重新啟動 tunnel 可能會換網址。

## 前端 Build

修改 `travel-agent-interface.jsx` 後需要重新打包：

```powershell
npm run build
```

`openclaw_web.py` 會優先服務 `dist/index.html`。若 `dist` 不存在，啟動腳本會自動 build。

## Agent API

- `GET /api/openclaw/status`
- `GET /api/openclaw/latest?limit=12`
- `GET /api/openclaw/search?q=泰國 曼谷 5月`
- `GET /api/openclaw/duplicates`
- `POST /api/openclaw/chat`
- `POST /api/openclaw/run`
- `GET /media?path=<project-relative-image-path>`

`POST /api/openclaw/run` 會啟動手動抓取、OCR、組圖、索引流程。
最近一次 job 狀態會寫到 `logs/openclaw/latest_job.json`，並由
`GET /api/openclaw/status` 回傳 `latest_job`。

## 注意

- 查不到資料時，聊天框會回答沒有找到，不再回傳假推薦。
- 圖片預覽在原頁面 Modal 開啟，不會開新分頁。
- Cloudflare 使用 `127.0.0.1`，避免 Windows `localhost` 解析到 IPv6 `::1`。
