@echo off
setlocal
title Trust Mastervolt Local HTTPS
cd /d "%~dp0"

if not exist "%~dp0certs\Mastervolt-Local-CA.cer" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_local_https.ps1"
  if errorlevel 1 (
    echo Certificate setup failed.
    pause
    exit /b 1
  )
)

certutil.exe -user -addstore -f Root "%~dp0certs\Mastervolt-Local-CA.cer"
if errorlevel 1 (
  echo The certificate could not be trusted for this Windows user.
  pause
  exit /b 1
)

set /p MASTERVOLT_BIND=<"%~dp0certs\bind-address.txt"
echo.
echo Mastervolt Local CA is now trusted for this Windows browser account.
echo Opening https://%MASTERVOLT_BIND%:8000
start "" "https://%MASTERVOLT_BIND%:8000"
timeout /t 4 >nul
