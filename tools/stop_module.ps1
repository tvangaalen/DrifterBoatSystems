# Stops one module wherever it runs: its scheduled task (if it has one), the process listening on its port, and the
# launchers directly above that process (venv python.exe, py/pyw, the cmd of its console window, which would otherwise
# stay open at "pause"). Used by switch_module.ps1 and by the Drifter supervisor (restart from the app).
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File tools\stop_module.ps1 <module>   exit 0 = stopped, 1 = port still in use
param([Parameter(Mandatory)][string]$Module)
$ErrorActionPreference = 'Stop'
# Python: the gateway's environment (python.org 3.12, built from uv.lock by tools\sync_envs.py); py only as a fallback.
$venv = Join-Path (Split-Path -Parent $PSScriptRoot) '.venv\Scripts'
$py = if (Test-Path "$venv\python.exe") { "$venv\python.exe" } else { 'py' }
$m = (& $py (Join-Path $PSScriptRoot 'modules.py') plan | Out-String | ConvertFrom-Json).modules | Where-Object name -eq $Module
if (-not $m) { Write-Host "unknown module $Module"; exit 2 }
function Listener($port) { (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess }

if ($m.task) { Stop-ScheduledTask -TaskName $m.task -ErrorAction SilentlyContinue }
$procId = Listener $m.port
if ($procId) {
    $chain = @(); $id = $procId
    while ($id) { $pr = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
                  if (-not $pr -or ($chain.Count -and $pr.Name -notmatch '^(cmd|py|pyw|python[\d.]*|pythonw[\d.]*)\.exe$')) { break }
                  $chain += $id; $id = $pr.ParentProcessId }
    foreach ($x in $chain) { Stop-Process -Id $x -Force -ErrorAction SilentlyContinue }   # a launcher may already have exited by itself
}
$deadline = (Get-Date).AddSeconds(20); while ((Listener $m.port) -and (Get-Date) -lt $deadline) { Start-Sleep 1 }
if (Listener $m.port) { Write-Host "port $($m.port) still in use"; exit 1 }
Write-Host "stopped"; exit 0
