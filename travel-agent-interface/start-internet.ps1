param(
  [int]$Port = 4173
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"

if (-not (Test-Path $Cloudflared)) {
  $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
  if (-not $cmd -or -not (Test-Path $cmd.Source) -or (Get-Item $cmd.Source).Length -eq 0) {
    throw "cloudflared was not found. Install Cloudflare Tunnel or use start-public.ps1 for LAN only."
  }
  $Cloudflared = $cmd.Source
}

$existing = netstat -ano | Select-String "0.0.0.0:$Port" | Select-Object -First 1
$healthy = $false
if ($existing) {
  try {
    $status = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/auth/session" -TimeoutSec 3
    $healthy = $status.StatusCode -eq 200
  } catch {
    $healthy = $false
  }
}

if ($existing -and -not $healthy) {
  $pidText = (($existing.ToString() -split "\s+") | Where-Object { $_ })[-1]
  if ($pidText -and $pidText -ne "0") {
    Stop-Process -Id ([int]$pidText) -Force
    Start-Sleep -Seconds 1
  }
}

if (-not $existing -or -not $healthy) {
  if (-not (Test-Path (Join-Path $Root "dist\index.html"))) {
    Write-Host "dist not found; building React interface..." -ForegroundColor Yellow
    Push-Location $Root
    npm run build
    Pop-Location
  }
  # Background server: route stdout/stderr to project-level logs/openclaw/
  # so the per-process log files don't pile up next to the React source.
  $LogDir = Join-Path (Split-Path -Parent $Root) "logs\openclaw"
  if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
  Start-Process -FilePath python `
    -ArgumentList @(".\openclaw_web.py", "$Port") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "openclaw_web.out.log") `
    -RedirectStandardError (Join-Path $LogDir "openclaw_web.err.log") | Out-Null
  Start-Sleep -Seconds 2
}

Write-Host ""
Write-Host "OpenClaw travel chat UI is running locally:" -ForegroundColor Green
Write-Host "  http://127.0.0.1:$Port/"
Write-Host ""
Write-Host "Starting Cloudflare Tunnel:"
Write-Host "  https://travel.quick-buyer.com/"
Write-Host "Keep this window open while others are using the site. Press Ctrl+C to stop the tunnel."
Write-Host ""

& $Cloudflared tunnel run travel
