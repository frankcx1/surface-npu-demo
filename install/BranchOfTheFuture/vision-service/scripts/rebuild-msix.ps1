# Rebuild, sign, and reinstall vision-service MSIX
# Run from anywhere -- paths are relative to this script's location
$ErrorActionPreference = 'Stop'
$projDir = Split-Path $PSScriptRoot -Parent
$thumbprint = 'D105059461CAEB607A40723E92CBDFB91917A570'

# Find signtool (try common SDK paths)
$signtool = @(
    'C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe'
    'C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe'
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $signtool) { Write-Error "signtool.exe not found -- install Windows SDK"; exit 1 }

Write-Host "Project dir: $projDir"
Write-Host "Signtool: $signtool"

# Remove old output (build places AppPackages at project root)
$appPkgDir = Join-Path $projDir 'AppPackages'
if (Test-Path $appPkgDir) {
    Write-Host "Removing old AppPackages..."
    Remove-Item -Recurse -Force $appPkgDir -ErrorAction SilentlyContinue
}

# Build
Set-Location $projDir
& dotnet publish -c Release -p:GenerateAppxPackageOnBuild=true
if ($LASTEXITCODE -ne 0) { Write-Error "Build failed"; exit 1 }

# Find the MSIX
$msix = Get-ChildItem -Path $appPkgDir -Recurse -Filter '*.msix' |
    Where-Object { $_.Name -notlike '*Runtime*' -and $_.Directory.Name -like '*_Test' } |
    Select-Object -First 1
if (-not $msix) { Write-Error "MSIX not found in $appPkgDir"; exit 1 }
Write-Host "MSIX: $($msix.FullName)"

# Sign
& $signtool sign /fd SHA256 /a /sha1 $thumbprint $msix.FullName
if ($LASTEXITCODE -ne 0) { Write-Error "Signing failed"; exit 1 }

# Uninstall old
$oldPkg = Get-AppxPackage -Name 'Microsoft.NPUDemo.VisionService' -ErrorAction SilentlyContinue
if ($oldPkg) {
    Write-Host "Removing old package..."
    Remove-AppxPackage -Package $oldPkg.PackageFullName
}

# Install framework dependency if needed (stable 1.8 WinAppRuntime)
$depsDir = Join-Path $msix.Directory.FullName 'Dependencies\x64'
if (Test-Path $depsDir) {
    $frameworks = Get-ChildItem $depsDir -Filter '*.msix'
    foreach ($fw in $frameworks) {
        Write-Host "Installing framework: $($fw.Name)..."
        Add-AppxPackage -Path $fw.FullName -ErrorAction SilentlyContinue
    }
}

# Install
Write-Host "Installing..."
Add-AppxPackage -Path $msix.FullName
Write-Host "Installed successfully!"

# Verify
$pkg = Get-AppxPackage -Name 'Microsoft.NPUDemo.VisionService'
Write-Host "PFN: $($pkg.PackageFamilyName)"
Write-Host "Location: $($pkg.InstallLocation)"
