# ============================================================
# Copilot+ PC -- NPU Demo Setup Script (v2)
# Works on Intel Core Ultra (x64) and Qualcomm Snapdragon (ARM64)
# ============================================================
# Run in PowerShell (admin NOT required unless Vision Service cert needs installing)
#
# Design principle: every step checks desired state first, installs only if
# needed, then re-checks. Re-running this script is always safe.
# ============================================================

$ErrorActionPreference = 'Continue'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# -------------------------------------------------------------------
# Step function: check -> install -> re-check
# -------------------------------------------------------------------
$script:stepsPassed = 0
$script:stepsFailed = 0
$script:stepsSkipped = 0

function Step {
    param(
        [string]$Name,
        [scriptblock]$Check,
        [scriptblock]$Install
    )
    Write-Host ""
    Write-Host ">> $Name" -ForegroundColor Yellow -NoNewline
    if (& $Check) {
        Write-Host " [SKIP - already done]" -ForegroundColor Green
        $script:stepsSkipped++
        return $true
    }
    Write-Host ""  # newline after step name
    & $Install
    if (& $Check) {
        Write-Host "   [OK]" -ForegroundColor Green
        $script:stepsPassed++
        return $true
    }
    Write-Host "   [FAIL]" -ForegroundColor Red
    $script:stepsFailed++
    return $false
}

# -------------------------------------------------------------------
# Silicon detection
# -------------------------------------------------------------------
$cpuName = (Get-CimInstance Win32_Processor).Name
$isARM = ($cpuName -match "Qualcomm|Snapdragon")

if ($isARM) {
    $silicon = "Qualcomm"; $chipLabel = "Snapdragon X NPU"
    $modelAlias = "qwen2.5-7b"; $modelLabel = "Qwen 2.5 7B"
} elseif ($cpuName -match "Intel") {
    $silicon = "Intel"; $chipLabel = "Intel Core Ultra NPU"
    $modelAlias = "phi-4-mini"; $modelLabel = "Phi-4 Mini"
} else {
    $osArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
    if ($osArch -eq [System.Runtime.InteropServices.Architecture]::Arm64) {
        $silicon = "ARM64"; $chipLabel = "ARM64 NPU"; $isARM = $true
        $modelAlias = "qwen2.5-7b"; $modelLabel = "Qwen 2.5 7B"
    } else {
        $silicon = "Intel"; $chipLabel = "Intel Core Ultra NPU"
        $modelAlias = "phi-4-mini"; $modelLabel = "Phi-4 Mini"
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Copilot+ PC - NPU Demo Setup (v2)" -ForegroundColor Cyan
Write-Host "  Detected: $cpuName" -ForegroundColor Cyan
Write-Host "  Platform: $silicon -- $chipLabel" -ForegroundColor Cyan
Write-Host "  Model: $modelLabel ($modelAlias)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Working directory: $ScriptDir" -ForegroundColor Gray

# -------------------------------------------------------------------
# Helper: resolve real Python (skip Microsoft Store stub)
# -------------------------------------------------------------------
function Find-Python {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:ProgramFiles\Python314\python.exe",
        "$env:ProgramFiles\Python313\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "$env:ProgramFiles\Python310\python.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }
    # Last resort: Get-Command, skipping the WindowsApps Store stub
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notlike "*WindowsApps*" } |
        Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    return $null
}

# ============================================================
# Step 1: Python 3.10+
# ============================================================
$pythonExe = $null

Step "Python 3.10+" -Check {
    $script:pythonExe = Find-Python
    if ($script:pythonExe) {
        $v = & $script:pythonExe --version 2>&1
        if ($v -match "Python 3\.1[0-9]") {
            Write-Host " ($v at $script:pythonExe)" -ForegroundColor Gray -NoNewline
            return $true
        }
    }
    return $false
} -Install {
    Write-Host "   Installing Python 3.11 via winget..." -ForegroundColor Cyan
    winget install Python.Python.3.11 --accept-source-agreements --accept-package-agreements --scope user 2>&1 | Select-Object -Last 3 | Out-Host
    # Refresh PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
    # Remove Store stubs if they exist
    $stubs = @(
        "$env:LOCALAPPDATA\Microsoft\WindowsApps\python.exe",
        "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.exe"
    )
    foreach ($s in $stubs) {
        if ((Test-Path $s) -and (Get-Item $s).Length -eq 0) {
            Remove-Item $s -Force -ErrorAction SilentlyContinue
        }
    }
    $script:pythonExe = Find-Python
}

if (-not $pythonExe) {
    Write-Host "[FATAL] Python not found after install. Aborting." -ForegroundColor Red
    Write-Host "   Install Python 3.10+ manually: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# ============================================================
# Step 2: Foundry Local CLI
# ============================================================
Step "Foundry Local CLI" -Check {
    try {
        $v = foundry --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host " ($v)" -ForegroundColor Gray -NoNewline
            return $true
        }
    } catch {}
    return $false
} -Install {
    Write-Host "   Installing Foundry Local via winget..." -ForegroundColor Cyan
    winget install Microsoft.FoundryLocal --accept-source-agreements --accept-package-agreements 2>&1 | Select-Object -Last 3 | Out-Host
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
}

# ============================================================
# Step 3: Python dependencies
# ============================================================
Step "Python dependencies" -Check {
    $r = & $pythonExe -c "import flask, openai, foundry_local, msal, pypdf, docx, yaml, psutil, requests; print('ALL_OK')" 2>&1
    return ($r -match "ALL_OK")
} -Install {
    Write-Host "   Installing from requirements.txt..." -ForegroundColor Cyan
    & $pythonExe -m pip install --upgrade pip 2>&1 | Select-Object -Last 1 | Out-Host
    & $pythonExe -m pip install -r (Join-Path $ScriptDir "requirements.txt") 2>&1 | Select-Object -Last 5 | Out-Host
    # If foundry-local-sdk 1.0.0+ snuck in, downgrade
    $fCheck = & $pythonExe -c "from foundry_local import FoundryLocalManager; print('OK')" 2>&1
    if ($fCheck -notmatch "OK") {
        Write-Host "   foundry_local import failed -- pinning SDK <1.0.0..." -ForegroundColor Yellow
        & $pythonExe -m pip install "foundry-local-sdk>=0.5.0,<1.0.0" 2>&1 | Select-Object -Last 2 | Out-Host
    }
}

# ============================================================
# Step 4: .NET 8 runtime (Vision Service dependency)
# ============================================================
Step ".NET 8 runtime (NETCore + AspNetCore)" -Check {
    $dotnet = "C:\Program Files\dotnet\dotnet.exe"
    if (-not (Test-Path $dotnet)) { return $false }
    $rt = & $dotnet --list-runtimes 2>&1
    $hasBase = $rt -match "Microsoft\.NETCore\.App 8\.0\."
    $hasAsp = $rt -match "Microsoft\.AspNetCore\.App 8\.0\."
    return ($hasBase -and $hasAsp)
} -Install {
    Write-Host "   Installing .NET 8 runtimes via winget..." -ForegroundColor Cyan
    winget install Microsoft.DotNet.Runtime.8 --accept-source-agreements --accept-package-agreements --silent 2>&1 | Out-Null
    winget install Microsoft.DotNet.AspNetCore.8 --accept-source-agreements --accept-package-agreements --silent 2>&1 | Out-Null
}

# ============================================================
# Step 5: Demo data directory
# ============================================================
Step "Demo data (My_Day + Inbox)" -Check {
    return (Test-Path (Join-Path $ScriptDir "demo_data\My_Day\Inbox"))
} -Install {
    Write-Host "   Creating demo data directory..." -ForegroundColor Cyan
    New-Item -Path (Join-Path $ScriptDir "demo_data\My_Day\Inbox") -ItemType Directory -Force | Out-Null
    Write-Host "   [WARN] Add demo data files (calendar.ics, tasks.csv, emails) to demo_data\My_Day\" -ForegroundColor Yellow
}

# ============================================================
# Step 6: Foundry Local SDK import
# ============================================================
Step "Foundry Local SDK import" -Check {
    $r = & $pythonExe -c "from foundry_local import FoundryLocalManager; print('OK')" 2>&1
    return ($r -match "OK")
} -Install {
    Write-Host "   Installing foundry-local-sdk..." -ForegroundColor Cyan
    & $pythonExe -m pip install "foundry-local-sdk>=0.5.0,<1.0.0" 2>&1 | Select-Object -Last 2 | Out-Host
}

# ============================================================
# Step 7: Vision Service MSIX (cert + package)
# ============================================================
$msixTestDir = Join-Path $ScriptDir "vision-service\AppPackages\vision-service_1.0.0.0_x64_Test"
$msixPath = Join-Path $msixTestDir "vision-service_1.0.0.0_x64.msix"

Step "Vision Service MSIX" -Check {
    $pkg = Get-AppxPackage -Name 'Microsoft.NPUDemo.VisionService' -ErrorAction SilentlyContinue
    if ($pkg) {
        Write-Host " (v$($pkg.Version))" -ForegroundColor Gray -NoNewline
        return $true
    }
    return $false
} -Install {
    if (-not (Test-Path $msixPath)) {
        Write-Host "   [SKIP] Pre-built MSIX not found at: $msixPath" -ForegroundColor Gray
        return
    }

    # Find the signing cert (.cer) -- NEVER regenerate, only use bundled certs
    $certFile = $null
    $cerCandidates = @(
        (Join-Path $ScriptDir "vision-service\scripts\FrankBu_Original.cer"),
        (Join-Path $ScriptDir "vision-service\scripts\FrankBu.cer")
    )
    # Also check the MSIX test directory
    $cerCandidates += (Get-ChildItem -Path $msixTestDir -Filter "*.cer" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    foreach ($c in $cerCandidates) {
        if (Test-Path $c) { $certFile = $c; break }
    }

    if (-not $certFile) {
        Write-Host "   [WARN] No .cer file found. Enable Developer Mode as an alternative." -ForegroundColor Yellow
        Write-Host "   Settings > System > For developers > Developer Mode" -ForegroundColor Cyan
        return
    }

    Write-Host "   Using cert: $certFile" -ForegroundColor Gray

    # Install cert to both Trusted Root CA and Trusted People (requires elevation)
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $certInstallScript = @"
`$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2('$certFile')
`$rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', 'LocalMachine')
`$rootStore.Open('ReadWrite'); `$rootStore.Add(`$cert); `$rootStore.Close()
`$peopleStore = New-Object System.Security.Cryptography.X509Certificates.X509Store('TrustedPeople', 'LocalMachine')
`$peopleStore.Open('ReadWrite'); `$peopleStore.Add(`$cert); `$peopleStore.Close()
"@

    if ($isAdmin) {
        try {
            Invoke-Expression $certInstallScript
            Write-Host "   Cert installed to Trusted Root + Trusted People" -ForegroundColor Gray
        } catch {
            Write-Host "   [WARN] Cert install failed: $_" -ForegroundColor Yellow
            return
        }
    } else {
        Write-Host "   Requesting admin elevation for certificate install (UAC prompt)..." -ForegroundColor Cyan
        try {
            $proc = Start-Process powershell -ArgumentList "-NoProfile", "-Command", $certInstallScript -Verb RunAs -Wait -PassThru
            if ($proc.ExitCode -ne 0) {
                Write-Host "   [WARN] Elevated cert install returned exit code $($proc.ExitCode)" -ForegroundColor Yellow
                return
            }
            Write-Host "   Cert installed via elevated prompt" -ForegroundColor Gray
        } catch {
            Write-Host "   [WARN] UAC elevation declined. Vision Service skipped." -ForegroundColor Yellow
            Write-Host "   The app works without it. To install later, run setup.ps1 as Administrator." -ForegroundColor Cyan
            return
        }
    }

    # Verify cert is trusted before MSIX install
    try {
        $certObj = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($certFile)
        $thumb = $certObj.Thumbprint
        $inRoot = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Thumbprint -eq $thumb }
        $inPeople = Get-ChildItem Cert:\LocalMachine\TrustedPeople | Where-Object { $_.Thumbprint -eq $thumb }
        if (-not ($inRoot -and $inPeople)) {
            Write-Host "   [WARN] Cert not in both stores. MSIX install may fail." -ForegroundColor Yellow
        }
    } catch {}

    # Install Windows App Runtime dependency
    try {
        winget install Microsoft.WindowsAppRuntime.1.8 --accept-source-agreements --accept-package-agreements --silent 2>&1 | Out-Null
    } catch {
        $runtimeMsix = Join-Path $msixTestDir "Dependencies\x64\Microsoft.WindowsAppRuntime.1.8.msix"
        if (Test-Path $runtimeMsix) {
            Add-AppxPackage -Path $runtimeMsix -ErrorAction SilentlyContinue
        }
    }

    # Install the MSIX package
    Write-Host "   Installing Vision Service package..." -ForegroundColor Gray
    try {
        Add-AppxPackage -Path $msixPath
    } catch {
        Write-Host "   [WARN] MSIX install failed: $_" -ForegroundColor Yellow
        Write-Host "   Try: Enable Developer Mode (Settings > For developers)" -ForegroundColor Cyan
    }
}

# ============================================================
# Step 8: Pre-download model
# ============================================================
Step "Model cache ($modelLabel)" -Check {
    try {
        $cache = foundry cache ls 2>&1
        return ($cache -match [regex]::Escape($modelAlias))
    } catch { return $false }
} -Install {
    Write-Host "   Pre-downloading $modelLabel ($modelAlias) -- ~2-3 GB..." -ForegroundColor Cyan
    try {
        foundry service start 2>&1 | Out-Null
        Start-Sleep -Seconds 2
        $dlScript = @"
import sys, time
from foundry_local import FoundryLocalManager
print('[Foundry] Initializing...', flush=True)
mgr = FoundryLocalManager('$modelAlias')
print(f'[Foundry] Endpoint: {mgr.endpoint}', flush=True)
t0 = time.time()
try:
    model_id = mgr.download_model('$modelAlias')
    print(f'[Foundry] DONE in {time.time()-t0:.0f}s -- model_id: {model_id}', flush=True)
except Exception as e:
    print(f'[Foundry] FAIL: {type(e).__name__}: {e}', flush=True)
    sys.exit(1)
"@
        & $pythonExe -u -c $dlScript 2>&1 | ForEach-Object {
            if ($_ -match "DONE in") { Write-Host "   $_" -ForegroundColor Green }
            elseif ($_ -match "FAIL:") { Write-Host "   $_" -ForegroundColor Yellow }
            else { Write-Host "   $_" -ForegroundColor Gray }
        }
        foundry service stop 2>&1 | Out-Null
    } catch {
        Write-Host "   [WARN] Model download failed: $_" -ForegroundColor Yellow
        Write-Host "   The app will download on first launch." -ForegroundColor Gray
    }
}

# ============================================================
# Step 9: Patch run.bat with PYTHONPYCACHEPREFIX
# ============================================================
$runBat = Join-Path $ScriptDir "run.bat"

Step "run.bat PYTHONPYCACHEPREFIX" -Check {
    if (-not (Test-Path $runBat)) { return $false }
    return (Select-String -Path $runBat -Pattern 'PYTHONPYCACHEPREFIX' -Quiet)
} -Install {
    if (-not (Test-Path $runBat)) {
        Write-Host "   [SKIP] run.bat not found" -ForegroundColor Gray
        return
    }
    Write-Host "   Patching run.bat to set PYTHONPYCACHEPREFIX..." -ForegroundColor Cyan
    $content = Get-Content $runBat -Raw
    # Insert the SET line before the python launch line
    $content = $content -replace '(python npu_demo_flask\.py)', "SET PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\NPUDemo\__pycache__`r`n`$1"
    Set-Content -Path $runBat -Value $content -NoNewline
}

# ============================================================
# Step 10: Local state directory
# ============================================================
$localStateDir = Join-Path $env:LOCALAPPDATA "NPUDemo"

Step "Local state directory ($localStateDir)" -Check {
    return (Test-Path $localStateDir)
} -Install {
    New-Item -Path $localStateDir -ItemType Directory -Force | Out-Null
}

# ============================================================
# Summary
# ============================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Setup Complete" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Silicon:  $cpuName" -ForegroundColor White
Write-Host "  Platform: $silicon -- $chipLabel" -ForegroundColor White
Write-Host "  Model:    $modelLabel ($modelAlias)" -ForegroundColor White
Write-Host "  Python:   $pythonExe" -ForegroundColor White
Write-Host ""
Write-Host "  Steps: $($script:stepsPassed) installed, $($script:stepsSkipped) skipped, $($script:stepsFailed) failed" -ForegroundColor $(if ($script:stepsFailed -gt 0) { "Yellow" } else { "Green" })
Write-Host ""

if ($script:stepsFailed -gt 0) {
    Write-Host "  Some steps failed. Review the output above." -ForegroundColor Yellow
    Write-Host "  Re-run setup.ps1 after fixing issues -- it will skip completed steps." -ForegroundColor Gray
} else {
    Write-Host "  Next steps:" -ForegroundColor Green
    Write-Host "    1. Verify:  .\verify.ps1" -ForegroundColor Cyan
    Write-Host "    2. Launch:  .\start-demo.ps1" -ForegroundColor Cyan
    Write-Host "    3. Stop:    .\stop-demo.ps1" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Or launch manually:" -ForegroundColor Gray
    Write-Host "    python npu_demo_flask.py              (with D365/Graph tenants)" -ForegroundColor Gray
    Write-Host "    python npu_demo_flask.py --demo-mode  (standalone, no tenants needed)" -ForegroundColor Gray
}
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
