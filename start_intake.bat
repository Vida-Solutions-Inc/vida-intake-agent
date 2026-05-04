@echo off
REM Intake agent runner — double-click to start the watcher.
cd /d "%~dp0"
python watcher.py
pause
