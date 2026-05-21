# Read the vision service initialization log
$logPath = Join-Path $env:LOCALAPPDATA 'vision-service-init.log'
Write-Host "Log path: $logPath"
Write-Host "Exists: $(Test-Path $logPath)"
if (Test-Path $logPath) {
    Get-Content $logPath
} else {
    # Check package-specific LocalAppData
    $pkgDir = Join-Path $env:LOCALAPPDATA "Packages\Microsoft.NPUDemo.VisionService_r0xr04974zwaa\LocalState"
    Write-Host "Checking package dir: $pkgDir"
    if (Test-Path $pkgDir) {
        Get-ChildItem $pkgDir -ErrorAction SilentlyContinue
    }
    # Also check temp
    $tempLog = Join-Path $env:TEMP 'vision-service-init.log'
    Write-Host "Checking temp: $tempLog"
    if (Test-Path $tempLog) { Get-Content $tempLog }
}
