<#
  Start Drifter Boat Systems when the PC boots, before anybody logs on, and keep it running after logging off.

  Run once from an ELEVATED PowerShell (right-click PowerShell, Run as administrator), from C:\Drifter:

      powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_autostart.ps1           check, then install (asks for your Windows password)
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_autostart.ps1 -Status   show the tasks and what runs where
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_autostart.ps1 -Remove   back to starting at log-on

  What it does
  1. Asks for the Windows password of this account (Task Scheduler needs it for a task that runs while nobody is logged
     on; it is handed to Task Scheduler, which keeps it protected, and is not saved anywhere else) and checks it.
  2. Runs tools\session0_check.py once in that session (a temporary task): can it see the MasterBus USB Link and
     Bluetooth, and start a process the way the supervisor does? Read-only: it opens no device. If something fails,
     nothing is changed.
  3. Makes DrifterBoatSystems the one scheduled task: at startup (after 2 min), whether anybody is logged on or not,
     restarted within a minute if it stops, running the gateway on its own Python environment. The gateway's
     supervisor starts all four modules in that session. The old BoatGuard task is stopped and removed: the supervisor
     starts BoatGuard from then on (within a few seconds).
  4. Restarts the gateway in that session (the module servers keep running and are adopted; Float and the anchor
     watch are not paused). BoatGuard is off for a few seconds in between.
  In that session there is no desktop: no console windows (the System page shows each module's log) and no sound on
  the PC (the anchor watch's PC beep stays silent; the alarm on the iPhone/iPad and the push alerts are unchanged).
#>
param([switch]$Status, [switch]$Remove, [switch]$Force)
$ErrorActionPreference = 'Stop'
$Task = 'DrifterBoatSystems'
$Root = Split-Path -Parent $PSScriptRoot
# The environments built from uv.lock (tools\sync_envs.py) on the python.org Python 3.12, not the py launcher: the Store
# Python behind it hung at boot in session 0.
$Pyw = Join-Path $Root '.venv\Scripts\pythonw.exe'
$Py = Join-Path $Root 'modules\energy\.venv\Scripts\python.exe'     # has hidapi and bleak for the check
$User = "$env:USERDOMAIN\$env:USERNAME"

function Show-Status {
    foreach ($n in $Task, 'BoatGuard') {
        $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
        if (-not $t) { "{0,-20} {1}" -f $n, $(if ($n -eq 'BoatGuard') { 'no own task (started by Drifter)' } else { 'not installed' }); continue }
        $trig = ($t.Triggers | ForEach-Object { $_.CimClass.CimClassName -replace 'MSFT_Task|Trigger', '' }) -join ','
        "{0,-20} {1,-8} trigger {2,-8} logon {3,-11} runs as {4}" -f $n, $t.State, $trig, $t.Principal.LogonType, $t.Principal.UserId
    }
    foreach ($port in 8100, 8000, 8766, 8095, 8080) {
        $l = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($l) { $p = Get-Process -Id $l.OwningProcess -ErrorAction SilentlyContinue; "port {0,-5} listening, session {1}" -f $port, $p.SessionId }
        else { "port {0,-5} not listening" -f $port }
    }
}
if ($Status) { Show-Status; return }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Run this from an elevated PowerShell (right-click PowerShell, Run as administrator).' }
if (-not (Test-Path (Join-Path $Root 'drifter.py'))) { throw "Run it from the Drifter folder (C:\Drifter): $Root has no drifter.py." }
foreach ($p in $Pyw, $Py) { if (-not (Test-Path $p)) { throw "$p missing: build the environments first (py -3.12 tools\sync_envs.py)." } }

$action = New-ScheduledTaskAction -Execute $Pyw -Argument "`"$Root\tools\run_module.py`" gateway" -WorkingDirectory $Root
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

if ($Remove) {   # back to the old way: start at log-on, in the user's session (BoatGuard then also runs only after log-on)
    $p = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $Task -Action $action -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $User) -Principal $p -Settings $settings -Force | Out-Null
    "$Task starts at log-on again (from the next log-on). Running servers are not touched."; return
}

$cred = Get-Credential -UserName $User -Message "Windows password of $User (for the task that runs while nobody is logged on)"
if (-not $cred) { throw 'Cancelled.' }
Add-Type -AssemblyName System.DirectoryServices.AccountManagement
$ctx = New-Object System.DirectoryServices.AccountManagement.PrincipalContext('Machine')
if (-not $ctx.ValidateCredentials($env:USERNAME, $cred.GetNetworkCredential().Password)) { throw "Windows did not accept that password for $User. Nothing was changed." }

# 2. the read-only check, in the session the boot task will run in
$result = Join-Path $env:TEMP "drifter_session0_check.json"; Remove-Item $result -ErrorAction SilentlyContinue
$checkTask = 'Drifter session check (temporary)'
$checkAction = New-ScheduledTaskAction -Execute $Py -Argument "`"$Root\tools\session0_check.py`" `"$result`"" -WorkingDirectory $Root
Register-ScheduledTask -TaskName $checkTask -Action $checkAction -User $User -Password $cred.GetNetworkCredential().Password `
    -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 3)) -Force | Out-Null
try {
    Write-Host 'Checking USB, Bluetooth and starting processes in the session that runs while nobody is logged on (up to a minute)...'
    Start-ScheduledTask -TaskName $checkTask
    $deadline = (Get-Date).AddSeconds(90); while (-not (Test-Path $result) -and (Get-Date) -lt $deadline) { Start-Sleep 2 }
} finally { Unregister-ScheduledTask -TaskName $checkTask -Confirm:$false }
if (-not (Test-Path $result)) { throw 'The check did not report back within 90 s. Nothing was changed.' }
$check = Get-Content $result -Raw | ConvertFrom-Json; Remove-Item $result
$check | Format-List session, masterbus_usb, bluetooth_adapter, bluetooth_on, bluetooth_devices_heard, bluetooth_error, usb_error, process_create_session, process_create_result | Out-Host
if (-not $check.ok -and -not $Force) { throw 'The check failed (see above): MasterVolt would not reach the MasterBus USB Link or the batteries in that session. Nothing was changed. (-Force installs anyway.)' }

# 3. the boot task
# 2 min: with 30 s the py launcher hung before starting Python on 2026-11-02 (the Store Python was not ready yet; BoatGuard,
# started after 1 min, was fine), and a hung launcher keeps the task "running", so it is never restarted.
$trigger = New-ScheduledTaskTrigger -AtStartup; $trigger.Delay = 'PT2M'
# -User with -Password = "run whether the user is logged on or not" (logon type Password), not elevated
Register-ScheduledTask -TaskName $Task -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited `
    -User $User -Password $cred.GetNetworkCredential().Password -Force | Out-Null
"`n$Task now starts at boot, whether anybody is logged on or not."
# 4. one task: BoatGuard no longer has its own (tools/modules.py treats it as a task module only while that task exists,
# so the supervisor never starts a second copy next to it)
if (Get-ScheduledTask -TaskName 'BoatGuard' -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName 'BoatGuard' -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName 'BoatGuard' -Confirm:$false
    "The BoatGuard task is removed; Drifter's supervisor starts BoatGuard."
}
Write-Host 'Restarting the Drifter gateway in that session (the module servers keep running; BoatGuard comes back within a minute)...'
Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue; Start-Sleep 3; Start-ScheduledTask -TaskName $Task
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline -and -not (Get-NetTCPConnection -State Listen -LocalPort 8095 -ErrorAction SilentlyContinue)) { Start-Sleep 3 }
Show-Status
