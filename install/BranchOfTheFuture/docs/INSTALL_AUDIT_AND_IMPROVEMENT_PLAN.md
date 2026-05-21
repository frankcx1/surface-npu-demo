# New-Device Install Audit & Improvement Plan

**Captured:** 2026-04-28, after a clean Surface Pro setup for an NYC PR demo (Apr 30, 2026).
**Scope:** Everything we touched to take a brand-new Intel Core Ultra 5 Surface Pro (Win 11 Pro, build 26200) from "out of the box" to "Branch of the Future demo running, all 6 tabs functional, D365 + Graph + Vision Service live."

---

## 1. Goal of this document

1. Capture the chronological install steps and **every issue we hit** (so the next setup doesn't relive them).
2. Propose concrete improvements ranked by impact/effort.
3. Account for the **OneDrive shared-folder constraint** — at least two demo devices (Surface Laptop, Surface Pro) now run the app from the same synced directory.

---

## 2. Chronological install — what actually happened

| # | Step | What ran | Result |
|---|------|---------|--------|
| 1 | Detect environment | WMI CPU probe, OS version, arch | ✅ Intel Core Ultra 5 338H, Win11 26200, x64 |
| 2 | Verify Python / Foundry / git | `python --version`, `foundry --version`, `git --version` | Python missing (Store stub), Foundry missing, git ✅ |
| 3 | Run `setup.ps1` (background) | Auto Python + Foundry + pip + Vision Service + model | Partial — see issues below |
| 4 | Investigate `[WARN] Foundry Local SDK import failed` (Step 6 of setup.ps1) | Manual probe | pip had installed to a phantom interpreter, not the new Python |
| 5 | Re-install pip deps to the right interpreter | `python.exe -m pip install -r requirements.txt msal` | ✅ but pulled `foundry-local-sdk 1.0.0` which renamed the import → app broken |
| 6 | Pin foundry-local-sdk | `pip install foundry-local-sdk==0.5.1` | ✅ `from foundry_local import` works |
| 7 | Pre-download Phi-4 Mini | Manual `mgr.download_model('phi-4-mini')` | ✅ ~2.2 GB cached on NPU (setup.ps1 had silently completed this earlier — output was Out-Null'd) |
| 8 | Patch app for missing LoRA | Edit `npu_demo_flask.py:658-680` | ✅ Probe + fallback to stock Phi-4 Mini |
| 9 | Patch fallback to use full MODEL_ID | One-line fix in same block | ✅ Chat returned 200 |
| 10 | D365 silent reauth | `POST /d365/authenticate` | ✅ refreshed from OneDrive-synced cache |
| 11 | Graph silent reauth | Direct `_graph_get_token()` probe | ✅ same |
| 12 | Smoke test 6 tabs | `/`, `/chat`, `/brief-me`, `/d365/customer-lookup` | ✅ all green |
| 13 | Vision Service cert mismatch | setup-cert.ps1 had **overwritten** `FrankBu.cer` with a NEW local cert; original `D105...` cert wasn't trusted | Required manual recovery |
| 14 | Recover original cert | Surface Laptop exported `D105...` public cert → OneDrive → import on Pro | ✅ cert in Trusted Root + TrustedPeople |
| 15 | Add-AppxPackage | Direct PowerShell call after Dev Mode toggled on | ✅ MSIX registered |
| 16 | Launch Vision Service | `shell:AppsFolder\...!App` URI | ❌ crashed — needs .NET 8 runtime |
| 17 | Install ASP.NET Core 8 | `winget install Microsoft.DotNet.AspNetCore.8` | ✅ AspNetCore 8.0.26 + base 8.0.21 |
| 18 | Service still crashed | App needs base NETCore.App 8.0.26, not 8.0.21 | Need to bump base runtime |
| 19 | Install base .NET 8.0.26 | `winget install Microsoft.DotNet.Runtime.8 --version 8.0.26` | ✅ both runtimes at 8.0.26 |
| 20 | Relaunch Vision Service | shell:AppsFolder URI | ✅ `/health` returns 200, `phi_silica_available: true`, `writing_assistant_available: true` |

**Total wall time:** ~2 hours of clock time (most of it me investigating the silent failures, not actual install time).

---

## 3. Issues encountered — root causes

### 3.1 Python install never escaped the Microsoft Store stub
- winget installed Python 3.11 to `%LOCALAPPDATA%\Programs\Python\Python311\` and added it to user PATH, but the Microsoft Store **App Execution Alias** for `python` intercepted bare `python` calls.
- **Result:** `python --version` returned the Store stub even after install. Anything in setup.ps1 calling bare `python` after the install hit the wrong (or non-existent) interpreter.

### 3.2 setup.ps1 reported "[OK] Python dependencies installed" without verifying
- Step 3 of setup.ps1 runs `pip install -r requirements.txt 2>&1 | Out-Null` and only reports failure on `$LASTEXITCODE -ne 0`. It does NOT verify that the packages are importable from the right interpreter.
- **Result:** False-positive green checkmark even when packages went to a phantom interpreter.

### 3.3 `foundry-local-sdk>=0.5.0` resolved to 1.0.0 — breaking change
- The 1.0.0 release renamed the package import from `foundry_local` to `foundry_local_sdk`.
- The app code uses the old import name, so `ModuleNotFoundError` at startup.
- `requirements.txt` constraint is open-ended (`>=0.5.0`), so every new device picks up the broken version.

### 3.4 setup.ps1 Step 8 silently consumed the model-download output
- The model-download python `-c` invocation pipes through implicit Out-Null. No progress, no completion signal in the human-readable log.
- **Result:** Looked like a 30-minute hang. Was actually fine.

### 3.5 setup-cert.ps1 OVERWRITES `FrankBu.cer` in OneDrive
- On a device that doesn't already have a `CN=FrankBu` cert in `Cert:\CurrentUser\My`, `setup-cert.ps1` generates a NEW self-signed cert with a fresh thumbprint and **exports it to `vision-service/scripts/FrankBu.cer` regardless of whether one already exists**.
- The MSIX in OneDrive was signed by the Surface Laptop's `D105...` cert. The new device's cert is `069A...`. After overwrite:
  - The OneDrive `.cer` no longer matches the MSIX signature → MSIX won't install.
  - Surface Laptop's MSIX trust depends on its **cert store**, not the .cer file, so it survived. But this was lucky.
- The setup.ps1 hardcoded thumbprint check (`D105...`) is also fragile — if anyone ever rotates the cert, the check fails permanently.

### 3.6 Foundry Local v0.8+ rejects bare aliases in chat completions
- `client.chat.completions.create(model="phi-4-mini", ...)` returns HTTP 400 with empty body.
- Must pass the resolved full ID (`phi-4-mini-instruct-openvino-npu:3`).
- The app already does this correctly at startup but it's a footgun for anyone adding new code or fallback paths (I bit on this myself during the LoRA fallback patch).

### 3.7 Marcus LoRA model swap was unconditional
- App sets `DEFAULT_MODEL = phi-4-mini-zava-openvino-npu:1` whenever `configs/personas/marcus_reed.yaml` loads, with no check that the LoRA is actually registered in Foundry Local.
- The LoRA only exists on the Surface Laptop where it was trained.
- Any new device syncing the YAML via OneDrive will fail at `/chat` until manually patched (which we did, lines 658–680).

### 3.8 Vision Service is .NET 8 (not in default Win 11 image)
- The MSIX is a published .NET 8 ASP.NET Core app. Win 11 ships without .NET 8.
- Worse: the published runtimeconfig pins to specific minor versions (8.0.26 today). winget's `Microsoft.DotNet.AspNetCore.8` brought down 8.0.26 for AspNetCore but only 8.0.21 for the base NETCore.App — needed both packages installed at the matching minor.

### 3.9 Vision Service requires Developer Mode OR a chain-trusted cert
- A self-signed cert never chains to a public root. To install MSIX without Dev Mode, the cert must be in **both** `Cert:\LocalMachine\Root` AND `Cert:\LocalMachine\TrustedPeople`.
- Even with Dev Mode on, the cert that signed the MSIX must still be trusted (we hit this).

### 3.10 MSAL token caches sync across devices via OneDrive
- `.d365_token_cache.json` and `.graph_token_cache.json` are in the project root, gitignored, but **NOT** OneDrive-excluded.
- Today this saved us — both silently reauth'd from the Surface Laptop's tokens.
- Tomorrow it's a race condition: if both devices try to refresh at the same time, the loser overwrites the winner's tokens.

---

## 4. Proposed changes — by tier

### Tier 1 — bug fixes to existing scripts (low risk, ship before next install)

| Fix | File | Change |
|----|------|--------|
| Pin `foundry-local-sdk` | `requirements.txt` | `foundry-local-sdk>=0.5.0,<1.0.0` (or `==0.5.1` outright) |
| Disable Python Store stub | `setup.ps1` Step 1 | After winget install, programmatically remove the App Execution Aliases for `python.exe` and `python3.exe` (delete the 0-byte stub files in `%LOCALAPPDATA%\Microsoft\WindowsApps\`) or instruct user to do it |
| Resolve full Python path before pip | `setup.ps1` Step 3 | Cache `$pythonExe = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'` and use `& $pythonExe -m pip ...` instead of bare `pip` |
| Don't silence pip output | `setup.ps1` Step 3 | Drop `2>&1 \| Out-Null`. Show last 5 lines on success, full output on failure |
| Verify install before declaring success | `setup.ps1` Step 3 | After pip, run `& $pythonExe -c "import flask, openai, foundry_local, msal, pypdf, docx, yaml, psutil, requests; print('ALL_OK')"` and only print `[OK]` if it returns ALL_OK |
| Don't overwrite `FrankBu.cer` if it exists | `setup-cert.ps1` | Wrap `Export-Certificate` in `if (-not (Test-Path $certPath))`. If a cert file is already there with a different thumbprint, log a warning and skip — don't clobber. |
| Remove hardcoded thumbprint | `setup.ps1` Step 7 | Replace the `D105...` thumbprint check with: read the .cer file, extract its thumbprint, check that thumbprint is in both stores. Self-discovering. |
| Surface model download progress | `setup.ps1` Step 8 | Don't pipe to Out-Null. Print a one-line progress every 10 seconds via a polling loop, OR call `mgr.download_model()` with the SDK's progress callback if 0.5.1 supports it |
| Probe Marcus LoRA before swap | `npu_demo_flask.py:658-680` | **Already done** in the patch we shipped today. Commit it. |
| Add `.NET 8.0.26+ runtime` step to setup.ps1 | new step before Vision Service | `winget install Microsoft.DotNet.Runtime.8` AND `winget install Microsoft.DotNet.AspNetCore.8`, both at the version Vision Service was built against |

### Tier 2 — process changes (medium effort, big payoff for repeat installs)

#### 2.1 Add a `verify.ps1` "doctor" script
A single command that runs in <30 seconds and reports the health of every dependency:
- Python on PATH, version
- Foundry Local CLI version + service running
- Phi-4 Mini in cache
- Vision Service installed + `/health` responding
- D365 + Graph token state (live, expired, missing)
- Brand config name + sanity check
- Disk space, network reachable

Run before every demo. Catches silent regressions (cert near-expiry, runtime upgrade broke something) before they bite during the live demo.

#### 2.2 Convert setup.ps1 into idempotent steps with explicit checks
Today's setup.ps1 reports `[OK]` on a flag like "the install command exited 0", but doesn't verify the *actual outcome*. Pattern to flip to:

```powershell
function Step ($name, [scriptblock]$check, [scriptblock]$install) {
    Write-Host "▶ $name..." -NoNewline
    if (& $check) { Write-Host " [SKIP, already done]" -F Green; return $true }
    & $install
    if (& $check) { Write-Host " [OK]" -F Green; return $true }
    Write-Host " [FAIL]" -F Red
    return $false
}
```

Now every step is "assert the desired state, install if not, re-assert." Re-running setup.ps1 is safe and only does the work that's actually needed.

#### 2.3 Detect and exclude the Microsoft Store Python stubs early
Add a one-liner that, on detection of stubs at `%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe` etc., either deletes them (preserving the user's choice) or prepends the real Python path with absolute path to PATH for the rest of the script.

### Tier 3 — structural improvements (nontrivial refactor, big payoff for OneDrive cohabitation)

#### 3.1 Move device-specific state out of the project directory
Every file that's "this device only" should live in `%LOCALAPPDATA%\NPUDemo\`, NOT in the OneDrive-synced repo:

| File | Today | Proposed |
|------|-------|----------|
| `.d365_token_cache.json` | repo root | `%LOCALAPPDATA%\NPUDemo\d365_token_cache.json` |
| `.graph_token_cache.json` | repo root | `%LOCALAPPDATA%\NPUDemo\graph_token_cache.json` |
| `.azure-foundry.env` | repo root (ACL'd, but still synced) | `%USERPROFILE%\.npudemo\foundry.env` (truly per-user) |
| `__pycache__/*.pyc` | wherever Python writes them (in repo) | Set `PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\NPUDemo\__pycache__\` in `run.bat` and `start-demo.ps1` |
| `vision-service/scripts/FrankBu.cer` | repo, OneDrive-synced, can be overwritten | Cert store only — never write the .cer back to the repo |

Code change: add a `LOCAL_STATE_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'NPUDemo')` constant in `npu_demo_flask.py`. Update `_D365_CACHE_FILE`, `_GRAPH_CACHE_FILE`, etc. to default to that. Migration: detect old paths at startup, copy once, log the migration.

#### 3.2 Stop self-signing dev certs; use Developer Mode + unsigned MSIX
Self-signed certs break in three ways:
- Expire (`D105...` expires Feb 2027 — silent failure date)
- Don't transfer between devices without manual export/import
- Get accidentally rotated by setup-cert.ps1

Alternatives:
- (a) **Buy a real code-signing cert** (Sectigo/DigiCert OV cert, ~$200/year). Trusted on every Windows device by default. No cert install step needed. Highest cost, lowest friction.
- (b) **Embrace Developer Mode + unsigned MSIX**. Modify `vision-service` build to skip signing in Debug/Test configs. Add `Add-AppxPackage -AllowUnsigned` to the install script. Requires Win 11 22H2+. Lowest cost, requires Dev Mode toggle each install.
- (c) **Ship the MSIX dependencies inside the package.** Bundle the .cer next to the MSIX in the repo (committed to git, NOT just OneDrive-only) and have `setup.ps1` read it from the bundled location, never regenerate. Mid cost, mid friction. **My recommendation for the next 90 days** — costs nothing, is most compatible with current state.

#### 3.3 Distribute the Phi-4 Mini Zava LoRA via a manifest
Right now the LoRA model lives only on the Surface Laptop and any device without it falls back to stock Phi-4 Mini (Track A). To make Track B (LoRA) the default, we need a way to ship the model to new devices:
- **Option A:** TheBeast publishes a signed manifest + download URL. `setup.ps1` reads the manifest, downloads the model files, registers them in Foundry Local. Closest to a "single click install."
- **Option B:** Use git-lfs for the OpenVINO IR files. ~2 GB of LFS quota required. Cheap but rate-limited.
- **Option C:** Manual copy via `tailscale scp` (per CLAUDE.md). Works but requires another machine.

This is gated on actually finishing Track B's LoRA training and producing publishable artifacts. Don't build the distribution pipeline before the model is real.

### Tier 4 — aspirational (single installer)

True "one EXE/MSI install" is unrealistic for this stack. Hard requirements that block a self-contained installer:
- **Foundry Local** is a separate Microsoft product with its own installer. Can't bundle without redistribution license.
- **Phi-4 Mini model files** are 2.2 GB — too big for any installer payload without first-run download.
- **.NET 8 runtime** — bundling a self-contained .NET app would 3x the MSIX size. The framework-dependent layout we have today is the right tradeoff.
- **D365 + Graph OAuth** is per-user, must be interactive at least once.
- **Phi Silica provisioning** (per `docs/QUICK_START.md` Step 3) — Microsoft requires a one-time activation in VS Code AI Toolkit. Out of our control.

What IS realistic:
- A `setup.ps1` that, once Tier 1 + Tier 2 fixes are in, completes a clean install in <10 minutes with explicit checks at each step and zero false-positive `[OK]` markers.
- A self-extracting wrapper EXE built with `iexpress.exe` or 7-zip SFX that bundles `setup.ps1` + the repo zip + a manifest of dependencies. Runs `setup.ps1` after extraction. Looks like an "EXE installer" to the end user even though it's not really.

This is the realistic ceiling. **Don't promise an MSI.**

---

## 5. OneDrive cross-device cohabitation — explicit rules

The repo is now synced across at least two demo devices. Treat the OneDrive folder as **shared mutable state**.

### 5.1 Files that MUST NOT live in the OneDrive folder
- MSAL token caches (Tier 3.1 fix)
- Per-device cert files (Tier 3.2 fix)
- `.azure-foundry.env` if its ACLs are honored (move to `%USERPROFILE%\.npudemo\`)
- `__pycache__/` (set `PYTHONPYCACHEPREFIX`)

### 5.2 Files that are intentionally shared (don't move)
- Source code, configs, demo data — git is the source of truth, OneDrive is just a faster sync mechanism than git for binary edits in flight.

### 5.3 Concurrent-access risk
- If both devices run the Flask app at the same time, they will both try to write logs and cache files to the same OneDrive paths. Today the app writes nothing transient (good), but anything we add must respect this.
- **Rule:** Any new feature that writes runtime state must either go to `%LOCALAPPDATA%\NPUDemo\` or be guarded with a "this device's PID owns this file" check.

### 5.4 What about memory and CLAUDE.md?
- The harness memory at `~/.claude/projects/.../memory/` is **per-device** and NOT in OneDrive. Memory entries saved on Surface Pro do NOT show up on Surface Laptop. Mirror critical lessons to `<repo>/docs/` if you want both Claude Code sessions to know them.
- `CLAUDE.md` IS in OneDrive and is shared correctly.

---

## 6. Recommended next steps (in order)

1. **Commit the Marcus LoRA fallback patch** in `npu_demo_flask.py:658-680`. Without it, every new device install breaks at `/chat`.
2. **Pin `foundry-local-sdk` in `requirements.txt`** to `>=0.5.0,<1.0.0`. Pure prevention, no risk.
3. **Refactor `setup-cert.ps1`** to never overwrite an existing `.cer` and to commit the `.cer` to git (not just OneDrive). This makes the cert deterministic and shareable.
4. **Fix `setup.ps1` Step 3** to use the resolved Python path and verify imports before declaring success.
5. **Add `.NET 8.0.26+ runtime` step** to setup.ps1 ahead of Vision Service install.
6. **Build `verify.ps1`** ("doctor" script). Run before every demo.
7. **Move token caches and pycache out of the project dir** (Tier 3.1). One-time refactor, eliminates the OneDrive race risk forever.
8. (Optional, if doing Track B distribution) Plan the LoRA manifest pipeline.

If we ship items 1–5 before the next clean install, the next setup should be 15–20 minutes of mostly-supervised winget installs with no manual debugging. That's the pragmatic ceiling without a real code-signing cert.

---

## 7. Appendix — what we CAN'T change

- **Foundry Local must be installed separately.** Microsoft product, not bundlable.
- **Phi-4 Mini must be downloaded on first run** (~2.2 GB). Can be pre-warmed but not skipped.
- **Vision Service needs .NET 8 runtime.** Either install separately or self-contained-publish (3x size).
- **D365 + Graph need OAuth device-code flow at least once.** Token refresh is silent thereafter.
- **Phi Silica provisioning may need VS Code AI Toolkit step** (per `docs/QUICK_START.md`). Out of our control.
- **MSIX requires a trusted signing cert OR Developer Mode toggle.** No way around either.

These are upstream constraints. Plan the install flow around them, don't fight them.
