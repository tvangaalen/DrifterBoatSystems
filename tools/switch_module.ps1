# Moves one module from its old folder to Drifter (C:\Drifter + C:\DrifterData), or back with -Back.
# Usage (from C:\Drifter):  powershell -NoProfile -ExecutionPolicy Bypass -File tools\switch_module.ps1 <energy|anchor|guard|washer|gateway> [-Back] [-Yes]
#
# What it does: read-only pre-checks; copy the runtime files while the old server still runs; ask for confirmation;
# stop the old server; copy again (final, consistent copy); check the CA is in place; point the scheduled task at
# the new location; record the location; start the module and wait for its port. Copying never deletes or moves
# anything in the old folder, so -Back is possible (it starts the old folder again with its old files; changes
# made in the meantime stay in C:\DrifterData). A switch restarts the module: Float protection or the anchor watch
# pause for about a minute. Run it only when the user wants that.
param([Parameter(Mandatory)][ValidateSet('energy', 'anchor', 'guard', 'washer', 'gateway')][string]$Module, [switch]$Back, [switch]$Yes)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$tools = $PSScriptRoot
$planAll = & py (Join-Path $tools 'modules.py') plan | Out-String | ConvertFrom-Json
function Resolve($name, $loc) { & py -c "import sys,json; sys.path.insert(0, r'$tools'); import modules; print(json.dumps(modules.resolve('$name', '$loc')))" | ConvertFrom-Json }
function Listener($port) { (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess }
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function ViaDrifter($path) {   # read-only GET through the running Drifter gateway (it listens on its LAN address only)
    $gw = $planAll.modules | Where-Object name -eq 'gateway'; $cf = Join-Path $gw.data 'config.json'
    if (-not (Test-Path $cf)) { return $null }; $c = Get-Content $cf -Raw | ConvertFrom-Json
    try { curl.exe -sk --max-time 15 "https://$($c.bind):$($c.port)/api/$path" | ConvertFrom-Json } catch { $null }
}

$cur = $planAll.modules | Where-Object name -eq $Module
$target = if ($Back) { 'legacy' } else { 'drifter' }
if ($cur.location -eq $target) { Write-Host "$Module already runs from $target."; exit 0 }
$from = Resolve $Module $cur.location; $to = Resolve $Module $target
Write-Host "$($cur.title): $($from.location) ($($from.folder)) -> $($to.location) ($($to.folder))"
if ($root.TrimEnd('\') -ne $planAll.live.TrimEnd('\')) { throw "Run this script from the live clone $($planAll.live), not from $root" }

# ---- pre-checks (read-only)
Step 'Pre-checks'
if (-not (Test-Path $to.folder)) { throw "Missing folder $($to.folder) (run tools\prepare_live.ps1 first)" }
$exe = Join-Path $to.folder $to.command[0]
if ($to.command[0] -like '.venv*' -and -not (Test-Path $exe)) { throw "Missing $exe (run tools\prepare_live.ps1 first)" }
if ($cur.precheck -eq 'energy' -and (Listener $cur.port)) {
    $bms = ViaDrifter 'power/api/bms'; $en = ViaDrifter 'power/api/energy'
    if (-not $bms -or -not $en) { Write-Host '  could not read /api/bms and /api/energy through Drifter: check them yourself' -ForegroundColor Yellow }
    else {
        if ($bms.control_status.busy) { throw 'A BMS control is running (control_status.busy): try again later' }
        if ($en.high_soc_float_policy.float_latched) { throw 'Float is latched (float_latched): do not restart now' }
        Write-Host "  BMS idle, Float not latched (house SOC $($en.storage.house.soc) %)" -ForegroundColor Green
    }
}
if ($cur.task) {
    # The task must run tools\run_module.py, which starts the module from whatever locations.json says; then a switch
    # never has to edit the task. Checked before anything is stopped. A task that runs "whether the user is logged on
    # or not" can only be changed with the user's Windows password, so the user changes it once, by hand.
    $act = (Get-ScheduledTask -TaskName $cur.task).Actions[0]
    $runner = Join-Path $root 'tools\run_module.py'
    if ("$($act.Execute) $($act.Arguments)" -notmatch [regex]::Escape($runner)) {
        $pyw = (Get-Command pyw.exe).Source
        try { Set-ScheduledTask -TaskName $cur.task -Action (New-ScheduledTaskAction -Execute $pyw -Argument "`"$runner`" $Module" -WorkingDirectory $root) -ErrorAction Stop | Out-Null
              Write-Host "  scheduled task $($cur.task) now runs tools\run_module.py (follows locations.json)" }
        catch {
            Write-Host "`nScheduled task '$($cur.task)' cannot be changed from here ($($_.Exception.Message.Trim())). Change it once yourself:" -ForegroundColor Yellow
            Write-Host "  Task Scheduler > $($cur.task) > Properties > Actions > Edit"
            Write-Host "    Program/script:  $pyw"
            Write-Host "    Add arguments:   `"$runner`" $Module"
            Write-Host "    Start in:        $root"
            Write-Host "  OK, enter your Windows password, then run this script again. Nothing was stopped or changed."
            exit 3
        }
    } else { Write-Host "  scheduled task $($cur.task) runs tools\run_module.py: OK" -ForegroundColor Green }
}
if ($Module -eq 'anchor' -and (Listener $cur.port)) {
    $st = ViaDrifter 'anchor/api/state'
    if (-not $st) { Write-Host '  could not read the anchor state through Drifter: check it yourself' -ForegroundColor Yellow }
    elseif ($st.alarms.Count) { throw "Anchor alarm active ($($st.alarms.text -join ', ')): do not switch now" }
    if ($st.anchor) { Write-Host '  The anchor is set: the watch pauses for about a minute and continues with the same anchor (state is copied).' -ForegroundColor Yellow }
}

# ---- copy runtime files (first pass while the old server runs)
function Copy-Runtime($final) {
    if ($target -eq 'drifter') { $pairs = @(@($from.folder, $to.data, $to.runtime), @($from.folder, $to.folder, $to.code_runtime)) }
    else { $pairs = @(@($from.data, $to.folder, $from.runtime)) }           # back: the newer state goes back to the old folder
    foreach ($p in $pairs) {
        $src, $dst, $items = $p
        foreach ($it in $items) {
            $s = Join-Path $src $it; $d = Join-Path $dst $it
            if (-not (Test-Path $s)) { continue }
            if ((Get-Item $s).PSIsContainer) { robocopy $s $d /E /COPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null; if ($LASTEXITCODE -ge 8) { throw "copy of $s failed ($LASTEXITCODE)" } }
            else { New-Item -ItemType Directory -Force (Split-Path $d) | Out-Null; Copy-Item -LiteralPath $s -Destination $d -Force }
            if ($final) { Write-Host "  $it" }
        }
    }
}
if (-not $Back) { Step 'Copying runtime files (first pass, server still running)'; Copy-Runtime $false }

if (-not $Yes) {
    Write-Host "`nThis stops $($cur.title) in $($from.folder) and starts it from $($to.folder)." -ForegroundColor Yellow
    if ((Read-Host 'Type yes to continue') -ne 'yes') { Write-Host 'Nothing changed.'; exit 1 }
}

# From here on the old server is being stopped. Safety net: if anything fails before the new one is started, record
# the old location again and start the module from there, so it is never left stopped.
# A hold file keeps the Drifter supervisor from starting the module while it is being moved.
$hold = Join-Path $planAll.data "hold\$Module"
function Release-Hold { Remove-Item -LiteralPath $hold -Force -ErrorAction SilentlyContinue }
$stopped = $false
trap {
    if ($stopped) {
        Write-Host "`nFailed after stopping the old server: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Starting $($cur.title) again from $($cur.location)..." -ForegroundColor Yellow
        & py (Join-Path $tools 'modules.py') set $Module $cur.location | Out-Null
        & (Join-Path $root 'start_all.ps1') -Only $Module -NoWait
        $deadline = (Get-Date).AddSeconds(120); while (-not (Listener $cur.port) -and (Get-Date) -lt $deadline) { Start-Sleep 2 }
        Write-Host $(if (Listener $cur.port) { "$($cur.title) runs again from $($cur.location)." } else { "$($cur.title) did NOT come back: start it by hand!" }) -ForegroundColor Yellow
        Release-Hold; exit 4
    }
    Write-Host "`n$($_.Exception.Message)" -ForegroundColor Red; exit 1      # before stopping: nothing was changed
}

# ---- stop the old server
Step 'Stopping the old server'
New-Item -ItemType Directory -Force (Split-Path $hold) | Out-Null; Set-Content -LiteralPath $hold -Value "switch_module $(Get-Date -Format s)" -Encoding ascii
$stopped = $true
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tools 'stop_module.ps1') $Module | Out-Null
if (Listener $cur.port) { throw "Port $($cur.port) is still in use: stop it by hand, then run this again" }
Remove-Item -LiteralPath (Join-Path $planAll.data "starting\$Module") -Force -ErrorAction SilentlyContinue   # stopped for sure: a new start is allowed
Write-Host "  stopped"

Step 'Copying runtime files (final)'; Copy-Runtime $true
foreach ($r in $to.requires) { if (-not (Test-Path (Join-Path $to.folder $r))) { throw "Missing $r in $($to.folder): not starting (the start script would create a new CA). Run -Back to restore." } }

# ---- location, start (a scheduled task follows locations.json through run_module.py)
& py (Join-Path $tools 'modules.py') set $Module $target | Out-Null
Step 'Starting'
& (Join-Path $root 'start_all.ps1') -Only $Module -NoWait
$stopped = $false                                   # the new server is being started: do not start the old one as well
$deadline = (Get-Date).AddSeconds(120); while (-not (Listener $to.port) -and (Get-Date) -lt $deadline) { Start-Sleep 2 }
Release-Hold
if (Listener $to.port) { Write-Host "`n$($to.title) runs from $target (port $($to.port))." -ForegroundColor Green }
else { Write-Host "`n$($to.title) did not start: see $($to.data)\logs. Undo with: tools\switch_module.ps1 $Module $(if ($Back) { '' } else { '-Back' })" -ForegroundColor Red; exit 2 }
