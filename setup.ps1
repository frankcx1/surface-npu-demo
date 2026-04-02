# ============================================================
# Copilot+ PC -- NPU Demo Setup Script
# Works on Intel Core Ultra (x64) and Qualcomm Snapdragon (ARM64)
# ============================================================
# Run in PowerShell (admin NOT required -- all installs are user-scope)
# ============================================================

# --- Detect silicon ---
# NOTE: On Windows-on-ARM, OSArchitecture may report X64 when running
# under emulation. Use CPU name from WMI as the authoritative source.
$cpuName = (Get-CimInstance Win32_Processor).Name
$isARM = ($cpuName -match "Qualcomm|Snapdragon")

if ($isARM) {
    $silicon = "Qualcomm"
    $chipLabel = "Snapdragon X NPU"
    $modelAlias = "qwen2.5-7b"
    $modelLabel = "Qwen 2.5 7B"
} elseif ($cpuName -match "Intel") {
    $silicon = "Intel"
    $chipLabel = "Intel Core Ultra NPU"
    $modelAlias = "phi-4-mini"
    $modelLabel = "Phi-4 Mini"
} else {
    # Fallback: check OS architecture
    $osArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
    if ($osArch -eq [System.Runtime.InteropServices.Architecture]::Arm64) {
        $silicon = "ARM64"
        $chipLabel = "ARM64 NPU"
        $isARM = $true
        $modelAlias = "qwen2.5-7b"
        $modelLabel = "Qwen 2.5 7B"
    } else {
        $silicon = "Intel"
        $chipLabel = "Intel Core Ultra NPU"
        $modelAlias = "phi-4-mini"
        $modelLabel = "Phi-4 Mini"
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Copilot+ PC - NPU Demo Setup" -ForegroundColor Cyan
Write-Host "  Detected: $cpuName" -ForegroundColor Cyan
Write-Host "  Platform: $silicon -- $chipLabel" -ForegroundColor Cyan
Write-Host "  Model: $modelLabel ($modelAlias)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "Working directory: $ScriptDir" -ForegroundColor Gray
Write-Host ""

# ============================================================
# Step 1: Check/Install Python
# ============================================================
Write-Host "Step 1: Checking Python installation..." -ForegroundColor Yellow

$pythonInstalled = $false
try {
    $pythonVersion = python --version 2>&1
    # Guard against the Windows Store stub, which prints an error
    # string instead of "Python 3.x.x" and returns non-zero.
    if ($LASTEXITCODE -eq 0 -and $pythonVersion -match "Python 3") {
        Write-Host "[OK] Python already installed: $pythonVersion" -ForegroundColor Green
        $pythonInstalled = $true
    }
} catch {
    $pythonInstalled = $false
}

if (-not $pythonInstalled) {
    # winget auto-detects ARM64 vs x64 and picks the right installer
    Write-Host "Installing Python 3.11 via winget (auto-detects architecture)..." -ForegroundColor Cyan
    try {
        winget install Python.Python.3.11 --accept-source-agreements --accept-package-agreements --scope user 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Python installed" -ForegroundColor Green
        } else {
            throw "winget returned non-zero"
        }
    } catch {
        Write-Host "[WARN] winget install failed. Trying direct download..." -ForegroundColor Yellow
        if ($isARM) {
            $pythonUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-arm64.exe"
        } else {
            $pythonUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
        }
        $pythonInstaller = "$env:TEMP\python-installer.exe"
        try {
            Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonInstaller -UseBasicParsing
            Write-Host "Installing Python..." -ForegroundColor Cyan
            Start-Process $pythonInstaller -ArgumentList "/passive", "InstallAllUsers=0", "PrependPath=1" -Wait
            Write-Host "[OK] Python installed" -ForegroundColor Green
        } catch {
            Write-Host "[FAIL] Could not install Python. Please install manually:" -ForegroundColor Red
            Write-Host "   https://www.python.org/downloads/windows/" -ForegroundColor Yellow
            Write-Host "   (Choose ARM64 for Snapdragon, x64 for Intel)" -ForegroundColor Yellow
        }
    }

    # Refresh PATH so python/pip are available in this session
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
}

Write-Host ""

# ============================================================
# Step 2: Install Foundry Local (if not already installed)
# ============================================================
Write-Host "Step 2: Checking Foundry Local installation..." -ForegroundColor Yellow

$foundryInstalled = $false
try {
    $foundryCheck = foundry --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Foundry Local CLI already installed: $foundryCheck" -ForegroundColor Green
        $foundryInstalled = $true
    }
} catch {
    $foundryInstalled = $false
}

if (-not $foundryInstalled) {
    Write-Host "Installing Foundry Local via winget..." -ForegroundColor Cyan
    try {
        winget install Microsoft.FoundryLocal --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Foundry Local installed" -ForegroundColor Green
            $foundryInstalled = $true
        } else {
            throw "winget returned non-zero"
        }
    } catch {
        Write-Host "[FAIL] Could not install Foundry Local." -ForegroundColor Red
        Write-Host "   Try manually: winget install Microsoft.FoundryLocal" -ForegroundColor Yellow
    }

    # Refresh PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
}

Write-Host ""

# ============================================================
# Step 3: Install Python Dependencies
# ============================================================
Write-Host "Step 3: Installing Python dependencies..." -ForegroundColor Yellow

$requirementsPath = Join-Path $ScriptDir "requirements.txt"

try {
    pip install -r $requirementsPath 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Python dependencies installed" -ForegroundColor Green
    } else {
        Write-Host "   Trying individual package install..." -ForegroundColor Gray
        pip install flask openai pypdf python-docx foundry-local-sdk
        Write-Host "[OK] Python dependencies installed" -ForegroundColor Green
    }
} catch {
    Write-Host "[WARN] Some packages may have failed. Try manually:" -ForegroundColor Yellow
    Write-Host "   pip install flask openai pypdf python-docx foundry-local-sdk" -ForegroundColor Cyan
}

Write-Host ""

# ============================================================
# Step 4: Verify demo files exist
# ============================================================
Write-Host "Step 4: Verifying demo files..." -ForegroundColor Yellow

# Check for exe (kit layout) or Python file (dev layout)
$exePath = Join-Path $ScriptDir "app\npu-demo.exe"
$pyPath = Join-Path $ScriptDir "npu_demo_flask.py"
$missingFiles = @()

if (Test-Path $exePath) {
    Write-Host "[OK] npu-demo.exe (standalone app)" -ForegroundColor Green
} elseif (Test-Path $pyPath) {
    Write-Host "[OK] npu_demo_flask.py (Python app)" -ForegroundColor Green
} else {
    Write-Host "[MISSING] No app found (expected app\npu-demo.exe or npu_demo_flask.py)" -ForegroundColor Red
    $missingFiles += "app"
}

# Check for demo data and tesseract in both layouts
$demoDataPaths = @(
    (Join-Path $ScriptDir "app\_internal\demo_data"),
    (Join-Path $ScriptDir "demo_data")
)
$foundDemoData = $false
foreach ($dd in $demoDataPaths) {
    if (Test-Path $dd) {
        Write-Host "[OK] demo_data/" -ForegroundColor Green
        $foundDemoData = $true
        break
    }
}
if (-not $foundDemoData) {
    Write-Host "[WARN] demo_data/ not found" -ForegroundColor Yellow
}

$tesseractPaths = @(
    (Join-Path $ScriptDir "app\_internal\tesseract"),
    (Join-Path $ScriptDir "tesseract")
)
$foundTesseract = $false
foreach ($tp in $tesseractPaths) {
    if (Test-Path $tp) {
        Write-Host "[OK] tesseract/ (offline OCR)" -ForegroundColor Green
        $foundTesseract = $true
        break
    }
}
if (-not $foundTesseract) {
    Write-Host "[WARN] tesseract/ not found (ID Verification tab will need online OCR)" -ForegroundColor Yellow
}

Write-Host ""

# ============================================================
# Step 5: Setup demo data
# ============================================================
Write-Host "Step 5: Setting up demo data..." -ForegroundColor Yellow

# Demo data lives inside the project repo (demo_data/) so it's self-contained
$demoDir = Join-Path $PSScriptRoot "demo_data"
$myDayDir = Join-Path $demoDir "My_Day"
$inboxDir = Join-Path $myDayDir "Inbox"

if (Test-Path $myDayDir) {
    Write-Host "[OK] Demo data directory exists: $myDayDir" -ForegroundColor Green
} else {
    Write-Host "[INFO] Creating demo data directory: $myDayDir" -ForegroundColor Cyan
    New-Item -Path $inboxDir -ItemType Directory -Force | Out-Null
    Write-Host "[OK] Demo data directory created" -ForegroundColor Green
    Write-Host "[WARN] Add demo data files (calendar.ics, tasks.csv, emails) to $myDayDir" -ForegroundColor Yellow
}

Write-Host ""

# ============================================================
# Step 6: Test Foundry Local SDK
# ============================================================
Write-Host "Step 6: Testing Foundry Local SDK..." -ForegroundColor Yellow

try {
    $testResult = python -c "from foundry_local import FoundryLocalManager; print('OK')" 2>&1
    if ($testResult -match "OK") {
        Write-Host "[OK] Foundry Local SDK is importable" -ForegroundColor Green
        Write-Host "   The app will auto-download $modelAlias on first run" -ForegroundColor Gray
    } else {
        Write-Host "[WARN] Foundry Local SDK import failed" -ForegroundColor Yellow
        Write-Host "   Try: pip install foundry-local-sdk" -ForegroundColor Cyan
    }
} catch {
    Write-Host "[WARN] Could not verify Foundry Local SDK" -ForegroundColor Yellow
    Write-Host "   Try: pip install foundry-local-sdk" -ForegroundColor Cyan
}

Write-Host ""

# ============================================================
# Step 7: Vision Service (Phi Silica MSIX)
# ============================================================
Write-Host "Step 7: Setting up Vision Service (Phi Silica)..." -ForegroundColor Yellow

$visionServiceDir = Join-Path $ScriptDir "vision-service"
$msixTestDir = Join-Path $visionServiceDir "AppPackages\vision-service_1.0.0.0_x64_Test"
$msixPath = Join-Path $msixTestDir "vision-service_1.0.0.0_x64.msix"

if (Test-Path $msixPath) {
    # Check if already installed
    $existingPkg = Get-AppxPackage -Name 'Microsoft.NPUDemo.VisionService' -ErrorAction SilentlyContinue
    if ($existingPkg) {
        Write-Host "[OK] Vision Service already installed" -ForegroundColor Green
        Write-Host "   PFN: $($existingPkg.PackageFamilyName)" -ForegroundColor Gray
    } else {
        Write-Host "Installing Vision Service MSIX..." -ForegroundColor Cyan

        # Step 7a: Install signing certificate in both Trusted Root CA and Trusted People
        # MSIX requires the self-signed cert in BOTH stores
        Write-Host "   Setting up signing certificate..." -ForegroundColor Gray
        $certFile = $null
        # Look for .cer file in the MSIX test directory
        $cerSearch = Get-ChildItem -Path $msixTestDir -Filter "*.cer" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cerSearch) {
            $certFile = $cerSearch.FullName
        } else {
            # Try the scripts directory
            $cerSearch2 = Get-ChildItem -Path (Join-Path $visionServiceDir "scripts") -Filter "*.cer" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($cerSearch2) { $certFile = $cerSearch2.FullName }
        }

        # Also try the existing setup-cert.ps1 script first
        $certScript = Join-Path $visionServiceDir "scripts\setup-cert.ps1"
        if (Test-Path $certScript) {
            try {
                & $certScript 2>&1 | Out-Null
            } catch { }
        }

        # Manually install cert to both required stores (needs elevation)
        if ($certFile -and (Test-Path $certFile)) {
            Write-Host "   Installing cert to Trusted Root CA and Trusted People..." -ForegroundColor Gray
            try {
                $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($certFile)
                # Trusted Root Certificate Authorities (LocalMachine)
                $rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "LocalMachine")
                $rootStore.Open("ReadWrite")
                $rootStore.Add($cert)
                $rootStore.Close()
                # Trusted People (LocalMachine)
                $peopleStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("TrustedPeople", "LocalMachine")
                $peopleStore.Open("ReadWrite")
                $peopleStore.Add($cert)
                $peopleStore.Close()
                Write-Host "   [OK] Certificate installed in Trusted Root CA + Trusted People" -ForegroundColor Green
            } catch {
                Write-Host "   [WARN] Certificate install needs admin privileges. Run PowerShell as Administrator and re-run setup.ps1" -ForegroundColor Yellow
                Write-Host "   Or manually import the cert:" -ForegroundColor Yellow
                Write-Host "      1. Right-click $certFile > Install Certificate" -ForegroundColor Cyan
                Write-Host "      2. Choose 'Local Machine' > 'Trusted Root Certification Authorities'" -ForegroundColor Cyan
                Write-Host "      3. Repeat and choose 'Trusted People'" -ForegroundColor Cyan
            }
        } else {
            Write-Host "   [WARN] No .cer file found. Vision Service MSIX may fail to install." -ForegroundColor Yellow
            Write-Host "   Enable Developer Mode as an alternative: Settings > System > For developers" -ForegroundColor Cyan
        }

        # Step 7b: Install Windows App Runtime 1.8 dependency
        Write-Host "   Installing Windows App Runtime 1.8..." -ForegroundColor Gray
        try {
            winget install Microsoft.WindowsAppRuntime.1.8 --accept-source-agreements --accept-package-agreements --silent 2>&1 | Out-Null
            Write-Host "   [OK] Windows App Runtime 1.8 installed" -ForegroundColor Green
        } catch {
            Write-Host "   [WARN] Could not install via winget. Trying MSIX dependency..." -ForegroundColor Yellow
            $runtimeMsix = Join-Path $msixTestDir "Dependencies\x64\Microsoft.WindowsAppRuntime.1.8.msix"
            if (Test-Path $runtimeMsix) {
                try {
                    Add-AppxPackage -Path $runtimeMsix -ErrorAction SilentlyContinue
                    Write-Host "   [OK] Windows App Runtime installed from MSIX" -ForegroundColor Green
                } catch {
                    Write-Host "   [WARN] Runtime install failed -- Vision Service may not start" -ForegroundColor Yellow
                }
            }
        }

        # Step 7c: Install the Vision Service MSIX
        Write-Host "   Installing Vision Service package..." -ForegroundColor Gray
        try {
            Add-AppxPackage -Path $msixPath
            $pkg = Get-AppxPackage -Name 'Microsoft.NPUDemo.VisionService' -ErrorAction SilentlyContinue
            if ($pkg) {
                Write-Host "   [OK] Vision Service installed" -ForegroundColor Green
                Write-Host "   PFN: $($pkg.PackageFamilyName)" -ForegroundColor Gray
            } else {
                Write-Host "   [WARN] Install command ran but package not found" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "   [FAIL] Could not install MSIX. Common fixes:" -ForegroundColor Red
            Write-Host "      1. Trust the signing cert (run vision-service\scripts\setup-cert.ps1 as admin)" -ForegroundColor Yellow
            Write-Host "      2. Enable Developer Mode (Settings > For developers)" -ForegroundColor Yellow
            Write-Host "      3. Rebuild from source: vision-service\scripts\rebuild-msix.ps1" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "[SKIP] Pre-built MSIX not found at: $msixPath" -ForegroundColor Gray
    Write-Host "   To build from source: vision-service\scripts\rebuild-msix.ps1" -ForegroundColor Cyan
}

Write-Host ""

# ============================================================
# Step 8: Pre-download model (optional but saves time on first run)
# ============================================================
Write-Host "Step 8: Pre-downloading model..." -ForegroundColor Yellow

if ($foundryInstalled) {
    try {
        # Check if model is already cached by starting service briefly
        foundry service start 2>&1 | Out-Null
        Start-Sleep -Seconds 2

        $modelList = foundry model list 2>&1
        if ($modelList -match $modelAlias) {
            Write-Host "[OK] $modelLabel ($modelAlias) is available in Foundry catalog" -ForegroundColor Green
            Write-Host "   Pre-downloading model to avoid delay on first demo..." -ForegroundColor Gray
            Write-Host "   (This may take a few minutes for ~3 GB download)" -ForegroundColor Gray
            try {
                # Loading the model via chat triggers the download if not cached
                $testResult = python -c @"
from foundry_local import FoundryLocalManager
mgr = FoundryLocalManager()
model_id = mgr.download_model('$modelAlias')
print(f'OK: {model_id}')
"@ 2>&1
                if ($testResult -match "OK:") {
                    Write-Host "[OK] Model downloaded and cached: $testResult" -ForegroundColor Green
                } else {
                    Write-Host "[INFO] Model will download on first app launch" -ForegroundColor Gray
                }
            } catch {
                Write-Host "[INFO] Model will download on first app launch (~3 GB)" -ForegroundColor Gray
            }
        } else {
            Write-Host "[WARN] $modelAlias not found in catalog" -ForegroundColor Yellow
        }

        foundry service stop 2>&1 | Out-Null
    } catch {
        Write-Host "[SKIP] Could not check model catalog" -ForegroundColor Gray
    }
} else {
    Write-Host "[SKIP] Foundry Local not installed -- skipping model download" -ForegroundColor Gray
}

Write-Host ""

# ============================================================
# Summary
# ============================================================
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Setup Complete" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Silicon:  $cpuName" -ForegroundColor White
Write-Host "  Platform: $silicon -- $chipLabel" -ForegroundColor White
Write-Host "  Model:    $modelLabel ($modelAlias)" -ForegroundColor White
Write-Host ""

if ($missingFiles.Count -gt 0) {
    Write-Host "[WARN] Missing files: $($missingFiles -join ', ')" -ForegroundColor Red
    Write-Host ""
}

Write-Host "To launch the demo (starts all 3 services + opens browser):" -ForegroundColor Green
Write-Host ""
Write-Host "   .\start-demo.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "To stop all services:" -ForegroundColor Green
Write-Host ""
Write-Host "   .\stop-demo.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "Or start manually:" -ForegroundColor Gray
Write-Host "   python npu_demo_flask.py    (Flask app on localhost:5000)" -ForegroundColor Gray
Write-Host ""
Write-Host "Silicon auto-detected: the app will brand itself for $chipLabel." -ForegroundColor Gray
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
