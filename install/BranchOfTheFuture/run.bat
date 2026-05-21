@echo off
title Copilot+ PC - NPU Demo
echo.
echo ============================================================
echo   Copilot+ PC - NPU Demo
echo   Powered by Foundry Local + Phi-4 Mini
echo   (Auto-detects Intel Core Ultra / Snapdragon X)
echo ============================================================
echo.

:: Resolve Python: prefer path saved by setup.ps1, fall back to bare python
set PYEXE=python
if exist "%~dp0.python_path.txt" (
    set /p PYEXE=<"%~dp0.python_path.txt"
)

:: Check Python
"%PYEXE%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Run setup.ps1 first.
    echo         Or install Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check Flask
"%PYEXE%" -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing dependencies...
    "%PYEXE%" -m pip install -r "%~dp0requirements.txt"
    echo.
)

:: Verify demo data exists in repo (app reads from demo_data/ directly)
if not exist "%~dp0demo_data\My_Day" (
    echo [WARN] demo_data\My_Day not found. Demo data ships with the repo.
    echo.
)

echo Starting NPU Demo on http://localhost:5000
echo Press Ctrl+C to stop.
echo.

:: Keep __pycache__ out of OneDrive-synced folder
SET PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\NPUDemo\__pycache__

:: Launch the app
cd /d "%~dp0"
"%PYEXE%" npu_demo_flask.py

pause
