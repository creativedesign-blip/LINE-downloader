$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root
chcp 65001 | Out-Null

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Build LINE-downloader.zip (no-exe delivery)" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

$stage = Join-Path $env:TEMP "ldl-zip-stage-$(Get-Random)"
New-Item -ItemType Directory -Path $stage | Out-Null
$projectDirName = 'line-downloader'
$projectDir = Join-Path $stage $projectDirName
New-Item -ItemType Directory -Path $projectDir | Out-Null

Write-Host "[1/4] staging project files"
# Legacy Chinese data-dir names (旅遊相關 / 非旅遊 / 錯誤) — use codepoints so file stays ASCII
$legacyTravel = [string]::new([char[]](0x65c5,0x904a,0x76f8,0x95dc))
$legacyOther  = [string]::new([char[]](0x975e,0x65c5,0x904a))
$legacyError  = [string]::new([char[]](0x932f,0x8aa4))
$robocopyArgs = @(
  $root, $projectDir, '/E',
  '/XD', 'node_modules', 'downloads', '.claude', '__pycache__', 'state', '.git',
         $legacyTravel, $legacyOther, $legacyError,
  '/XF', '*.exe', '*.zip', '*.bak', '*.db', 'build-zip.ps1',
  '/NFL', '/NDL', '/NJH', '/NJS', '/NP'
)
& robocopy @robocopyArgs | Out-Null
if ($LASTEXITCODE -gt 7) { throw "robocopy failed: $LASTEXITCODE" }

# Reset config/targets.json
$cfgDir = Join-Path $projectDir 'config'
if (Test-Path $cfgDir) {
  $targetsJson = Join-Path $cfgDir 'targets.json'
  [IO.File]::WriteAllText($targetsJson, '{"targets": []}', [Text.UTF8Encoding]::new($false))
  $stateDir = Join-Path $cfgDir 'state'
  if (Test-Path $stateDir) { Remove-Item $stateDir -Recurse -Force }
}

Write-Host "[2/4] writing start.bat (entry point for recipient)"
$startBatPath = Join-Path $projectDir 'start.bat'
$startBatContent = @'
@echo off
chcp 65001 >nul
title LINE 下載器
cd /d "%~dp0"

echo ================================================
echo   LINE 下載器 啟動中...
echo ================================================
echo 目前資料夾: %CD%
echo.

REM ---- detect if run from zip preview ----
if not exist "%~dp0_legacy\app.js" (
  echo [ERROR] 抓不到 _legacy\app.js
  echo.
  echo 你可能從 zip 內直接執行 start.bat。
  echo 請先把 zip 解壓到資料夾，再進 line官方-download 雙擊 start.bat。
  echo.
  pause
  exit /b 1
)

REM ---- detect deps ----
set "MISSING="
where node >nul 2>nul
if errorlevel 1 set "MISSING=%MISSING% Node.js"

set "CHROME_FOUND="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if not defined CHROME_FOUND set "MISSING=%MISSING% Chrome"

set "CONDA_BAT=%UserProfile%\miniconda3\Scripts\activate.bat"
if not exist "%CONDA_BAT%" set "CONDA_BAT=%UserProfile%\anaconda3\Scripts\activate.bat"
if not exist "%CONDA_BAT%" set "MISSING=%MISSING% Miniconda"

if not "%MISSING%"=="" (
  echo ================================================
  echo   首次安裝：缺少系統軟體 [%MISSING%]
  echo ================================================
  echo.
  where winget >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] 找不到 winget（Windows Package Manager）。
    echo 請從 Microsoft Store 安裝「App Installer」，或手動下載：
    echo   Node.js LTS: https://nodejs.org
    echo   Chrome:      https://google.com/chrome
    echo   Miniconda:   https://docs.anaconda.com/miniconda
    echo.
    pause
    exit /b 1
  )
  where node >nul 2>nul || winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
  if not defined CHROME_FOUND winget install --id Google.Chrome -e --accept-package-agreements --accept-source-agreements
  if not exist "%CONDA_BAT%" winget install --id Anaconda.Miniconda3 -e --accept-package-agreements --accept-source-agreements
  echo.
  echo ================================================
  echo   系統軟體裝好了。PATH 需要重新整理。
  echo.
  echo   下一步：關掉本視窗 → 再雙擊一次 start.bat
  echo ================================================
  echo.
  pause
  exit /b 0
)

REM ---- npm install ----
if not exist "%~dp0_legacy\node_modules\playwright" (
  echo [安裝] Node 套件（playwright 等）...
  pushd "%~dp0_legacy"
  call npm install
  set "NPM_ERR=%errorlevel%"
  popd
  if not "%NPM_ERR%"=="0" (
    echo [ERROR] npm install 失敗，錯誤代碼 %NPM_ERR%
    pause
    exit /b 1
  )
)

REM ---- paddleocr env ----
set "PADDLE_OK="
call "%CONDA_BAT%" paddleocr 2>nul
if not errorlevel 1 (
  python -c "from paddleocr import PaddleOCR" 2>nul
  if not errorlevel 1 set "PADDLE_OK=1"
)

if not defined PADDLE_OK (
  echo.
  echo [安裝] paddleocr env（首次約 5-10 分鐘）...
  call "%~dp0filter\install.bat"
)

REM ---- launch UI ----
echo.
echo ================================================
echo   啟動 UI server
echo ================================================
call "%~dp0launch-ui.bat"

echo.
echo [注意] UI 已關閉。按任意鍵離開。
pause
'@
# Windows cmd 需要 CRLF line endings；PowerShell here-string 是 LF → 轉一下避免瞬間閃退
$crlfContent = $startBatContent -replace "`r?`n", "`r`n"
[IO.File]::WriteAllText($startBatPath, $crlfContent, [Text.UTF8Encoding]::new($false))

Write-Host "[3/4] compressing to LINE-downloader.zip"
$zipOut = Join-Path $root 'LINE-downloader.zip'
if (Test-Path $zipOut) { Remove-Item $zipOut -Force }
Compress-Archive -Path $projectDir -DestinationPath $zipOut -CompressionLevel Optimal

Remove-Item $stage -Recurse -Force

$zipKB = [Math]::Round((Get-Item $zipOut).Length / 1024, 1)
Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host ("  done: " + $zipOut) -ForegroundColor Green
Write-Host ("  size: " + $zipKB + " KB") -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "發佈：把 LINE-downloader.zip 傳給對方"
Write-Host "對方：解壓 → 進 $projectDirName 資料夾 → 雙擊 start.bat"
Write-Host "首次執行會自動裝 Node/Chrome/Miniconda + paddleocr（bat 檔不會被 AV 擋）"
