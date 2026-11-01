Write-Host "Searching Windows PnP devices for the MasterBus USB Link..." -ForegroundColor Cyan
Write-Host ""

Get-PnpDevice |
    Where-Object {
        $_.InstanceId -match "VID_1A64&PID_0000" -or
        $_.FriendlyName -match "MasterBus|Mastervolt"
    } |
    Format-Table -AutoSize Status, Class, FriendlyName, InstanceId
