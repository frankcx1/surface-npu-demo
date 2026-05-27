# setup-touch-hotkey.ps1 — One-time setup: creates scheduled task + desktop shortcut
# Run this ONCE as admin. After that, Ctrl+Alt+T toggles touch with no UAC popup.

$ErrorActionPreference = "Stop"

# Must be admin
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Run this script as Administrator (right-click > Run as admin)" -ForegroundColor Red
    exit 1
}

$taskName = "ToggleTouchScreen"
$scriptPath = Join-Path $PSScriptRoot "toggle-touch.ps1"

if (-not (Test-Path $scriptPath)) {
    Write-Host "toggle-touch.ps1 not found in $PSScriptRoot" -ForegroundColor Red
    exit 1
}

# Create scheduled task that runs as SYSTEM (no UAC prompt when triggered)
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 30)

# Remove old task if exists
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal `
    -Settings $settings -Description "Toggle Surface touch screen on/off"

Write-Host "Scheduled task '$taskName' created" -ForegroundColor Green
Write-Host "  Test it: schtasks /run /tn `"$taskName`"" -ForegroundColor Cyan

# Create desktop shortcut with Ctrl+Alt+T hotkey
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Toggle Touch.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "schtasks.exe"
$shortcut.Arguments = "/run /tn `"$taskName`""
$shortcut.WindowStyle = 7  # Minimized
$shortcut.Hotkey = "Ctrl+Alt+T"
$shortcut.Description = "Toggle Surface touch screen on/off"
$shortcut.IconLocation = "shell32.dll,176"
$shortcut.Save()

Write-Host "Desktop shortcut created: $shortcutPath" -ForegroundColor Green
Write-Host "Hotkey: Ctrl+Alt+T" -ForegroundColor Cyan
Write-Host ""
Write-Host "Done! Press Ctrl+Alt+T to toggle touch screen." -ForegroundColor Green
