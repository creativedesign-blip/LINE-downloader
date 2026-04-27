@echo off
chcp 65001 >nul
title 打包 LINE-downloader.zip
setlocal
cd /d "%~dp0"

echo ================================================
echo   打包 LINE-downloader.zip（無 exe、不會被誤判）
echo ================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-zip.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] 打包失敗
  pause
  exit /b 1
)

echo.
echo ================================================
echo   發佈步驟：
echo     1. 把 LINE-downloader.zip 傳給對方
echo     2. 對方解壓縮 → 進 line官方-download 資料夾
echo     3. 雙擊「開始.bat」
echo        首次會自動檢查 + 裝 Node/Chrome/Miniconda/paddleocr
echo        裝完後重新執行一次即可啟動 UI
echo ================================================
pause
endlocal
