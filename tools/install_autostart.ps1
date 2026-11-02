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
  3. Changes the scheduled task DrifterBoatSystems: at startup (after 30 s), whether anybody is logged on or not,
     restarted within a minute if it stops. The gateway's supervisor then starts MasterVolt, the anchor watch and the
     washer controller in that same session; BoatGuard has its own boot task already.
  Nothing is restarted now: the running servers carry on, and the new way applies from the next boot (or -Now).
  In that session there is no desktop: no console windows (the System page shows each module's log) and no sound on
  the PC (the anchor watch's PC beep stays silent; the alarm on the iPhone/iPad and the push alerts are unchanged).
#>
param([switch]$Status, [switch]$Remove, [switch]$Now, [switch]$Force)
$ErrorActionPreference = 'Stop'
$Task = 'DrifterBoatSystems'
$Root = Split-Path -Parent $PSScriptRoot
$Pyw = (Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if (-not $Pyw) { $Pyw = 'C:\Windows\pyw.exe' }
$Py = (Get-Command py.exe -ErrorAction SilentlyContinue).Source; if (-not $Py) { $Py = 'C:\Windows\py.exe' }
$User = "$env:USERDOMAIN\$env:USERNAME"

function Show-Status {
    foreach ($n in $Task, 'BoatGuard') {
        $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
        if (-not $t) { "{0,-20} not installed" -f $n; continue }
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

$action = New-ScheduledTaskAction -Execute $Pyw -Argument "`"$Root\tools\run_module.py`" gateway" -WorkingDirectory $Root
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

if ($Remove) {   # back to the old way: start at log-on, in the user's session
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
$checkAction = New-ScheduledTaskAction -Execute $Py -Argument "-3.13 `"$Root\tools\session0_check.py`" `"$result`"" -WorkingDirectory $Root
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
$trigger = New-ScheduledTaskTrigger -AtStartup; $trigger.Delay = 'PT30S'      # let USB and Bluetooth finish starting
# -User with -Password = "run whether the user is logged on or not" (logon type Password), not elevated
Register-ScheduledTask -TaskName $Task -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited `
    -User $User -Password $cred.GetNetworkCredential().Password -Force | Out-Null
"`n$Task now starts at boot, whether anybody is logged on or not."
if ($Now) {
    Write-Host 'Restarting the Drifter gateway in that session now (the module servers keep running until their next restart)...'
    Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue; Start-Sleep 3; Start-ScheduledTask -TaskName $Task; Start-Sleep 15
} else { 'It applies from the next boot; the servers running now are not touched (-Now restarts the gateway in that session at once).' }
Show-Status
