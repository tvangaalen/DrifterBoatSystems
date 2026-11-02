# The "Drifter Boat Systems" desktop icon: makes sure the Drifter service runs (it starts the gateway and every module
# itself), waits until every server answers, shows the status and opens the app. It never restarts a running server.
# Before tools\install_service.ps1 has run, it starts the old scheduled task DrifterBoatSystems instead.
$ErrorActionPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = 'Drifter Boat Systems'
$venv = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'; $py = if (Test-Path $venv) { $venv } else { 'py' }
$plan = (& $py (Join-Path $PSScriptRoot 'tools\modules.py') plan | Out-String) | ConvertFrom-Json
function Listening($port) { [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) }
function Start-Drifter {
    $svc = Get-Service Drifter -ErrorAction SilentlyContinue
    if ($svc) { if ($svc.Status -eq 'Stopped') { Start-Service Drifter -ErrorAction Stop; return 'starting the service' }; return "service $($svc.Status.ToString().ToLower())" }
    if (Get-ScheduledTask -TaskName DrifterBoatSystems -ErrorAction SilentlyContinue) {
        if ((Get-ScheduledTask -TaskName DrifterBoatSystems).State -ne 'Running') { Start-ScheduledTask -TaskName DrifterBoatSystems; return 'starting the task' }
        return 'task running'
    }
    throw 'neither the Drifter service nor the DrifterBoatSystems task is installed (tools\install_service.ps1)'
}

Write-Host "`n  Drifter Boat Systems`n" -ForegroundColor Cyan
try { Write-Host "  Drifter: $(Start-Drifter)" } catch { Write-Host "  could not start Drifter: $($_.Exception.Message)" -ForegroundColor Red }
# MasterVolt can take up to 3 minutes after a boot. Right after "Switch all systems off" the service is still ending
# (about 15 s): when it has stopped, it is started again.
$deadline = (Get-Date).AddMinutes(4)
while ((Get-Date) -lt $deadline -and ($plan.modules | Where-Object { -not (Listening $_.port) })) {
    $svc = Get-Service Drifter -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Stopped') { Write-Host '  the service had stopped meanwhile: starting it again' -ForegroundColor Yellow; try { Start-Service Drifter } catch {} }
    Start-Sleep -Seconds 2
}
Write-Host ''
$allOk = $true
foreach ($m in $plan.modules) {
    if (Listening $m.port) { Write-Host ("  {0,-26} OK  (port {1})" -f $m.title, $m.port) -ForegroundColor Green }
    else { $allOk = $false; Write-Host ("  {0,-26} NOT RUNNING (port {1}) - see the System page or {2}" -f $m.title, $m.port, $m.log) -ForegroundColor Red }
}
$gw = $plan.modules | Where-Object name -eq 'gateway'; $cfgFile = Join-Path $gw.data 'config.json'
if ((Listening $gw.port) -and (Test-Path $cfgFile)) {
    $cfg = Get-Content $cfgFile -Raw | ConvertFrom-Json; $url = "https://$($cfg.bind):$($cfg.port)/"
    Write-Host "`n  Opening $url"; Start-Process $url
}
Write-Host ''
if ($allOk) { Write-Host '  This window closes in 10 s.'; Start-Sleep -Seconds 10 }
else { Write-Host '  Press Enter to close.'; [void](Read-Host) }
