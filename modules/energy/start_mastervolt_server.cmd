@echo off
setlocal
title Mastervolt HTTPS Web Server
cd /d "%~dp0"

echo Preparing local HTTPS certificates...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_local_https.ps1"
if errorlevel 1 (
  echo HTTPS certificate setup failed.
  pause
  exit /b 1
)

echo.
py -c "import bleak" >nul 2>nul
if errorlevel 1 (
  echo Installing the DALY Bluetooth component for the current Windows user...
  py -m pip install --user "bleak>=2.0,<4"
  if errorlevel 1 echo WARNING: BLE component installation failed. The Mastervolt dashboard will still start, but the BMS page will report Bluetooth unavailable.
)

echo Starting Mastervolt HTTPS web server...
set /p MASTERVOLT_BIND=<"%~dp0certs\bind-address.txt"
echo Private network address: https://%MASTERVOLT_BIND%:8000
echo The application binds only to this private-LAN address, never to a public interface.
echo.
echo Press Ctrl+C to stop the server.
echo.

py -m uvicorn app:app --host %MASTERVOLT_BIND% --port 8000 --ssl-keyfile "%~dp0certs\server-key.pem" --ssl-certfile "%~dp0certs\server-cert.pem" --timeout-graceful-shutdown 5

echo.
echo Web server stopped.
pause
