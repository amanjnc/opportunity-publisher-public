@echo off
cd /d "%~dp0"
echo Repairing unapproved drafts only. No posts will be published.
echo Existing review text and custom captions will be regenerated. A database backup is made first.
echo Stop the dashboard and worker before running this command.
".venv\Scripts\python.exe" repair_drafts.py
if errorlevel 1 echo ERROR: Repair did not finish. Keep the error output.
pause
