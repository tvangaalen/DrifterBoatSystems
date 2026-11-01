$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$certDir = Join-Path $projectDir "certs"
New-Item -ItemType Directory -Path $certDir -Force | Out-Null

$opensslCommand = Get-Command openssl.exe -ErrorAction SilentlyContinue
if (-not $opensslCommand) {
    $knownOpenSsl = "C:\Program Files\FireDaemon OpenSSL 3\bin\openssl.exe"
    if (Test-Path -LiteralPath $knownOpenSsl) {
        $opensslPath = $knownOpenSsl
    } else {
        throw "OpenSSL was not found. Install OpenSSL locally before starting the server."
    }
} else {
    $opensslPath = $opensslCommand.Source
}

$caKey = Join-Path $certDir "ca-key.pem"
$caPem = Join-Path $certDir "ca-cert.pem"
$caCer = Join-Path $certDir "Mastervolt-Local-CA.cer"
$serverKey = Join-Path $certDir "server-key.pem"
$serverCsr = Join-Path $certDir "server.csr"
$serverPem = Join-Path $certDir "server-cert.pem"
$serverConfig = Join-Path $certDir "server-openssl.cnf"
$serialFile = Join-Path $certDir "ca-cert.srl"

if (-not (Test-Path -LiteralPath $caKey) -or -not (Test-Path -LiteralPath $caPem)) {
    & $opensslPath req -x509 -newkey rsa:3072 -nodes -sha256 -days 3650 `
        -keyout $caKey -out $caPem -subj "/CN=Mastervolt Local CA" `
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" `
        -addext "keyUsage=critical,keyCertSign,cRLSign" `
        -addext "subjectKeyIdentifier=hash"
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Mastervolt local CA" }
}

& $opensslPath x509 -in $caPem -outform DER -out $caCer
if ($LASTEXITCODE -ne 0) { throw "Could not export the iPhone CA certificate" }

$localAddresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -ExpandProperty IPAddress -Unique

function Test-PrivateIPv4([string]$address) {
    if ($address -match '^10\.' -or $address -match '^192\.168\.') { return $true }
    if ($address -match '^172\.(\d+)\.') {
        $secondOctet = [int]$Matches[1]
        return $secondOctet -ge 16 -and $secondOctet -le 31
    }
    return $false
}

$routedAddresses = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric |
    ForEach-Object {
        Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue |
            Where-Object { $_.AddressState -eq "Preferred" } |
            Select-Object -ExpandProperty IPAddress
    }
$privateAddress = $routedAddresses | Where-Object { Test-PrivateIPv4 $_ } | Select-Object -First 1
if (-not $privateAddress) {
    $privateAddress = $localAddresses | Where-Object { Test-PrivateIPv4 $_ } | Select-Object -First 1
}
if (-not $privateAddress) { $privateAddress = "127.0.0.1" }
Set-Content -LiteralPath (Join-Path $certDir "bind-address.txt") -Value $privateAddress -Encoding ascii

$altNames = @("DNS.1 = localhost", "DNS.2 = $env:COMPUTERNAME", "IP.1 = 127.0.0.1")
$ipIndex = 2
foreach ($address in $localAddresses) {
    $altNames += "IP.$ipIndex = $address"
    $ipIndex++
}

$configText = @"
[req]
prompt = no
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = $env:COMPUTERNAME

[req_ext]
subjectAltName = @alt_names
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
$($altNames -join "`r`n")
"@
Set-Content -LiteralPath $serverConfig -Value $configText -Encoding ascii

& $opensslPath req -new -newkey rsa:2048 -nodes -sha256 -keyout $serverKey -out $serverCsr -config $serverConfig
if ($LASTEXITCODE -ne 0) { throw "Could not create the HTTPS server request" }

$signArguments = @(
    "x509", "-req", "-in", $serverCsr, "-CA", $caPem, "-CAkey", $caKey,
    "-out", $serverPem, "-days", "825", "-sha256", "-extfile", $serverConfig,
    "-extensions", "req_ext"
)
if (Test-Path -LiteralPath $serialFile) {
    $signArguments += @("-CAserial", $serialFile)
} else {
    $signArguments += "-CAcreateserial"
}
& $opensslPath @signArguments
if ($LASTEXITCODE -ne 0) { throw "Could not sign the HTTPS server certificate" }

& certutil.exe -user -addstore -f Root $caCer | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not trust the local CA for the current Windows user" }

try {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $caKey /inheritance:r /grant:r "${currentIdentity}:(R,W)" | Out-Null
    & icacls.exe $serverKey /inheritance:r /grant:r "${currentIdentity}:(R,W)" | Out-Null
} catch {
    Write-Warning "Could not restrict private-key file permissions: $($_.Exception.Message)"
}

Write-Host "Local HTTPS certificates are ready."
Write-Host "Trusted PC CA: CN=Mastervolt Local CA"
Write-Host "iPhone certificate: $caCer"
Write-Host "Certificate addresses: localhost, $env:COMPUTERNAME, $($localAddresses -join ', ')"
Write-Host "Private-LAN bind address: $privateAddress"
