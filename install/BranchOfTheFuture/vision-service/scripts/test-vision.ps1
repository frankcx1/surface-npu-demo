# Quick test: run any image through the vision service
# Usage: .\test-vision.ps1 path\to\image.jpg
param([string]$ImagePath)

if (-not $ImagePath -or -not (Test-Path $ImagePath)) {
    Write-Host "Usage: .\test-vision.ps1 <path-to-image>"
    Write-Host "Example: .\test-vision.ps1 C:\temp\water_damage.jpg"
    exit 1
}

Write-Host "`n=== Phi Silica Vision Test ===" -ForegroundColor Cyan
Write-Host "Image: $ImagePath"
Write-Host "Size: $((Get-Item $ImagePath).Length / 1KB) KB`n"

# Health check
Write-Host "--- /health ---" -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri http://localhost:5100/health -TimeoutSec 5
    Write-Host "Status: $($health.status)" -ForegroundColor Green
} catch {
    Write-Host "Vision service not running! Launch it first:" -ForegroundColor Red
    Write-Host "  .\launch-vision.ps1"
    exit 1
}

# Describe
Write-Host "`n--- /describe (detailed) ---" -ForegroundColor Yellow
$desc = curl.exe -s -X POST http://localhost:5100/describe -F "image=@$ImagePath" -F "kind=detailed" | ConvertFrom-Json
Write-Host "Description: $($desc.description)`n"

# Classify
Write-Host "--- /classify ---" -ForegroundColor Yellow
$cls = curl.exe -s -X POST http://localhost:5100/classify -F "image=@$ImagePath" | ConvertFrom-Json
Write-Host "Category:   $($cls.category)" -ForegroundColor Green
Write-Host "Severity:   $($cls.severity)"
Write-Host "Confidence: $($cls.confidence)%"
Write-Host "Explanation: $($cls.explanation)`n"
Write-Host "Raw description: $($cls.raw_description)`n"

# Extract text
Write-Host "--- /extract-text ---" -ForegroundColor Yellow
$txt = curl.exe -s -X POST http://localhost:5100/extract-text -F "image=@$ImagePath" | ConvertFrom-Json
Write-Host "Extracted text: $($txt.text)`n"
