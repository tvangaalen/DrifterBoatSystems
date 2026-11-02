@echo off
rem Starts the Orca Core live reader (read-only) and opens its page on this PC. Extra arguments are passed on
rem (e.g. run.cmd --record). Uses the anchor watch's environment, built by tools\sync_envs.py of the repository.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo No .venv here: run  py -3.12 tools\sync_envs.py  in the repository first.
  exit /b 1
)
start "" http://localhost:8765/
".venv\Scripts\python.exe" orca_reader.py %*
