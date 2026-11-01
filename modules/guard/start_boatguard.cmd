@echo off
rem Starts BoatGuard hidden-friendly from its own folder.
cd /d "%~dp0"
".venv\Scripts\python.exe" boatguard.py run
