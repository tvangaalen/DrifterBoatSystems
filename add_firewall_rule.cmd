@echo off
rem Lets the boat's own network and UniFi Teleport clients (192.168.2.x) reach Drifter, and nobody else:
rem   the app (TCP 8100), network GPS (NMEA over TCP/UDP 10110) and the YDEN-02's engine data (UDP 1456).
rem The rules hold on every network profile: after a router update or reboot Windows can take the boat's network for a
rem new one and make it Public, and a Private-only rule then blocks the iPhone (2026-11-15). The remote addresses keep
rem them closed to any other network. Run again any time (it replaces its own rules). Right-click -> Run as administrator.
net session >nul 2>&1
if errorlevel 1 (
  echo Run this file as administrator: right-click, Run as administrator.
  pause
  exit /b 1
)
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; Get-NetFirewallRule -Group 'Drifter Boat Systems' -ErrorAction SilentlyContinue | Remove-NetFirewallRule; Get-NetFirewallRule -DisplayName 'Drifter Boat Systems' -ErrorAction SilentlyContinue | Remove-NetFirewallRule; $r = 'LocalSubnet','192.168.2.0/24'; foreach ($x in @(@('Drifter app','TCP',8100), @('Drifter network GPS (TCP)','TCP',10110), @('Drifter network GPS (UDP)','UDP',10110), @('Drifter YDEN-02 engine data','UDP',1456))) { New-NetFirewallRule -Group 'Drifter Boat Systems' -DisplayName $x[0] -Direction Inbound -Protocol $x[1] -LocalPort $x[2] -Profile Any -RemoteAddress $r -Action Allow | Out-Null }; Get-NetFirewallRule -Group 'Drifter Boat Systems' | Format-Table DisplayName, Enabled, Profile, Action -AutoSize"
pause
