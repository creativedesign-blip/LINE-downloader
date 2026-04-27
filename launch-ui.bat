@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "CONDA_NO_PLUGINS=true"

if not defined LINE_CDP_PORT set "LINE_CDP_PORT=9333"
if not defined LINE_UI_PORT set "LINE_UI_PORT=8787"

echo ================================================
echo   LINE group manager UI
echo ================================================
echo UI  : http://127.0.0.1:%LINE_UI_PORT%
echo CDP : http://127.0.0.1:%LINE_CDP_PORT%
echo.

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] node not found.
  pause
  exit /b 1
)

set "CONDA_BAT=%UserProfile%\miniconda3\Scripts\activate.bat"
if not exist "%CONDA_BAT%" set "CONDA_BAT=%UserProfile%\anaconda3\Scripts\activate.bat"
if exist "%CONDA_BAT%" (
  call "%CONDA_BAT%" paddleocr 2>nul
)

set PYTHONIOENCODING=utf-8
node app.js ui --port "%LINE_UI_PORT%"

echo.
echo UI stopped.
pause
endlocal
