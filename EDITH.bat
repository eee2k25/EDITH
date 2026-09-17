@echo off
title EDITH / JARVIS
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python is not installed or not on PATH.
  echo  Install: https://www.python.org/downloads/
  echo  IMPORTANT: tick "Add python.exe to PATH"
  echo  Then run EDITH.bat again.
  echo.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)

python -m pip install -q python-dotenv requests
python start_edith.py
if errorlevel 1 pause