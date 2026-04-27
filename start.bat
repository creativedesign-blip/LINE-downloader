@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title LINE Downloader
cd /d "%~dp0"
set "CONDA_NO_PLUGINS=true"

echo ================================================
echo   LINE downloader starting...
echo ================================================
echo Working directory: %CD%
echo.

REM ---- detect if run from zip preview ----
if not exist "%~dp0_legacy\app.js" (
  echo [ERROR] Missing _legacy\app.js
  echo.
  echo Please extract the zip file first, then run start.bat
  echo from the extracted LINE-downloader folder.
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
  echo   Missing required tools: [%MISSING%]
  echo ================================================
  echo.
  where winget >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] winget was not found.
    echo Install the missing tools manually:
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
  echo   Installation finished.
  echo.
  echo   Close this window and run start.bat again so PATH updates apply.
  echo ================================================
  echo.
  pause
  exit /b 0
)

REM ---- npm install ----
if not exist "%~dp0_legacy\node_modules\playwright-core" (
  echo [Setup] Installing Node dependencies...
  pushd "%~dp0_legacy"
  set "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1"
  call npm install
  set "NPM_ERR=!errorlevel!"
  popd
  if not "!NPM_ERR!"=="0" (
    echo [ERROR] npm install failed with exit code !NPM_ERR!
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
  echo [Setup] PaddleOCR env is missing. First-time setup can take 5-10 minutes.
  call "%~dp0filter\install.bat"
)

REM ---- launch UI ----
echo.
echo ================================================
echo   Starting UI server
echo ================================================
call "%~dp0launch-ui.bat"

echo.
echo UI closed. Press any key to exit.
pause
