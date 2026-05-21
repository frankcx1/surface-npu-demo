# Branch of the Future — Technical Guide

## Overview

A single-file Flask application (`npu_demo_flask.py`, ~16,400 lines) that demonstrates six AI-powered capabilities running entirely on-device using the NPU on Microsoft Surface Copilot+ PCs. The app is white-labeled per banking customer and demoed live to enterprise CXOs as "Branch of the Future," proving that a Surface Copilot+ PC can run a full AI advisor workstation with zero cloud dependencies and zero data egress.

Supports Intel Core Ultra (Lunar Lake / Panther Lake) with auto-detection at startup. Optional live integrations with Microsoft Graph (calendar, email) and Dynamics 365 (CRM) fall back gracefully to local demo data when offline.

**Architecture:**
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

---

## How to Run

```
python npu_demo_flask.py
```

**Prerequisites:**
- Windows 11 24H2 on a Copilot+ PC (Intel Core Ultra or Qualcomm Snapdragon X)
- Foundry Local installed (`winget install Microsoft.FoundryLocal`) — runtime auto-starts on first model call
- Python 3.10+ with Flask, OpenAI SDK, `foundry-local-sdk` (NOT the squatted `foundry-local` pip package)
- Tesseract.js files bundled in `tesseract/` directory (included)
- Demo data in `demo_data/` within the project directory
- Vision Service MSIX installed and running for camera classification (optional — text fallback available)

**Ports:**
| Service | Port | Notes |
|---------|------|-------|
| Flask app | `127.0.0.1:5000` | Bound to localhost only |
| Foundry Local | Dynamic (via SDK) | OpenAI-compatible `/v1` API |
| Vision Service | `127.0.0.1:5100` | C# MSIX, Phi Silica Vision + TextRewriter |

**Cross-platform detection:**
On Windows-on-ARM, `platform.machine()` and `PROCESSOR_ARCHITECTURE` may report `AMD64`/`X64` due to emulation. The app uses WMI CPU name (`Win32_Processor`) as the authoritative source for silicon detection. Never use `platform.machine()` or env vars to detect ARM64.

---

## Model Usage

| Silicon | Model | Alias | Context | Notes |
|---------|-------|-------|---------|-------|
| Intel Core Ultra | Phi-4 Mini | `phi-4-mini` | ~4K tokens | OpenVINO NPU, reliable |
| Qualcomm Snapdragon X | Qwen 2.5 7B | `qwen2.5-7b` | ~4K tokens | QNN NPU, needs special handling |
| Intel/Qualcomm | Phi Silica Vision | N/A | N/A | Via Vision Service (localhost:5100), image classification |
| Intel/Qualcomm | Phi Silica TextRewriter | N/A | N/A | Via Vision Service `/rewrite`, email polishing |

**All inference goes through the OpenAI-compatible API** provided by Foundry Local. The `foundry_chat()` wrapper (line 643) handles auto-reconnection when Foundry's port changes.

**Token budget constraints:**
- Max output: ~1,536 tokens
- Max input: ~1,000 tokens (~4K chars)
- Data payloads compressed to hard cap of 3,600 chars (see `compress_for_briefing()`, line 1007)
- Never send raw PowerShell output to the model — only pre-computed ratings text

---

## The Six Tabs

The UI is a sidebar + main content layout (`.app-shell` > `.sidebar` + `.main-content`). Sidebar nav items are `<a class="sidebar-nav-item" data-tab="KEY">` tags. Each tab's content is a `<div id="KEY-tab" class="tab-content">` block. Tab switching is handled by JavaScript `data-tab` click handlers.

| data-tab | Default Name | Subtitle | Purpose |
|----------|-------------|----------|---------|
| `chat` | Advisor Assistant | Knowledge & Tools | Chat interface with tool-calling AI agent |
| `day` | Morning Briefing | Daily Prep | Executive morning briefing from calendar/email/task data |
| `auditor` | PII Guard | Compliance Check | Dual-mode compliance analysis (contract + marketing) |
| `id` | ID & Check Verify | Scan & Deposit | On-device document verification and check deposit |
| `live` | Live Assist | Client Meeting AI | Real-time meeting copilot with AI insight cards |
| `field` | Meeting Notes | Post-Meeting Workflow | Post-meeting workflow with voice, camera, reports |

Tab names, subtitles, and icons are all configurable via `demo_config.yaml`.

---

### Tab 1: Advisor Assistant (`chat`)

Chat interface with tool-calling AI agent. Uses `[TOOL_CALL]` marker shim (Phi-4 Mini doesn't have native tool calling).

**Agent Tools:**
| Tool | What It Does | Constraints |
|------|-------------|-------------|
| `read` | Read a file and return contents (max 5,000 chars) | Path must resolve within `demo_data/` |
| `write` | Create or overwrite a file | Path must resolve within `demo_data/` |
| `exec` | Run a PowerShell command | Allowlisted cmdlets only |
| `d365_customer_lookup` | Search D365 contacts by name | MCP tool via D365 Dataverse |
| `d365_check_in_queue` | Get branch check-in queue | MCP tool via D365 Dataverse |
| `d365_log_activity` | Log task/note on customer timeline | MCP tool via D365 Dataverse |
| `d365_recent_activities` | Get customer activity history | MCP tool via D365 Dataverse |
| `my_calendar_today` | Fetch today's calendar via Graph | Returns live or demo calendar |
| `prep_next_client` | Generate prep brief for next meeting | Cross-references calendar + D365 |

**Marcus Reed Persona:**
When the Zava Financial brand is active and `configs/personas/marcus_reed.yaml` is loaded, the chat route automatically routes through the Marcus Reed persona — a Senior Wealth Advisor with specialized knowledge in retirement, estate planning, and college savings. See the [Persona System](#persona-system) section for full details.

**Suggestion chips:** My Calendar, Prep Next Client, Customer Queue, Outlook/Office

**Device Intelligence sub-features** (accessible via chips in the chat or dedicated UI):

| Feature | Endpoint | Description |
|---------|----------|-------------|
| Device Health | `POST /demo/device-health` | 9 PowerShell collectors + AI narrative |
| Security Audit | `POST /demo/security-audit` | 28 security checks + weighted grading |
| Device Search | `POST /demo/device-search` | Natural language file search (two AI calls) |
| Document upload | `POST /upload-to-demo` | Upload PDF/DOCX/TXT/MD, extract text |
| Summarize document | `POST /summarize-doc` | Single-step AI summarization |
| Detect PII | `POST /detect-pii` | PII detection (SSNs, emails, phones, names) |
| Knowledge Q&A | `POST /knowledge` | Pure AI explanation — no tool access |

**Tool-Calling Shim:**
1. System prompt defines available tools with `[TOOL_CALL]` markers (AGENT_SYSTEM_PROMPT)
2. Model outputs `[TOOL_CALL]{"name":"...", "arguments":{...}}[/TOOL_CALL]`
3. `parse_tool_call()` (line 1059) extracts the JSON via regex
4. `execute_tool()` (line 1091) runs the tool, returns result
5. Result is fed back to the model for a natural-language summary

**Known limitation:** The model hangs when making consecutive API calls (tool decision -> followup summary). Solution: use dedicated single-step endpoints instead of the agent loop for complex operations.

---

### Tab 2: Morning Briefing (`day`)

Executive morning briefing synthesized from calendar, email, and task data.

**Data Sources:**
| Source | Live (Graph) | Local Fallback |
|--------|-------------|----------------|
| Calendar | Microsoft Graph `GET /me/calendarView` | `demo_data/My_Day/calendar.ics` |
| Emails | Microsoft Graph `GET /me/mailFolders/inbox/messages` | `demo_data/My_Day/Inbox/*.eml` |
| Tasks | N/A (local only) | `demo_data/My_Day/tasks.csv` |

When Graph tokens are available, the app fetches live Outlook calendar events and emails. When offline or unauthenticated, it falls back to local demo files.

**Features:**
| Feature | Endpoint | Description |
|---------|----------|-------------|
| Brief Me | `POST /brief-me` | Cross-referenced executive briefing (streaming JSONL) |
| Triage Inbox | `POST /triage-inbox` | Categorize emails: URGENT / ACTION NEEDED / FYI |
| Prep for Next Meeting | `POST /prep-next-meeting` | Prep brief for first substantive meeting |
| Top 3 Focus | `POST /top-3-focus` | AI identifies three highest-priority items |
| Tomorrow Preview | `POST /tomorrow-preview` | Next day schedule overview |
| Data Cards | `GET /my-day-counts`, `GET /my-day-data` | Card counts + peek data |

**Brief Me Flow:**
1. Backend parses all data sources (progress streamed to UI)
2. `compress_for_briefing()` compresses ~32 data items into ~3,600 characters
3. Combined with `BRIEFING_SYSTEM_PROMPT` (~723 chars)
4. Model generates: narrative summary → ACTIONS → PEOPLE TO KNOW → KEY WARNINGS
5. Frontend splits into executive summary card + collapsible breakdown
6. Footer: "Analyzed N emails, N events, N tasks in Xs on NPU"

---

### Tab 3: PII Guard / Auditor (`auditor`)

Dual-mode compliance analysis with on-device document review.

**Modes:**
| Mode | Use Case | Demo Docs |
|------|----------|-----------|
| Contract / Legal Review | NDA and contract risk analysis | `GET /auditor-demo-doc`, `GET /auditor-escalation-demo-doc` |
| Marketing / Campaign Review | CELA compliance for marketing assets | `GET /auditor-marketing-demo-doc`, `GET /auditor-marketing-escalation-demo-doc` |

**Contract Review Flow:**
1. Load or upload a contract document
2. AI performs structured clause-by-clause risk analysis
3. Risk levels assigned per clause
4. Escalation recommendation if high-risk clauses found
5. Escalation consent flow with PII redaction before any cloud escalation

**Marketing CELA Review Flow (document-first architecture):**
1. Sends actual document text to model (not pre-extracted phrases)
2. Model reads document and identifies compliance claims itself
3. Fallback: hardcoded findings for demo docs, regex+metadata for uploaded docs
4. SSE events: `claims` → `verdict` → `summary` → `escalation_available` → `audit` → `complete`
5. Verdict: **SELF-SERVICE OK** or **CELA INTAKE REQUIRED**

**PII Scanner:**
`_scan_pii()` detects SSNs, emails, phone numbers, and person names (curated list via `_DEMO_PERSON_NAMES` regex). `_redact_text()` replaces findings with `[REDACTED Type]` before any escalation to frontier models.

**Two-Brain Router:**
| Endpoint | Purpose |
|----------|---------|
| `POST /router/analyze` | Local attempt → knowledge search → decision card → escalation consent |
| `POST /router/decide` | Record decision, generate Trust Receipt, produce redacted payload |
| `GET /router/log` | Return full Router decision log |

---

### Tab 4: ID & Check Verify (`id`)

On-device document verification with two modes.

**ID Verification Flow:**
1. Camera capture or demo preset image
2. Client-side OCR via Tesseract.js (bundled, no CDN)
3. `POST /analyze-id` — AI extracts: name, address, DOB, ID number, expiration, state, class, validity status

**Check Deposit Flow:**
1. Camera capture or demo check image
2. Client-side OCR via Tesseract.js
3. `POST /analyze-check` — AI extracts: payee, amount, routing number, account number, date, memo, signature presence
4. D365 customer profile card populated via `/d365/customer-lookup`
5. D365 transaction logging via `/d365/log-transaction`
6. Pen signature pad with pressure sensitivity via `/signature/verify`

**Tesseract.js Local Bundle:**
```
tesseract/
  tesseract.min.js          66 KB
  worker.min.js            121 KB
  core/*.wasm.js           3.8-4.6 MB (SIMD/LSTM variants)
  lang/eng.traineddata.gz  10.9 MB
```

All OCR files served via `/tesseract/<path>` route — no CDN dependency.

---

### Tab 5: Live Assist (`live`)

Real-time meeting copilot for advisor-client conversations.

**Layout:** Two-pane — left (60%) live transcript, right (40%) AI advisor insight cards.

**Features:**
| Feature | Endpoint | Description |
|---------|----------|-------------|
| Analyze transcript | `POST /live-assist/analyze` | Real-time advisor tips + sentiment from transcript chunks |
| Translate | `POST /live-assist/translate` | Translate transcript to target language (EN/ES) |

**Analyze Flow:**
1. Web Speech API captures live voice transcription (or 19-line demo script fallback)
2. Transcript chunks sent to `/live-assist/analyze` with prior insights
3. AI returns 1-3 actionable bullet points (max 12 words each) + SENTIMENT (POSITIVE/NEUTRAL/CAUTIOUS)
4. Insight cards rendered in real-time, buffered and deduped
5. Post-session translation available

**Demo Script Fallback:** A 19-turn scripted banking conversation (Jackie Rodriguez discussing checking, 529 plans, and Roth IRA) plays automatically when live voice isn't available. Script is defined in `demo_config.yaml` under `demo_script`.

---

### Tab 6: Meeting Notes (`field`)

Post-meeting workflow (formerly "Field Inspection"). Captures meeting notes, classifies documents, generates reports.

**Layout:** Four-panel workspace (form, photo, report, bottom bar).

**Features:**
| Milestone | Capability | Key Detail |
|-----------|-----------|------------|
| M1 | Scaffold | Four-panel grid layout, tab switching, CSS |
| M2 | Voice/Text Capture + Field Extraction | Win+H dictation or scripted input → AI extracts client, location, datetime, products, source |
| M3 | Camera Capture + Classification | getUserMedia camera with flip button, demo presets, three-tier classification |
| M4 | Pen Annotation | Dual-canvas overlay, Pointer Events ink drawing, OCR extraction of handwritten notes |
| M5 | Report Generation | AI generates Client Meeting Summary with risk rating and next steps |
| M6 | Translation | AI translates report EN/ES, language toggle |
| M7 | Router Escalation + Dashboard | Escalation dialog on low-confidence classifications, dashboard tally |

**Classification three-tier fallback:**
1. Demo preset → hardcoded `_DEMO_CLASSIFICATIONS` (1.5s simulated)
2. Phi Silica Vision → image to Vision Service :5100 → NPU inference → category mapping
3. Phi-4 Mini text fallback → filename hint → structured JSON classification

**Routes:**
| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/inspection/fluid-dictation` | Toggle Windows Voice Typing |
| POST | `/inspection/transcribe` | Extract meeting fields from transcript |
| GET | `/inspection/demo-photo/<type>` | Serve demo photo |
| POST | `/inspection/classify` | Classify photo (3-tier fallback) |
| POST | `/inspection/annotate` | Extract text from annotated photo |
| POST | `/inspection/report` | Generate meeting summary report |
| POST | `/inspection/translate` | Translate report to target language |

**D365 Integration:** Meeting notes can be posted to the customer's D365 timeline via the agent's `d365_log_activity` tool.

---

## Brand Configuration System

The app is white-labeled per customer using YAML config files. Each customer gets their own colors, logo, tab names, advisor identity, personas, and demo script.

### Config Loading

1. `_load_yaml_config()` (line 26) reads `demo_config.yaml` from the app root
2. Nested YAML keys are flattened: `brand.accent` → `brand_accent`, `advisor.name` → `advisor_name`, etc.
3. If pyyaml is missing or the file doesn't exist, falls back to hardcoded `DEMO_CONFIG` dict (line 491)

### Config Structure

```yaml
app_title: "Branch of the Future"
app_subtitle: "Powered by Surface + On-Device AI"

brand:
  primary: "#f7f9fb"           # sidebar background start
  primary_end: "#ebeff3"       # sidebar background end
  accent: "#183D4C"            # active states, links
  accent_rgb: "24,61,76"       # RGB for rgba() usage
  hover: "#9EC9D9"             # hover accent
  theme: "light"               # "light" activates Urbanist font + light palette
  logo: "zava-logo.png"        # logo file in repo root
  company_name: "Zava Financial"

advisor:
  name: "Sarah Chen"
  title: "Vice President & Senior Relationship Manager"
  company: "Zava Financial"
  phone: "(415) 555-0142"
  email: "sarah.chen@zavafinancial.com"
  branch: "Financial District, San Francisco"

tabs:                          # name, sub, icon for each of the 6 tabs
  chat: {name: "Advisor Assistant", sub: "Knowledge & Tools", icon: "<svg .../>"}
  day:  {name: "Morning Briefing", sub: "Daily Prep", icon: "<svg .../>"}
  auditor: {name: "PII Guard", sub: "Compliance Check", icon: "<svg .../>"}
  id:   {name: "ID & Check Verify", sub: "Scan & Deposit", icon: "<svg .../>"}
  live: {name: "Live Assist", sub: "Client Meeting AI", icon: "<svg .../>"}
  field: {name: "Meeting Notes", sub: "Post-Meeting Workflow", icon: "<svg .../>"}

personas:                      # persona switcher buttons in sidebar
  - {name: "Marcus", role: "Branch Manager", tabs: ["auditor", "id"]}
  - {name: "Sarah", role: "Relationship Manager", tabs: ["day", "chat", "live", "field"]}

customer:
  name: "Jackie Rodriguez"
  full_name: "Jackie Marie Rodriguez"
  d365_contact_id: ""

branches:
  - {name: "Financial District", city: "San Francisco", state: "CA"}

poc:
  footer: "This application is a proof-of-concept..."
  auditor: "PROOF OF CONCEPT..."
  id: "PROOF OF CONCEPT..."

industry:
  context: "banking"
  annotation_role: "banking advisor"
  annotation_documents: "financial documents"
  annotation_actions: "rollovers, transfers, beneficiary changes, account updates"
  annotation_fallback: "Rollover to Roth IRA - review tax implications"
  annotation_label: "Document Analysis"
  report_type: "Client Meeting Summary"
  report_role: "client meeting report generator for a bank wealth advisor"
  placeholders:
    client: "e.g. Jackie Rodriguez"
    location: "e.g. Starbucks Midtown Manhattan"
    issue: "e.g. 529 Plan, Roth IRA"
    source: "e.g. Existing Member Referral"
    notes: "Meeting notes will appear here..."

economics:
  cost_per_1k_tokens: 0.01
  carbon_per_1k_tokens: 0.25
  device_cost: 1599

demo_script:                   # 19-turn scripted conversation for Live Assist
  - {delay: 0, speaker: "Customer", text: "Hi, I'm Jackie..."}
  ...
```

### Template Variable Injection

The `index()` route does ~40 `.replace()` calls to inject config values into `HTML_TEMPLATE`:

| Variable | Source | Example |
|----------|--------|---------|
| `{{APP_TITLE}}` | `app_title` | "Branch of the Future" |
| `{{BRAND_ACCENT}}` | `brand.accent` | "#183D4C" |
| `{{BRAND_ACCENT_RGB}}` | `brand.accent_rgb` | "24,61,76" |
| `{{BRAND_PRIMARY}}` | `brand.primary` | "#f7f9fb" |
| `{{BRAND_PRIMARY_END}}` | `brand.primary_end` | "#ebeff3" |
| `{{BRAND_HOVER}}` | `brand.hover` | "#9EC9D9" |
| `{{BRAND_COMPANY}}` | `brand.company_name` | "Zava Financial" |
| `{{TAB_CHAT_NAME}}` / `SUB` / `ICON` | `tabs.chat.*` | per-tab labels and SVG icons |
| `{{TAB_DAY_NAME}}` / `SUB` / `ICON` | `tabs.day.*` | (same pattern for all 6 tabs) |
| `{{ADVISOR_NAME}}` | `advisor.name` | "Sarah Chen" |
| `{{ADVISOR_TITLE}}` | `advisor.title` | "VP & Senior Relationship Manager" |
| `{{ADVISOR_COMPANY}}` | `advisor.company` | "Zava Financial" |
| `{{ADVISOR_PHONE}}` | `advisor.phone` | "(415) 555-0142" |
| `{{POC_FOOTER}}` | `poc.footer` | POC disclaimer text |
| `{{POC_AUDITOR}}` | `poc.auditor` | Auditor tab POC banner |
| `{{POC_ID}}` | `poc.id` | ID tab POC banner |
| `{{PLACEHOLDER_CLIENT}}` | `industry.placeholders.client` | "e.g. Jackie Rodriguez" |
| `{{PLACEHOLDER_LOCATION}}` | `industry.placeholders.location` | "e.g. Starbucks Midtown" |
| `{{CHIP_LABEL}}` | Global `CHIP_LABEL` | "Intel Core Ultra NPU" |
| `{{MODEL_LABEL}}` | Global `MODEL_LABEL` | "Phi-4 Mini" |
| `{{THEME_OVERRIDES}}` | Computed CSS | Light theme overrides |
| `{{SIDEBAR_LOGO}}` | Computed HTML | Brand logo or default logos |
| `{{PERSONA_SWITCHER}}` | Computed HTML | Persona buttons (if defined) |

### Light Theme

When `brand.theme: "light"` is set in config, `_build_theme_overrides()` generates CSS overrides:
- Font-face declarations for Urbanist 300-700 (bundled in `fonts/`)
- Light backgrounds, dark text, accent-colored active states
- Sidebar styling with light palette

### Brand Switching

```cmd
switch-brand.cmd <brand>
```

The script:
1. Validates `configs/<brand>/demo_config.yaml` exists
2. Copies brand's `demo_config.yaml` to root `demo_config.yaml`
3. Copies brand's `product_catalog.yaml` if it exists
4. Prints reminder to restart Flask app

**Available brands:**
| Brand | Directory | Key Differences |
|-------|-----------|-----------------|
| Zava Financial | `configs/zava/` | Teal theme (#183D4C), Sarah Chen advisor, Marcus Reed persona |
| Flagstar Bank | `configs/flagstar/` | Orange theme (#f18f12), Alan Thornbury advisor |
| Bank of America | `configs/bofa/` | Navy theme (#012169), Michael Torres advisor |

---

## Persona System

The app supports AI personas — domain-specialized advisor characters with distinct knowledge, tone, compliance guardrails, and a financial advice safety gate. This demonstrates the "run *your* AI locally" story: each bank customer can have their own advisor persona running entirely on-device.

### Architecture

```
configs/personas/marcus_reed.yaml    ← persona definition (YAML)
        |
        ↓  (loaded at startup)
_MARCUS_SYSTEM_PROMPT                ← system prompt string
_MARCUS_AVAILABLE = True             ← feature flag
        |
        ↓  (on each /chat request)
_marcus_chat(message, history)       ← foundry_chat() with persona system prompt
        |
        ↓  (before returning response)
_financial_advice_gate(response)     ← safety filter
        |
        ↓
Final response to user
```

### Persona YAML Structure

```yaml
name: Marcus Reed
title: Senior Wealth Advisor
company: Zava Financial

specializations:
  - Retirement planning (401(k), IRA, Roth conversions)
  - Estate planning basics (wills, beneficiaries, trusts)
  - College savings (529 plans, UGMA/UTMA, education tax credits)

tone: warm, professional, consultative

style_notes:
  - Speaks in plain English, avoids unexplained jargon
  - Uses analogies for complex concepts
  - Asks clarifying questions before recommending
  - Names trade-offs explicitly rather than pushing one option
  - Acknowledges uncertainty; never bluffs

compliance:
  stance: conservative
  disclaimer_style: |
    Vary phrasing every time. Avoid the same verbatim disclaimer twice.
    The disclaimer should feel embedded in genuine reasoning, not stamped.
  always_defers_on:
    - Specific tax filing questions → "talk to your CPA"
    - Legal questions about wills/trusts → "an estate attorney"
    - Medical or insurance underwriting decisions
  never_does:
    - Quote specific interest rates, APRs, or yields
    - Promise approval, guaranteed returns, or specific outcomes
    - Recommend individual stocks, ETFs, or fund tickers by name
    - Give binding commitments on the bank's behalf

system_prompt: |
  You are Marcus Reed, a Senior Wealth Advisor at Zava Financial...
  (72 lines of detailed behavioral instructions)
```

### Loading (lines 659-671)

At startup, the app checks for `configs/personas/marcus_reed.yaml`. If pyyaml is available and the file exists, it loads the system prompt into `_MARCUS_SYSTEM_PROMPT` and sets `_MARCUS_AVAILABLE = True`.

### Chat Integration (line 12137)

The `/chat` route checks `_MARCUS_AVAILABLE`. When active, messages that don't require tool calls are routed through `_marcus_chat()` instead of the generic agent pipeline. The persona's system prompt replaces the default agent system prompt.

### Financial Advice Safety Gate (lines 674-707)

`_financial_advice_gate(response)` is a post-processing filter that catches five categories of unsafe financial content:

| Category | Detection | Action |
|----------|-----------|--------|
| Rate quotes | Regex for APR/APY/yield percentages | Deflect: "let me confirm with the product team" |
| Dollar projections | Regex for dollar outcome amounts | Redirect: "walk through the factors that affect that number" |
| Fund tickers | Regex for stock/ETF tickers (excludes IRA, CPA, ETF) | Block: explain limitations |
| Tax filing specifics | Forms (1099, Schedule A) + should/must intent | Redirect: "talk to your CPA" |

Returns `(is_safe, filtered_text)`. If unsafe, the original response is replaced with a deflection message that stays in character.

### Adding a New Persona

1. Create `configs/personas/<name>.yaml` following the structure above
2. Add the persona to `demo_config.yaml` under `personas:`
3. Add loading code parallel to the Marcus Reed block (lines 659-671)
4. Add a `_<name>_chat()` function parallel to `_marcus_chat()` (line 710)
5. Add routing logic in `/chat` to dispatch to the new persona

---

## Key Integrations

### Dynamics 365 Dataverse

**Auth flow** (MSAL device code flow):
1. Check cached token + expiry in `.d365_token_cache.json` (5-min buffer)
2. Try silent acquisition from cache
3. If no cached account, initiate device code flow (user enters code at microsoft.com)
4. Cache token for next startup

**API functions:**
- `_d365_get_token()` (line 268) — token acquisition + caching
- `_d365_api_get(path, params)` (line 337) — GET with Bearer token + OData headers
- `_d365_api_post(path, payload)` (line 362) — POST with JSON

**D365 Routes:**
| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/d365/auth-status` | Check if token cached/valid |
| POST | `/d365/authenticate` | Initiate device code flow |
| POST | `/d365/customer-lookup` | Query Dataverse for customer by name |
| POST | `/d365/log-transaction` | Create transaction record |

All D365 routes fall back to demo data if the API is unreachable.

### Microsoft Graph

**Auth flow** (MSAL with app registration):
- App ID: registered in tenant with scopes `Calendars.ReadWrite`, `Mail.ReadWrite`, `Mail.Send`, `User.Read`
- Token cached in `.graph_token_cache.json`

**API functions:**
- `_graph_get_token()` (line 397) — token acquisition
- `_graph_get_calendar_today()` (line 433) — GET `/me/calendarView` for today's events
- `_graph_get_recent_emails(count)` (line 462) — GET `/me/mailFolders/inbox/messages`

**Integration points:**
- Morning Briefing uses live calendar + email data when Graph is connected
- `/api/send-followup` sends emails via Graph `POST /me/sendMail`
- Falls back to local demo files when offline

### MCP D365 Server

Standalone FastMCP server at `mcp-d365/server.py` (405 lines). Shares MSAL token cache with main app.

**4 MCP Tools:**
| Tool | Purpose |
|------|---------|
| `d365_customer_lookup(name)` | Search contacts by name, return profile |
| `d365_check_in_queue()` | Get branch check-in queue |
| `d365_log_activity(customer, note, type)` | Log task/note on customer timeline |
| `d365_recent_activities(customer)` | Get 5 most recent customer activities |

Each tool has demo fallback data for offline operation.

---

## Branch Concierge

The Branch Concierge is a VIP arrival awareness system. When customers check in (via app, appointment, or teller identification), the system shows their profile, tier, and generates an AI greeting brief with product recommendations.

### VIP Tiers

| Tier | Label | Use Case |
|------|-------|----------|
| private | Private Client | High-net-worth, dedicated RM |
| premier | Premier | Relationship banking |
| business | Business Banking | Business accounts |
| retail | Retail | Walk-in customers |

### Demo Customers (line 200)

| Customer | Tier | RM | Key Opportunities |
|----------|------|-----|-------------------|
| Jackie Rodriguez | Premier | Jennifer | 529 plan, Roth IRA conversion |
| Marcus Chen | Private | Frank | $12M portfolio, business line of credit |
| Sarah Henderson | Premier | Jennifer | Trust review, managed portfolio |

### Arrivals Routes

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/arrivals` | Fetch active arrivals (auto-expire after 30 min) |
| POST | `/arrivals/checkin` | Register mobile app check-in |
| POST | `/arrivals/appointment` | Register scheduled appointment |
| POST | `/arrivals/teller-identified` | Register teller ID scan (VIP) |
| GET | `/arrivals/<id>/brief` | Generate AI greeting brief with product recs |
| POST | `/arrivals/<id>/status` | Update status (waiting → being_greeted → met) |
| POST | `/arrivals/reset` | Clear all arrivals (demo reset) |

### Greeting Brief

`/arrivals/<id>/brief` generates a personalized greeting using:
1. Customer profile from `_get_concierge_customer()`
2. Product recommendations from `_match_product_recommendations()`
3. AI prompt: "Write greeting prep: RECENT CONTEXT (2 sentences), KEY OPPORTUNITIES (2-3 bullets), CONVERSATION STARTER (1 opening line)"
4. Returns brief + tokens_used + inference_time

---

## Product Recommendations Engine

Cross-sell recommendation engine powered by `product_catalog.yaml`.

### Product Catalog Structure

```yaml
categories:                    # 8 categories, 27 products total
  - name: Deposits
    products: [Essential Checking, Preferred Checking, Savings, High-Yield, Money Market, CDs]
  - name: Cards
    products: [Cash Back, Travel Rewards, Secured Credit]
  - name: Lending
    products: [Mortgages, HELOCs, Auto Loans, Personal Loans]
  - name: Retirement
    products: [Traditional IRA, Roth IRA, 401(k) Rollover, 529 College, Managed Portfolio]
  - name: Protection
    products: [Overdraft, ID Theft, Life Insurance]
  - name: Digital
    products: [Mobile Banking, Online Bill Pay]
  - name: Business
    products: [Business Checking, Business LOC, Merchant Services]

cross_sell_triggers:           # 13 signal-based triggers
  - signal: has_checking_no_savings
    products: [savings_account, high_yield_savings]
    priority: high
  - signal: no_retirement_account
    products: [traditional_ira, roth_ira]
    priority: high
  ...

penetration_tiers:             # 5 tiers
  - name: New
    min_products: 0, max_products: 1
  - name: Developing
    min_products: 2, max_products: 3
  - name: Engaged
    min_products: 4, max_products: 5
  - name: Primary Bank
    min_products: 6, max_products: 8
  - name: Fully Banked
    min_products: 9
```

### Matching Algorithm (`_match_product_recommendations()`, line 96)

1. Flatten all products from categories
2. Fuzzy-match customer's current accounts against product names
3. Determine penetration tier
4. Evaluate 13 cross-sell signals against customer profile
5. For each matching trigger, suggest products
6. Sort by priority (high → medium → low), return top 5

**Routes:**
| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/product-catalog` | Return full product catalog |
| POST | `/api/product-recommendations` | Match customer profile to recommendations |

---

## Writing Assistant

Email polishing and sending capability using Phi Silica TextRewriter.

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/api/polish-email` | Rewrite email in professional banking tone |
| POST | `/api/send-followup` | Send polished email via Microsoft Graph |

**Polish Flow:**
1. Try Vision Service `/rewrite` endpoint (Phi Silica TextRewriter on NPU)
2. Fallback to Phi-4 Mini via `foundry_chat()`
3. System prompt uses advisor identity from brand config
4. Returns polished text + source model

**Send Flow:**
1. Build HTML email with advisor signature (name, title, company, phone)
2. Send via Graph `POST /me/sendMail`
3. Returns confirmation with timestamp

---

## Performance Monitor

Real-time system performance overlay toggled via `Ctrl+Shift+M`.

**Backend:** `/system-stats` (line 15853) returns cached stats from background polling thread.

**Polling Thread (`_poll_perf_stats`, line 15766):**
- Uses `win32pdh` (native Windows performance counters, no subprocess)
- Detects GPU vs NPU by LUID and engine type (3d = GPU, compute = NPU)
- Polls every 500ms
- EMA smoothing: fast rise (α=0.8), very slow decay (α=0.06) to keep spikes visible ~5s

**Stats returned:**
```json
{"cpu": 45.2, "gpu": 12.5, "npu": 78.9, "mem_pct": 62.3, "mem_used": 8.5, "mem_total": 16.0}
```

---

## Demo Hotkeys

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+M` | Toggle performance monitor overlay |
| `Ctrl+Shift+C` | Toggle carbon/cost savings display |
| `Ctrl+Shift+R` | Reset demo state (clear chat, reset arrivals, clear stats) |

---

## Vision Service

C# ASP.NET Core microservice on localhost:5100. MSIX-packaged with `systemAIModels` capability.

### API Surface

| Namespace | Class | Notes |
|-----------|-------|-------|
| `Microsoft.Windows.AI.Imaging` | `ImageDescriptionGenerator` | Vision classification |
| `Microsoft.Windows.AI.Text` | `TextRewriter` | Email polishing |
| `Microsoft.Windows.AI.ContentSafety` | `ContentFilterOptions` | Content safety |
| `Microsoft.Graphics.Imaging` | `ImageBuffer` | Factory: `CreateForSoftwareBitmap()` |

### Endpoints

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/health` | Service + model readiness |
| POST | `/describe` | Image description generation |
| POST | `/classify` | Image classification |
| POST | `/extract-text` | OCR / handwriting extraction |
| POST | `/rewrite` | Email text polishing (TextRewriter) |

### Packaging

| Item | Value |
|------|-------|
| NuGet | `Microsoft.WindowsAppSDK 1.8.260209005` (stable 1.8.5) |
| PFN | `Microsoft.NPUDemo.VisionService_r0xr04974zwaa` |
| Cert | `CN=FrankBu` |
| LAF feature | `com.microsoft.windows.ai.languagemodel` |
| MinVersion | `10.0.26100.0` (Windows 11 24H2) |

**Critical manifest fix:** Must include `Windows.Universal` TargetDeviceFamily alongside `Windows.Desktop`. Without it, `GetReadyState()` throws COMException.

---

## Security Measures

| # | Measure | Detail |
|---|---------|--------|
| 1 | File system jailing | All read/write via `_path_in_demo_dir()` — `os.path.realpath()` validation against `DEMO_DIR` |
| 2 | PowerShell allowlist | `_ALLOWED_COMMANDS` — only approved cmdlets for agent tool calls |
| 3 | Network binding | Flask on `127.0.0.1` only |
| 4 | Path traversal prevention | Static routes reject `..` and validate realpath |
| 5 | Upload restrictions | Extension allowlist `{.pdf, .docx, .txt, .md}`, `secure_filename()`, 16 MB limit |
| 6 | PII redaction | `_scan_pii()` + `_redact_text()` before any data leaves the device |
| 7 | Financial advice gate | Post-processing filter blocks rate quotes, fund tickers, tax advice |
| 8 | Approval gates | Destructive agent actions require explicit user approval |
| 9 | Audit trail | Every tool execution logged with timestamp, tool, args, result, elapsed time |

---

## API Endpoints Reference (69 Total)

### Static Asset Serving (4)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/logos/<path>` | Brand logo images |
| GET | `/fonts/<path>` | Bundled font files |
| GET | `/demo-assets/<path>` | Demo data images |
| GET | `/tesseract/<path>` | Tesseract.js OCR files |

### Core (4)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/` | Main HTML page with config injection |
| GET | `/health` | Model readiness for warmup overlay |
| GET | `/demo-mode-status` | Check demo mode flag |
| GET | `/api/config` | Return non-sensitive brand config |

### Advisor Assistant / Agent (13)

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/chat` | Agent chat (streaming JSONL, tool-calling, persona routing) |
| POST | `/demo/device-health` | 9 PowerShell health checks + AI summary |
| POST | `/demo/security-audit` | 28 security checks + weighted grading |
| POST | `/demo/device-search` | Natural language file search |
| POST | `/knowledge` | Knowledge Q&A |
| POST | `/knowledge/search` | Search local knowledge index |
| POST | `/knowledge/refresh` | Rebuild local knowledge index |
| POST | `/upload-to-demo` | Upload file, extract text |
| POST | `/summarize-doc` | AI document summarization |
| POST | `/detect-pii` | PII detection |
| POST | `/save-summary` | Direct file write |
| GET | `/demo/list-files` | List Demo folder files |
| POST | `/demo/review-summarize` | Two-phase review with approval gate |

### Morning Briefing (7)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/my-day-counts` | Card counts {events, tasks, emails} |
| GET | `/my-day-data` | Full parsed data for peek cards |
| POST | `/brief-me` | Full morning briefing (streaming JSONL) |
| POST | `/triage-inbox` | Email triage |
| POST | `/prep-next-meeting` | Next meeting prep |
| POST | `/top-3-focus` | Top 3 priorities |
| POST | `/tomorrow-preview` | Next day preview |

### PII Guard / Auditor (7)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/auditor-demo-doc` | Demo NDA for contract review |
| GET | `/auditor-escalation-demo-doc` | Escalation-worthy contract |
| GET | `/auditor-marketing-demo-doc` | Clean marketing doc |
| GET | `/auditor-marketing-escalation-demo-doc` | Risky marketing doc |
| POST | `/router/analyze` | Two-Brain Router analysis |
| POST | `/router/decide` | Record decision + Trust Receipt |
| GET | `/router/log` | Router decision log |

### ID & Check Verify (5)

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/analyze-id` | Analyze ID OCR text |
| POST | `/analyze-check` | Analyze check OCR text |
| POST | `/signature/verify` | Verify pen signature |
| GET | `/audit-log` | Return audit trail |
| DELETE | `/audit-log` | Clear audit trail |

### D365 Integration (4)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/d365/auth-status` | Check D365 token |
| POST | `/d365/authenticate` | Initiate device code flow |
| POST | `/d365/customer-lookup` | Query Dataverse |
| POST | `/d365/log-transaction` | Log transaction |

### Live Assist (2)

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/live-assist/analyze` | Real-time transcript analysis |
| POST | `/live-assist/translate` | Translate transcript |

### Meeting Notes / Field Inspection (7)

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/inspection/fluid-dictation` | Toggle Windows Voice Typing |
| POST | `/inspection/transcribe` | Extract fields from transcript |
| GET | `/inspection/demo-photo/<type>` | Serve demo photo |
| POST | `/inspection/classify` | Classify photo (3-tier) |
| POST | `/inspection/annotate` | Extract annotated text |
| POST | `/inspection/report` | Generate report |
| POST | `/inspection/translate` | Translate report |

### Branch Concierge (7)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/arrivals` | Fetch active arrivals |
| POST | `/arrivals/checkin` | Register app check-in |
| POST | `/arrivals/appointment` | Register appointment |
| POST | `/arrivals/teller-identified` | Register teller ID |
| GET | `/arrivals/<id>/brief` | Generate AI greeting brief |
| POST | `/arrivals/<id>/status` | Update arrival status |
| POST | `/arrivals/reset` | Clear arrivals |

### Product Recommendations (2)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/product-catalog` | Full product catalog |
| POST | `/api/product-recommendations` | Match customer to recs |

### Writing Assistant (2)

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/api/polish-email` | Polish email text |
| POST | `/api/send-followup` | Send email via Graph |

### System (5)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/session-stats` | Session call counts + savings |
| POST | `/session-stats/reset` | Reset session counters |
| GET | `/system-stats` | Live CPU/GPU/NPU/memory stats |
| GET | `/connectivity-check` | Check internet connectivity |
| POST | `/network-toggle` | Toggle offline/online mode |

---

## File Layout

| Path | Purpose |
|------|---------|
| `npu_demo_flask.py` | The entire app (~16,400 lines): Python backend + HTML template + CSS + JS, all inline |
| `demo_config.yaml` | Active brand config (loaded at startup, swappable per customer) |
| `product_catalog.yaml` | Product catalog for cross-sell recommendations (27 products, 13 triggers) |
| `configs/zava/` | Zava Financial brand config files |
| `configs/flagstar/` | Flagstar Bank brand config files |
| `configs/bofa/` | Bank of America brand config files |
| `configs/personas/` | AI persona definitions (marcus_reed.yaml) |
| `switch-brand.cmd` | Copies config files from `configs/<brand>/` to root, requires restart |
| `demo_data/` | All demo data (calendar, tasks, emails, documents, photos) |
| `demo_data/My_Day/` | Morning Briefing data: `calendar.ics`, `tasks.csv`, `Inbox/*.eml` |
| `demo_data/inspection_photos/` | Demo photos for Meeting Notes classification |
| `vision-service/` | C# ASP.NET Core microservice (Phi Silica Vision + TextRewriter) |
| `mcp-d365/server.py` | MCP server exposing D365 Dataverse as 4 tools |
| `tests/` | Test suite: `test_phase1.py` (190), `test_phase1_wave2.py` (41), `test_phase2.py` (52) |
| `fonts/` | Urbanist font files for light-theme branding |
| `tesseract/` | Bundled Tesseract.js for client-side OCR |
| `docs/` | Technical docs, demo scripts, field inspection workflow |
| `setup.ps1` | Automated setup script for new devices |
| `run.bat` | Simple launcher |

---

## Performance Characteristics

| Operation | Typical Latency | Token Budget | Power Draw |
|-----------|----------------|--------------|------------|
| Brief Me | 40-50s | ~1,884 tokens | ~5W |
| Agent chat (simple) | 5-10s | ~1,824 tokens max | ~5W |
| Agent chat (tool + summary) | 15-25s | Two model calls | ~5W |
| Security Audit (28 checks + AI) | ~32s | Compact ratings only | ~5W |
| Triage Inbox | 30-40s | ~1,800 tokens | ~5W |
| Prep for Next Meeting | 15-25s | ~1,300 tokens | ~5W |
| Marketing CELA review | 15-35s | ~1,300-2,850 tokens | ~5W |
| OCR (Tesseract.js) | 3-8s | N/A (CPU/WASM) | Varies |
| ID/Check Analysis | 5-10s | ~1,024 tokens | ~5W |
| Live Assist: analyze | 5-10s | — | ~5W |
| Meeting Notes: transcribe | 5-10s | — | ~5W |
| Meeting Notes: classify (demo) | 1.5s | Simulated | — |
| Meeting Notes: classify (vision) | 3-8s | — | ~5W |
| Meeting Notes: report | 10-20s | — | ~5W |
| Meeting Notes: translate | 10-20s | — | ~5W |
| Email polish (TextRewriter) | 3-8s | — | ~5W |
| Greeting brief (concierge) | 5-10s | ~300 tokens | ~5W |
| Product recommendations | <1s | N/A (rule engine) | — |

**Energy:** ~0.06 Wh per briefing (~0.1% of a 58 Wh battery).

---

## Key Constants

| Constant | Value |
|----------|-------|
| `DEMO_DIR` | `<project_root>/demo_data` |
| `MY_DAY_DIR` | `<project_root>/demo_data/My_Day` |
| `MY_DAY_INBOX` | `<project_root>/demo_data/My_Day/Inbox` |
| `MAX_CONTENT_LENGTH` | 16 MB |
| Flask host | `127.0.0.1` |
| Flask port | `5000` |
| Vision Service port | `5100` |
| `max_tokens` (Brief Me) | 800 |
| `max_tokens` (Triage) | 800 |
| `max_tokens` (Prep) | 500 |
| `max_tokens` (Agent chat) | 1024 |
| `max_tokens` (Marcus persona) | 600 |
| `max_tokens` (Greeting brief) | 300 |
| Compression hard cap | 3,600 chars |
| PowerShell timeout | 15s (general) / 30s (network) |
| Arrival expiry | 30 minutes |

---

## Common Debugging

| Problem | Solution |
|---------|----------|
| Model hangs on second API call | Use dedicated single-step endpoints, not the agent loop |
| Foundry connection lost | `foundry_chat()` auto-reconnects; check Foundry Local is running |
| Flask serving stale code | Delete `__pycache__/npu_demo_flask.cpython-*.pyc` and restart |
| Brand changes not showing | Run `switch-brand.cmd <brand>` and restart the Flask app |
| Markdown not rendering | Apply `mdToHtml()` to all code paths rendering model output |
| Model hallucinating file paths | Use dedicated endpoints that control paths directly |
| Vision Service not responding | Check MSIX is installed and running |
| D365 auth expired | Re-run `/d365/authenticate` (device code flow) |
| Graph auth expired | Re-run Graph authentication flow |
| Camera fails offline | Use demo preset photos instead of live camera |
| Marcus persona not loading | Check `configs/personas/marcus_reed.yaml` exists and pyyaml installed |
| Perf monitor shows 0% | Check `win32pdh` is installed; may not work on all hardware |
