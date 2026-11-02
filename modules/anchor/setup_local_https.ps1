param(
    # Folder holding the "Mastervolt Local CA" (ca-cert.pem + ca-key.pem) that the iPhone already trusts.
    # Default: ANCHOR_CA_DIR, else the default of ..\..\common\issue_cert.ps1 (DRIFTER_CA_DIR, else modules\energy\certs).
    [string]$CaDir = $env:ANCHOR_CA_DIR
)
# Issues this app's HTTPS certificate (certs\server-*.pem) from the existing Mastervolt Local CA, so phones that already
# trust it open the anchor watch without any change, and writes certs\bind-address.txt (the private LAN address the
# network GPS listens on). It never creates a new CA, never writes into the CA folder and never touches the Windows
# certificate store.
$certDir = Join-Path $PSScriptRoot 'certs'
& (Join-Path $PSScriptRoot '..\..\common\issue_cert.ps1') -Name server -Cn "$env:COMPUTERNAME Anchor Watch" -OutDir $certDir -CaDir $CaDir -BindFile (Join-Path $certDir 'bind-address.txt')
