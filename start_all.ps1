# Starts everything Drifter Boat Systems needs, then opens the app. Used by the "Drifter Boat Systems" desktop icon.
# A server that is already running is never restarted (a restart pauses Float protection and the anchor watch).
# Each server is started the way it normally is: its own start script or scheduled task, hidden, output to its logs folder.
$ErrorActionPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = 'Drifter Boat Systems'
$work = Split-Path $PSScriptRoot -Parent                      # the folder with the sibling projects
$cfg = Get-Content (Join-Path $PSScriptRoot 'config.json') -Raw | ConvertFrom-Json
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$noInput = Join-Path $env:TEMP 'drifter-empty-input.txt'      # stdin for the start scripts: their closing "pause" returns at once
Set-Content -LiteralPath $noInput -Value '' -Encoding ascii

function Listening($port) { [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) }
function StartScript($script, $logDir, $prefix) {
    New-Item -ItemType Directory -Force $logDir | Out-Null
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$script`"" -WorkingDirectory (Split-Path $script) -WindowStyle Hidden `
        -RedirectStandardInput $noInput -RedirectStandardOutput (Join-Path $logDir "${prefix}_$stamp.out.log") -RedirectStandardError (Join-Path $logDir "${prefix}_$stamp.err.log") | Out-Null
}

$services = @(
    @{Name = 'Energy (MasterVolt YMS)'; Port = 8000; Start = { StartScript 'C:\Temp\mastervoltproject\start_mastervolt_server.cmd' 'C:\Temp\mastervoltproject\logs' 'server' }},
    @{Name = 'Anchor watch';            Port = 8766; Start = { StartScript (Join-Path $work 'OrcaCore2\start_anchor_watch.cmd') (Join-Path $work 'OrcaCore2\logs') 'anchor' }},
    @{Name = 'BoatGuard';               Port = 8095; Start = { Start-ScheduledTask -TaskName BoatGuard }},
    @{Name = 'Washer (VIOMI)';          Port = 8080; Start = {
        $d = Join-Path $work 'viomi-w1-controller'; New-Item -ItemType Directory -Force "$d\logs" | Out-Null
        Start-Process -FilePath "$d\.venv\Scripts\python.exe" -ArgumentList 'viomi_web_english_v58.py' -WorkingDirectory $d -WindowStyle Hidden `
            -RedirectStandardInput $noInput -RedirectStandardOutput "$d\logs\viomi_$stamp.out.log" -RedirectStandardError "$d\logs\viomi_$stamp.err.log" | Out-Null }},
    @{Name = 'Drifter app';             Port = [int]$cfg.port; Start = { Start-ScheduledTask -TaskName DrifterBoatSystems }}
)

Write-Host ''
Write-Host '  Drifter Boat Systems' -ForegroundColor Cyan
Write-Host ''
foreach ($s in $services) {
    if (Listening $s.Port) { Write-Host ("  {0,-26} already running" -f $s.Name) -ForegroundColor DarkGray; $s.Started = $false; continue }
    Write-Host ("  {0,-26} starting..." -f $s.Name)
    try { & $s.Start; $s.Started = $true } catch { Write-Host "    could not start: $($_.Exception.Message)" -ForegroundColor Red; $s.Failed = $true }
}

# MasterVolt opens the USB link and Bluetooth first and can take a minute; wait up to 90 s for every port.
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline -and ($services | Where-Object { -not $_.Failed -and -not (Listening $_.Port) })) { Start-Sleep -Seconds 2 }

Write-Host ''
$allOk = $true
foreach ($s in $services) {
    if (Listening $s.Port) { Write-Host ("  {0,-26} OK  (port {1})" -f $s.Name, $s.Port) -ForegroundColor Green }
    else { $allOk = $false; Write-Host ("  {0,-26} NOT RUNNING (port {1}) - see its logs folder" -f $s.Name, $s.Port) -ForegroundColor Red }
}

$url = "https://$($cfg.bind):$($cfg.port)/"
if (Listening ([int]$cfg.port)) { Write-Host "`n  Opening $url"; Start-Process $url }
Write-Host ''
if ($allOk) { Write-Host '  This window closes in 10 s.'; Start-Sleep -Seconds 10 }
else { Write-Host '  Press Enter to close.'; [void](Read-Host) }
