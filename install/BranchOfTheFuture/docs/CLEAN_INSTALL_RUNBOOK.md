# Clean Install Runbook

Step-by-step guide for deploying the NPU Demo on a fresh Surface Copilot+ PC.
Covers both Intel Core Ultra and Qualcomm Snapdragon X devices.

**Target time:** 15-20 minutes of mostly-supervised installs (no manual debugging).

**Prerequisite:** Windows 11 24H2 on a Copilot+ PC, signed into a Microsoft account, OneDrive syncing.

---

## Phase 1: Get the code (2 min)

### Option A: OneDrive sync (recommended for Microsoft employees)
The repo is in Frank's OneDrive at `C:\Users\<you>\OneDrive - Microsoft\NPU`.
Wait for OneDrive to sync the full folder (check for cloud icons — all files should show green checkmarks).

### Option B: Git clone
```powershell
git clone https://github.com/frankcx1/surface-npu-demo.git
cd surface-npu-demo
git checkout industry-packs
```

---

## Phase 2: Run setup (10-15 min)

Open PowerShell in the repo directory and run:

```powershell
.\setup.ps1
```

This runs 10 idempotent steps. Each step checks if it's already done before installing.
Watch for `[FAIL]` messages — everything else is fine.

**Expected output on a fresh device:**
```
>> Python 3.10+ [OK]
>> Foundry Local CLI [OK]
>> Python dependencies [OK]
>> .NET 8 runtime (NETCore + AspNetCore) [OK]
>> Demo data (My_Day + Inbox) [SKIP - already done]
>> Foundry Local SDK import [SKIP - already done]
>> Vision Service MSIX [OK]        ← may prompt UAC for cert install
>> Model cache (Phi-4 Mini) [OK]   ← downloads ~2-3 GB on first run
>> run.bat PYTHONPYCACHEPREFIX [OK]
>> Local state directory [OK]
```

**If setup reports failures:**
- Re-run `.\setup.ps1` — it skips completed steps
- Vision Service cert requires elevation — say Yes to the UAC prompt
- If Python install fails, install manually from https://python.org (uncheck "Windows Store" option)

---

## Phase 3: Verify (30 sec)

```powershell
.\verify.ps1
```

All checks should show `[OK]`. Common warnings on a fresh device:
- `[WARN] D365 token cache missing` — expected, use `--demo-mode`
- `[WARN] Graph token cache missing` — expected, use `--demo-mode`
- `[WARN] Vision Service not running` — will start with `start-demo.ps1`

---

## Phase 4: Launch the demo

### Without D365/Graph tenants (most common for new devices):
```powershell
.\start-demo.ps1 --demo-mode
```

### With live D365/Graph:
```powershell
.\start-demo.ps1
```

This starts 3 services in order:
1. Foundry Local (NPU inference runtime)
2. Vision Service (Phi Silica image classification)
3. Flask app (the demo itself)

Then opens http://localhost:5000 in the browser.

**First launch takes 30-90 seconds** for model warmup. Subsequent launches are faster.

---

## Phase 5: Validate (optional, 2 min)

Run the smoke test to exercise all route categories:

```powershell
.\smoke-test.ps1
```

Or with demo-mode if no tenants:
```powershell
.\smoke-test.ps1 --demo-mode
```

Expects 14/14 routes passing.

---

## Phase 6: Stop

```powershell
.\stop-demo.ps1
```

Stops Flask, Vision Service, and Foundry Local.

---

## Switching brands

```cmd
switch-brand.cmd zava           (Zava Financial — default)
switch-brand.cmd flagstar       (Flagstar Bank)
switch-brand.cmd bofa           (Bank of America)
switch-brand.cmd zava-health    (Zava Health — healthcare industry pack)
```

Then restart with `.\start-demo.ps1`.

---

## Demo-mode: what it does

When `--demo-mode` is active:
- Branch Concierge pre-populates 3 demo customers (Jackie, Marcus, Sarah)
- D365 routes return demo data instead of "not authenticated" errors
- Agent chat D365 tools (customer lookup, check-in queue, log activity) use demo data
- "Send Follow-Up Email" returns "saved to drafts" instead of Graph error
- All 6 tabs are fully functional with zero cloud dependencies

When `--demo-mode` is NOT active:
- Behavior is identical to production — live D365/Graph when authenticated
- Falls back to local demo data when APIs are unreachable (same as before)

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `setup.ps1` says Python installed but `python` still opens Store | Close and reopen PowerShell after setup |
| Vision Service won't install | Enable Developer Mode: Settings > System > For developers |
| Model download hangs | Kill and re-run `setup.ps1` -- it will skip completed steps |
| Flask won't start | Run `foundry service stop` then `foundry service start` then retry |
| Stale code after edits | Delete `%LOCALAPPDATA%\NPUDemo\__pycache__\` and restart |
| Brief Me returns empty | Check `demo_data\My_Day\` has calendar.ics, tasks.csv, Inbox\*.eml |
| Camera fails | Use demo preset photos (airplane mode issue — known) |
| Vision Service /health not responding | First launch takes 30-60s -- use `vision-service\scripts\launch-vision.ps1` which polls and reports when ready. Check `C:\temp\vision-service-init.log` if it times out |

---

## Quick reference: demo hotkeys

| Hotkey | Action |
|--------|--------|
| Ctrl+Shift+M | Toggle performance monitor (CPU/GPU/NPU) |
| Ctrl+Shift+C | Toggle carbon/CO2 savings display |
| Ctrl+Shift+R | Hard refresh (clears cache + resets session) |

---

## For Claude Code on target devices

If running Claude Code on the target device to monitor the install:

```
Watch the setup.ps1 output for [FAIL] messages. After setup completes:
1. Run .\verify.ps1 and report any [WARN] or [FAIL]
2. Run .\start-demo.ps1 --demo-mode and verify /health returns ready
3. Run .\smoke-test.ps1 --demo-mode and report pass/fail count
4. If anything fails, read the error message and suggest a fix
```

---

## Intel vs Qualcomm differences

| Aspect | Intel Core Ultra | Qualcomm Snapdragon X |
|--------|-----------------|----------------------|
| Model | Phi-4 Mini (OpenVINO NPU) | Qwen 2.5 7B (QNN NPU) |
| Model size | ~2.2 GB | ~3.5 GB |
| Warmup | Yes (first load 3-10s) | Skipped (first real request loads) |
| Vision Service | x64 native | x64 under emulation |
| Python | x64 native | x64 under emulation |
| Silicon detection | WMI: "Intel" in CPU name | WMI: "Qualcomm"/"Snapdragon" in CPU name |
