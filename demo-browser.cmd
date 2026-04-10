@echo off
REM ============================================================
REM  Flagstar Demo Launcher — one-click full environment startup
REM  1. Vision service (MSIX)
REM  2. Flask app + Foundry model load (new terminal window)
REM  3. Edge InPrivate with 5 tabs (login pre-filled for MFA)
REM ============================================================

echo [1/3] Launching Vision Service (Phi Silica MSIX)...
powershell -Command "& { $shell = New-Object -ComObject Shell.Application; $shell.ShellExecute('shell:AppsFolder\Microsoft.NPUDemo.VisionService_r0xr04974zwaa!App') }"

echo [2/3] Starting Flask app + loading model on NPU...
start "NPU Demo - Flask" cmd /k "cd /d %~dp0 && python npu_demo_flask.py"

echo [3/3] Waiting for Flask app to be ready...
:wait_loop
timeout /t 5 /nobreak >nul
powershell -Command "try { (Invoke-WebRequest -Uri http://localhost:5000/health -UseBasicParsing -TimeoutSec 3).StatusCode } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo        Still loading model...
    goto wait_loop
)
echo        App is ready!

echo [3/3] Opening Edge InPrivate (5 tabs)...
REM Tab 1: Microsoft login with Frank's acct pre-filled (MFA only)
REM Tab 2: NPU Demo app
REM Tab 3: D365 Customer 360 dashboard
REM Tab 4: D365 Jackie Rodriguez contact
REM Tab 5: Outlook Calendar
start msedge --inprivate ^
  "https://login.microsoftonline.com/D365DemoTSCE32685848.onmicrosoft.com?login_hint=fbuchholz%%40D365DemoTSCE32685848.onmicrosoft.com" ^
  "http://localhost:5000" ^
  "https://orgdf28000a.crm.dynamics.com/main.aspx?appid=e386e65f-ec29-f111-8342-002248357e0e&pagetype=genux&id=6e691a49-650c-419f-8177-3d0e41c38cd8" ^
  "https://orgdf28000a.crm.dynamics.com/main.aspx?appid=aedf8383-df29-f111-8342-002248357e0e&forceUCI=1&pagetype=entityrecord&etn=contact&id=5cdc2c3f-ad29-f111-8342-002248357e0e" ^
  "https://outlook.cloud.microsoft/calendar/view/workweek"

echo.
echo Demo environment launched. Flask console is in the other window.
