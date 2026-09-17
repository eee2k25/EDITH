@echo off
title EDITH / JARVIS setup
cd /d "%~dp0"

echo.
echo  === EDITH setup ===
echo  Folder: %cd%
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python is not installed or not on PATH.
  echo Install from https://www.python.org/downloads/
  echo Tick "Add python.exe to PATH", then run this setup again.
  pause
  exit /b 1
)

echo [1/3] Installing Python packages...
python -m pip install --upgrade pip
if exist requirements.txt (
  python -m pip install -r requirements.txt
) else (
  python -m pip install python-dotenv requests
)

echo [2/3] Creating .env if missing...
if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
  ) else (
    (
      echo JARVIS_LLM_BASE_URL=https://openrouter.ai/api/v1
      echo JARVIS_LLM_API_KEY=
      echo JARVIS_HEADLESS=false
    ) > ".env"
  )
  echo Created .env — you MUST paste your OpenRouter key in it.
) else (
  echo .env already exists — not overwritten.
)

echo [3/3] Opening .env in Notepad...
echo.
echo  Get a free key: https://openrouter.ai/keys
echo  Put it on the JARVIS_LLM_API_KEY= line, save, close Notepad.
echo.
notepad .env

echo.
echo  Setup done. Start with launch_jarvis.bat or:
echo    python chat.py
echo.
pause
