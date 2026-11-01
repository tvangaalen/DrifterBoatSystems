@echo off
rem Starts the Drifter Boat Systems gateway from its own folder (settings in config.json; logs in logs\drifter.log).
cd /d "%~dp0"
if not exist logs mkdir logs
py drifter.py >> logs\drifter.log 2>&1
