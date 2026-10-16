@echo off
setlocal
cd /d "%~dp0"
echo ===============================================
echo Opportunity Publisher - Python 3.15 compatible
 echo ===============================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo Creating a private Python environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo ERROR: Could not create Python environment.
    echo Check that Python is installed and run: py -3 --version
    pause
    exit /b 1
  )
)
if not exist .env copy .env.example .env >nul
if not exist data mkdir data
 echo.
echo Main application setup complete. No extra libraries required for dashboard, RSS and publishing.
echo.
echo Installing optional Telegram channel reader...
".venv\Scripts\python.exe" -m pip install "telethon>=1.36,<2"
if errorlevel 1 (
  echo.
  echo WARNING: Telegram channel reader could not be installed.
  echo Dashboard, manual import, RSS feeds, and Telegram bot publishing still work.
  echo You can retry this later: .venv\Scripts\python.exe -m pip install telethon
) else (
  echo Telegram channel reader installed successfully.
)
echo.
echo READY. To open your dashboard run: run_dashboard.bat
 echo To configure automatic posting, edit .env and config.yaml first.
pause
