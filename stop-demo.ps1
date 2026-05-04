# stop-demo.ps1 -- Stop all NPU Demo services

$ErrorActionPreference = 'Continue'

Write-Host ""
Write-Host "Stopping NPU Demo services..." -ForegroundColor Cyan
Write-Host ""

# 1. Stop Flask (anything on port 5000)
$listener = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Host "  [OK] Stopped Flask (PID $($listener.OwningProcess))" -ForegroundColor Green
} else {
    Write-Host "  [--] Flask not running" -ForegroundColor Gray
}

# 2. Stop Vision Service
$visionProc = Get-Process -Name 'vision-service' -ErrorAction SilentlyContinue
if ($visionProc) {
    $visionProc | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        Write-Host "  [OK] Stopped Vision Service (PID $($_.Id))" -ForegroundColor Green
    }
} else {
    Write-Host "  [--] Vision Service not running" -ForegroundColor Gray
}

# 3. Stop Foundry Local service
try {
    $foundryOut = foundry service stop 2>&1
    if ($foundryOut -match "stopped") {
        Write-Host "  [OK] Stopped Foundry Local service" -ForegroundColor Green
    } else {
        Write-Host "  [--] Foundry Local: $foundryOut" -ForegroundColor Gray
    }
} catch {
    Write-Host "  [--] Foundry Local not running or CLI not available" -ForegroundColor Gray
}

Write-Host ""
Write-Host "All services stopped." -ForegroundColor Green
Write-Host ""
