# CLAUDE.md -- Project Guide for Claude Code

## What This Is

A single-file Flask demo app (`npu_demo_flask.py`, ~16,200 lines) that showcases on-device AI running on NPU hardware via Microsoft's Foundry Local runtime. The app is branded and demoed to enterprise banking customers as "Branch of the Future," proving that a Surface Copilot+ PC can run a full AI advisor workstation with zero cloud dependencies and zero data egress.

The app auto-detects silicon at startup (Intel Core Ultra vs Qualcomm Snapdragon X) and selects the appropriate model variant. It ships as a self-contained repo with demo data, bundled fonts, and Tesseract.js for OCR.

**Primary use case:** Live, in-person executive demos for bank CXOs. This is a sales tool, not a product.

## Architecture

```
Browser (localhost:5000)
    |
Flask backend (npu_demo_flask.py)
    |
    +-- Foundry Local runtime (dynamic port, discovered via SDK)
    |       |
    |       +-- Phi-4 Mini (Intel, OpenVINO NPU)
    |       +-- Qwen 2.5 7B (Qualcomm, QNN NPU)
    |
    +-- Vision Service (localhost:5100, C# MSIX)
    |       |
    |       +-- Phi Silica Vision (image classification)
    |       +-- TextRewriter (email polishing)
    |
    +-- Microsoft Graph API (calendar, email -- optional, live)
    +-- Dynamics 365 Dataverse API (CRM data -- optional, live)
    +-- MCP D365 Server (mcp-d365/server.py, 4 tools)
```

**Key principle:** Everything runs on-device by default. Graph and D365 are optional live integrations that fall back gracefully to local demo data when offline.

## Entry Point and Boot Sequence

**File:** `npu_demo_flask.py` -- there is no `main.py`, no `app/` package, no blueprints. Everything is in one file.

**Start:** `python npu_demo_flask.py` (optionally with `--demo-mode` to bypass offline checks)

**Boot sequence** (all at module level, lines 1-16193):
1. Load `demo_config.yaml` and `product_catalog.yaml` from app root (lines 26-91)
2. Fall back to hardcoded `DEMO_CONFIG` dict if YAML/pyyaml missing (line 491)
3. Detect silicon via WMI `Win32_Processor` (line 533, `detect_silicon()`)
4. Select model: `phi-4-mini` (Intel) or `qwen2.5-7b` (Qualcomm) (line 578)
5. Initialize Foundry Local: NPU -> GPU -> localhost:5272 fallback chain (line 586)
6. Create Flask app, configure upload folder (line 527)
7. Define all routes (69 `@app.route` decorators)
8. In `__main__` block (line 16079): warmup model, build knowledge index, start keepalive thread, run Flask on 127.0.0.1:5000

## File Layout

| Path | Purpose |
|------|---------|
| `npu_demo_flask.py` | The entire app: Python backend + HTML template + CSS + JS, all inline |
| `demo_config.yaml` | Active brand config (loaded at startup, swappable per customer) |
| `product_catalog.yaml` | Product catalog for cross-sell recommendations (27 products, 13 triggers) |
| `configs/zava/` | Zava Financial brand config files |
| `configs/flagstar/` | Flagstar Bank brand config files |
| `configs/bofa/` | Bank of America brand config files |
| `switch-brand.cmd` | Copies config files from `configs/<brand>/` to root, requires restart |
| `demo_data/` | All demo data (calendar .ics, tasks .csv, emails .eml, documents, photos) |
| `demo_data/My_Day/` | Morning Briefing data: `calendar.ics`, `tasks.csv`, `Inbox/*.eml` |
| `demo_data/inspection_photos/` | Demo photos for Meeting Notes camera/classification |
| `vision-service/` | C# ASP.NET Core microservice (Phi Silica Vision + TextRewriter) |
| `mcp-d365/server.py` | MCP server exposing D365 Dataverse as 4 tools |
| `tests/` | Test suite: `test_phase1.py` (190), `test_phase1_wave2.py` (41), `test_phase2.py` (52) |
| `fonts/` | Urbanist font files for light-theme branding |
| `tesseract/` | Bundled Tesseract.js for client-side OCR |
| `docs/` | Technical docs, demo scripts, field inspection workflow, marketing |
| `setup.ps1` | Automated setup script for new devices |
| `run.bat` | Simple launcher |

**There are no** `/static`, `/templates`, `/app`, or `/services` directories. The HTML template is a raw string literal (`HTML_TEMPLATE`, starting at line 1468) embedded in the Python file. CSS is in a `<style>` tag within that template. JavaScript is inline in `<script>` blocks. Static assets (logos, fonts, Tesseract) are served via dedicated Flask routes (lines 10216-10303).

## Silicon Detection (Critical Rule)

**Function:** `detect_silicon()` at line 533.

On Windows-on-ARM, Python x64 runs under emulation, so `platform.machine()` and `PROCESSOR_ARCHITECTURE` both report `AMD64`/`X64` -- they are **not** reliable. The app uses WMI as the authoritative source:

```python
# Authoritative: WMI CPU name
result = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "(Get-CimInstance Win32_Processor).Name"],
    capture_output=True, text=True, timeout=5,
)
```

If "qualcomm" or "snapdragon" appears in the CPU name, the app uses `qwen2.5-7b`. Otherwise, it defaults to `phi-4-mini` on Intel.

**Rule:** Never use `platform.machine()` or env vars to detect ARM64. Always use WMI.

## Foundry Local SDK (Critical Rule)

**The pip package `foundry-local` (v0.0.1) is a squatted fake.** The real SDK is `foundry-local-sdk`.

The SDK manages Foundry Local's lifecycle. The runtime starts on a dynamic port -- never hardcode a port. Always use the SDK's discovered endpoint:

```python
from foundry_local import FoundryLocalManager
manager = FoundryLocalManager(MODEL_ALIAS)
client = OpenAI(base_url=manager.endpoint, api_key=manager.api_key)
```

**Fallback chain** (lines 586-609):
1. Try NPU variant via `FoundryLocalManager(MODEL_ALIAS)`
2. If NPU fails (driver issue), try GPU: `FoundryLocalManager(MODEL_ALIAS, device=DeviceType.GPU)`
3. If both fail, fall back to `http://localhost:5272/v1`

**Auto-reconnect:** `foundry_chat()` wrapper (line 643) catches connection errors and calls `_reconnect_foundry()` which re-discovers the endpoint. Foundry Local's port can change when the service restarts.

## Model Usage

| Silicon | Model | Alias | Context | Notes |
|---------|-------|-------|---------|-------|
| Intel Core Ultra | Phi-4 Mini | `phi-4-mini` | ~4K tokens | OpenVINO NPU, reliable |
| Qualcomm Snapdragon X | Qwen 2.5 7B | `qwen2.5-7b` | ~4K tokens | QNN NPU, needs special handling |
| Intel/Qualcomm | Phi Silica Vision | N/A | N/A | Via Vision Service (localhost:5100), image classification |
| Intel/Qualcomm | Phi Silica TextRewriter | N/A | N/A | Via Vision Service, email polishing |

**All inference goes through the OpenAI-compatible API** provided by Foundry Local. The `foundry_chat()` wrapper (line 643) should be used for all model calls -- it handles reconnection.

**Token budget constraints:**
- Max output: ~1,536 tokens
- Max input: ~1,000 tokens (~4K chars)
- Data payloads compressed to hard cap of 3,600 chars (see `compress_for_briefing()`, line 1007)
- Never send raw PowerShell output to the model -- only pre-computed ratings text

## The Six Tabs

The UI is a sidebar + main content layout (`.app-shell` > `.sidebar` + `.main-content`). Sidebar nav items are `<a class="sidebar-nav-item" data-tab="KEY">` tags defined in the HTML template starting at line 3439. Each tab's content is a `<div id="KEY-tab" class="tab-content">` block. Tab switching is handled by JavaScript `data-tab` click handlers.

### Tab 1: Advisor Assistant (`chat`)
Chat interface with tool-calling AI agent. Uses `[TOOL_CALL]` marker shim (Phi doesn't have native tool calling). Tools: read/write/exec (local), D365 MCP tools (d365_customer_lookup, d365_check_in_queue, d365_log_activity, d365_recent_activities), calendar tools (my_calendar_today, prep_next_client). Suggestion chips: My Calendar, Prep Next Client, Customer Queue, Outlook/Office.
- **Route:** `POST /chat` (line 11969)
- **Tool parser:** `parse_tool_call()` (line 1059), regex for `[TOOL_CALL]...[/TOOL_CALL]`
- **Tool executor:** `execute_tool()` (line 1091)
- **PowerShell allowlist:** `_ALLOWED_COMMANDS` (line 1051): get-childitem, get-content, set-content, etc.

### Tab 2: Morning Briefing (`day`)
Executive morning briefing synthesized from calendar, email, and task data. Data sources: Microsoft Graph API (live Outlook calendar + email) with fallback to local files (`demo_data/My_Day/`).
- **Routes:** `POST /brief-me` (line 14371), `POST /triage-inbox` (line 14478), `POST /prep-next-meeting` (line 14527), `POST /top-3-focus` (line 14600), `POST /tomorrow-preview` (line 14645)
- **Parsers:** `parse_ics()` (line 903), `parse_tasks_csv()` (line 957), `parse_eml()` (line 970)

### Tab 3: PII Guard / Auditor (`auditor`)
Dual-mode compliance analysis:
- **Contract/Legal Review:** Structured NDA risk analysis with smart escalation to frontier model
- **Marketing/Campaign Review:** CELA compliance check, document-first architecture, progressive reveal
- **Routes:** `POST /router/analyze` (line 13767), `POST /router/decide` (line 14161)
- **PII scanner:** `_scan_pii()` (line 13563) -- detects SSNs, emails, phones, person names
- **Redaction:** `_redact_text()` (line 13744) -- replaces findings with `[REDACTED Type]` before any cloud escalation

### Tab 4: ID & Check Verify (`id`)
On-device document verification with two modes (ID scan and check deposit):
- Camera capture or demo preset images
- Client-side OCR via Tesseract.js
- AI analysis of extracted text
- D365 integration for check deposits (logs to customer timeline)
- Pen signature canvas with pressure sensitivity
- **Routes:** `POST /analyze-id` (line 12895), `POST /analyze-check` (line 13026), `POST /signature/verify` (line 13436)

### Tab 5: Live Assist (`live`)
Real-time meeting copilot:
- Web Speech API for live voice transcription (or 19-line demo script fallback)
- AI insight cards generated during conversation (buffered, deduped)
- Sentiment analysis per utterance
- Post-session translation (EN/ES)
- **Routes:** `POST /live-assist/analyze` (line 15433), `POST /live-assist/translate` (line 15501)

### Tab 6: Meeting Notes (`field`)
Post-meeting workflow (originally "Field Inspection"):
- Voice/text capture with field extraction
- Camera + document classification (demo presets or live via Vision Service)
- Pen annotation on documents
- Report generation (Client Meeting Summary)
- Translation (EN/ES)
- D365 posting (logs meeting notes to customer timeline)
- Escalation workflow for low-confidence classifications
- **Routes:** `POST /inspection/transcribe` (line 14817), `POST /inspection/classify` (line 14919), `POST /inspection/report` (line 15147), `POST /inspection/translate` (line 15356), `POST /inspection/annotate` (line 15036)

## Brand Configuration System

The app is white-labeled per customer using YAML config files:

- `demo_config.yaml` -- brand colors, tab names, icons, personas, advisor info, demo script
- `product_catalog.yaml` -- product list, cross-sell triggers, penetration tiers
- `configs/<brand>/` directories hold per-customer variants (zava, flagstar, bofa)
- `switch-brand.cmd <brand>` copies configs to root (requires app restart)

At startup, `_load_yaml_config()` (line 26) reads the YAML. If pyyaml is missing or the file doesn't exist, the app falls back to a hardcoded `DEMO_CONFIG` dict (line 491, Flagstar defaults).

The `index()` route (line 10771) does ~40 `.replace()` calls to inject config values as template variables (`{{APP_TITLE}}`, `{{BRAND_ACCENT}}`, `{{TAB_CHAT_NAME}}`, etc.) into `HTML_TEMPLATE`.

Light theme is activated when `brand_theme: "light"` in config. `_build_theme_overrides()` (line 10305) generates CSS overrides for the light palette.

## Key Integrations (Optional, Live)

### Dynamics 365
- MSAL device code flow, token cached in `.d365_token_cache.json`
- Org URL: configurable (`_D365_ORG_URL`, line 262)
- Functions: `_d365_get_token()` (line 268), `_d365_api_get()` (line 337), `_d365_api_post()` (line 362)
- All D365 routes fall back to demo data if the API is unreachable

### Microsoft Graph
- App registration with Calendars.ReadWrite, Mail.ReadWrite, Mail.Send, User.Read
- Token cached in `.graph_token_cache.json`
- Functions: `_graph_get_token()` (line 397), `_graph_get_calendar_today()` (line 433), `_graph_get_recent_emails()` (line 462)

### MCP D365 Server
- Standalone server at `mcp-d365/server.py` (FastMCP framework)
- 4 tools: `d365_customer_lookup`, `d365_check_in_queue`, `d365_log_activity`, `d365_recent_activities`
- Shares MSAL token cache with main app

### Vision Service
- C# ASP.NET Core at `vision-service/`, MSIX-packaged, runs on localhost:5100
- Endpoints: `/health`, `/describe`, `/classify`, `/extract-text`, `/rewrite`
- Uses Phi Silica Vision (`Microsoft.Windows.AI.Imaging`) and TextRewriter (`Microsoft.Windows.AI.Text`)
- Requires `systemAIModels` capability and LAF token

### Azure Foundry Credentials

- **File:** `.azure-foundry.env` in repo root -- **NOT in git** (matched by `*.env` in `.gitignore`, ACL-locked to local user)
- **Contains:** Two Azure Foundry deployment endpoints (GPT-5.4 and Claude Opus 4.7) and a shared API key. Do not read, paste, or log this file's contents.
- **Used for:** Pilot corpus generation for LoRA training. The corpus builder script (future, on TheBeast) calls these deployments as scenario planner/generator (GPT-5.4) and judge (Claude Opus 4.7) to produce high-quality training pairs.
- **Not used on Surface** -- this file is only consumed by the training pipeline on TheBeast.
- **To regenerate:** Any Claude Code session with `az` CLI auth to the `surhub.onmicrosoft.com` tenant can regenerate this file.
- **Transfer to TheBeast:** `tailscale scp` (TheBeast is not corp-trusted, so OneDrive sync is not available). Copy to the same relative path in TheBeast's local repo clone.

## Security Measures

1. **File system jailing:** All read/write via `_path_in_demo_dir()` (line 1081) -- `os.path.realpath()` validation against `DEMO_DIR`
2. **PowerShell allowlist:** `_ALLOWED_COMMANDS` (line 1051) -- only approved cmdlets
3. **Network binding:** Flask on `127.0.0.1` only (line 16193)
4. **Path traversal prevention:** Static file routes reject `..` and validate realpath
5. **Upload restrictions:** Extension allowlist `{.pdf, .docx, .txt, .md}`, `secure_filename()`, 16MB limit (line 528)
6. **PII redaction:** `_scan_pii()` + `_redact_text()` before any data leaves the device

## Tool-Calling Shim (Critical Pattern)

Phi-4 Mini and Qwen 2.5 do **not** support native tool calling. The app uses a prompt-based shim:

1. System prompt defines available tools with `[TOOL_CALL]` markers (line 847, `AGENT_SYSTEM_PROMPT`)
2. Model outputs `[TOOL_CALL]{"name":"...", "arguments":{...}}[/TOOL_CALL]`
3. `parse_tool_call()` (line 1059) extracts the JSON via regex
4. `execute_tool()` (line 1091) runs the tool, returns result
5. Result is fed back to the model for a natural-language summary

**Known limitation:** The model hangs when making consecutive API calls (tool decision -> followup summary). Solution: use dedicated single-step endpoints instead of the agent loop for complex operations.

## Running the App

```bash
python npu_demo_flask.py
```

**Prerequisites:**
- Windows 11 on Copilot+ PC (Intel Core Ultra or Qualcomm Snapdragon X)
- Foundry Local installed: `winget install Microsoft.FoundryLocal`
- Python 3.10+ with packages from `requirements.txt`
- Run `setup.ps1` on a new device to install everything

**Key packages (requirements.txt):**
- `flask>=3.0.0` -- web framework
- `openai>=1.0.0` -- OpenAI-compatible client for Foundry Local
- `foundry-local-sdk>=0.5.0` -- Foundry Local control plane SDK (NOT `foundry-local`)
- `pyyaml>=6.0` -- YAML config loading
- `psutil>=5.9.0` -- system performance monitoring
- `pypdf>=4.0.0`, `python-docx>=1.0.0` -- document text extraction
- `requests>=2.31.0` -- HTTP client for Graph/D365

**Optional (not in requirements.txt):**
- `msal` -- for live D365 and Graph authentication

## Testing

Tests mock the OpenAI client and Foundry Local at import time (no NPU required):

```bash
python -m pytest tests/ -v
```

283 tests across 3 files. Tests patch `openai.OpenAI` before importing `npu_demo_flask`, then use Flask's test client to verify routes, HTML elements, and response structures.

## Common Debugging

| Problem | Solution |
|---------|----------|
| Model hangs on second API call | Use dedicated single-step endpoints, not the agent loop |
| Foundry connection lost | `foundry_chat()` auto-reconnects; check Foundry Local is running |
| Flask serving stale code | Delete `__pycache__/npu_demo_flask.cpython-*.pyc` and restart |
| Brand changes not showing | Run `switch-brand.cmd <brand>` and restart the Flask app |
| Markdown not rendering | Apply `mdToHtml()` to all code paths rendering model output |
| Model hallucinating file paths | Use dedicated endpoints that control paths directly |

## Handoff Context

This repo is developed across two machines:

- **Surface Laptop** -- the target deployment device where the app is demoed on real NPU hardware. This is the source of truth for what runs in production.
- **TheBeast** -- dev and training workstation (dual RTX 3090s) where LoRA adapters are trained and OpenVINO exports are compiled. This is the source of truth for training artifacts and compiled models.

Git is the sync mechanism. When working on TheBeast, assume the Surface is the source of truth for what runs in production. When working on the Surface, assume TheBeast is the source of truth for training artifacts and compiled models.

See `docs/ZAVA_ADVISOR_PLAN.md` for the current extension work.
See `docs/ADDING_A_NEW_CAPABILITY.md` for how to add a new tab or feature.
See `docs/CURRENT_STATE.md` for the state of the repo at the time of the TheBeast handoff.
