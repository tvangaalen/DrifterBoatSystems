# Creates BoatGuard's HTTPS certificate (certs\boatguard-*.pem) from the Mastervolt Local CA the iPhone already trusts.
# Run again if the PC's LAN address changes. Usage: powershell -NoProfile -ExecutionPolicy Bypass -File setup_https.ps1 [-CaDir <folder>]
param([string]$CaDir = '')  # default: see ..\..\common\issue_cert.ps1
& (Join-Path $PSScriptRoot '..\..\common\issue_cert.ps1') -Name boatguard -Cn "BoatGuard $env:COMPUTERNAME" -OutDir (Join-Path $PSScriptRoot 'certs') -CaDir $CaDir
