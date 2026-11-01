@echo off
rem Allows the Drifter page (TCP 8100) from the boat's own network and from UniFi Teleport clients (192.168.2.x) only,
rem on the Private profile. Right-click -> Run as administrator.
net session >nul 2>&1
if errorlevel 1 (
  echo Run this file as administrator: right-click, Run as administrator.
  pause
  exit /b 1
)
powershell.exe -NoProfile -Command "Get-NetFirewallRule -DisplayName 'Drifter Boat Systems' -ErrorAction SilentlyContinue | Remove-NetFirewallRule; New-NetFirewallRule -DisplayName 'Drifter Boat Systems' -Direction Inbound -Protocol TCP -LocalPort 8100 -Profile Private -RemoteAddress LocalSubnet,192.168.2.0/24 -Action Allow | Select-Object DisplayName, Enabled, Profile, Action"
pause
