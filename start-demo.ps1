# start-demo.ps1 -- Launch all NPU Demo services and open browser
# Usage: .\start-demo.ps1              (with D365/Graph tenants)
#        .\start-demo.ps1 --demo-mode  (standalone, no tenants needed)

$ErrorActionPreference = 'Continue'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$demoMode = $args -contains '--demo-mode'

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  NPU Demo -- Starting Services" -ForegroundColor Cyan
if ($demoMode) { Write-Host "  Mode: DEMO (no D365/Graph tenants needed)" -ForegroundColor Yellow }
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Keep __pycache__ out of OneDrive
$env:PYTHONPYCACHEPREFIX = "$env:LOCALAPPDATA\NPUDemo\__pycache__"

# --- Resolve Python ---
$pythonExe = $null
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "$env:ProgramFiles\Python314\python.exe",
    "$env:ProgramFiles\Python313\python.exe",
    "$env:ProgramFiles\Python312\python.exe",
    "$env:ProgramFiles\Python311\python.exe"
)
foreach ($p in $candidates) {
    if (Test-Path $p) { $pythonExe = $p; break }
}
if (-not $pythonExe) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notlike "*WindowsApps*" } | Select-Object -First 1
    if ($cmd) { $pythonExe = $cmd.Source }
}
if (-not $pythonExe) {
    Write-Host "[FATAL] Python not found. Run setup.ps1 first." -ForegroundColor Red
    exit 1
}
Write-Host "Python: $pythonExe" -ForegroundColor Gray

# --- 1. Start Foundry Local service ---
Write-Host "Starting Foundry Local service..." -ForegroundColor Cyan
try {
    $foundryOut = foundry service start 2>&1
    if ($foundryOut -match "http://") {
        $match = [regex]::Match($foundryOut, 'http://[^\s,]+')
        Write-Host "  Foundry: $($match.Value)" -ForegroundColor Green
    } else {
        Write-Host "  Foundry: started" -ForegroundColor Green
    }
} catch {
    Write-Host "  [WARN] Could not start Foundry service: $_" -ForegroundColor Yellow
}

# --- 2. Launch Vision Service MSIX ---
$pkg = Get-AppxPackage -Name 'Microsoft.NPUDemo.VisionService' -ErrorAction SilentlyContinue
if ($pkg) {
    # Check if already running
    $visionProc = Get-Process -Name 'vision-service' -ErrorAction SilentlyContinue
    if ($visionProc) {
        Write-Host "  Vision Service: already running (PID $($visionProc.Id))" -ForegroundColor Green
    } else {
        Write-Host "Launching Vision Service..." -ForegroundColor Cyan
        Start-Process "shell:AppsFolder\$($pkg.PackageFamilyName)!App"
        # Wait for /health (up to 20 seconds)
        $ready = $false
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Seconds 1
            try {
                $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5100/health' -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
                if ($r.StatusCode -eq 200) { $ready = $true; break }
            } catch {}
        }
        if ($ready) { Write-Host "  Vision Service: ready on :5100" -ForegroundColor Green }
        else { Write-Host "  Vision Service: launched but /health not responding yet" -ForegroundColor Yellow }
    }
} else {
    Write-Host "  Vision Service: not installed (camera classification will use Phi-4 Mini fallback)" -ForegroundColor Gray
}

# --- 3. Start Flask app ---
# Check if already running on :5000
$existing = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "  Flask: already running on :5000 (PID $($existing.OwningProcess))" -ForegroundColor Green
} else {
    Write-Host "Starting Flask app (model warmup may take 30-60s)..." -ForegroundColor Cyan
    $flaskArgs = @("$ScriptDir\npu_demo_flask.py")
    if ($demoMode) { $flaskArgs += '--demo-mode' }
    $proc = Start-Process -FilePath $pythonExe -ArgumentList $flaskArgs -WorkingDirectory $ScriptDir -PassThru -WindowStyle Normal
    Write-Host "  Flask PID: $($proc.Id)" -ForegroundColor Gray

    # Wait for /health (up to 120 seconds -- first run downloads model)
    Write-Host "  Waiting for model to load..." -ForegroundColor Gray -NoNewline
    $ready = $false
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Seconds 1
        if ($i % 10 -eq 0 -and $i -gt 0) { Write-Host "." -NoNewline }
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/health' -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
    }
    Write-Host ""
    if ($ready) {
        Write-Host "  Flask: ready on http://localhost:5000" -ForegroundColor Green
    } else {
        Write-Host "  Flask: not responding yet (model may still be loading)" -ForegroundColor Yellow
        Write-Host "  Check the Flask console window for progress." -ForegroundColor Gray
    }
}

# --- 4. Open browser ---
Write-Host ""
Write-Host "Opening browser..." -ForegroundColor Cyan
Start-Process "http://localhost:5000"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  All services launched. Demo is live." -ForegroundColor Green
Write-Host "  Stop with: .\stop-demo.ps1" -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
