@echo off
echo ============================================
echo  Vision Service — Phi Silica on NPU
echo  localhost:5100
echo ============================================
echo.

cd /d "%~dp0"

REM Check .NET is available
where dotnet >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: .NET SDK not found. Install with: winget install Microsoft.DotNet.SDK.8
    pause
    exit /b 1
)

echo Building vision-service...
dotnet build -c Release --nologo -v q
if %ERRORLEVEL% neq 0 (
    echo.
    echo BUILD FAILED. Check errors above.
    pause
    exit /b 1
)

echo.
echo Starting vision-service on http://localhost:5100 ...
echo.
dotnet run -c Release --no-build
