# Creates BoatGuard's HTTPS certificate, signed by a local CA the iPhone already trusts (ca-cert.pem + ca-key.pem in -CaDir).
# Run again if the PC's LAN address changes. Usage: powershell -NoProfile -ExecutionPolicy Bypass -File setup_https.ps1 [-CaDir <folder>]
param([string]$CaDir = 'C:\Temp\mastervoltproject\certs')  # default: the MasterVolt-YMS local CA on this boat PC
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$caDir = $CaDir
$certDir = Join-Path $here 'certs'
New-Item -ItemType Directory -Force $certDir | Out-Null

$openssl = (Get-Command openssl.exe -ErrorAction SilentlyContinue).Source
if (-not $openssl) { $openssl = 'C:\Program Files\FireDaemon OpenSSL 3\bin\openssl.exe' }
if (-not (Test-Path $openssl)) { throw 'openssl.exe not found' }
foreach ($f in 'ca-cert.pem', 'ca-key.pem') { if (-not (Test-Path (Join-Path $caDir $f))) { throw "missing $caDir\$f (YMS local CA)" } }

$addresses = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)' } | Select-Object -ExpandProperty IPAddress
$alt = @('DNS.1 = localhost', "DNS.2 = $env:COMPUTERNAME", 'IP.1 = 127.0.0.1')
$i = 2; foreach ($a in $addresses) { $alt += "IP.$i = $a"; $i++ }

$cnf = Join-Path $certDir 'boatguard-openssl.cnf'
@"
[req]
prompt = no
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = BoatGuard $env:COMPUTERNAME

[req_ext]
subjectAltName = @alt_names
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
$($alt -join "`n")
"@ | Set-Content -LiteralPath $cnf -Encoding ascii

$ErrorActionPreference = 'Continue'  # PowerShell 5.1 turns openssl's progress output on stderr into errors; check $LASTEXITCODE instead
$key = Join-Path $certDir 'boatguard-key.pem'; $csr = Join-Path $certDir 'boatguard.csr'; $crt = Join-Path $certDir 'boatguard-cert.pem'
& $openssl req -new -newkey rsa:2048 -nodes -sha256 -keyout $key -out $csr -config $cnf 2>$null
if ($LASTEXITCODE) { throw 'openssl req failed' }
# 825 days: the longest validity iOS accepts for a server certificate.
& $openssl x509 -req -in $csr -CA (Join-Path $caDir 'ca-cert.pem') -CAkey (Join-Path $caDir 'ca-key.pem') -CAserial (Join-Path $certDir 'ca.srl') -CAcreateserial `
    -out $crt -days 825 -sha256 -extfile $cnf -extensions req_ext 2>$null
if ($LASTEXITCODE) { throw 'openssl x509 signing failed' }
Remove-Item $csr
Write-Output "BoatGuard certificate for: $($alt -join ', ')"
