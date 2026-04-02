# Marketing CELA Review — Integration Spec
## NPU Demo Flask App: Auditor Tab Enhancement

### 1. Overview

Add a dual-mode capability to the Auditor tab: **Contract/Legal Review** (existing) and **Marketing/Campaign Review** (new). The marketing mode applies Microsoft's CELA Marketing compliance framework to detect claims requiring substantiation, flag high-risk categories, determine whether a CELA intake request is required, and offer AI-assisted document revision.

### 2. Architecture Changes

#### 2.1 Mode Selector (New UI Component)

**Location:** Top of Auditor tab, replaces current direct-to-dropzone layout.

Two mode cards displayed side-by-side:

| Mode | Icon | Title | Subtitle |
|------|------|-------|----------|
| Contract | 🔒 | Contract / Legal Review | Structured risk analysis + smart escalation |
| Marketing | 📢 | Marketing / Campaign Review | CELA compliance check + claims analysis |

**Behavior:**
- On tab load, show mode selector (no mode pre-selected)
- Clicking a mode card reveals the appropriate dropzone/input area
- Mode selection stored in `currentAuditorMode` JS variable
- Mode passed to `/router/analyze` as `"mode": "contract"` or `"mode": "marketing"` in JSON body
- "Back" link from results returns to mode selector, not dropzone

#### 2.2 Backend Route Modifications

##### `/router/analyze` (line 6194)

Add mode branching after existing setup code:

```python
mode = data.get('mode', 'contract')  # Default to contract for backward compat
```

**Pipeline comparison:**

| Step | Contract Mode (existing) | Marketing Mode (new) |
|------|-------------------------|---------------------|
| Step 0: Preview | ✅ Same | ✅ Same |
| Step 1: PII Scan | ✅ Scan for PII | ✅ Scan for PII (marketing shouldn't contain PII) |
| Step 2: Knowledge Search | ✅ Same | ✅ Same (might surface relevant internal docs) |
| Step 3: System Prompt | Contract analyst prompt | **Marketing CELA prompt** (see §3) |
| Step 3: Analysis Prompt | Risk finding format | **CELA compliance format** (see §3) |
| Step 3: Max Tokens | 800 | **1200** (marketing reviews produce more findings) |
| Step 4: Parse Response | `_parse_analysis_response()` | **`_parse_marketing_response()`** (new function) |
| Step 4: Event Types | `risk`, `obligations`, `summary` | **`claims`, `verdict`, `summary`** (new events) |
| Step 5: Escalation Trigger | Confidence-based (MEDIUM/LOW) | **Rule-based** (any mandatory intake trigger hit) |
| Step 6: Audit Stamp | ✅ Same | ✅ Same (add mode label) |

##### New Flask Route: `/auditor-marketing-demo-doc` (GET)

Returns the "clean" demo marketing asset (self-service OK path).

##### New Flask Route: `/auditor-marketing-escalation-demo-doc` (GET)

Returns the "risky" demo marketing asset (CELA intake required path).

#### 2.3 New Backend Functions

##### `_parse_marketing_response(ai_response)`

Parses the model's structured output into claim findings:

```python
def _parse_marketing_response(ai_response):
    """Parse marketing CELA review output into structured findings."""
    claims = []
    current_claim = {}
    verdict_data = {}
    
    for line in ai_response.split('\n'):
        stripped = line.strip()
        upper = stripped.upper()
        
        # Claim-level fields
        if upper.startswith('CATEGORY:'):
            if current_claim:
                claims.append(current_claim)
            current_claim = {'category': stripped.split(':', 1)[1].strip()}
        elif upper.startswith('CLAIM_TEXT:'):
            current_claim['claim_text'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('RISK_LEVEL:'):
            current_claim['risk_level'] = stripped.split(':', 1)[1].strip().upper()
        elif upper.startswith('ISSUE:'):
            current_claim['issue'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('SUBSTANTIATION:'):
            current_claim['substantiation'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('RECOMMENDATION:'):
            current_claim['recommendation'] = stripped.split(':', 1)[1].strip()
        
        # Verdict-level fields
        elif upper.startswith('VERDICT:'):
            verdict_data['verdict'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('VERDICT_REASON:'):
            verdict_data['verdict_reason'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('TRIGGER_CATEGORIES:'):
            verdict_data['trigger_categories'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('TOTAL_FINDINGS:'):
            verdict_data['total_findings'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('HIGH_RISK_COUNT:'):
            verdict_data['high_risk_count'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('MEDIUM_RISK_COUNT:'):
            verdict_data['medium_risk_count'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('LOW_RISK_COUNT:'):
            verdict_data['low_risk_count'] = stripped.split(':', 1)[1].strip()
    
    if current_claim:
        claims.append(current_claim)
    
    return claims, verdict_data
```

##### New SSE Event Types

```javascript
// Claims findings (replaces 'risk' event in marketing mode)
{ "type": "claims", "findings": [
    {
        "category": "B",
        "claim_text": "3x faster AI processing than the leading competitor",
        "risk_level": "HIGH",
        "issue": "Unsubstantiated comparative claim against unnamed competitor",
        "substantiation": "Benchmark data comparing specific competitor products required",
        "recommendation": "Remove comparative language or provide verifiable benchmark data"
    }
]}

// Verdict (new event, marketing mode only)
{ "type": "verdict",
  "verdict": "CELA INTAKE REQUIRED",
  "verdict_reason": "Asset contains comparative claims, unsubstantiated performance stats, and AI overclaims",
  "trigger_categories": "Comparative, Performance, AI Claims, Green Claims, Endorsements, CVP Authorship, Promotions",
  "total_findings": "14",
  "high_risk_count": "8",
  "medium_risk_count": "4",
  "low_risk_count": "2"
}
```

### 3. System Prompts

See `marketing_cela_prompts.py` for the complete prompt definitions:

- `MARKETING_CELA_SYSTEM_PROMPT` — comprehensive review framework (categories A-J)
- `MARKETING_CELA_ANALYSIS_PROMPT` — task-specific instructions prepended to asset text

Key design decisions:
- Categories A-J map directly to CELA source documents
- Output format mirrors contract mode's structured output pattern
- VERDICT field provides binary self-service vs. intake determination
- TRIGGER_CATEGORIES field lists which mandatory intake triggers were hit
- Confidence assessment retained for escalation-to-frontier compatibility

### 4. UI Changes

#### 4.1 Mode Selector HTML

```html
<!-- Mode Selector (new, replaces immediate dropzone display) -->
<div id="auditorModeSelector">
    <div class="auditor-header">🔒 AUDITOR</div>
    <div class="mode-cards">
        <div class="mode-card" data-mode="contract">
            <div class="mode-card-icon">🔒</div>
            <div class="mode-card-title">Contract / Legal Review</div>
            <div class="mode-card-desc">Structured risk analysis of contracts,
            NDAs, and legal documents with smart escalation.</div>
        </div>
        <div class="mode-card" data-mode="marketing">
            <div class="mode-card-icon">📢</div>
            <div class="mode-card-title">Marketing / Campaign Review</div>
            <div class="mode-card-desc">CELA compliance check for marketing assets.
            Claims analysis, substantiation requirements, and intake determination.</div>
        </div>
    </div>
</div>
```

#### 4.2 Marketing-Specific Results Cards

**Claims Card** — Replaces risk findings card. Each claim shows:
- Category badge (color-coded A-J)
- Quoted claim text (highlighted)
- Risk level indicator (HIGH=red, MEDIUM=amber, LOW=green)
- Issue description
- Substantiation requirement
- Recommendation
- "Edit" button (for edit mode, see §5)

**Verdict Card** — New card type, shows:
- Large verdict badge: "✅ SELF-SERVICE OK" (green) or "🔴 CELA INTAKE REQUIRED" (red)
- Verdict reason
- Trigger categories hit (as tags/badges)
- Counts: total findings, high/medium/low breakdown

**Marketing Demo Buttons:**
```html
<button class="auditor-demo-btn" id="marketingDemoCleanBtn">
    📄 Review: Clean Campaign Page
</button>
<button class="auditor-demo-btn" id="marketingDemoRiskyBtn" 
    style="border-color:rgba(255,185,0,0.4);color:#FFB900;">
    ⚠️ Review: Risky Campaign Brief
</button>
```

#### 4.3 Marketing Escalation Logic

Unlike contract mode (confidence-based), marketing escalation is **rule-based**:

```javascript
// Marketing: escalate if verdict requires intake
if (evt.type === "verdict" && evt.verdict.includes("CELA INTAKE REQUIRED")) {
    // Show escalation consent panel
    // In this context, escalation = "send to frontier for detailed rewrite suggestions"
    // Rather than CELA itself, this demonstrates the two-brain pattern:
    //   Local NPU catches the issues → Frontier AI generates compliant alternatives
}
```

### 5. Edit Mode (New Feature — Both Modes)

After review completes, user can enter **Edit Mode** to accept AI-suggested rewrites.

#### 5.1 UI Layout

Split-panel view:
- **Left panel:** Original document with flagged sections highlighted (yellow for claims in marketing, red for risks in contract)
- **Right panel:** Suggested revision with changes shown as tracked-change-style diffs (strikethrough for removed text, green highlight for inserted text)

#### 5.2 Per-Finding Edit Controls

Each finding in the review results gets an "Edit" button. Clicking it:
1. Scrolls the left panel to the relevant section
2. Highlights the flagged text
3. Calls the model to generate a compliant rewrite of JUST that section
4. Shows the suggested rewrite in the right panel
5. User clicks "Accept" (applies the change) or "Reject" (keeps original)

#### 5.3 Rewrite Prompt

```python
MARKETING_REWRITE_PROMPT = (
    "You are a marketing compliance editor. Rewrite ONLY the flagged text "
    "to be CELA-compliant. Keep the marketing intent and persuasive quality "
    "while removing the compliance issue.\n\n"
    "ORIGINAL TEXT: {claim_text}\n"
    "ISSUE: {issue}\n"
    "RECOMMENDATION: {recommendation}\n\n"
    "Provide ONLY the rewritten text, nothing else."
)
```

#### 5.4 Edit Mode Route

```python
@app.route('/router/rewrite', methods=['POST'])
def router_rewrite():
    """Generate a CELA-compliant rewrite of a flagged section."""
    data = request.get_json()
    claim_text = data.get('claim_text', '')
    issue = data.get('issue', '')
    recommendation = data.get('recommendation', '')
    
    prompt = MARKETING_REWRITE_PROMPT.format(
        claim_text=claim_text,
        issue=issue,
        recommendation=recommendation
    )
    
    response = foundry_chat(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": "You are a concise marketing compliance editor."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=300,
        temperature=0.3,
    )
    
    rewrite = (response.choices[0].message.content or "").strip()
    return jsonify({"original": claim_text, "rewrite": rewrite})
```

### 6. Demo Data Files

| File | Path | Purpose |
|------|------|---------|
| `marketing_surface_campaign_clean.txt` | `demo_data/` | "Clean" asset — mostly compliant, minor flags, self-service OK verdict |
| `marketing_surface_campaign_risky.txt` | `demo_data/` | "Risky" asset — loaded with triggers, CELA intake required verdict |

**Clean asset expected findings (~3-4 items):**
- Recall marked as preview but "Find anything" could be read as overclaim (LOW)
- Customer quote present — verify CQA on file (LOW)
- "AI-Powered Workplace" in hero — verify against approved AI terminology (LOW)

**Risky asset expected findings (~12-16 items):**
- "Most Intelligent PC Ever Made" — superlative (HIGH)
- "The only laptop that truly understands you" — exclusivity + AI overclaim (HIGH)
- "40% more productive" — unsubstantiated performance claim (HIGH)
- "3x faster AI processing than the leading competitor" — comparative claim (HIGH)
- "47% improvement in battery life" — unsubstantiated performance claim (HIGH)
- "60% less energy consumption" — unsubstantiated green claim (HIGH)
- "Customers report an average ROI of 340%" — unsubstantiated ROI claim (HIGH)
- Anonymous customer quote — explicitly prohibited (HIGH)
- Named customer quote (JPMorgan) — verify CQA + ECA (HIGH)
- Customer logos without documented permission (HIGH)
- "responsible AI-compliant platform" — prohibited AI messaging (HIGH)
- "guaranteed free from bias" — prohibited AI overclaim (HIGH)
- "Recall: Perfect photographic memory" — overclaim, not GA everywhere (HIGH)
- Health insights feature — sensitive AI use (MEDIUM)
- "Autonomous Email Triage" — autonomous AI claim (MEDIUM)
- CVP authorship — mandatory intake trigger (HIGH)
- Sweepstakes/contest — mandatory intake trigger (HIGH)
- "Guaranteed lowest price" — absolute pricing claim (HIGH)
- Above-the-line asset type — mandatory intake trigger (HIGH)
- Missing Copilot+ PC disclaimers for global/China (MEDIUM)
- "Carbon neutral" / "100% recycled ocean-bound plastic" — green claims (HIGH)

### 7. Implementation Sequence

1. **Phase 1: Demo Data + Prompts** ✅ (this document)
   - Create demo marketing assets
   - Write marketing CELA system prompt
   - Write integration spec

2. **Phase 2: Backend Routes**
   - Add `mode` parameter to `/router/analyze`
   - Add marketing system prompt branch
   - Add `_parse_marketing_response()` function
   - Add marketing demo doc routes
   - Add `/router/rewrite` route

3. **Phase 3: Frontend - Mode Selector**
   - Add mode selector HTML/CSS
   - Wire mode selection to JS state
   - Update `startRouterAnalysis()` to pass mode
   - Update demo button handlers

4. **Phase 4: Frontend - Marketing Results**
   - Add claims card renderer
   - Add verdict card renderer
   - Update SSE handler for new event types
   - Wire marketing escalation logic

5. **Phase 5: Edit Mode**
   - Add split-panel layout
   - Add per-finding edit buttons
   - Wire rewrite API calls
   - Implement accept/reject per finding
   - Show final document with all accepted changes

### 8. Demo Flow Scripts

**Demo 1: Clean Campaign (Self-Service Path)**
1. Select "Marketing / Campaign Review" mode
2. Click "Review: Clean Campaign Page"
3. Watch: PII scan → Claims analysis → Results
4. Show: 3-4 low-risk findings, verdict = SELF-SERVICE OK
5. Talking point: "The on-device model caught minor style issues but confirmed this asset can proceed without CELA review."

**Demo 2: Risky Campaign (Escalation Path)**
1. Click "Review: Risky Campaign Brief"
2. Watch: PII scan → Claims analysis → Results cascade
3. Show: 12+ findings across 8+ categories, verdict = CELA INTAKE REQUIRED
4. Show: Trigger categories lit up like a Christmas tree
5. Click "Edit" on a finding → Show AI-generated compliant rewrite
6. Talking point: "The local model identified every compliance issue in seconds, told the marketer exactly what needs fixing, and can even suggest compliant alternatives — all without the document leaving the device."

**Demo 3: Two-Brain Escalation (if time permits)**
1. From risky campaign results, click escalation
2. Show PII redaction (if any PII present)
3. Show cost estimate for frontier review
4. Talking point: "When the local model flags high-risk content, the user can optionally escalate to a frontier model for more detailed rewrite suggestions — but only with explicit consent, and only after PII is scrubbed."
