<#
  Installs drifterd as the Windows service "Drifter" (display name "Drifter Boat Systems"): it starts at boot, whether
  anybody is logged on or not, runs the gateway and all four modules as its own processes, and Windows restarts it after
  a crash. Replaces the scheduled task DrifterBoatSystems.

  Run once from an ELEVATED PowerShell (right-click PowerShell, Run as administrator), from C:\Drifter:

      powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_service.ps1           install and switch over
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_service.ps1 -Status   show the service and what runs where
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_service.ps1 -Remove   back to the scheduled task

  What it does
  1. Asks for your Windows password (the service runs as your account: your Python, your files, Bluetooth) and checks it.
  2. Checks in a session without desktop that the MasterBus USB Link, Bluetooth and starting processes work
     (tools\session0_check.py, read-only). If not, nothing is changed.
  3. Asks the running Drifter whether a restart is safe now (no BMS control running, Float not latched, no anchor alarm).
  4. Gives your account the right "Log on as a service" (Windows needs it for a service that runs as a user), creates
     the service (automatic, delayed start; restart after a crash), and lets your account start and stop it (the
     desktop icon starts it again after "Switch all systems off").
  5. Switches over: stops the old task and the servers, starts the service, waits until the app answers. If it does not
     come up within 3 minutes, it goes back to the scheduled task by itself. Float protection and the anchor watch pause
     for about a minute.
#>
param([switch]$Status, [switch]$Remove, [switch]$Force)
$ErrorActionPreference = 'Stop'
$Service = 'Drifter'; $Task = 'DrifterBoatSystems'
$Root = Split-Path -Parent $PSScriptRoot
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'; $VenvPyw = Join-Path $Root '.venv\Scripts\pythonw.exe'
$EnergyPy = Join-Path $Root 'modules\energy\.venv\Scripts\python.exe'      # has hidapi and bleak for the check
$User = "$env:COMPUTERNAME\$env:USERNAME"
$Ports = [ordered]@{ gateway = 8100; energy = 8000; anchor = 8766; guard = 8095; washer = 8080 }

function Listening($port) { [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) }
function Show-Status {
    $s = Get-Service $Service -ErrorAction SilentlyContinue
    if ($s) { $c = Get-CimInstance Win32_Service -Filter "Name='$Service'"; "service {0}: {1}, start {2}, runs as {3}" -f $Service, $s.Status, $c.StartMode, $c.StartName }
    else { "service ${Service}: not installed" }
    $t = Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue; if ($t) { "task ${Task}: $($t.State)" } else { "task ${Task}: removed" }
    foreach ($n in $Ports.Keys) { "{0,-8} port {1,-5} {2}" -f $n, $Ports[$n], $(if (Listening $Ports[$n]) { 'listening' } else { 'not listening' }) }
}
if ($Status) { Show-Status; return }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Run this from an elevated PowerShell (right-click PowerShell, Run as administrator).' }
foreach ($p in (Join-Path $Root 'drifterd.py'), $VenvPy, $EnergyPy) { if (-not (Test-Path $p)) { throw "$p missing (pull the latest code and run py -3.12 tools\sync_envs.py first)." } }
$BasePy = (& $VenvPy -c "import sys; print(sys._base_executable)").Trim()    # drifterd is stdlib only: the plain python.org Python
$BasePyw = Join-Path (Split-Path $BasePy) 'pythonw.exe'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12   # Windows PowerShell 5.1 does not offer TLS 1.2 by itself
function Remove-DrifterService {   # also one that hangs (Start Pending): end its process first, or it stays "marked for deletion"
    $c = Get-CimInstance Win32_Service -Filter "Name='$Service'" -ErrorAction SilentlyContinue
    if (-not $c) { return }
    if ($c.ProcessId) { Stop-Process -Id $c.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Service $Service -Force -ErrorAction SilentlyContinue; sc.exe delete $Service | Out-Null
    $deadline = (Get-Date).AddSeconds(20); while ((Get-Date) -lt $deadline -and (Get-Service $Service -ErrorAction SilentlyContinue)) { Start-Sleep 1 }
}

$cred = Get-Credential -UserName $User -Message "Windows password of $User (the Drifter service runs as this account)"
if (-not $cred) { throw 'Cancelled.' }
$pw = $cred.GetNetworkCredential().Password
Add-Type -AssemblyName System.DirectoryServices.AccountManagement
if (-not (New-Object System.DirectoryServices.AccountManagement.PrincipalContext('Machine')).ValidateCredentials($env:USERNAME, $pw)) {
    throw "Windows did not accept that password for $User. Nothing was changed."
}
# the way back: drifterd itself from a boot task (the same daemon, without the service manager)
$taskAction = New-ScheduledTaskAction -Execute $BasePyw -Argument "`"$Root\drifterd.py`" run" -WorkingDirectory $Root
$taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
function Restore-Task {   # drifterd from a boot task instead of the service
    $trigger = New-ScheduledTaskTrigger -AtStartup; $trigger.Delay = 'PT2M'
    Register-ScheduledTask -TaskName $Task -Action $taskAction -Trigger $trigger -Settings $taskSettings -RunLevel Limited -User $User -Password $pw -Force | Out-Null
}
function Stop-Servers {   # every server, whoever started it (an administrator may stop processes in any session)
    foreach ($port in $Ports.Values) {
        $id = (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
        while ($id) {
            $pr = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
            if (-not $pr) { break }
            $parent = $pr.ParentProcessId; $name = $pr.Name
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
            $pp = Get-CimInstance Win32_Process -Filter "ProcessId=$parent" -ErrorAction SilentlyContinue
            if (-not $pp -or $pp.Name -notmatch '^(cmd|py|pyw|python|pythonw)\.exe$') { break }
            $id = $parent
        }
    }
    $deadline = (Get-Date).AddSeconds(30); while ((Get-Date) -lt $deadline -and ($Ports.Values | Where-Object { Listening $_ })) { Start-Sleep 1 }
}

if ($Remove) {
    Remove-DrifterService; Stop-Servers
    Restore-Task; Start-ScheduledTask -TaskName $Task
    "The service is removed; the scheduled task $Task runs drifterd instead (now and at boot)."; Show-Status; return
}

# 2. the read-only check in a session without desktop
$result = Join-Path $env:TEMP 'drifter_session0_check.json'; Remove-Item $result -ErrorAction SilentlyContinue
$checkTask = 'Drifter session check (temporary)'
Register-ScheduledTask -TaskName $checkTask -Action (New-ScheduledTaskAction -Execute $EnergyPy -Argument "`"$Root\tools\session0_check.py`" `"$result`"" -WorkingDirectory $Root) `
    -User $User -Password $pw -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 3)) -Force | Out-Null
try {
    Write-Host 'Checking USB, Bluetooth and starting processes in a session without desktop (up to a minute)...'
    Start-ScheduledTask -TaskName $checkTask
    $deadline = (Get-Date).AddSeconds(90); while (-not (Test-Path $result) -and (Get-Date) -lt $deadline) { Start-Sleep 2 }
} finally { Unregister-ScheduledTask -TaskName $checkTask -Confirm:$false }
if (-not (Test-Path $result)) { throw 'The check did not report back within 90 s. Nothing was changed.' }
$check = Get-Content $result -Raw | ConvertFrom-Json; Remove-Item $result
$check | Format-List masterbus_usb, bluetooth_on, bluetooth_devices_heard, bluetooth_error, usb_error, process_create_session | Out-Host
if (-not $check.ok -and -not $Force) { throw 'The check failed (see above). Nothing was changed. (-Force installs anyway.)' }

# 3. is a restart safe now? (the same questions the app asks before a restart)
$cfg = Get-Content (Join-Path $Root 'config.json') -Raw | ConvertFrom-Json
$base = "https://$($cfg.bind):$($cfg.port)"
$prev = [Net.ServicePointManager]::ServerCertificateValidationCallback; [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
try {
    $bms = Invoke-RestMethod "$base/api/power/api/bms" -TimeoutSec 15; $energy = Invoke-RestMethod "$base/api/power/api/energy" -TimeoutSec 15
    $anchor = Invoke-RestMethod "$base/api/anchor/api/state" -TimeoutSec 15
    $why = @()
    if ($bms.control_status.busy) { $why += 'a BMS control is running' }
    if ($energy.high_soc_float_policy.float_latched) { $why += 'Float is latched' }
    if (@($anchor.alarms).Count) { $why += 'the anchor watch has an alarm' }
    if ($why -and -not $Force) { throw "Not now: $($why -join ', '). Nothing was changed; try again later." }
} catch [System.Net.WebException] {
    if ($Ports.Values | Where-Object { Listening $_ }) { if (-not $Force) { throw "Drifter does not answer ($($_.Exception.Message)), so the pre-checks cannot be asked. Nothing was changed. (-Force goes on anyway.)" } }
    else { Write-Warning 'Nothing is running: nothing to pause.' }
}
finally { [Net.ServicePointManager]::ServerCertificateValidationCallback = $prev }

# 4. the service
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices; using System.Security.Principal;
public static class DrifterLsa {
    [StructLayout(LayoutKind.Sequential)] struct LSA_UNICODE_STRING { public ushort Length, MaximumLength; public IntPtr Buffer; }
    [StructLayout(LayoutKind.Sequential)] struct LSA_OBJECT_ATTRIBUTES { public int Length; public IntPtr RootDirectory, ObjectName; public uint Attributes; public IntPtr SecurityDescriptor, SecurityQualityOfService; }
    [DllImport("advapi32.dll")] static extern uint LsaOpenPolicy(IntPtr system, ref LSA_OBJECT_ATTRIBUTES attr, uint access, out IntPtr handle);
    [DllImport("advapi32.dll")] static extern uint LsaAddAccountRights(IntPtr handle, byte[] sid, LSA_UNICODE_STRING[] rights, uint count);
    [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr handle);
    [DllImport("advapi32.dll")] static extern int LsaNtStatusToWinError(uint status);
    public static int Grant(string account, string right) {
        var sid = (SecurityIdentifier)new NTAccount(account).Translate(typeof(SecurityIdentifier));
        var b = new byte[sid.BinaryLength]; sid.GetBinaryForm(b, 0);
        var attr = new LSA_OBJECT_ATTRIBUTES(); IntPtr h;
        uint r = LsaOpenPolicy(IntPtr.Zero, ref attr, 0x810, out h);   // POLICY_CREATE_ACCOUNT | POLICY_LOOKUP_NAMES
        if (r != 0) return LsaNtStatusToWinError(r);
        var s = new LSA_UNICODE_STRING(); s.Buffer = Marshal.StringToHGlobalUni(right); s.Length = (ushort)(right.Length * 2); s.MaximumLength = (ushort)(s.Length + 2);
        r = LsaAddAccountRights(h, b, new[] { s }, 1); Marshal.FreeHGlobal(s.Buffer); LsaClose(h);
        return r == 0 ? 0 : LsaNtStatusToWinError(r);
    }
}
"@
$e = [DrifterLsa]::Grant($User, 'SeServiceLogonRight'); if ($e) { throw "Could not give $User the right to log on as a service (error $e). Nothing else was changed." }
"$User may log on as a service."
Remove-DrifterService
New-Service -Name $Service -DisplayName 'Drifter Boat Systems' -Description 'Runs the Drifter app and the boat systems (energy, anchor watch, BoatGuard, washer); C:\Drifter\drifterd.py' `
    -BinaryPathName "`"$BasePy`" `"$Root\drifterd.py`" service" -StartupType Automatic -Credential $cred | Out-Null
sc.exe config $Service start= delayed-auto | Out-Null                                                        # after the boot settles (USB, Bluetooth)
sc.exe failure $Service reset= 86400 actions= restart/10000/restart/30000/restart/60000 | Out-Null          # restart after a crash
sc.exe failureflag $Service 1 | Out-Null                                                                    # also when drifterd ends with an error
$sid = (New-Object Security.Principal.NTAccount($User)).Translate([Security.Principal.SecurityIdentifier]).Value
$sd = (sc.exe sdshow $Service | Where-Object { $_ }) -join ''
if ($sd -notmatch [regex]::Escape($sid)) { sc.exe sdset $Service ($sd -replace '^D:', "D:(A;;RPWPLCLORC;;;$sid)") | Out-Null }   # this user may start, stop, query
"Service $Service created (automatic, delayed start; restarts after a crash)."

# 5. switch over, with a way back
Write-Host 'Switching over: stopping the old task and the servers, starting the service...'
Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
Stop-Servers
sc.exe start $Service | Out-Null                     # not Start-Service: that waits without end when a service hangs
$deadline = (Get-Date).AddMinutes(3); while ((Get-Date) -lt $deadline -and -not (Listening 8100)) { Start-Sleep 3 }
if (-not (Listening 8100)) {
    Write-Warning 'The app did not come up under the service within 3 minutes: going back to the scheduled task. See C:\DrifterData\logs\drifterd.log.'
    $c = Get-CimInstance Win32_Service -Filter "Name='$Service'"; if ($c.ProcessId) { Stop-Process -Id $c.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Service $Service -Force -ErrorAction SilentlyContinue; Set-Service $Service -StartupType Disabled
    Stop-Servers; Restore-Task; Start-ScheduledTask -TaskName $Task; Show-Status; throw 'Service not working; the scheduled task runs Drifter again.'
}
$deadline = (Get-Date).AddMinutes(4); while ((Get-Date) -lt $deadline -and ($Ports.Values | Where-Object { -not (Listening $_) })) { Start-Sleep 3 }
if (Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $Task -Confirm:$false }
"`nDrifter runs as the service $Service; the scheduled task is removed."
Show-Status
