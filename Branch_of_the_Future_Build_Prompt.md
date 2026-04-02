# Branch of the Future: Banking Demo Build Spec

## Context

You are modifying an existing Flask app (`npu_demo_flask.py`, ~11,100 lines, single file with inline HTML/CSS/JS) that runs on-device AI demos on Surface Copilot+ PCs using Foundry Local (NPU inference). The app has 5 tabs, 45 endpoints, and supports both Intel Core Ultra and Qualcomm Snapdragon silicon. It is located at `C:\Users\frankbu\OneDrive - Microsoft\NPU\npu_demo_flask.py`.

The goal is to fork this app into a **banking-specific "Branch of the Future" demo** that shows two day-in-the-life journeys: **Anna** (branch manager, customer intake) and **Sam** (wealth advisor, client meetings). This will premiere at a Flagstar Bank executive session on April 7, 2026. The demo must be repeatable for other banking customers.

**Read the full TECHNICAL_GUIDE.md and README.md in the docs/ folder before starting any work.** These contain the complete architecture, endpoint reference, code patterns, and known constraints you need to follow.

## Important Constraints

- **Never use em dashes** in any text, UI labels, prompts, or comments. Use commas, periods, or parentheses instead.
- **Single-file architecture.** All HTML/CSS/JS stays inline in `npu_demo_flask.py`. Do not create separate files for frontend code.
- **Foundry Local + OpenAI SDK pattern.** All AI calls go through the existing `client` (OpenAI SDK pointed at localhost). Do not add new AI dependencies.
- **Token budget.** Phi-4 Mini has ~4K context window. System prompts must stay compact (~500-800 chars). Never send raw data to the model; pre-process and compress first (see how `compress_for_briefing()` works in Tab 2).
- **IIFE code pattern for new features.** Follow the Field Inspection pattern: each major feature block is a self-contained IIFE with `// -- Feature Name: Section -- ...` comments.
- **Test on both Intel and Qualcomm.** Use the existing silicon detection. Model name may differ (Phi-4 Mini on Intel, Phi-3.5 Mini on Qualcomm).
- **Demo data in `demo_data/`.** All sample files go here. File system jailing (`_path_in_demo_dir()`) restricts reads/writes to this directory.
- **Do not break existing tabs.** All current functionality must still work. The banking features are additions/modifications, not replacements.

---

## Session 1: Config Layer + Re-skin + Re-prompt

### Task 1.1: Create Config Layer

Add a `BANK_CONFIG` dictionary near the top of the file (after imports, before Flask app creation) that controls all customer-specific values:

```python
BANK_CONFIG = {
    "bank_name": "Branch of the Future",
    "bank_subtitle": "Powered by Surface + Local AI",
    "brand_primary": "#1B3A5C",     # navy
    "brand_secondary": "#0078D4",   # Microsoft blue
    "brand_accent": "#C8A951",      # gold
    "brand_bg_light": "#F0F6FC",
    "persona_1_name": "Anna",
    "persona_1_role": "Branch Manager",
    "persona_2_name": "Sam",
    "persona_2_role": "Wealth Advisor",
    "products": {
        "529_plan": "529 College Savings Plan",
        "roth_ira": "Roth IRA",
        "traditional_ira": "Traditional IRA",
        "checking": "Essential Checking",
        "savings": "High-Yield Savings",
        "retirement": "Retirement Planning Package",
    },
    "demo_customer": {
        "name": "Jackie Rodriguez",
        "purpose": "Open a new account and discuss retirement planning",
    }
}
```

The HTML template should reference `BANK_CONFIG` values via Jinja-style injection (the app already uses `render_template_string`, so pass the config dict to the template).

**Acceptance:** Config values appear in the UI. Changing `bank_name` in the dict changes the header text without any other code changes.

### Task 1.2: Banking UI Re-skin

Modify the CSS in the inline HTML template:

1. **Color palette:** Replace the current accent colors with `BANK_CONFIG` brand colors. The sidebar background should use `brand_primary` (navy). Accent links/buttons use `brand_secondary`. Hover states use `brand_accent` (gold).
2. **Rename sidebar nav items:**
   - "Device Intelligence" becomes "Advisor Assistant"
   - "My Day" becomes "Morning Briefing"
   - "Auditor" becomes "PII Guard"
   - "ID Verification" becomes "ID & Check Verify"
   - "Field Inspection" becomes "Meeting Notes"
3. **Add persona switcher** to the sidebar, above the nav items. Two clickable badges: "Anna - Branch Manager" and "Sam - Wealth Advisor". Clicking a persona highlights the tabs relevant to that journey (Anna: PII Guard, ID & Check Verify; Sam: Morning Briefing, Advisor Assistant, Meeting Notes). Both personas can access all tabs; the switcher just provides visual guidance.
4. **Replace header/branding text** with `BANK_CONFIG["bank_name"]` and `BANK_CONFIG["bank_subtitle"]`.

**Acceptance:** App loads with navy/gold banking theme. Sidebar shows new tab names. Persona switcher is visible and highlights relevant tabs. No existing functionality broken.

### Task 1.3: Re-prompt AI Agent for Banking (Tab 1)

Modify the AI Agent system prompt (the one used in the `/chat` endpoint and `/knowledge` endpoint) to be a banking wealth advisor assistant:

```
You are a local AI assistant for a bank wealth advisor. You help with financial product questions, client meeting preparation, and compliance checks. You have knowledge of: 529 College Savings Plans, Roth and Traditional IRAs, retirement planning, checking and savings accounts, and general banking regulations. All your processing runs on-device. No customer data leaves this device. Be concise and professional.
```

Update the suggestion chips (the clickable prompt buttons in the Agent tab) to banking queries:
- "What are the 2026 529 plan contribution limits?"
- "Compare Roth vs Traditional IRA for a 45-year-old"
- "Draft a follow-up email to a new retirement planning client"
- "What documents are needed to open a new account?"

Update the Device Health and Security Audit chips to keep working (they are hardware-specific, not persona-specific). Rename "Device Search" to "Document Search" and adjust the search prompt to emphasize finding client-related documents.

**Acceptance:** Agent chat responds with banking knowledge. Suggestion chips show banking queries. Device Health and Security Audit still work unchanged.

### Task 1.4: Re-context Auditor to PII Guard (Tab 3)

1. **Rename all UI labels** from "Auditor" to "PII Guard" and from "Clean Room" to "Compliance Pre-Check".
2. **Contract/Legal Review mode** becomes "Document PII Scan". The system prompt should focus on detecting PII in banking documents: SSNs, account numbers, routing numbers, dates of birth, driver license numbers, addresses, phone numbers, email addresses.
3. **Create new demo documents** in `demo_data/`:
   - `banking_account_application.txt`: A mock new account application form containing sample PII (fake SSN, fake account numbers, fake DOB, fake address). Use obviously fake data (SSN: 078-05-1120, etc.).
   - `banking_loan_application.txt`: A mock loan application with income details and PII.
4. **Update the demo doc endpoints** (`/auditor-demo-doc`, etc.) to serve the new banking documents.
5. **Marketing/Campaign Review mode** becomes "Compliance Communication Review" for reviewing customer-facing communications for regulatory compliance language.
6. **Two-Brain Router and Trust Receipts** remain unchanged (they are already generic).

**Acceptance:** PII Guard tab loads with banking demo docs. Scanning the account application correctly identifies and flags PII. Trust Receipt logs the scan as a local operation.

### Task 1.5: Re-context My Day to Morning Briefing (Tab 2)

1. **Rename UI labels** from "My Day" to "Morning Briefing".
2. **Create new demo data** in `demo_data/My_Day/`:
   - `calendar.ics`: Sam's advisor schedule. 6-8 events including: "Client meeting - Jackie Rodriguez (new, referred by Anna) 4:00 PM at Starbucks on Main St", "Team huddle 9:00 AM", "Portfolio review - Henderson family 11:00 AM", "Lunch", "Compliance training webinar 2:00 PM".
   - `tasks.csv`: Advisor tasks. Include: "Send 529 contribution limits to Jackie Rodriguez (High)", "Complete quarterly compliance review (High)", "Follow up with Henderson on estate planning referral (Medium)", "Update CRM notes from yesterday's meetings (Medium)", "Review new retirement product training materials (Low)".
   - `Inbox/*.eml`: 8-10 sample emails. Mix of: manager asking for weekly pipeline update, client asking about account transfer, compliance reminder, Jackie Rodriguez confirming appointment, internal product bulletin about new IRA rates, etc.
3. **Update the Brief Me system prompt** to frame output as an advisor morning briefing. Keep the existing ACTIONS / PEOPLE TO KNOW / KEY WARNINGS structure.
4. **Rename chips:** "Brief Me" stays. "Top 3 Focus" stays. "Triage Inbox" stays. "Prep for Next Meeting" becomes "Prep for Next Client" and should skip internal meetings to find the first client meeting.

**Acceptance:** Morning Briefing tab shows advisor-relevant calendar, tasks, and emails. Brief Me generates a coherent advisor morning briefing mentioning Jackie Rodriguez by name.

### Task 1.6: Fork Field Inspection to Client Meeting Notes (Tab 5)

This is the most complex re-skin. The Field Inspection tab has 7 milestones of functionality. Fork the entire tab, keeping the same architecture, but swapping the context from field inspection to banking post-meeting workflow.

**Rename mapping:**
- Tab name: "Meeting Notes" (sidebar already renamed in Task 1.2)
- "Field Inspection" references in code comments become "Client Meeting Notes"
- `inspInspector` field becomes advisor name (default: "Sam")

**Milestone-by-milestone changes:**

**M2 - Voice Capture + Field Extraction:**
- Change the `/inspection/transcribe` system prompt from extracting inspection fields to extracting meeting fields:
  - `client_name` (was `location`)
  - `meeting_date` (was `datetime`)
  - `meeting_type` (was `issue`) - values like "Initial Consultation", "Portfolio Review", "Follow-up"
  - `products_discussed` (was `source`) - values like "529 Plan, Roth IRA"
  - `advisor_name` (was `inspector_name`)
  - Add: `action_items` (new field, extracted from transcript)
  - Add: `follow_up_date` (new field)
- Change the **scripted input** text from "Inspector Sarah Chen at Building C..." to: "Just finished meeting with Jackie Rodriguez at the Starbucks on Main Street. We discussed opening a 529 plan for her daughter Maya who starts college in 2030 and she's also interested in a Roth IRA conversion from her old employer 401k. Need to send her the contribution limits comparison by Friday and schedule a follow-up for next Thursday to review the paperwork."
- Update the form field labels and IDs in the HTML to match the new field names.
- Update the staggered field animation to populate the new fields.

**M3 - Camera Capture + Classification:**
- Change classification categories from hazard types to document types: "Business Card", "Financial Statement", "Tax Document", "Account Application", "Insurance Document"
- Update `_DEMO_CLASSIFICATIONS` with banking document presets and appropriate confidence scores
- If demo photos are used, add banking-relevant images to `demo_data/` (or repurpose with text-only classification)

**M5 - Report Generation:**
- Change the report prompt from generating an inspection report to generating:
  1. **Meeting Summary** (2-3 sentences)
  2. **Client Action Items** (bullet list)
  3. **Draft Follow-up Email** to the client
  4. **D365 Task List** (formatted for CRM entry)
- Update the report HTML template to show these four sections with appropriate headers

**M6 - Translation:**
- No changes needed. Translation from EN to ES already works generically.

**M7 - Router + Dashboard:**
- Update the dashboard task labels from inspection tasks to meeting tasks: "Transcribe Meeting Notes", "Extract Client Details", "Classify Document", "Generate Meeting Summary", "Draft Follow-up Email", "Create D365 Tasks", "Translate Email"
- Keep the 7 local tasks vs 0 cloud tasks counter

**M1 (Scaffold) and M4 (Pen Annotation):**
- No changes needed. Layout and pen annotation are generic.

**Acceptance:** Meeting Notes tab works end-to-end. Clicking scripted input populates banking fields. Report generates meeting summary + follow-up email + D365 tasks. Dashboard shows 7 local AI tasks. Translation still works.

### Task 1.7: Create Banking Demo Data

Create the following files in `demo_data/`:

1. `banking_account_application.txt` (Task 1.4)
2. `banking_loan_application.txt` (Task 1.4)
3. Updated `My_Day/calendar.ics` (Task 1.5)
4. Updated `My_Day/tasks.csv` (Task 1.5)
5. Updated `My_Day/Inbox/*.eml` (Task 1.5, 8-10 files)
6. `banking_products_reference.txt`: A concise reference doc (~2000 chars) covering 529 plans, IRAs, checking/savings accounts with key facts the AI Agent can reference. Include: contribution limits, eligibility rules, tax implications, and basic fee structures. Use 2026 IRS limits.

**Important:** All PII in demo data must be obviously fake. Use names like "Jackie Rodriguez", SSN "078-05-1120", account number "****4832", etc.

---

## Session 2: Live Transcript + AI Prompter + Check Scanner

### Task 2.1: Live Transcript Tab (UIA Wrapper for Windows Live Captions)

**This is a new tab.** Add it to the sidebar as "Live Assist" between "ID & Check Verify" and "Meeting Notes".

**Backend: Python UIA wrapper**

Add a new module section in the Flask file (follow the IIFE pattern used by Field Inspection). The wrapper uses the `uiautomation` package to scrape text from the Windows Live Captions window:

```python
# -- Live Assist: Backend --
import threading
import queue

_caption_queue = queue.Queue(maxsize=100)
_caption_thread = None
_caption_running = False

def _start_caption_listener():
    """Background thread that polls Windows Live Captions via UIA."""
    global _caption_running
    try:
        import uiautomation as auto
    except ImportError:
        print("WARNING: uiautomation not installed. Live Assist disabled.")
        return

    _caption_running = True
    last_text = ""

    while _caption_running:
        try:
            # Find the Live Captions window
            window = auto.WindowControl(Name='Live Captions', searchDepth=1)
            if window.Exists(0, 0):
                # Find the caption text element by AutomationId
                text_block = window.TextControl(AutomationId='CaptionsTextBlock')
                if text_block.Exists(0, 0):
                    current = text_block.Name or ""
                    if current and current != last_text:
                        _caption_queue.put(current)
                        last_text = current
        except Exception:
            pass  # Live Captions not running or UIA access issue
        time.sleep(0.1)  # 100ms polling interval

def _stop_caption_listener():
    global _caption_running
    _caption_running = False
```

**Endpoints:**

```
POST /live-assist/start     - Start the UIA listener thread + optionally launch Live Captions
POST /live-assist/stop      - Stop the listener
GET  /live-assist/stream    - SSE endpoint streaming caption text to frontend
POST /live-assist/analyze   - Send buffered transcript chunk to Phi-4 Mini for intelligence
```

The `/live-assist/stream` endpoint should use Server-Sent Events (same pattern as `/brief-me`). It reads from `_caption_queue` and sends each new text chunk as an SSE event.

The `/live-assist/analyze` endpoint receives a transcript chunk (2-3 sentences), sends it to Phi-4 Mini with this system prompt:

```
You are a real-time advisor intelligence system for a bank wealth advisor. Based on the customer conversation excerpt below, provide 1-2 brief, actionable insights. Focus on: product opportunities, compliance flags, follow-up actions, or relevant financial facts. Also rate the customer sentiment as POSITIVE, NEUTRAL, or CAUTIOUS. Be concise (3 sentences max). Do not repeat prior insights.
```

Return JSON: `{"insights": "...", "sentiment": "POSITIVE|NEUTRAL|CAUTIOUS"}`

**Frontend: Two-pane layout**

Left pane (60% width): Live scrolling transcript. New text appends with a fade-in animation. Show a small timestamp next to each chunk. Header: "Live Transcript" with a green pulsing dot when active.

Right pane (40% width): AI Intelligence cards. Each card shows the insight text, a sentiment badge (green/amber/yellow dot), and a timestamp. Cards stack newest on top, max 5 visible (scroll for history). Header: "AI Advisor Prompts".

Bottom bar: "Start Listening" / "Stop" button. Status indicator showing "Connected to Live Captions" or "Live Captions not detected". Language indicator (pulled from the transcript context).

**Buffering logic (in JavaScript):**
- Accumulate transcript text in a buffer
- When the buffer contains 2+ complete sentences (detect by period/question mark followed by space or newline), send the buffer to `/live-assist/analyze`
- Display the AI response as a new intelligence card
- Clear the buffer and start accumulating again
- Debounce: don't send a new analysis request if one is already in-flight

**Fallback:** If `uiautomation` is not installed or Live Captions is not running, show a clear message: "Live Captions not detected. Enable Live Captions (Win+Ctrl+L) and ensure the 'Include microphone audio' option is on." Provide a "Retry Connection" button.

**Demo mode fallback:** Add a "Demo Script" button that simulates a customer conversation by feeding pre-written sentences into the transcript pane at 3-second intervals. Use a banking conversation where a customer discusses retirement planning, mentions children's ages, asks about fees, and expresses interest in a 529 plan. This ensures the demo works even if Live Captions has issues on demo day.

**Acceptance:** Tab loads with two-pane layout. Start Listening connects to Live Captions and shows transcript. AI Prompter generates banking-relevant insights with sentiment. Demo Script button works as fallback. Trust Receipt logs all analysis as local operations.

### Task 2.2: Extend ID Verification with Check Scanner

Add a mode switcher to the ID Verification tab (now "ID & Check Verify"). Two modes: "Scan ID" (existing) and "Scan Check" (new).

**Scan Check mode:**
- Uses the same camera capture and Tesseract OCR pipeline
- After OCR, sends text to a different AI analysis prompt:

```
You are a check verification assistant. Analyze the OCR text from a scanned check image. Extract and validate these fields: payee name, payer name, check number, date, amount in numbers, amount in words, bank name, routing number (last 4 only), account number (last 4 only), memo, signature present (yes/no). Flag any issues: amount mismatch between numbers and words, missing signature, stale date (>180 days), missing fields. Return as structured JSON.
```

- Display results as a styled card similar to the ID verification card, with a check-specific layout: payee, amount, date, check number, bank, and a validation status section showing any flags.
- Add "Scan Check" as a second demo preset that provides a sample check image (if available) or shows a placeholder instructing the user to position a check in front of the camera.

**Endpoint:** `POST /analyze-check` (new, mirrors `/analyze-id` but with check-specific prompt)

**Acceptance:** Mode switcher toggles between ID and Check scanning. Check scanner extracts fields from OCR text. Validation flags appear for mismatched amounts or missing signatures. Both modes share the same camera pipeline.

---

## Session 3: Pen Signature + Polish + Testing

### Task 3.1: Pen Signature Capture Flow

This is a standalone flow that can be triggered from the "ID & Check Verify" tab or as a cross-tab feature. It represents the moment where a customer signs a digital agreement on the Surface Pro in tablet mode.

**UI:** Full-width canvas area with:
- A mock account agreement text block above the signature area (3-4 lines of legal text, e.g., "I, the undersigned, authorize the opening of the account described above and agree to the terms and conditions...")
- HTML5 Canvas signature pad (full width, ~150px height)
- Pointer Events for pen pressure sensitivity (use `evt.pressure` to vary stroke width 2-6px)
- Black ink on white background
- Buttons: "Clear", "Accept & Sign"
- After signing, AI confirmation card: "Signature captured. Document hash: [generated locally]. No signature data transmitted to cloud. Trust Receipt logged."
- Add the signature event to the Trust Receipt / audit trail

**This reuses the pen annotation pattern from Field Inspection M4** (dual-canvas, Pointer Events, stroke management). Adapt rather than rebuild.

**Endpoint:** `POST /signature/verify` receives the signature image (base64), returns confirmation JSON with a locally-generated hash (use Python `hashlib.sha256` on the image bytes).

**Acceptance:** Signature canvas captures pen input with pressure sensitivity. Clear button works. Accept & Sign generates hash and Trust Receipt entry. Works in tablet mode.

### Task 3.2: Cross-tab Polish

1. **Offline Mode badge** in sidebar: update the label from "Go Offline" to "Airplane Mode Demo" with a small airplane icon (CSS only, no image).
2. **Savings Widget:** Update the example calculation text to use banking context: "Equivalent to X cloud API calls saved across 8,000 branch devices per day."
3. **POC Disclaimers:** Update disclaimer text on PII Guard and ID & Check Verify to reference banking compliance context.
4. **Tab order in sidebar:** Reorder to match the demo flow: Morning Briefing, Advisor Assistant, PII Guard, ID & Check Verify, Live Assist, Meeting Notes.

### Task 3.3: Demo Data Validation

Verify all demo data files are internally consistent:
- Jackie Rodriguez appears in: calendar (appointment), emails (confirmation email), Agent context, Meeting Notes scripted input
- Sam appears as the advisor name throughout
- Anna appears as the branch manager in relevant contexts
- Product names match `BANK_CONFIG["products"]`
- All PII is obviously fake
- No real bank names, real account numbers, or real personal data

---

## File Structure After Build

```
npu_demo_flask.py          # Modified main app with banking config + new features
demo_data/
  My_Day/
    calendar.ics           # Sam's advisor schedule (UPDATED)
    tasks.csv              # Advisor tasks (UPDATED)
    Inbox/                 # 8-10 banking-relevant emails (UPDATED)
  banking_account_application.txt    (NEW)
  banking_loan_application.txt       (NEW)
  banking_products_reference.txt     (NEW)
  contract_nda_vertex_pinnacle.txt   (KEEP - still works for generic demo)
  inspection_photos/                 (KEEP - still works for generic demo)
```

## Dependencies

Add to `requirements.txt`:
```
uiautomation>=2.0.18    # For Live Captions UIA wrapper (Windows only)
```

The `uiautomation` package is Windows-only. Guard all imports with try/except and disable Live Assist gracefully on non-Windows or if the package is missing.

---

## Testing Checklist

After each session, verify:

- [ ] App starts without errors: `python npu_demo_flask.py`
- [ ] All 5 original tabs still work (renamed but functional)
- [ ] Config layer: changing `BANK_CONFIG["bank_name"]` updates the UI
- [ ] Persona switcher toggles tab highlights
- [ ] Morning Briefing: Brief Me generates advisor-relevant output
- [ ] PII Guard: scans banking docs and flags PII correctly
- [ ] ID & Check Verify: both Scan ID and Scan Check modes work
- [ ] Advisor Assistant: responds to banking product questions
- [ ] Meeting Notes: scripted input populates banking fields, report generates summary + email + tasks
- [ ] Live Assist: connects to Live Captions (or shows clear error), Demo Script button works, AI Prompter generates insights
- [ ] Trust Receipts log all operations across all tabs
- [ ] Tokenomics counter accumulates correctly
- [ ] Airplane Mode: ID scan and Agent chat still work offline
- [ ] No em dashes anywhere in the UI or AI output
