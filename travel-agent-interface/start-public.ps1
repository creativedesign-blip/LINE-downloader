param(
  [int]$Port = 4173
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

$ip = $null
try {
  $ip = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.IPAddress -notlike "169.254.*" -and
      $_.PrefixOrigin -ne "WellKnown"
    } |
    Select-Object -First 1 -ExpandProperty IPAddress
} catch {
  $ip = (ipconfig |
    Select-String -Pattern "IPv4" |
    ForEach-Object { ($_ -split ":\s*", 2)[1].Trim() } |
    Where-Object { $_ -and $_ -notlike "127.*" -and $_ -notlike "169.254.*" } |
    Select-Object -First 1)
}

if (-not $ip) {
  $ip = "YOUR-LAN-IP"
}

if (-not (Test-Path (Join-Path $Root "dist\index.html"))) {
  Write-Host "dist not found; building React interface..." -ForegroundColor Yellow
  Push-Location $Root
  npm run build
  Pop-Location
}

Write-Host ""
Write-Host "Travel Agent Interface is starting..." -ForegroundColor Green
Write-Host "Local: http://127.0.0.1:$Port/"
Write-Host "LAN:   http://$ip`:$Port/"
Write-Host ""
Write-Host "For internet access, expose this port with Cloudflare Tunnel, ngrok, or router port forwarding."
Write-Host "Press Ctrl+C to stop."
Write-Host ""

Set-Location $Root
python .\openclaw_web.py $Port
