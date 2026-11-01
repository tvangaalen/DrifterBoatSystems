# Prepares the live location without touching any running server: clones (or fast-forwards) C:\Drifter from GitHub,
# creates the Python environments the modules need there, and creates C:\DrifterData. Safe to run again.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File tools\prepare_live.ps1
$ErrorActionPreference = 'Stop'
$git = (Get-Command git.exe -ErrorAction SilentlyContinue).Source; if (-not $git) { $git = 'C:\Program Files\Git\cmd\git.exe' }
$repo = 'https://github.com/tvangaalen/DrifterBoatSystems.git'
$spec = Get-Content (Join-Path (Split-Path $PSScriptRoot -Parent) 'modules.json') -Raw | ConvertFrom-Json
$live = [Environment]::ExpandEnvironmentVariables($spec.live); $data = [Environment]::ExpandEnvironmentVariables($spec.data)

if (Test-Path (Join-Path $live '.git')) { Write-Host "Updating $live"; & $git -C $live pull --ff-only; if ($LASTEXITCODE) { throw 'git pull failed (local changes in the live clone?)' } }
elseif (Test-Path $live) { throw "$live exists but is not a git clone: move it away first" }
else { Write-Host "Cloning $repo to $live"; & $git clone -q $repo $live; if ($LASTEXITCODE) { throw 'git clone failed' } }
New-Item -ItemType Directory -Force $data | Out-Null

foreach ($p in $spec.modules.PSObject.Properties) {
    $m = $p.Value; if (-not $m.venv) { continue }
    $dir = Join-Path $live $m.dir; $py = Join-Path $dir '.venv\Scripts\python.exe'
    if (-not (Test-Path $py)) {
        Write-Host "$($p.Name): creating .venv"
        $ver = if ($p.Name -eq 'washer') { '-3.12' } else { '-3' }      # the VIOMI controller is tested on 3.12/3.13 (python-miio)
        & py $ver -m venv (Join-Path $dir '.venv'); if ($LASTEXITCODE) { throw "venv for $($p.Name) failed" }
    }
    $reqs = $m.venv -split '\+'
    & $py -m pip install -q --disable-pip-version-check -r (Join-Path $dir $reqs[0]); if ($LASTEXITCODE) { throw "pip for $($p.Name) failed" }
    if ($reqs.Count -gt 1) { & $py -m pip install -q --disable-pip-version-check --no-deps -r (Join-Path $dir $reqs[1]); if ($LASTEXITCODE) { throw "pip (no-deps) for $($p.Name) failed" } }
    Write-Host "$($p.Name): environment ready"
}
Write-Host "`nReady. Nothing is running from $live yet; switch modules one by one with tools\switch_module.ps1 (from $live)."
