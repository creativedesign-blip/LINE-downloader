@echo off
chcp 65001 >nul
title PaddleOCR Setup
cd /d "%~dp0"
set "CONDA_NO_PLUGINS=true"

echo ================================
echo   PaddleOCR Setup (first time only)
echo ================================
echo.
echo This will create a dedicated conda env "paddleocr" with Python 3.11
echo and install paddlepaddle + paddleocr (about 500MB, 5-10 min).
echo.
pause

REM -------- find miniconda --------
set "CONDA_BAT=%UserProfile%\miniconda3\Scripts\activate.bat"
if not exist "%CONDA_BAT%" set "CONDA_BAT=%UserProfile%\anaconda3\Scripts\activate.bat"
if not exist "%CONDA_BAT%" (
  echo [ERROR] miniconda / anaconda not found under %UserProfile%\miniconda3 or anaconda3
  echo Please install miniconda first: https://docs.anaconda.com/miniconda/
  pause
  exit /b 1
)
echo [OK] conda: %CONDA_BAT%
echo.

REM -------- create env if missing --------
call "%CONDA_BAT%"
conda env list | findstr /I "paddleocr" >nul
if errorlevel 1 (
  echo Creating conda env paddleocr with Python 3.11...
  call conda create -n paddleocr python=3.11 -y
  if errorlevel 1 (
    echo [ERROR] conda create failed
    pause
    exit /b 1
  )
) else (
  echo [OK] conda env paddleocr already exists
)

REM -------- activate + install --------
call conda activate paddleocr
echo.
echo Upgrading pip...
python -m pip install --upgrade pip --quiet

echo Installing paddlepaddle...
python -m pip install paddlepaddle
if errorlevel 1 (
  echo [ERROR] paddlepaddle install failed
  pause
  exit /b 1
)

echo Installing paddleocr...
python -m pip install paddleocr
if errorlevel 1 (
  echo [ERROR] paddleocr install failed
  pause
  exit /b 1
)

echo.
echo Verifying...
python -c "from paddleocr import PaddleOCR; print('PaddleOCR ready')"
if errorlevel 1 (
  echo [ERROR] import failed
  pause
  exit /b 1
)

echo.
echo ================================
echo   Setup complete! You can close this window.
echo ================================
pause
