# verify.ps1 -- pre-demo health check
# Run this before every demo. Reports the state of every dependency in <30 seconds.
# No installs, no side effects -- read-only diagnostics.

$ErrorActionPreference = 'Continue'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$problems = @()

function OK   ($msg) { Write-Host "[OK]   $msg" -ForegroundColor Green }
function WARN ($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow; $script:problems += $msg }
function FAIL ($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red;    $script:problems += $msg }
function INFO ($msg) { Write-Host "       $msg" -ForegroundColor Gray }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  NPU Demo -- pre-demo health check" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Silicon
$cpuName = (Get-CimInstance Win32_Processor).Name
$expectedModel = if ($cpuName -match "Qualcomm|Snapdragon") { "qwen2.5-7b" } else { "phi-4-mini" }
INFO "CPU: $cpuName"
INFO "Expected model: $expectedModel"

# 2. Python
$pythonExe = $null
foreach ($p in @(
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "$env:ProgramFiles\Python314\python.exe",
    "$env:ProgramFiles\Python313\python.exe",
    "$env:ProgramFiles\Python312\python.exe",
    "$env:ProgramFiles\Python311\python.exe"
)) {
    if (Test-Path $p) { $pythonExe = $p; break }
}
if ($pythonExe) {
    $pyVer = & $pythonExe --version 2>&1
    OK "Python: $pyVer at $pythonExe"
} else {
    FAIL "No real Python found (Microsoft Store stub doesn't count). Run setup.ps1."
}

# 3. Critical Python imports
if ($pythonExe) {
    $script = "import flask, openai, foundry_local, msal, pypdf, docx, yaml, psutil, requests; print('OK')"
    $r = & $pythonExe -c $script 2>&1
    if ($r -match "^OK$") {
        OK "Python dependencies importable (flask, openai, foundry_local, msal, ...)"
    } else {
        FAIL "Python imports broken: $r"
    }
}

# 4. Foundry Local CLI + model cache
try {
    $foundryVer = foundry --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        OK "Foundry Local CLI: $foundryVer"
        $cache = foundry cache ls 2>&1
        if ($cache -match [regex]::Escape($expectedModel)) {
            OK "Model $expectedModel is cached"
        } else {
            WARN "Model $expectedModel NOT cached -- will download on first run"
        }
    } else {
        FAIL "Foundry Local CLI not available"
    }
} catch {
    FAIL "Foundry Local CLI not available: $_"
}

# 5. Vision Service MSIX + .NET 8 + /health
$pkg = Get-AppxPackage -Name 'Microsoft.NPUDemo.VisionService' -ErrorAction SilentlyContinue
if ($pkg) {
    OK "Vision Service MSIX installed (version $($pkg.Version))"
    $dotnetExe = "C:\Program Files\dotnet\dotnet.exe"
    if (Test-Path $dotnetExe) {
        $rt = & $dotnetExe --list-runtimes 2>&1
        if ($rt -match "Microsoft\.NETCore\.App 8\.0\." -and $rt -match "Microsoft\.AspNetCore\.App 8\.0\.") {
            OK ".NET 8 runtime present (NETCore + AspNetCore)"
        } else {
            FAIL ".NET 8 runtime missing or incomplete -- Vision Service won't start"
        }
    } else {
        FAIL ".NET runtime not installed"
    }
    try {
        $h = Invoke-WebRequest -Uri 'http://127.0.0.1:5100/health' -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($h.StatusCode -eq 200) {
            $body = $h.Content
            if ($body -match '"phi_silica_available":true') {
                OK "Vision Service /health responding, phi_silica_available=true"
            } else {
                WARN "Vision Service responding but phi_silica_available!=true: $body"
            }
        }
    } catch {
        WARN "Vision Service installed but not running. Launch with: vision-service\scripts\launch-vision.ps1"
    }
} else {
    WARN "Vision Service MSIX not installed (Field Inspection / Meeting Notes loses live photo classification)"
}

# 6. Brand config
$cfgPath = Join-Path $ScriptDir "demo_config.yaml"
if (Test-Path $cfgPath) {
    $line = Select-String -Path $cfgPath -Pattern 'company_name:' | Select-Object -First 1
    if ($line) { OK "Brand config: $($line.Line.Trim())" } else { WARN "demo_config.yaml present but no company_name found" }
} else {
    WARN "demo_config.yaml missing -- app will fall back to hardcoded DEMO_CONFIG"
}

# 7. Token caches (D365, Graph) -- check LOCALAPPDATA (new) and warn if still in project root (old)
$localStateDir = Join-Path $env:LOCALAPPDATA 'NPUDemo'
foreach ($pair in @(@('D365', 'd365_token_cache.json', '.d365_token_cache.json'), @('Graph', 'graph_token_cache.json', '.graph_token_cache.json'))) {
    $name = $pair[0]; $newFile = Join-Path $localStateDir $pair[1]; $oldFile = Join-Path $ScriptDir $pair[2]
    if (Test-Path $newFile) {
        $age = (Get-Date) - (Get-Item $newFile).LastWriteTime
        if ($age.TotalDays -lt 60) {
            OK "$name token cache in LOCALAPPDATA ($([math]::Round($age.TotalHours,1))h old)"
        } else {
            WARN "$name token cache is $([math]::Round($age.TotalDays,0))d old -- refresh token may have expired"
        }
    } elseif (Test-Path $oldFile) {
        WARN "$name token cache still in project root (OneDrive). Run the app once to auto-migrate."
    } else {
        WARN "$name token cache missing -- live integration will need device-code auth"
    }
}

# 8. Flask not already running on :5000
$listener = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    INFO "Flask is already listening on :5000 (PID $($listener.OwningProcess))"
} else {
    INFO "Flask not yet running. Launch with: python npu_demo_flask.py"
}

# 9. Disk space
$drive = Get-PSDrive C
$freeGB = [math]::Round($drive.Free / 1GB, 1)
if ($freeGB -lt 5) {
    WARN "Low disk space: $freeGB GB free on C:"
} else {
    OK "Disk space: $freeGB GB free on C:"
}

# 10. Network reachable (only matters for live D365/Graph)
$net = Test-NetConnection -ComputerName 8.8.8.8 -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue
if ($net) { OK "Network reachable (live D365/Graph will work)" } else { WARN "No network -- demo will run offline; D365/Graph fall back to local data" }

# 11. __pycache__ prefix in run.bat
$runBat = Join-Path $ScriptDir 'run.bat'
if (Test-Path $runBat) {
    $hasPyCache = Select-String -Path $runBat -Pattern 'PYTHONPYCACHEPREFIX' -Quiet
    if ($hasPyCache) { OK "run.bat sets PYTHONPYCACHEPREFIX (keeps __pycache__ out of OneDrive)" }
    else { WARN "run.bat missing PYTHONPYCACHEPREFIX -- __pycache__ will pollute OneDrive. Run setup.ps1." }
}

# 12. Demo-mode recommendation
$hasD365 = Test-Path (Join-Path $localStateDir 'd365_token_cache.json')
$hasGraph = Test-Path (Join-Path $localStateDir 'graph_token_cache.json')
if (-not $hasD365 -and -not $hasGraph) {
    INFO "No D365/Graph tokens found. For standalone demos use: python npu_demo_flask.py --demo-mode"
}

# 13. Orchestration scripts
foreach ($script in @('start-demo.ps1', 'stop-demo.ps1', 'smoke-test.ps1')) {
    $sp = Join-Path $ScriptDir $script
    if (Test-Path $sp) { OK "$script present" }
    else { WARN "$script missing -- run setup.ps1 or check repo" }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
if ($problems.Count -eq 0) {
    Write-Host "  All systems green. Ready to demo." -ForegroundColor Green
} else {
    Write-Host "  $($problems.Count) issue(s) flagged above. Review before demo." -ForegroundColor Yellow
}
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
