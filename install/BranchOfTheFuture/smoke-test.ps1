# smoke-test.ps1 -- End-to-end route exerciser for NPU Demo
# Hits every major route category. Verifies the full stack is functional.
# If Flask isn't running, starts it (and stops it when done).
# Usage: .\smoke-test.ps1
#        .\smoke-test.ps1 --demo-mode   (passes --demo-mode to Flask if starting it)

$ErrorActionPreference = 'Continue'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$demoMode = $args -contains '--demo-mode'

$script:pass = 0
$script:fail = 0
$script:skip = 0
$script:total = 0

function Test-Route {
    param(
        [string]$Method,
        [string]$Url,
        [hashtable]$Body = $null,
        [string]$Label = "",
        [int]$Timeout = 60
    )
    $script:total++
    $display = if ($Label) { $Label } else { "$Method $Url" }
    Write-Host "  $display ... " -NoNewline
    try {
        $params = @{
            Uri = $Url
            Method = $Method
            TimeoutSec = $Timeout
            UseBasicParsing = $true
        }
        if ($Body) {
            $params['Body'] = ($Body | ConvertTo-Json -Depth 5)
            $params['ContentType'] = 'application/json'
        }
        $r = Invoke-WebRequest @params -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
            $size = if ($r.Content) { "$($r.Content.Length) bytes" } else { "" }
            Write-Host "[PASS] $size" -ForegroundColor Green
            $script:pass++
        } else {
            Write-Host "[FAIL] status $($r.StatusCode)" -ForegroundColor Red
            $script:fail++
        }
    } catch {
        $err = $_.Exception.Message
        if ($err.Length -gt 80) { $err = $err.Substring(0, 80) + "..." }
        Write-Host "[FAIL] $err" -ForegroundColor Red
        $script:fail++
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  NPU Demo -- Smoke Test" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# --- Check if Flask is running, start if needed ---
$weStartedFlask = $false
$flaskPID = $null

try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/health' -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
    Write-Host "Flask is running. Starting tests." -ForegroundColor Green
} catch {
    Write-Host "Flask not running. Starting it for the test..." -ForegroundColor Yellow

    # Resolve Python
    $pythonExe = $null
    foreach ($p in @(
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )) { if (Test-Path $p) { $pythonExe = $p; break } }
    if (-not $pythonExe) {
        $cmd = Get-Command python.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.Source -notlike "*WindowsApps*" } | Select-Object -First 1
        if ($cmd) { $pythonExe = $cmd.Source }
    }
    if (-not $pythonExe) {
        Write-Host "[FATAL] Python not found. Run setup.ps1 first." -ForegroundColor Red
        exit 1
    }

    $env:PYTHONPYCACHEPREFIX = "$env:LOCALAPPDATA\NPUDemo\__pycache__"
    $flaskArgs = @("$ScriptDir\npu_demo_flask.py")
    if ($demoMode) { $flaskArgs += '--demo-mode' }
    $proc = Start-Process -FilePath $pythonExe -ArgumentList $flaskArgs -WorkingDirectory $ScriptDir -PassThru -WindowStyle Minimized
    $flaskPID = $proc.Id
    $weStartedFlask = $true

    # Wait for /health (up to 120 seconds)
    Write-Host "  Waiting for model load..." -NoNewline
    $ready = $false
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Seconds 1
        if ($i % 15 -eq 0 -and $i -gt 0) { Write-Host "." -NoNewline }
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/health' -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
    }
    Write-Host ""
    if ($ready) { Write-Host "Flask ready." -ForegroundColor Green }
    else { Write-Host "Flask not responding after 120s. Tests may fail." -ForegroundColor Red }
}

Write-Host ""

# --- Core routes ---
Write-Host "Core:" -ForegroundColor Yellow
Test-Route GET 'http://127.0.0.1:5000/health' -Label "GET /health"
Test-Route GET 'http://127.0.0.1:5000/' -Label "GET / (main page)"
Test-Route GET 'http://127.0.0.1:5000/demo-mode-status' -Label "GET /demo-mode-status"
Test-Route GET 'http://127.0.0.1:5000/api/config' -Label "GET /api/config"

# --- D365 routes ---
Write-Host ""
Write-Host "D365 Integration:" -ForegroundColor Yellow
Test-Route GET 'http://127.0.0.1:5000/d365/auth-status' -Label "GET /d365/auth-status"
Test-Route POST 'http://127.0.0.1:5000/d365/customer-lookup' -Body @{name="Jackie Rodriguez"} -Label "POST /d365/customer-lookup (Jackie)"

# --- Branch Concierge ---
Write-Host ""
Write-Host "Branch Concierge:" -ForegroundColor Yellow
Test-Route GET 'http://127.0.0.1:5000/arrivals' -Label "GET /arrivals"
Test-Route GET 'http://127.0.0.1:5000/api/product-catalog' -Label "GET /api/product-catalog"

# --- Morning Briefing (AI inference) ---
Write-Host ""
Write-Host "Morning Briefing (NPU inference ~15-30s):" -ForegroundColor Yellow
Test-Route POST 'http://127.0.0.1:5000/brief-me' -Label "POST /brief-me" -Timeout 90

# --- Advisor Chat (AI inference) ---
Write-Host ""
Write-Host "Advisor Chat (NPU inference ~5-15s):" -ForegroundColor Yellow
Test-Route POST 'http://127.0.0.1:5000/chat' -Body @{message="What is a 529 college savings plan?"; history=@()} -Label "POST /chat (529 question)" -Timeout 30

# --- Meeting Notes ---
Write-Host ""
Write-Host "Meeting Notes:" -ForegroundColor Yellow
Test-Route POST 'http://127.0.0.1:5000/inspection/transcribe' -Body @{text="Met with Jackie Rodriguez at the downtown branch to discuss 529 plan options for her two children"} -Label "POST /inspection/transcribe" -Timeout 30

# --- Live Assist ---
Write-Host ""
Write-Host "Live Assist:" -ForegroundColor Yellow
Test-Route POST 'http://127.0.0.1:5000/live-assist/analyze' -Body @{text="Customer is asking about retirement options and seems interested in a Roth IRA conversion"; prior=""} -Label "POST /live-assist/analyze" -Timeout 30

# --- Session Stats ---
Write-Host ""
Write-Host "System:" -ForegroundColor Yellow
Test-Route GET 'http://127.0.0.1:5000/session-stats' -Label "GET /session-stats"
Test-Route GET 'http://127.0.0.1:5000/my-day-counts' -Label "GET /my-day-counts"

# --- Summary ---
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Results: $($script:pass) passed, $($script:fail) failed, $($script:total) total" -ForegroundColor $(if ($script:fail -gt 0) { "Yellow" } else { "Green" })
if ($script:fail -eq 0) {
    Write-Host "  ALL SMOKE TESTS PASSED" -ForegroundColor Green
} else {
    Write-Host "  $($script:fail) FAILURE(S) -- review output above" -ForegroundColor Red
}
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# --- Cleanup: stop Flask if we started it ---
if ($weStartedFlask -and $flaskPID) {
    Write-Host "Stopping Flask (PID $flaskPID)..." -ForegroundColor Gray
    Stop-Process -Id $flaskPID -Force -ErrorAction SilentlyContinue
}
