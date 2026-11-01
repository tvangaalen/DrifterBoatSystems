@echo off
rem Allows the BoatGuard web page (TCP 8095) from the boat's own network only (Private profile, local subnet).
rem Right-click -> Run as administrator.
net session >nul 2>&1
if errorlevel 1 (
  echo Run this file as administrator: right-click, Run as administrator.
  pause
  exit /b 1
)
powershell.exe -NoProfile -Command "Get-NetFirewallRule -DisplayName 'BoatGuard web page' -ErrorAction SilentlyContinue | Remove-NetFirewallRule; New-NetFirewallRule -DisplayName 'BoatGuard web page' -Direction Inbound -Protocol TCP -LocalPort 8095 -Profile Private -RemoteAddress LocalSubnet -Action Allow | Select-Object DisplayName, Enabled, Profile, Action"
pause
