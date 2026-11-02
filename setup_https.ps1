# Creates Drifter's HTTPS certificate (certs\drifter-*.pem) from the Mastervolt Local CA the iPhone and iPad already trust.
# Only reads the CA folder. Run again if the PC's LAN address changes, then restart Drifter.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File setup_https.ps1 [-CaDir <folder>]   (default: common\issue_cert.ps1)
param([string]$CaDir = '')
& (Join-Path $PSScriptRoot 'common\issue_cert.ps1') -Name drifter -Cn "Drifter Boat Systems $env:COMPUTERNAME" -OutDir (Join-Path $PSScriptRoot 'certs') -CaDir $CaDir
