# External LINE RPA Flow

## Golden Path

1. User opens LINE PC on the visible Windows desktop and confirms it is logged in.
2. User starts the external interface from the same visible desktop:

   ```powershell
   cd C:\Users\user\Desktop\LINE-downloader-main\travel-agent-interface
   .\start-internet.ps1
   ```

3. `start-internet.ps1` stops any existing server on port `4173`.
4. It opens a visible PowerShell window running:

   ```powershell
   python .\openclaw_web.py 4173
   ```

5. It starts Cloudflare Tunnel for:

   ```text
   https://travel.quick-buyer.com/
   ```

6. The external UI sends:

   ```text
   POST /api/openclaw/run
   ```

7. `openclaw_web.py` starts:

   ```powershell
   tools\openclaw\run_scheduled_line_rpa.ps1 -TriggerSource manual
   ```

8. The pipeline runs in order:

   ```text
   LINE RPA download -> OCR sync -> compose sync -> index sync
   ```

## Important Rules

- The web server PID on port `4173` is the external service PID.
- The manual run PID shown in the UI is a short-lived worker PID, not the external service.
- Do not run `openclaw_web.py` as a hidden/background process for GUI RPA. It may serve HTTP but fail to see desktop windows.
- If LINE is not visible or logged in, RPA must fail the job instead of continuing to OCR/compose/index.

## Quick Checks

```powershell
netstat -ano | Select-String ':4173'
Get-Content logs\openclaw\latest_job.json
```

The latest job should only report success when every step succeeds.
