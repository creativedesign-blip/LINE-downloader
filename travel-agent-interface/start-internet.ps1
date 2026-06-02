param(
  [int]$Port = 4173
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"

function Test-AuthEnvValue {
  param(
    [string]$Name,
    [string]$DefaultValue = ""
  )
  $value = [Environment]::GetEnvironmentVariable($Name, "Process")
  if (-not $value) {
    $value = [Environment]::GetEnvironmentVariable($Name, "User")
  }
  if (-not $value) {
    $value = [Environment]::GetEnvironmentVariable($Name, "Machine")
  }
  return ($value -and $value -ne $DefaultValue)
}

if (-not (Test-AuthEnvValue "OPENCLAW_WEB_USER" "admin_dadova") -or
    -not (Test-AuthEnvValue "OPENCLAW_WEB_PASSWORD" "StarBit123") -or
    -not (Test-AuthEnvValue "OPENCLAW_WEB_AUTH_SECRET")) {
  throw @"
Internet mode requires custom authentication settings before starting Cloudflare Tunnel.

Set these environment variables, then reopen PowerShell:
  OPENCLAW_WEB_USER
  OPENCLAW_WEB_PASSWORD
  OPENCLAW_WEB_AUTH_SECRET

Do not use the built-in default username or password for internet access.
"@
}

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

& $Cloudflared tunnel run travel
