@echo off
chcp 65001 >nul
setlocal

set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if "%LINE_CDP_PORT%"=="" set "LINE_CDP_PORT=9333"
if "%LINE_CDP_PROFILE%"=="" set "LINE_CDP_PROFILE=%LocalAppData%\line-official-download-cdp-profile"

if not exist "%CHROME_EXE%" (
  echo [ERROR] Chrome not found.
  echo Start Chrome manually with:
  echo chrome.exe --remote-debugging-port=9333 --user-data-dir^="%LocalAppData%\line-official-download-cdp-profile^" https://line.me/R/
  pause
  exit /b 1
)

if not exist "%LINE_CDP_PROFILE%" mkdir "%LINE_CDP_PROFILE%" >nul 2>nul

echo ================================================
echo   LINE automation Chrome
echo ================================================
echo Chrome : %CHROME_EXE%
echo Port   : %LINE_CDP_PORT%
echo Profile: %LINE_CDP_PROFILE%
echo.
echo This uses a dedicated Chrome profile for automation.
echo Keep this Chrome window open while running the downloader.
echo.

start "" "%CHROME_EXE%" ^
  --remote-debugging-port=%LINE_CDP_PORT% ^
  --user-data-dir="%LINE_CDP_PROFILE%" ^
  --new-window ^
  https://line.me/R/

echo Chrome launch requested.
echo DevTools endpoint:
echo   http://127.0.0.1:%LINE_CDP_PORT%/json/version
echo.
endlocal
