# (Re)creates the desktop icon "Drifter Boat Systems", which runs start_all.ps1: starts the scheduled tasks (Drifter,
# BoatGuard) if needed, waits for every server, shows the status and opens the app. The target is the full path of
# powershell.exe: a shortcut that only stored arguments (seen 2026-11-02 on the OneDrive desktop) did nothing when clicked.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File tools\create_shortcut.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')          # the OneDrive desktop when OneDrive backs it up
$lnk = Join-Path $desktop 'Drifter Boat Systems.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$s.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$root\start_all.ps1`""
$s.WorkingDirectory = $root
$icon = Join-Path $root 'web\icons\drifter.ico'; if (Test-Path $icon) { $s.IconLocation = "$icon,0" }
$s.Description = 'Start Drifter Boat Systems and open the app'
$s.Save()
$check = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
if (-not $check.TargetPath) { throw "The shortcut $lnk was saved without a target." }
"Desktop icon: $lnk -> $($check.TargetPath) $($check.Arguments)"
