# Starts everything Drifter Boat Systems needs, then opens the app. Used by the "Drifter Boat Systems" desktop icon.
# What to start and from where comes from modules.json and <data>\locations.json (tools\modules.py plan).
# A server that is already running is never restarted (a restart pauses Float protection and the anchor watch).
# Processes are created through Win32_Process Create: they run in the user's session, outside the process tree of
# whoever ran this script (servers started inside a tool session's tree disappeared when that session ended).
# MasterVolt and the anchor watch get their usual console window (minimised); the rest runs without a window.
# -Only <module>: start just that one (used by tools\switch_module.ps1); -NoWait: no waiting, status or browser.
param([string]$Only, [switch]$NoWait)
$ErrorActionPreference = 'Continue'
if (-not $NoWait) { $Host.UI.RawUI.WindowTitle = 'Drifter Boat Systems' }
$plan = (& py (Join-Path $PSScriptRoot 'tools\modules.py') plan | Out-String) | ConvertFrom-Json
if ($Only) { $plan.modules = @($plan.modules | Where-Object name -eq $Only) }
$runner = Join-Path $PSScriptRoot 'tools\run_module.py'
$pyw = (Get-Command pyw.exe -ErrorAction SilentlyContinue).Source; if (-not $pyw) { $pyw = 'pyw.exe' }

function Listening($port) { [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) }
function Launch($line, $dir, $show) {
    $si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow = [uint16]$show}
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $line; CurrentDirectory = $dir; ProcessStartupInformation = $si}
    if ($r.ReturnValue -ne 0) { throw "Win32_Process Create returned $($r.ReturnValue)" }
}
function Start-Module($m) {
    if ($m.task) { Start-ScheduledTask -TaskName $m.task; return }
    if ($m.console) {
        $cmd = ($m.command | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) -join ' '
        if ($m.env.DRIFTER_DATA) { $cmd = "cmd.exe /c `"set `"DRIFTER_DATA=$($m.env.DRIFTER_DATA)`" && $($cmd -replace '^cmd /c ', '')`"" }
        Launch $cmd $m.folder 7; return                              # 7 = minimised, not activated
    }
    Launch "`"$pyw`" `"$runner`" $($m.name)" $m.folder 0             # 0 = hidden; output in <data>\logs\<module>.console.log
}

if (-not $NoWait) { Write-Host "`n  Drifter Boat Systems`n" -ForegroundColor Cyan }
foreach ($m in $plan.modules) {
    $where = if ($m.location -eq 'drifter') { 'Drifter' } else { 'old folder' }
    if (Listening $m.port) { Write-Host ("  {0,-26} already running" -f $m.title) -ForegroundColor DarkGray; continue }
    Write-Host ("  {0,-26} starting ({1})..." -f $m.title, $where)
    try { Start-Module $m } catch { Write-Host "    could not start: $($_.Exception.Message)" -ForegroundColor Red; $m | Add-Member Failed $true }
}

if ($NoWait) { return }
# MasterVolt opens the USB link and Bluetooth first and can take a minute; wait up to 90 s for every port.
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline -and ($plan.modules | Where-Object { -not $_.Failed -and -not (Listening $_.port) })) { Start-Sleep -Seconds 2 }

Write-Host ''
$allOk = $true
foreach ($m in $plan.modules) {
    if (Listening $m.port) { Write-Host ("  {0,-26} OK  (port {1})" -f $m.title, $m.port) -ForegroundColor Green }
    else { $allOk = $false; Write-Host ("  {0,-26} NOT RUNNING (port {1}) - see the logs in {2}" -f $m.title, $m.port, $m.data) -ForegroundColor Red }
}

$gw = $plan.modules | Where-Object name -eq 'gateway'
$cfgFile = Join-Path $gw.data 'config.json'
if ((Listening $gw.port) -and (Test-Path $cfgFile)) {
    $cfg = Get-Content $cfgFile -Raw | ConvertFrom-Json; $url = "https://$($cfg.bind):$($cfg.port)/"
    Write-Host "`n  Opening $url"; Start-Process $url
}
Write-Host ''
if ($allOk) { Write-Host '  This window closes in 10 s.'; Start-Sleep -Seconds 10 }
else { Write-Host '  Press Enter to close.'; [void](Read-Host) }
