@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo You need to run setup_windows.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" setup_telegram.py
pause
