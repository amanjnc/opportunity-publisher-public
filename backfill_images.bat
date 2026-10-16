@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Please run setup_windows.bat in your main project first.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" backfill_images.py
pause
