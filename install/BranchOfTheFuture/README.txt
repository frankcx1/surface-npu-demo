INSTALLING THE BRANCH OF THE FUTURE DEMO
=========================================

This guide walks you through installing the NPU Demo ("Branch of the Future")
on a fresh Surface Copilot+ PC. Total time: ~15-20 minutes, mostly waiting
for downloads.


WHAT YOU NEED
-------------
- Surface Copilot+ PC (Intel Core Ultra or Qualcomm Snapdragon X)
- Windows 11 24H2 (build 26100 or later)
- Internet connection for initial setup (app runs fully offline after that)
- No admin account required (setup prompts UAC once for the Vision Service cert)


STEP 1: GET THE FILES ONTO THE DEVICE
--------------------------------------

Option A -- USB thumbdrive (fastest):
  Copy the entire "BranchOfTheFuture" folder from the thumbdrive to
  C:\BranchOfTheFuture

Option B -- OneDrive:
  If you're on a Microsoft account with access to Frank's OneDrive, the repo
  is at: C:\Users\<you>\OneDrive - Microsoft\NPU
  Wait for OneDrive to fully sync (all files should show green checkmarks,
  not cloud icons).

Option C -- Git clone:
  git clone https://github.com/frankcx1/surface-npu-demo.git C:\BranchOfTheFuture
  cd C:\BranchOfTheFuture
  git checkout industry-packs


STEP 2: RUN SETUP (~10-15 min)
-------------------------------

Open PowerShell in the folder and run:

  .\setup.ps1

This installs everything automatically in 11 idempotent steps (safe to re-run
anytime):

  Step                  What it does                            Time
  --------------------  --------------------------------------  ----------
  Python 3.11           Installs via winget                     1-2 min
  Foundry Local CLI     AI runtime for NPU inference            ~1 min
  Python dependencies   pip install from requirements.txt       ~1 min
  .NET 8 runtime        Required by Vision Service              1-2 min
  Demo data             Verifies calendar/email/task data       instant
  Foundry SDK           Python SDK for Foundry Local            instant
  Vision Service        MSIX package + signing cert (UAC)       ~1 min
  Model download        Phi-4 Mini (~2-3 GB) via Foundry CLI    5-10 min
  run.bat patch         Keeps __pycache__ out of OneDrive       instant
  Local state dir       Creates %LOCALAPPDATA%\NPUDemo          instant
  Python path           Saves resolved Python path for run.bat  instant

What to expect:
  - Each step prints [OK], [SKIP - already done], or [FAIL]
  - The model download step shows a progress bar with ETA
  - You'll get one UAC prompt for the Vision Service certificate -- click Yes
  - A UTF-8 log is saved to %TEMP%\botf_setup.log

If a step fails: Just re-run .\setup.ps1. It skips everything already done.


STEP 3: VERIFY (30 seconds)
----------------------------

  .\verify.ps1

Everything should show [OK]. These warnings are normal on a fresh device:
  - [WARN] D365 token cache missing -- expected, use --demo-mode
  - [WARN] Graph token cache missing -- expected, use --demo-mode


STEP 4: LAUNCH THE DEMO
------------------------

  .\start-demo.ps1 --demo-mode

This starts three services in order:
  1. Foundry Local -- NPU inference runtime
  2. Vision Service -- Phi Silica image classification (first launch: 30-60s)
  3. Flask app -- the demo itself at http://localhost:5000

The browser opens automatically. First launch takes 30-90 seconds for model
warmup.

Use --demo-mode unless you have D365/Graph credentials configured. Demo mode
provides full functionality with local sample data.


STEP 5: STOP THE DEMO
----------------------

  .\stop-demo.ps1


SWITCHING BRANDS
----------------

The demo white-labels per customer. To switch:

  switch-brand.cmd zava           (Zava Financial -- default)
  switch-brand.cmd flagstar       (Flagstar Bank)
  switch-brand.cmd bofa           (Bank of America)

Then restart with .\start-demo.ps1 --demo-mode


DEMO HOTKEYS
-------------

  Ctrl+Shift+M    Toggle performance monitor (CPU/GPU/NPU utilization)
  Ctrl+Shift+C    Toggle carbon/CO2 savings display
  Ctrl+Shift+R    Hard refresh (clears cache + resets session)


TROUBLESHOOTING
---------------

setup.ps1 won't run
  Run: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser

Python opens the Microsoft Store
  Close and reopen PowerShell after setup (PATH refresh needed)

Model download hangs
  Kill and re-run setup.ps1 -- it skips completed steps

Vision Service /health not responding
  First launch takes 30-60s. Run vision-service\scripts\launch-vision.ps1 to
  see live status. Check C:\temp\vision-service-init.log if it times out.

Flask won't start
  Run: foundry service stop
  Then: foundry service start
  Then retry.

Camera doesn't work
  Use demo preset photos (camera requires browser permission + may not work
  in airplane mode)

Everything works offline?
  Yes! That's the point. Turn on Airplane Mode for the demo.


USING CLAUDE CODE TO HELP WITH THE INSTALL
-------------------------------------------

Claude Code can monitor the install for you. Recommended approach:

  1. "Run .\setup.ps1 in the background"
  2. "Monitor %TEMP%\botf_setup.log for errors or warnings"
  3. "/loop 2m give me a one-line install status update"

This gives you background execution + real-time error alerts + periodic
summaries while you do other things.

After setup finishes, ask Claude Code to:

  Run .\verify.ps1 and report any issues, then run
  .\start-demo.ps1 --demo-mode and verify http://localhost:5000 loads
  and http://localhost:5100/health returns OK


QUESTIONS?
----------

Contact Frank Bu (frankbu@microsoft.com) or check the full docs in the
docs\ folder:
  - docs\CLEAN_INSTALL_RUNBOOK.md  -- detailed install reference
  - docs\QUICK_START.md            -- demo walkthrough
  - docs\PARTNER_DEMO_TALK_TRACK.md -- talk track for customer demos
