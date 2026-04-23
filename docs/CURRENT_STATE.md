# Current State Snapshot

Captured on **2026-04-23** for handoff to TheBeast.

## Git State

| Field | Value |
|-------|-------|
| Branch | `banking-demo` |
| Last commit | `4557e60` -- "Update D365 links to new combined app, improve Prep Next Client formatting" |
| Main branch | `main` at `c6071c0` (DEMO_CONFIG layer) |
| Remote | `https://github.com/frankcx1/surface-npu-demo` |

**Uncommitted changes at time of handoff:**
- `CLAUDE.md` -- rewritten for TheBeast handoff (will be committed with this file)
- `Stop_Waiting_Start_Building.pptx` -- modified binary (presentation asset, not code)
- `vision-service/.../vision-service_1.0.0.0_x64.msix` -- rebuilt MSIX package

**Untracked files (not committed):**
- Various `.pptx`, `.pdf`, `.png`, `.jpg` presentation and marketing assets
- `zava/` directory with Zava corporate presentation templates and logo variants
- `docs/ADDING_A_NEW_CAPABILITY.md`, `docs/ZAVA_ADVISOR_PLAN.md` -- new docs (will be committed)

## Surface Development Environment

| Component | Version |
|-----------|---------|
| OS | Windows 11 Enterprise 10.0.26200 |
| CPU | Intel Core Ultra 7 268V (Lunar Lake) |
| Python | 3.14.2 |
| Flask | 3.1.2 |
| OpenAI SDK | 2.16.0 |
| Foundry Local SDK | 0.5.1 |
| Foundry Local runtime | 0.8.119.102 |
| MSAL | 1.35.1 |
| PyYAML | 6.0.3 |
| psutil | 7.2.2 |
| pypdf | 6.6.2 |
| python-docx | 1.2.0 |
| requests | 2.32.5 |
| OpenVINO | 2026.0.0 |
| OpenVINO GenAI | 2026.0.0.0 |
| OpenVINO Tokenizers | 2026.0.0.0 |
| PEFT | 0.18.1 |
| PyTorch | 2.11.0 |

**Note:** OpenVINO, PEFT, and PyTorch are installed on the Surface but are not used by the running app (it uses Foundry Local for inference). They are installed from earlier experimentation. TheBeast will need these for LoRA training.

## What's Installed Locally on Surface (Won't Be on TheBeast)

| Component | Purpose | Notes |
|-----------|---------|-------|
| Foundry Local runtime | NPU inference engine | `winget install Microsoft.FoundryLocal` -- TheBeast doesn't have an NPU |
| Vision Service MSIX | Phi Silica Vision + TextRewriter | C# MSIX on localhost:5100, requires `systemAIModels` capability |
| Phi Silica models | On-device vision + text rewriting | Provisioned via Windows AI, not manually installable |
| Intel NPU drivers | Lunar Lake NPU hardware | Device-specific |
| Phi-4 Mini model files | ~3GB, downloaded by Foundry Local on first run | Cached locally |
| MSAL token caches | `.d365_token_cache.json`, `.graph_token_cache.json` | User-specific auth tokens |

**TheBeast will need:** CUDA toolkit, PyTorch with CUDA support, PEFT library, OpenVINO for export. It does NOT need Foundry Local or the Vision Service.

## Known Issues

No `TODO`, `FIXME`, or `HACK` markers exist in the codebase. Known issues from development:

1. **Model hang on consecutive API calls** -- The SLM hangs when asked to make a tool call and then summarize the result in a single agent loop. Workaround: all complex operations use dedicated single-step endpoints.

2. **Foundry Local port instability** -- The runtime can restart and bind to a new port, especially on Qualcomm. The `foundry_chat()` wrapper (line 643) and `_reconnect_foundry()` (line 615) handle this automatically.

3. **Qualcomm warmup crash** -- On Qualcomm QNN NPU, rapid warmup pings crash the Foundry service. Warmup is skipped on Qualcomm (line 16120); the first real request triggers model load.

4. **Flask debug reloader** -- `use_reloader=False` (line 16193) because the auto-reloader doesn't reliably pick up changes. Delete `__pycache__/` and restart manually.

5. **Camera in airplane mode** -- Camera capture fails on some Surface devices when fully offline. Use demo preset photos instead.

6. **python-pptx 1.0.2 on Python 3.14** -- Can write PPTX but cannot read back (compatibility bug). Write-only approach works.

7. **Brand config requires restart** -- `switch-brand.cmd` copies YAML files but the app must be restarted. Config is loaded once at module level.

## Last Successful Demo Baseline

**Bank of America demo -- April 21, 2026** (2 days ago)

Successfully demoed all six tabs to BofA executives:
- Advisor Assistant with live D365 integration (customer lookup, calendar, check-in queue)
- Morning Briefing with live Microsoft Graph calendar and email
- PII Guard with contract analysis and escalation workflow
- ID & Check Verify with demo Jackie Rodriguez assets
- Live Assist with demo script and real-time AI insight cards
- Meeting Notes with camera classification, pen annotation, report generation, D365 posting

**Outcome:** Opened pipeline to 20,000-device/year purchase (Surface Copilot+ PCs across 4,000 branches, 8 devices per branch, 3-year deal).

The demo was running the Zava Financial brand config (switched from BofA config post-demo). All features were functional on the Intel Core Ultra 7 268V Surface Laptop.

## Test Suite Status

283 tests across 3 files (all passing as of last run):
- `tests/test_phase1.py` -- 190 tests
- `tests/test_phase1_wave2.py` -- 41 tests
- `tests/test_phase2.py` -- 52 tests

Tests mock the OpenAI client at import time and do not require NPU hardware or Foundry Local.

## Branch Strategy

- `main` -- stable base with DEMO_CONFIG layer (commit `c6071c0`)
- `banking-demo` -- current active branch with all banking features, D365, Graph, brand configs
- `zava-bank` -- public-facing fork at `https://github.com/frankcx1/zava-financial-demo`

The `banking-demo` branch has not been merged to `main` and is significantly ahead (banking features, D365, Graph, 6 tabs vs 4 on main).
