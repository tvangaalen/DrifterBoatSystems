@echo off
setlocal
title Mastervolt iPhone Certificate Installer
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_local_https.ps1"
if errorlevel 1 (
  echo Certificate setup failed.
  pause
  exit /b 1
)

echo.
echo On the iPhone, while connected to this local network, open:
set /p MASTERVOLT_BIND=<"%~dp0certs\bind-address.txt"
echo http://%MASTERVOLT_BIND%:8001/Mastervolt-Local-CA.cer
echo.
echo This temporary helper serves only the public CA certificate.
echo Press Ctrl+C immediately after the iPhone has downloaded it.
echo.
py -m http.server 8001 --bind %MASTERVOLT_BIND% --directory "%~dp0certs"
