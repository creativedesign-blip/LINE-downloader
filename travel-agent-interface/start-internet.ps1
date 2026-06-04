param(
  [int]$Port = 4173
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"

if (-not [Environment]::GetEnvironmentVariable("OPENCLAW_WEB_USER", "Process") -and
    -not [Environment]::GetEnvironmentVariable("OPENCLAW_WEB_USER", "User") -and
    -not [Environment]::GetEnvironmentVariable("OPENCLAW_WEB_USER", "Machine")) {
  throw "OPENCLAW_WEB_USER is not set. Set it before starting internet mode."
}
if (-not [Environment]::GetEnvironmentVariable("OPENCLAW_WEB_PASSWORD", "Process") -and
    -not [Environment]::GetEnvironmentVariable("OPENCLAW_WEB_PASSWORD", "User") -and
    -not [Environment]::GetEnvironmentVariable("OPENCLAW_WEB_PASSWORD", "Machine")) {
  throw "OPENCLAW_WEB_PASSWORD is not set. Set it before starting internet mode."
}

foreach ($name in "OPENCLAW_WEB_USER", "OPENCLAW_WEB_PASSWORD") {
  if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
    $val = [Environment]::GetEnvironmentVariable($name, "User")
    if (-not $val) { $val = [Environment]::GetEnvironmentVariable($name, "Machine") }
    [Environment]::SetEnvironmentVariable($name, $val, "Process")
  }
}

# Internet mode is served only over HTTPS via the Cloudflare tunnel, so force the
# Secure attribute on the auth-session cookie instead of trusting the (spoofable)
# X-Forwarded-Proto header. The launched server inherits this Process env var.
[Environment]::SetEnvironmentVariable("OPENCLAW_WEB_SECURE_COOKIES", "1", "Process")

if (-not (Test-Path $Cloudflared)) {
  $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
  if (-not $cmd -or -not (Test-Path $cmd.Source) -or (Get-Item $cmd.Source).Length -eq 0) {
    throw "cloudflared was not found. Install Cloudflare Tunnel or use start-public.ps1 for LAN only."
  }
  $Cloudflared = $cmd.Source
}

function Get-PortProcessId {
  $line = netstat -ano | Select-String "0.0.0.0:$Port" | Select-Object -First 1
  if (-not $line) { return $null }
  $pidText = (($line.ToString() -split "\s+") | Where-Object { $_ })[-1]
  if ($pidText -and $pidText -ne "0") { return [int]$pidText }
  return $null
}

function Test-WebServerHealthy {
  try {
    $status = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/auth/session" -TimeoutSec 3
    return $status.StatusCode -eq 200
  } catch {
    return $false
  }
}

$existingPid = Get-PortProcessId
if ($existingPid) {
  Write-Host "Stopping existing web server on port $Port (PID $existingPid) so RPA starts from this desktop session." -ForegroundColor Yellow
  Stop-Process -Id $existingPid -Force
  Start-Sleep -Seconds 1
  $existingPid = Get-PortProcessId
}

if ($existingPid) {
  throw "Port $Port is still occupied by PID $existingPid after stop attempt."
}

if (-not (Test-Path (Join-Path $Root "dist\index.html"))) {
  Write-Host "dist not found; building React interface..." -ForegroundColor Yellow
  Push-Location $Root
  npm run build
  Pop-Location
}

$serverCommand = "Set-Location -LiteralPath '$($Root.Replace("'", "''"))'; python .\openclaw_web.py $Port"
Start-Process -FilePath powershell.exe `
  -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $serverCommand) `
  -WindowStyle Normal | Out-Null

for ($i = 0; $i -lt 15; $i++) {
  Start-Sleep -Seconds 1
  if (Test-WebServerHealthy) { break }
}

if (-not (Test-WebServerHealthy)) {
  throw "openclaw_web.py did not become healthy on http://127.0.0.1:$Port/"
}

Write-Host ""
Write-Host "OpenClaw travel chat UI is running locally:" -ForegroundColor Green
Write-Host "  http://127.0.0.1:$Port/"
Write-Host ""
Write-Host "Starting Cloudflare Tunnel:"
Write-Host "  https://travel.quick-buyer.com/"
Write-Host "Keep this window open while others are using the site. Press Ctrl+C to stop the tunnel."
Write-Host ""

$TunnelLog = Join-Path $env:USERPROFILE ".cloudflared\travel-live.log"
& $Cloudflared --logfile $TunnelLog --loglevel info tunnel run travel
