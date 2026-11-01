<#
  Start the Mastervolt server automatically when the PC boots - before anybody has logged on - with a scheduled task.

  Run it once from an ELEVATED PowerShell (Run as administrator), from the folder the server runs from. Windows blocks
  unsigned scripts by default, so start it like this (this one command only; the system policy stays as it is):

      powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\install_autostart.ps1             install (asks for the Windows password of the account that runs the server)
      powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\install_autostart.ps1 -Status     show the task and whether the server answers
      powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\install_autostart.ps1 -Remove     remove the task again

  Why the password: a task that runs "whether the user is logged on or not" must be stored with that account's
  password. The account matters because Python and its packages (hidapi, bleak, fastapi) are installed for that user only.
  The password is handed to Task Scheduler, which keeps it protected; this script does not save it anywhere.

  Limits you should know: a boot-time task has no desktop, so there is no console window (use -Status or the log files in
  logs\), and Windows may refuse Bluetooth or USB access to a session without a desktop. After the first reboot check the
  BMS page: batteries connected and values showing means it works. If not, remove the task and use a log-on start instead.
#>
param(
    [switch]$Remove,
    [switch]$Status,
    [string]$UserName = "$env:USERDOMAIN\$env:USERNAME"
)

$ErrorActionPreference = 'Stop'
$TaskName = 'Mastervolt Server (autostart)'
$Folder = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $Folder 'start_mastervolt_server.cmd'

function Test-Admin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if ($Status) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        "Task     : $TaskName ($($task.State)), runs as $($task.Principal.UserId)"
        "Last run : $($info.LastRunTime)  result $($info.LastTaskResult)"
    } else {
        "Task     : not installed"
    }
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) { "Server   : listening on port 8000 (process $($listener.OwningProcess))" } else { "Server   : not listening on port 8000" }
    return
}

if (-not (Test-Admin)) {
    throw 'Run this script from an elevated PowerShell (right-click PowerShell, Run as administrator).'
}

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        "Removed the scheduled task '$TaskName'. A running server is not stopped."
    } else {
        "The scheduled task '$TaskName' is not installed."
    }
    return
}

if (-not (Test-Path $Launcher)) { throw "Cannot find $Launcher - run this script from the folder the server runs from." }

$credential = Get-Credential -UserName $UserName -Message "Windows password of $UserName (needed to run the server before anybody logs on)"
if (-not $credential) { throw 'Cancelled.' }

# Check the password first, so a typo does not leave a task that can never start.
Add-Type -AssemblyName System.DirectoryServices.AccountManagement
$account = $credential.UserName
$name = if ($account -match '\\') { $account.Split('\')[1] } else { $account }
$contextType = if ($account -match '^(?<domain>[^\\]+)\\' -and $Matches.domain -ne $env:COMPUTERNAME) { 'Domain' } else { 'Machine' }
$context = New-Object System.DirectoryServices.AccountManagement.PrincipalContext($contextType)
if (-not $context.ValidateCredentials($name, $credential.GetNetworkCredential().Password)) {
    throw "Windows did not accept that password for $account. Nothing was changed."
}

$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"`"$Launcher`"`"" -WorkingDirectory $Folder
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = 'PT30S'   # let USB and Bluetooth finish starting
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -User $credential.UserName -Password $credential.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null

"Installed '$TaskName': it starts $Launcher 30 seconds after every boot, as $account."
"It is not started now (a server may already be running). Check it after the next reboot with:  powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\install_autostart.ps1 -Status"
