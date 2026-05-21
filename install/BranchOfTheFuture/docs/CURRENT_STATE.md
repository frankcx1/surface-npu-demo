# Current State Snapshot

Captured on **2026-05-01** (documentation refresh).

## Git State

| Field | Value |
|-------|-------|
| Branch | `banking-demo` |
| Last commit | `ef38c3c` -- "feat: add Marcus Reed persona chat with safety gate (Track A, no LoRA)" |
| Main branch | `main` at `c6071c0` (DEMO_CONFIG layer) |
| Remote | `https://github.com/frankcx1/surface-npu-demo` |

**Uncommitted changes:**
- `.gitignore` -- modified
- `Stop_Waiting_Start_Building.pptx` -- modified binary
- `npu_demo_flask.py` -- progress steps, perf monitor, carbon toggle (uncommitted work)
- `requirements.txt` -- updated dependencies
- `setup.ps1` -- updated setup script
- `vision-service/` -- rebuilt MSIX package, updated cert script

**Untracked files (not committed):**
- Various `.pptx`, `.pdf`, `.png`, `.jpg` presentation and marketing assets
- `zava/` directory with corporate presentation templates and logo variants
- `_create_meetings.py`, `_live_assist_preview.html`, `_ul/` -- scratch files
- `verify.ps1` -- device verification script
- `docs/INSTALL_AUDIT_AND_IMPROVEMENT_PLAN.md` -- new doc

## App Statistics

| Metric | Value |
|--------|-------|
| Lines of code | ~16,400 |
| Flask routes | 69 |
| Sidebar tabs | 6 |
| Test count | 283 across 3 files |
| Brand configs | 3 (Zava, Flagstar, BofA) |
| Personas | 1 (Marcus Reed) |
| Product catalog | 27 products, 13 cross-sell triggers, 5 tiers |
| Demo customers | 3 (Jackie Rodriguez, Marcus Chen, Sarah Henderson) |

## Surface Development Environment

| Component | Version |
|-----------|---------|
| OS | Windows 11 Enterprise 10.0.26200 |
| CPU | Intel Core Ultra 7 268V (Lunar Lake) |
| Python | 3.14.2 |
| Flask | 3.1.2 |
| OpenAI SDK | 2.16.0 |
| Foundry Local SDK | 0.5.1 |
| MSAL | 1.35.1 |
| PyYAML | 6.0.3 |
| psutil | 7.2.2 |
| pypdf | 6.6.2 |
| python-docx | 1.2.0 |
| requests | 2.32.5 |

## What's Running on the Surface

| Component | Purpose | Notes |
|-----------|---------|-------|
| Foundry Local runtime | NPU inference engine | `winget install Microsoft.FoundryLocal` |
| Vision Service MSIX | Phi Silica Vision + TextRewriter | C# MSIX on localhost:5100 |
| Phi Silica models | On-device vision + text rewriting | Provisioned via Windows AI |
| Intel NPU drivers | Lunar Lake NPU hardware | Device-specific |
| Phi-4 Mini model files | ~3GB, cached by Foundry Local | Downloaded on first run |
| MSAL token caches | `.d365_token_cache.json`, `.graph_token_cache.json` | User-specific auth |

## Features Built (Complete)

### Core Platform
- Single-file Flask app with inline HTML/CSS/JS
- Foundry Local SDK integration with NPU/GPU/fallback chain
- Auto-reconnect on Foundry port changes
- Silicon detection via WMI (Intel/Qualcomm)
- Tool-calling shim (`[TOOL_CALL]` markers)
- Warmup overlay on first load

### Six Tabs
1. **Advisor Assistant** -- Agent chat with tool calling, D365 MCP tools, Graph calendar, Marcus Reed persona
2. **Morning Briefing** -- Executive briefing from live Graph calendar/email + local fallbacks
3. **PII Guard** -- Contract review + marketing CELA review, PII scanner, Two-Brain Router
4. **ID & Check Verify** -- Tesseract.js OCR, ID analysis, check deposit, D365 logging, pen signature
5. **Live Assist** -- Real-time meeting copilot, Web Speech API, sentiment analysis, translation
6. **Meeting Notes** -- Voice capture, camera classification, pen annotation, report generation, translation, D365 posting

### Integrations
- Dynamics 365 Dataverse (MSAL device code, customer lookup, transaction logging)
- Microsoft Graph (calendar, email, send mail)
- MCP D365 Server (4 tools: customer lookup, check-in queue, log activity, recent activities)
- Vision Service (Phi Silica Vision classification + TextRewriter email polishing)

### Cross-Tab Features
- Branch Concierge (VIP arrivals, AI greeting briefs, product recommendations)
- Product Recommendations Engine (27 products, 13 triggers, 5 penetration tiers)
- Writing Assistant (Phi Silica TextRewriter + Graph email send)
- YAML Brand Config System (Zava, Flagstar, BofA + switch-brand.cmd)
- Marcus Reed Persona (wealth advisor + financial advice safety gate)
- Performance Monitor (Ctrl+Shift+M, win32pdh, NPU sparkline)
- Demo Hotkeys (Ctrl+Shift+M/C/R)
- Progress Steps UI (progressive checklist for multi-step operations)
- Light Theme Support (Urbanist font, light palette)
- Local AI Savings Widget (cost + CO2 tracking)
- Offline Mode Toggle

### Not Yet Built
- Product Penetration Dashboard (DESIGNED, NOT BUILT)
- Additional personas beyond Marcus Reed

## Known Issues

1. **Model hang on consecutive API calls** -- SLM hangs on tool call + summary in single agent loop. Workaround: dedicated single-step endpoints.

2. **Foundry Local port instability** -- Runtime can restart and bind to new port. `foundry_chat()` wrapper handles this automatically.

3. **Qualcomm warmup crash** -- Rapid warmup pings crash Foundry on QNN NPU. Warmup skipped on Qualcomm.

4. **Flask debug reloader** -- `use_reloader=False` set; delete `__pycache__/` and restart manually.

5. **Camera in airplane mode** -- Camera fails on some devices when fully offline. Use demo presets.

6. **Brand config requires restart** -- `switch-brand.cmd` copies YAML but app must restart (config loaded at module level).

## Last Successful Demo

**NYC Press Demo -- April 30, 2026**
- 18 tech press attendees, demo started ~7 PM ET
- All six tabs demonstrated on Intel Core Ultra Surface Laptop
- 7 calendar meetings created for the demo day via Graph API
- Jackie Rodriguez customer scenario with 529/Roth IRA conversation

**Prior: Bank of America -- April 21, 2026**
- Opened pipeline to 20,000-device/year purchase (4,000 branches, 3-year deal)

## Branch Strategy

- `main` -- stable base with DEMO_CONFIG layer (commit `c6071c0`)
- `banking-demo` -- current active branch with all banking features, 6 tabs, D365, Graph, brand configs
- `zava-bank` -- public-facing fork at `https://github.com/frankcx1/zava-financial-demo`

The `banking-demo` branch has not been merged to `main` and is significantly ahead.

## Test Suite

283 tests across 3 files (all passing):
- `tests/test_phase1.py` -- 190 tests
- `tests/test_phase1_wave2.py` -- 41 tests
- `tests/test_phase2.py` -- 52 tests

Tests mock the OpenAI client at import time and do not require NPU hardware or Foundry Local.
