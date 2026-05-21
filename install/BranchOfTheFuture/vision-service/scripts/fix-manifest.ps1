# Post-build: unpack MSIX, patch MaxVersionTested, repack, re-sign
$ErrorActionPreference = 'Stop'
$projDir = Split-Path $PSScriptRoot -Parent
$thumbprint = 'D105059461CAEB607A40723E92CBDFB91917A570'

# Find SDK tools
$sdkBins = @(
    'C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64'
    'C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64'
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $sdkBins) { Write-Error "Windows SDK not found"; exit 1 }
$signtool = Join-Path $sdkBins 'signtool.exe'
$makeappx = Join-Path $sdkBins 'makeappx.exe'

# Find the MSIX
$appPkgDir = Join-Path $projDir 'AppPackages'
$msix = Get-ChildItem -Path $appPkgDir -Recurse -Filter '*.msix' |
    Where-Object { $_.Name -notlike '*Runtime*' -and $_.Directory.Name -like '*_Test' } |
    Select-Object -First 1
if (-not $msix) { Write-Error "MSIX not found -- run rebuild-msix.ps1 first"; exit 1 }
Write-Host "MSIX: $($msix.FullName)"

$unpackDir = Join-Path $env:TEMP 'msix-unpack'

# Unpack
if (Test-Path $unpackDir) { Remove-Item -Recurse -Force $unpackDir }
& $makeappx unpack /p $msix.FullName /d $unpackDir /o
if ($LASTEXITCODE -ne 0) { Write-Error "Unpack failed"; exit 1 }

# Patch MaxVersionTested
$manifest = Join-Path $unpackDir 'AppxManifest.xml'
$content = Get-Content $manifest -Raw
$content = $content -replace 'MaxVersionTested="10\.0\.26100\.0"', 'MaxVersionTested="10.0.26226.0"'
$content = $content -replace 'MinVersion="10\.0\.26100\.0"', 'MinVersion="10.0.22621.0"'
Set-Content $manifest $content -NoNewline
Write-Host "Patched manifest:"
Select-String 'MaxVersionTested|MinVersion' $manifest

# Repack
Remove-Item $msix.FullName
& $makeappx pack /d $unpackDir /p $msix.FullName /o
if ($LASTEXITCODE -ne 0) { Write-Error "Repack failed"; exit 1 }

# Re-sign
& $signtool sign /fd SHA256 /a /sha1 $thumbprint $msix.FullName
if ($LASTEXITCODE -ne 0) { Write-Error "Signing failed"; exit 1 }

# Reinstall
$oldPkg = Get-AppxPackage -Name 'Microsoft.NPUDemo.VisionService' -ErrorAction SilentlyContinue
if ($oldPkg) { Remove-AppxPackage -Package $oldPkg.PackageFullName }
Add-AppxPackage -Path $msix.FullName
Write-Host "Installed!"
