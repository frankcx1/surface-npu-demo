# Branch of the Future — On-Device AI for Banking

A white-labeled demo application showcasing on-device AI capabilities using the Neural Processing Unit (NPU) on Microsoft Surface Copilot+ PCs. Built for live, in-person executive demos to bank CXOs, proving that a single Surface device can run a full AI advisor workstation with zero cloud dependencies and zero data egress.

Supports **Intel Core Ultra** (Lunar Lake / Panther Lake) with auto-detection at startup. Optional live integrations with Microsoft Graph and Dynamics 365 fall back gracefully to local demo data when offline.

**100% local processing — your data never leaves the device.**

---

## Features

### Six Tabs

| Tab | Description |
|-----|-------------|
| **Advisor Assistant** *(default)* | Chat interface with tool-calling AI agent, D365 CRM integration, and optional Marcus Reed wealth advisor persona |
| **Morning Briefing** | Executive morning briefing from live Outlook calendar/email (via Graph) or local demo data |
| **PII Guard** | Dual-mode compliance analysis: contract/NDA risk analysis + marketing CELA compliance review |
| **ID & Check Verify** | Camera capture + OCR + AI parsing of driver licenses and checks, with D365 deposit logging and pen signature |
| **Live Assist** | Real-time meeting copilot with voice transcription, AI advisor insight cards, and sentiment analysis |
| **Meeting Notes** | Post-meeting workflow with voice/text capture, document classification, pen annotation, reports, translation, and D365 posting |

---

### Tab 1: Advisor Assistant

AI-powered chat agent with tool-calling capabilities:

| Feature | Detail |
|---------|--------|
| **Agent tools** | File read/write, PowerShell exec, D365 customer lookup, check-in queue, activity logging, calendar, meeting prep |
| **Marcus Reed persona** | When Zava Financial brand is active, chat routes through a wealth advisor persona with retirement/estate/college savings specialization and a financial advice safety gate |
| **Device Intelligence** | 9 PowerShell health checks + AI summary, 28 security checks + weighted grading, natural language file search |
| **Document workflow** | Upload PDF/DOCX/TXT/MD, AI summarization, PII detection |

### Tab 2: Morning Briefing

| Feature | What it does |
|---------|-------------|
| **Brief Me** | Cross-references calendar, emails, and tasks into an executive briefing with ACTIONS, PEOPLE TO KNOW, KEY WARNINGS |
| **Top 3 Focus** | AI identifies three highest-priority items |
| **Tomorrow Preview** | Next day schedule overview |
| **Triage Inbox** | Categorizes emails into URGENT / ACTION NEEDED / FYI |
| **Prep for Next Meeting** | Generates prep brief with attendee profiles and talking points |

**Live data:** When Microsoft Graph is connected, pulls real Outlook calendar events and inbox emails. Falls back to local `.ics`, `.csv`, and `.eml` demo files when offline.

### Tab 3: PII Guard

#### Contract / Legal Review
Structured risk analysis of contracts and NDAs with clause-by-clause assessment, risk levels, and escalation recommendations.

#### Marketing / Campaign Review
CELA compliance check using document-first architecture — AI reads the full document and identifies claims, then renders verdict (SELF-SERVICE OK / CELA INTAKE REQUIRED).

**PII scanner** detects SSNs, emails, phone numbers, and person names. Redacts before any escalation to frontier models. Two-Brain Router handles local-first analysis with optional cloud escalation via explicit consent.

### Tab 4: ID & Check Verify

| Mode | Flow |
|------|------|
| **ID Verification** | Camera capture → Tesseract.js OCR → AI field extraction (name, DOB, address, expiration, validity) |
| **Check Deposit** | Camera capture → OCR → AI verification (amount, routing, account) → D365 transaction logging → pen signature |

All OCR runs locally via bundled Tesseract.js — no CDN dependency.

### Tab 5: Live Assist

Real-time meeting copilot:
- **Voice transcription** via Web Speech API (or 19-turn demo script fallback)
- **AI insight cards** generated in real-time from transcript chunks (1-3 actionable bullets, max 12 words each)
- **Sentiment analysis** per utterance (POSITIVE / NEUTRAL / CAUTIOUS)
- **Post-session translation** (EN/ES)

### Tab 6: Meeting Notes

Post-meeting workflow with seven capabilities:
1. **Voice/text capture** — Win+H dictation or scripted input → AI extracts client, location, products, source
2. **Camera + classification** — Three-tier fallback: Phi Silica Vision → demo presets → Phi-4 Mini text
3. **Pen annotation** — Dual-canvas overlay with pressure-sensitive ink
4. **Report generation** — AI generates Client Meeting Summary with risk rating and next steps
5. **Translation** — EN/ES language toggle
6. **D365 posting** — Log meeting notes to customer timeline
7. **Escalation workflow** — Dialog on low-confidence classifications

---

### Cross-Tab Features

| Feature | Description |
|---------|-------------|
| **Branch Concierge** | VIP arrival awareness system — bell icon, arrivals panel with tier badges, AI greeting briefs with product recommendations |
| **Product Recommendations** | Rule-based cross-sell engine: 27 products, 13 triggers, 5 penetration tiers from `product_catalog.yaml` |
| **Writing Assistant** | Email polishing via Phi Silica TextRewriter + sending via Microsoft Graph |
| **Performance Monitor** | `Ctrl+Shift+M` overlay showing live CPU/GPU/NPU/memory stats via win32pdh |
| **Brand Config System** | White-label per customer: colors, logos, tab names, advisor identity, personas, demo script |
| **Offline Mode** | Go Offline / Go Online toggle — works with Airplane Mode for clean room demos |
| **Local AI Savings Widget** | Cost saved + CO2 avoided vs cloud inference |
| **Demo Hotkeys** | `Ctrl+Shift+M` (perf), `Ctrl+Shift+C` (carbon toggle), `Ctrl+Shift+R` (reset) |
| **Audit Trail** | Every tool execution logged with timestamp, tool, args, result, elapsed time |

---

## Architecture

```
Browser (localhost:5000)
    |
Flask backend (npu_demo_flask.py, ~16,400 lines, single file)
    |
    +-- Foundry Local runtime (dynamic port, discovered via SDK)
    |       |
    |       +-- Intel: Phi-4 Mini on Core Ultra NPU (OpenVINO)
    |       +-- Qualcomm: Qwen 2.5 7B on Snapdragon X NPU (QNN)
    |
    +-- Vision Service (localhost:5100, C# MSIX)
    |       |
    |       +-- Phi Silica Vision (image classification, OCR)
    |       +-- Phi Silica TextRewriter (email polishing)
    |
    +-- Microsoft Graph API (calendar, email, send mail -- optional)
    +-- Dynamics 365 Dataverse API (CRM, customer lookup -- optional)
    +-- MCP D365 Server (mcp-d365/server.py, 4 tools -- optional)
```

- **No cloud dependencies** — everything runs on-device; Graph/D365 are optional live integrations
- **OpenAI-compatible API** — standard chat completions interface via Foundry Local SDK
- **Auto-detection** — WMI CPU name as authoritative source (not `platform.machine()`)
- **Single file** — Python backend + HTML/CSS/JS all inline in `npu_demo_flask.py`

---

## Brand Configuration

The app is white-labeled per customer. Three brands ship in the repo:

| Brand | Theme | Advisor | Persona |
|-------|-------|---------|---------|
| **Zava Financial** | Light teal (#183D4C) | Sarah Chen | Marcus Reed (wealth advisor) |
| **Flagstar Bank** | Orange (#f18f12) | Alan Thornbury | — |
| **Bank of America** | Navy (#012169) | Michael Torres | — |

**Switch brands:**
```cmd
switch-brand.cmd zava       # or: flagstar, bofa
# Then restart the Flask app
```

Each brand has its own `demo_config.yaml` with colors, logos, tab names, advisor identity, personas, demo script, and industry context. See `docs/TECHNICAL_GUIDE.md` for the full config structure.

---

## Persona System

The app supports AI personas — domain-specialized advisor characters with distinct knowledge, tone, and compliance guardrails.

**Marcus Reed** (Zava Financial):
- Senior Wealth Advisor specializing in retirement, estate planning, college savings
- Warm, consultative tone; plain English; asks clarifying questions before recommending
- **Financial advice safety gate** blocks rate quotes, fund tickers, tax filing advice, and dollar projections
- Defined in `configs/personas/marcus_reed.yaml`

When the Zava brand is active, the chat tab automatically routes through Marcus. The safety gate runs post-processing on every response to ensure compliance with banking regulations.

See `docs/TECHNICAL_GUIDE.md` and `docs/ADDING_A_NEW_CAPABILITY.md` for how to add new personas.

---

## Quick Start

**New to this?** See the **[Quick Start Guide for Non-Developers](docs/QUICK_START.md)** — step-by-step instructions with no coding required.

### Prerequisites

- Windows 11 24H2 on a Copilot+ PC (Intel Core Ultra or Snapdragon X)
- Python 3.10+
- Foundry Local (`winget install Microsoft.FoundryLocal`)

### Option 1: One-Click Setup

1. Run `setup.ps1` (installs Python, Foundry Local, dependencies, and Vision Service)
2. Double-click `run.bat`
3. Open http://localhost:5000

### Option 2: Manual Setup

```powershell
pip install -r requirements.txt
python npu_demo_flask.py
```

On first run, Foundry Local downloads the model (~3 GB). Subsequent launches start in seconds.

**Important:** The pip package `foundry-local` (v0.0.1) is a squatted fake. The real SDK is `foundry-local-sdk`.

---

## Files

| File | Description |
|------|-------------|
| `npu_demo_flask.py` | Main app (~16,400 lines: Python + HTML + CSS + JS, single file) |
| `demo_config.yaml` | Active brand config (YAML, loaded at startup) |
| `product_catalog.yaml` | Product catalog for cross-sell recommendations |
| `configs/` | Per-customer brand configs (zava, flagstar, bofa) + persona definitions |
| `switch-brand.cmd` | Brand switching script |
| `run.bat` | One-click launcher |
| `setup.ps1` | First-time device setup script |
| `requirements.txt` | Python dependencies |
| `vision-service/` | C# Phi Silica Vision microservice (MSIX, localhost:5100) |
| `mcp-d365/server.py` | MCP server for D365 Dataverse (4 tools) |
| `tests/` | Test suites (283 tests across 3 files) |
| `demo_data/` | Demo calendar, emails, tasks, contracts, inspection photos |
| `fonts/` | Urbanist font files for light-theme branding |
| `tesseract/` | Offline OCR engine (Tesseract.js + English training data) |
| `docs/` | Technical guide, demo scripts, capability docs |

---

## Demo Flow

### Advisor Assistant (Default Tab)
1. Chat with the AI agent — try "Prep Next Client" or "Customer Queue" chips
2. Upload a document → click **Summarize** or **Detect PII**
3. If Zava brand: meet Marcus Reed, the wealth advisor persona

### Morning Briefing
1. Click **Brief Me** — AI cross-references calendar, emails, and tasks
2. Click **Top 3 Focus** for prioritized action items
3. Click **Triage** to categorize inbox

### PII Guard
1. Choose **Contract / Legal Review** or **Marketing / Campaign Review**
2. Go offline (sidebar toggle) for clean room compliance demo
3. Upload or load a demo document — watch progressive analysis

### ID & Check Verify
1. Select camera → **Capture** → position ID or check
2. **Analyze** — 3-step pipeline runs entirely on-device
3. For checks: view D365 customer profile, sign with pen, log deposit

### Live Assist
1. Click **Start Voice** or **Run Demo Script**
2. Watch AI insight cards appear in real-time
3. Monitor sentiment analysis per utterance
4. Translate session to Spanish

### Meeting Notes
1. Dictate notes (Win+H) or use scripted input → AI extracts fields
2. Capture or load demo photos → AI classifies with confidence scores
3. Annotate photos with pen → AI extracts notes
4. Generate report → translate → post to D365

### The "Wow" Moment
1. **Turn on Airplane Mode**
2. Repeat any demo above
3. **Everything still works** — the AI never needed the cloud

---

## Technical Details

| Detail | Value |
|--------|-------|
| **Framework** | Flask (Python), single file |
| **AI Runtime** | Foundry Local SDK (dynamic endpoint) |
| **Text Model (Intel)** | Phi-4 Mini (OpenVINO, NPU) |
| **Text Model (Qualcomm)** | Qwen 2.5 7B (QNN, NPU) |
| **Vision Model** | Phi Silica Vision (Windows App SDK 1.8) |
| **Text Rewriter** | Phi Silica TextRewriter (Windows App SDK 1.8) |
| **OCR** | Tesseract.js 5.1.1 (browser, bundled locally) |
| **CRM** | Dynamics 365 Dataverse (MSAL device code, optional) |
| **Calendar/Email** | Microsoft Graph API (optional) |
| **MCP Server** | FastMCP with 4 D365 tools |
| **Tool Calling** | Text-based `[TOOL_CALL]` shim |
| **Token Budget** | ~1,000 input tokens, 1,536 max output |
| **Endpoints** | 69 Flask routes |
| **Tabs** | 6 configurable tabs |
| **Products** | 27 products, 13 cross-sell triggers, 5 penetration tiers |
| **Tests** | 283 tests across 3 test files |
| **Brands** | 3 (Zava, Flagstar, BofA) with YAML config switching |
| **Personas** | 1 (Marcus Reed) with safety gate |

---

## Performance

| Operation | Typical Latency | Power Draw |
|-----------|----------------|------------|
| Brief Me | 40-50s | ~5W sustained |
| Agent chat (simple) | 5-10s | ~5W |
| Security Audit (28 checks + AI) | ~32s | ~5W |
| Marketing CELA review | 15-35s | ~5W |
| OCR (Tesseract.js) | 3-8s | Varies (CPU/WASM) |
| Live Assist: analyze | 5-10s | ~5W |
| Meeting Notes: report | 10-20s | ~5W |
| Email polish (TextRewriter) | 3-8s | ~5W |
| Greeting brief (concierge) | 5-10s | ~5W |
| Product recommendations | <1s | Rule engine |

Energy: ~0.06 Wh per briefing (~0.1% of a 58 Wh battery).

---

## Security

| Measure | Detail |
|---------|--------|
| **File system jailing** | All read/write restricted to `demo_data/` via `os.path.realpath()` |
| **PowerShell allowlist** | Only approved cmdlets for agent tool calls |
| **Network binding** | Flask on `127.0.0.1` only |
| **Path traversal prevention** | Static routes reject `..` and validate realpath |
| **Upload restrictions** | Extension allowlist, `secure_filename()`, 16 MB limit |
| **PII scanner** | Detects SSNs, emails, phones, names; redacts before escalation |
| **Financial advice gate** | Blocks rate quotes, fund tickers, tax advice in persona mode |
| **Approval gates** | Destructive agent actions require explicit user approval |
| **Audit trail** | Every tool execution logged |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Connection refused" | Foundry Local may still be starting — wait 10-15s and retry |
| Model not responding | Restart the app — Foundry Local reinitializes |
| Brief Me timeout | Normal on first run while model loads |
| Camera not detected | Check browser permissions, try different camera |
| OCR quality poor | Improve lighting, hold document flat |
| Stale code after edits | Delete `__pycache__/npu_demo_flask.cpython-*.pyc` and restart |
| Brand changes not showing | Run `switch-brand.cmd <brand>` and restart |
| Vision Service not responding | Check MSIX installed and running |
| D365/Graph auth expired | Re-authenticate via device code flow |
| Marcus persona not loading | Check `configs/personas/marcus_reed.yaml` exists |

---

## Credits

Built with Claude Code by Microsoft Surface GTM Corp Marketing

*Demonstrating cloud AI for development + on-device AI for secure deployment*
