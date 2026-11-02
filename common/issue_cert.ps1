# Issues a server's HTTPS certificate from the existing "Mastervolt Local CA" that the iPhone and iPad already trust.
# It never creates a CA, never writes into the CA folder (random serial instead of a serial file) and never touches the
# Windows certificate store. Covers localhost, this PC's name, 127.0.0.1 and its private IPv4 addresses; 825 days
# (the longest validity iOS accepts). Run again if the PC's LAN address changes, then restart that server.
# Used by setup_https.ps1 (gateway), modules\guard\setup_https.ps1 and modules\anchor\setup_local_https.ps1.
param(
    [Parameter(Mandatory)][string]$Name,     # file prefix: <Name>-cert.pem, <Name>-key.pem, <Name>-openssl.cnf
    [Parameter(Mandatory)][string]$Cn,       # certificate common name
    [Parameter(Mandatory)][string]$OutDir,   # where the certificate and key go (created if missing)
    [string]$CaDir = '',                     # default: DRIFTER_CA_DIR, else modules\energy\certs of this repository
    [string]$BindFile = ''                   # optional: write the private address of the default route here
)
$ErrorActionPreference = 'Stop'
if (-not $CaDir) { $CaDir = if ($env:DRIFTER_CA_DIR) { $env:DRIFTER_CA_DIR } else { Join-Path (Split-Path -Parent $PSScriptRoot) 'modules\energy\certs' } }
$caPem = Join-Path $CaDir 'ca-cert.pem'; $caKey = Join-Path $CaDir 'ca-key.pem'
if (-not (Test-Path -LiteralPath $caPem) -or -not (Test-Path -LiteralPath $caKey)) {
    throw "Mastervolt Local CA not found in $CaDir (need ca-cert.pem and ca-key.pem). Pass -CaDir or set DRIFTER_CA_DIR. Never create a new CA: every iPhone/iPad would have to trust it again."
}
$openssl = (Get-Command openssl.exe -ErrorAction SilentlyContinue).Source
if (-not $openssl) { $openssl = 'C:\Program Files\FireDaemon OpenSSL 3\bin\openssl.exe' }
if (-not (Test-Path -LiteralPath $openssl)) { throw 'openssl.exe not found. Install OpenSSL locally first.' }
$subject = & $openssl x509 -in $caPem -noout -subject
if ($subject -notmatch 'Mastervolt Local CA') { throw "Unexpected CA in ${CaDir}: $subject" }
New-Item -ItemType Directory -Force $OutDir | Out-Null

function Test-PrivateIPv4([string]$a) { $a -match '^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)' }
$addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { Test-PrivateIPv4 $_.IPAddress } |
    Select-Object -ExpandProperty IPAddress -Unique)
if ($BindFile) {
    # The private address of the interface with the default route, else any private address, else localhost.
    $routed = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric |
        ForEach-Object { Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue |
            Where-Object { $_.AddressState -eq 'Preferred' } | Select-Object -ExpandProperty IPAddress }
    $bind = @($routed | Where-Object { Test-PrivateIPv4 $_ }) + $addresses + @('127.0.0.1') | Select-Object -First 1
    Set-Content -LiteralPath $BindFile -Value $bind -Encoding ascii
}
$alt = @('DNS.1 = localhost', "DNS.2 = $env:COMPUTERNAME", 'IP.1 = 127.0.0.1')
$i = 2; foreach ($a in $addresses) { $alt += "IP.$i = $a"; $i++ }

$cnf = Join-Path $OutDir "$Name-openssl.cnf"
@"
[req]
prompt = no
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = $Cn

[req_ext]
subjectAltName = @alt_names
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
$($alt -join "`n")
"@ | Set-Content -LiteralPath $cnf -Encoding ascii

$ErrorActionPreference = 'Continue'  # PowerShell 5.1 turns openssl's progress output on stderr into errors; check $LASTEXITCODE instead
$key = Join-Path $OutDir "$Name-key.pem"; $csr = Join-Path $OutDir "$Name.csr"; $crt = Join-Path $OutDir "$Name-cert.pem"
& $openssl req -new -newkey rsa:2048 -nodes -sha256 -keyout $key -out $csr -config $cnf 2>$null
if ($LASTEXITCODE) { throw 'openssl req failed' }
$serial = '0x' + (-join ((1..16) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) }))
& $openssl x509 -req -in $csr -CA $caPem -CAkey $caKey -set_serial $serial -out $crt -days 825 -sha256 -extfile $cnf -extensions req_ext 2>$null
if ($LASTEXITCODE) { throw 'openssl x509 signing failed' }
$ErrorActionPreference = 'Stop'
Remove-Item -LiteralPath $csr
try {
    $me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $key /inheritance:r /grant:r "${me}:(R,W)" | Out-Null
} catch { Write-Warning "Could not restrict the private key's file permissions: $($_.Exception.Message)" }
Write-Output "$Cn certificate for: $($alt -join ', ')$(if ($BindFile) { "; bind address $bind" })"
