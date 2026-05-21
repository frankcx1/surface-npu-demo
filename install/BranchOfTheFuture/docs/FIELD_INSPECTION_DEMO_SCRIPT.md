# Field Inspection Copilot — Demo Script & Manual Test Process

## Prerequisites

1. Flask app running: `python npu_demo_flask.py`
2. Foundry Local running with model loaded (check http://localhost:5000/health → `"ready": true`)
3. Browser open to http://localhost:5000

---

## Full Demo Flow (3-4 minutes)

### Step 1: Navigate to Field Inspection Tab

- Click **Field Inspection** in the left sidebar (magnifying glass icon)
- **Verify:** Four-panel layout appears — form (left), photo (center), report (right), bottom bar
- **Verify:** Bottom bar shows "Ready" status, "0 local tokens", "100% Local Processing"
- Tab title toast: "Same local AI — field inspection + on-site assessment"

---

### Step 2: Voice Capture + Field Extraction (Milestone 2)

**Option A — Scripted Input (reliable for demos, no mic needed):**
- Click **Use Scripted Input** button below the mic button
- **Verify:** Transcript appears: "Inspector Sarah Chen reporting from Building C, west wing..."
- **Verify:** Status shows "Extracting fields from transcript..."
- **Verify:** Four form fields populate with staggered animation (green borders):
  - Location: "Building C, West Wing, 3rd Floor"
  - Date/Time: "February 19, 2026 10:00 AM" (or similar)
  - Issue: "Water damage" (or similar from transcript)
  - Source: "Tenant complaint" (or similar)
- **Verify:** Token counter updates (e.g., "~250 local tokens")

**Option B — Live Microphone (if network available for Web Speech API):**
- Click the mic button, speak: "Inspector Frank reporting from the convention center, hall 3. Water stain on ceiling tiles near the northeast corner. Reported by facilities manager today February 19th."
- Same verification as above

---

### Step 3: Camera Capture + Classification (Milestone 3)

- Click **Load Demo Photo** button
- First click loads "Water Damage" demo image
- **Verify:** Photo appears in the grid with a severity badge
- **Verify:** Classification card appears showing:
  - Category: Water Damage
  - Severity: Moderate (amber badge)
  - Confidence: 82% (green bar — above 75%)
  - Explanation text about discoloration/water leak
- **Verify:** Finding #1 appears in the findings log (right panel)
- **Verify:** "Generate Report" button becomes enabled

**Click "Load Demo Photo" again** for structural crack:
- **Verify:** Classification card shows:
  - Category: Structural Crack
  - Severity: High (red badge)
  - Confidence: 72% (amber bar — in 60-74% escalation range)
- **Verify:** Finding #2 appears in findings log
- **THIS TRIGGERS THE ESCALATION DIALOG** (Step 4)

---

### Step 4: Router Escalation (Milestone 7, Part A)

- **Verify:** Escalation overlay appears with "LOW CONFIDENCE FINDING" header
- **Verify:** Two side-by-side panels:
  - Left: "Escalate to Cloud" — shows payload size, withheld items
  - Right: "Keep Local" — green highlight, "RECOMMENDED" badge, "$0.00"
- **Verify:** Payload preview shows "Sending: 1 photo (XX KB)"
- **Verify:** Withheld items listed: "voice transcript, pen annotations, report draft"

**Click "Keep Local" (recommended path):**
- **Verify:** Overlay closes
- **Verify:** "Inspection completed locally" banner appears with lock animation
- **Verify:** Status bar: "Finding flagged for expert review — data stayed local"
- **Verify:** "Show Summary" button appears in bottom bar

**Alternative — Click "Escalate to Cloud" (offline demo path):**
- **Verify:** Overlay closes
- **Verify:** Status: "No connectivity — keeping data local (airplane mode)"
- **Verify:** Same stayed-local banner appears (graceful offline fallback)

---

### Step 5: Capture Additional Photos (Optional)

- Click **Load Demo Photo** 3 more times to cycle through:
  - Mold (88% confidence, High severity) — no escalation
  - Electrical Hazard (91% confidence, Critical severity) — no escalation
  - Trip Hazard (85% confidence, Low severity) — no escalation
- **Verify:** Each adds to the photo grid with correct severity badges
- **Verify:** Findings log grows with each classification
- **Verify:** Token counter stays at 0 for demo presets (no model call)

---

### Step 6: Generate Report (Milestone 5)

- Click **Generate Report** button
- **Verify:** Button text changes to "Generating..."
- **Verify:** Status: "Generating inspection report with local AI..."
- **Wait 10-20 seconds** for model to respond
- **Verify:** Report Preview panel appears with:
  - Executive summary
  - Finding details with severity and confidence
  - Risk rating (should be High or Critical given the findings)
  - Recommended next steps (bullet points)
- **Verify:** Status: "Report generated — Risk: [rating] (Xs)"
- **Verify:** Token counter updates
- **Verify:** "Translate to Spanish" button appears
- **Verify:** Button text changes to "Regenerate Report"

**If model is offline/slow:** Fallback report generates instantly with structured findings from all captured data.

---

### Step 7: Translate to Spanish (Milestone 6)

- Click **Translate to Spanish**
- **Verify:** Button changes to "Translating..."
- **Verify:** Status: "Translating report to Spanish with local AI..."
- **Wait 10-20 seconds**
- **Verify:** Brief side-by-side flash (EN | ES columns, ~500ms) then settles on Spanish
- **Verify:** Report content is now in Spanish (look for "Informe", "Inspeccion", etc.)
- **Verify:** Status: "Translated to Spanish (Xs) — no cloud API call"
- **Verify:** Button text changes to "Switch to English"
- **Verify:** Token counter updates

**Click "Switch to English":**
- **Verify:** Report switches back to English original
- **Verify:** Button text returns to "Translate to Spanish"

---

### Step 8: Dashboard Tally (Milestone 7, Part B)

- Click **Show Summary** button in the bottom bar
- **Verify:** Full-screen overlay appears with "Inspection Summary" header
- **Verify:** Left column (green) "Local AI Tasks" shows checkmarks for completed tasks:
  - Speech-to-text
  - Field extraction
  - Vision classification
  - Report generation
  - Translation
  - Routing logic
- **Verify:** Right column (red) "Cloud Tasks" shows large "0"
- **Verify:** Bottom summary bar: "Total tokens: [N] | Cost: $0.00 | Transmitted: 0 bytes"
- Click **Close** to return to workspace

---

## Quick Demo (90 seconds)

If short on time:

1. Click **Field Inspection** tab (5s)
2. Click **Use Scripted Input** — fields populate (10s)
3. Click **Load Demo Photo** — water damage classified (5s)
4. Click **Load Demo Photo** again — structural crack → escalation dialog (5s)
5. Click **Keep Local** — lock animation (3s)
6. Click **Generate Report** — wait for report (15-20s)
7. Click **Translate to Spanish** — wait for translation (15-20s)
8. Click **Show Summary** — dashboard tally with all checkmarks (5s)
9. Point at "Cloud Tasks: 0" — *"Every step ran on the NPU. Zero data left the device."*

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Fields don't populate after scripted input | Check Flask is running, check browser console for `/inspection/transcribe` errors |
| Classification card doesn't appear | Check browser console for `/inspection/classify` errors |
| Report generation returns fallback instantly | Model may not be loaded — check `/health` endpoint |
| Translation shows "no disponible" message | Model offline — fallback is working correctly |
| Escalation dialog doesn't appear on structural crack | Verify confidence is 72% (in 60-74% amber band) |
| "Show Summary" button not visible | Only appears after an escalation decision (Step 4) |
| Demo photos cycle in wrong order | Order is: water_damage, structural_crack, mold, electrical_hazard, trip_hazard |
| Token counter shows 0 after demo photos | Correct — demo presets don't call the model |

## Demo Talking Points

- **"Every step ran on the neural processor. Voice, vision, report, translation — all local."**
- **"The escalation dialog shows exactly what WOULD leave the device. In airplane mode, nothing can."**
- **"This is the same AI engine powering all five tabs. One model, multiple jobs, zero cloud dependency."**
- **"The dashboard proves it: [N] tokens processed locally, zero bytes transmitted, zero dollars spent."**
