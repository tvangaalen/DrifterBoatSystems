$ErrorActionPreference = "Stop"

$Project = $PSScriptRoot
$CaptureDir = Join-Path $Project "captures"
New-Item -ItemType Directory -Force -Path $CaptureDir | Out-Null

Write-Host ""
Write-Host "Mastervolt ECU Power USB capture" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "IMPORTANT:"
Write-Host "  1. Stop the Mastervolt web server first."
Write-Host "  2. Close all Python MasterBus tools."
Write-Host "  3. MasterAdjust will own the MasterBus USB Link during the capture."
Write-Host ""

# Typical USBPcap locations. Wireshark bundles it on many Windows installs.
$candidates = @(
    "C:\Program Files\USBPcap\USBPcapCMD.exe",
    "C:\Program Files\Wireshark\extcap\USBPcapCMD.exe",
    "C:\Program Files\Wireshark\USBPcapCMD.exe",
    "C:\Program Files (x86)\USBPcap\USBPcapCMD.exe"
)

$usbpcap = $null
foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
        $usbpcap = $candidate
        break
    }
}

if (-not $usbpcap) {
    $cmd = Get-Command USBPcapCMD.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        $usbpcap = $cmd.Source
    }
}

if (-not $usbpcap) {
    Write-Host "USBPcapCMD.exe was not found." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Install Wireshark with the USBPcap component, then run this script again."
    Write-Host "No MasterBus changes have been made."
    exit 1
}

Write-Host "Found USBPcap:" -ForegroundColor Green
Write-Host "  $usbpcap"
Write-Host ""
Write-Host "USBPcap will open an elevated interactive window."
Write-Host ""
Write-Host "In that USBPcap window:"
Write-Host "  - Select the USB root/filter that lists the MasterBus USB Link."
Write-Host "  - For output file enter:"
Write-Host "    $CaptureDir\ecu_power_masteradjust.pcap"
Write-Host "  - Capture from all devices on that selected filter if prompted."
Write-Host ""
Write-Host "Then, while capture is running:"
Write-Host "  A. Open MasterAdjust."
Write-Host "  B. Locate INT Yanmar ECU -> Power."
Write-Host "  C. Change Power ON -> OFF."
Write-Host "  D. Wait about 3 seconds."
Write-Host "  E. Change Power OFF -> ON."
Write-Host "  F. Wait about 3 seconds."
Write-Host "  G. Return to USBPcap and press q to stop."
Write-Host ""
Write-Host "Do NOT run ecu_control_test.py during this capture."
Write-Host ""

$working = Split-Path $usbpcap -Parent
Start-Process -FilePath $usbpcap -WorkingDirectory $working -Verb RunAs -Wait

Write-Host ""
Write-Host "Capture session finished." -ForegroundColor Green
Write-Host "Expected file:"
Write-Host "  $CaptureDir\ecu_power_masteradjust.pcap"
Write-Host ""
Write-Host "Upload that .pcap file to ChatGPT for protocol comparison."
