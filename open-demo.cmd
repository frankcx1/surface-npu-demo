@echo off
REM ============================================================
REM  Open Demo Browser — Edge InPrivate with D365 login pre-filled
REM  Just double-click this. MFA with your phone, then you're in.
REM  Account: fbuchholz@D365DemoTSCE32685848.onmicrosoft.com
REM ============================================================

start msedge --inprivate ^
  "https://login.microsoftonline.com/D365DemoTSCE32685848.onmicrosoft.com?login_hint=fbuchholz%%40D365DemoTSCE32685848.onmicrosoft.com" ^
  "http://localhost:5000" ^
  "https://orgdf28000a.crm.dynamics.com/main.aspx?appid=e386e65f-ec29-f111-8342-002248357e0e&pagetype=genux&id=6e691a49-650c-419f-8177-3d0e41c38cd8" ^
  "https://orgdf28000a.crm.dynamics.com/main.aspx?appid=aedf8383-df29-f111-8342-002248357e0e&forceUCI=1&pagetype=entityrecord&etn=contact&id=5cdc2c3f-ad29-f111-8342-002248357e0e"
