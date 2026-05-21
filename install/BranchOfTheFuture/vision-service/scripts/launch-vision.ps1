# Launch the vision service MSIX app and wait for /health
# First launch can take 30-60s while Phi Silica Vision + TextRewriter initialize.
# Subsequent launches are faster (~5s).

$shell = New-Object -ComObject Shell.Application
$shell.ShellExecute('shell:AppsFolder\Microsoft.NPUDemo.VisionService_r0xr04974zwaa!App')
Write-Host "Launched Vision Service. Waiting for /health (first launch can take 30-60s)..." -ForegroundColor Cyan

$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest http://localhost:5100/health -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        $body = $r.Content | ConvertFrom-Json
        Write-Host ""
        Write-Host "Vision Service is up:" -ForegroundColor Green
        Write-Host "  phi_silica_available:       $($body.phi_silica_available)"
        Write-Host "  writing_assistant_available: $($body.writing_assistant_available)"
        if (-not $body.phi_silica_available) {
            Write-Host ""
            Write-Host "  Phi Silica not available on this build. This is rare on Copilot+ PCs" -ForegroundColor Yellow
            Write-Host "  running 24H2 build 26100+. To enable: Settings > Privacy & security >" -ForegroundColor Yellow
            Write-Host "  AI components > toggle Phi Silica on, then run Windows Update." -ForegroundColor Yellow
        }
        exit 0
    } catch {
        Write-Host "." -NoNewline
    }
    Start-Sleep -Seconds 2
}

Write-Host ""
Write-Host "Vision Service did not bind :5100 within 90s." -ForegroundColor Yellow
Write-Host "  Check init log: C:\temp\vision-service-init.log" -ForegroundColor Gray
Write-Host "  Check process:  Get-Process vision-service -ErrorAction SilentlyContinue" -ForegroundColor Gray
exit 1
