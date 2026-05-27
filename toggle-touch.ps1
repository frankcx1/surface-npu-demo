# toggle-touch.ps1 — Toggle Surface touch screen on/off
# Requires: Run as admin OR via scheduled task (no UAC prompt)
#
# Usage:
#   Direct:    powershell -ExecutionPolicy Bypass -File toggle-touch.ps1
#   Via task:  schtasks /run /tn "ToggleTouchScreen"
#   Hotkey:    Ctrl+Alt+T (after running setup below)

$ErrorActionPreference = "Stop"

# Find the HID touch screen device
$touch = Get-PnpDevice | Where-Object {
    $_.FriendlyName -like '*touch screen*' -and
    $_.Class -eq 'HIDClass'
}

if (-not $touch) {
    # Broader search fallback
    $touch = Get-PnpDevice | Where-Object {
        $_.FriendlyName -match 'touch' -and
        $_.Class -in @('HIDClass', 'Monitor', 'HumanInterfaceDevice')
    }
}

if (-not $touch) {
    Write-Host "No touch screen device found" -ForegroundColor Red
    exit 1
}

# Handle multiple matches (take first)
if ($touch -is [array]) { $touch = $touch[0] }

$name = $touch.FriendlyName
$current = $touch.Status

if ($current -eq "OK") {
    Write-Host "Disabling touch: $name" -ForegroundColor Yellow
    Disable-PnpDevice -InstanceId $touch.InstanceId -Confirm:$false
    Write-Host "Touch screen OFF" -ForegroundColor Red
} else {
    Write-Host "Enabling touch: $name" -ForegroundColor Green
    Enable-PnpDevice -InstanceId $touch.InstanceId -Confirm:$false
    Write-Host "Touch screen ON" -ForegroundColor Green
}
