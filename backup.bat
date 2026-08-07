@echo off
REM Scheduled database backup - see BACKUP.md for Task Scheduler setup.
cd /d "%~dp0"
set FLASK_APP=run.py
venv\Scripts\python.exe -m flask backup --keep 30
