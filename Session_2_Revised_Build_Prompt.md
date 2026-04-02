# Session 2 Revision: Live Assist + Check Scanner
# Feed this to Claude Code as a follow-up to the Session 1 work already committed.

## Context for Claude Code

Session 1 is complete. The DEMO_CONFIG layer is committed to main with CSS custom properties, persona switcher, and template variable injection. All 5 tabs render with config-driven branding. This session adds two new generic platform features to main: Live Assist (transcript + AI prompter) and Check Scanner.

**Read the TECHNICAL_GUIDE.md and README.md before starting.** The app is `npu_demo_flask.py` (~11,300 lines after Session 1). All constraints from Session 1 still apply: no em dashes, single-file architecture, IIFE code pattern, token budget awareness.

---

## Task 2.1: Live Assist Tab

### Important: Build Demo Script Mode FIRST

Build the Demo Script (simulated conversation) mode first and make it bulletproof. This is the primary demo path. The Live Captions UIA integration is a bonus layer on top. If UIA is unreliable on demo day, Demo Script carries the story. Nobody in the audience will know the difference. The AI Prompter intelligence cards are the wow moment, not the transcript source.

### Architecture Overview

This tab has two panes and two transcript sources (Demo Script and Live Captions UIA). The AI Prompter works identically regardless of source.

```
Transcript Sources (pick one):
  A) Demo Script (simulated, bulletproof)     ─┐
  B) Live Captions UIA (real, fragile)         ─┤
                                                │
                                    ┌───────────▼───────────┐
                                    │  Transcript Buffer    │
                                    │  (sentence detection) │
                                    └───────────┬───────────┘
                                                │
                              ┌─────────────────┼──────────────────┐
                              │                 │                  │
                    ┌─────────▼──────┐  ┌───────▼────────┐  ┌─────▼──────┐
                    │ Left Pane:     │  │ Right Pane:    │  │ Sentiment  │
                    │ Live Transcript│  │ AI Prompter    │  │ Indicator  │
                    │ (scrolling)    │  │ (Phi-4 Mini)   │  │ (dot)      │
                    └────────────────┘  └────────────────┘  └────────────┘
```

### Phase 1: Demo Script Mode + AI Prompter + Frontend

**Add sidebar nav item.** Insert between "ID Verification" and "Field Inspection" (or whatever the current tab names are). Use DEMO_CONFIG for the tab name/subtitle/icon:

```python
# Add to DEMO_CONFIG["tabs"]:
"live": {"name": "Live Assist", "sub": "Transcript + AI", "icon": "&#127908;"},
```

**Frontend: Two-pane layout (HTML/CSS in the inline template)**

```
┌─────────────────────────────┬──────────────────────────┐
│  LIVE TRANSCRIPT            │  AI ADVISOR PROMPTS       │
│  [green pulsing dot] Active │  [sentiment dot]          │
│                             │                           │
│  [10:32:15] Customer text   │  ┌─────────────────────┐  │
│  appears here as it flows   │  │ Insight Card         │  │
│  with fade-in animation...  │  │ "Customer mentioned  │  │
│                             │  │  two children..."    │  │
│  [10:32:18] More text       │  │ 🟢 POSITIVE          │  │
│  appears incrementally...   │  └─────────────────────┘  │
│                             │                           │
│                             │  ┌─────────────────────┐  │
│                             │  │ Older insight...     │  │
│                             │  └─────────────────────┘  │
├─────────────────────────────┴──────────────────────────┤
│ [▶ Start Demo Script] [🎙 Connect Live Captions]       │
│ Status: Ready                                           │
└─────────────────────────────────────────────────────────┘
```

Left pane: 60% width. Scrolling transcript area. Each chunk gets a timestamp and fade-in animation. Auto-scrolls to bottom.

Right pane: 40% width. AI intelligence cards stack newest on top, max 5 visible (overflow scrolls). Each card has: insight text, sentiment badge (green dot = POSITIVE, amber = NEUTRAL, red = CAUTIOUS), timestamp.

Bottom bar: Two buttons ("Start Demo Script" and "Connect Live Captions"), status text, language indicator.

**Demo Script engine (JavaScript, in IIFE):**

Create a pre-written banking conversation as an array of objects:

```javascript
var _liveAssistDemoScript = [
    {delay: 0,    text: "Hi, I'm Jackie. I called earlier about opening a new account."},
    {delay: 3000, text: "I just moved here from out of state and I need to set up checking and savings."},
    {delay: 3500, text: "I also have two kids, Maya is eight and Daniel is fifteen."},
    {delay: 4000, text: "My husband and I have been talking about saving for their college."},
    {delay: 3000, text: "Someone mentioned a 529 plan but I don't really understand how it works."},
    {delay: 3500, text: "Is there a limit on how much we can put in each year?"},
    {delay: 4000, text: "We're also thinking about retirement. I have an old 401k from my previous job that I never rolled over."},
    {delay: 3000, text: "I'm forty-five, so I feel like I'm behind on retirement planning."},
    {delay: 3500, text: "What would you recommend, a Roth IRA or a traditional IRA for someone my age?"},
    {delay: 4000, text: "And honestly, the fees at my last bank were ridiculous. That's part of why I'm switching."},
    {delay: 3000, text: "What are the monthly fees on your checking accounts?"},
    {delay: 3500, text: "OK that sounds reasonable. Let's go ahead and get the checking set up today."},
    {delay: 3000, text: "And I'd like to schedule a follow-up to go deeper on the college savings and retirement options."},
];
```

When "Start Demo Script" is clicked:
1. Iterate through the array, waiting `delay` ms between each line
2. Append each line to the transcript pane with timestamp and fade-in
3. Accumulate text in a buffer
4. Every 2-3 sentences (detect by period/question mark followed by capital letter or end of string), send the buffer to `/live-assist/analyze`
5. Display the AI response as a new card in the right pane
6. Button changes to "Stop Script" while running
7. At the end, show a summary: "Demo complete. X transcript lines. Y AI insights. All processed locally."

**Backend: AI Analysis endpoint**

```python
@app.route('/live-assist/analyze', methods=['POST'])
def live_assist_analyze():
    """Analyze a transcript chunk and return AI insights + sentiment."""
    data = request.get_json()
    transcript_chunk = data.get('text', '')
    prior_insights = data.get('prior', '')  # avoid repeats

    system = (
        "You are a real-time advisor intelligence system for a bank wealth advisor. "
        "Based on the customer conversation excerpt below, provide 1-2 brief, actionable insights. "
        "Focus on: product opportunities, compliance flags, follow-up actions, or relevant financial facts. "
        "Also rate the overall customer sentiment as POSITIVE, NEUTRAL, or CAUTIOUS. "
        "Be concise (3 sentences max for insights). Do not repeat these prior insights: " + prior_insights
    )

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Transcript: {transcript_chunk}"}
        ],
        max_tokens=256,
        temperature=0.3
    )

    result_text = response.choices[0].message.content
    # Parse sentiment from response (look for POSITIVE/NEUTRAL/CAUTIOUS)
    sentiment = "NEUTRAL"
    for s in ["POSITIVE", "CAUTIOUS", "NEUTRAL"]:
        if s in result_text.upper():
            sentiment = s
            break

    return jsonify({
        "insights": result_text,
        "sentiment": sentiment,
        "tokens_used": response.usage.total_tokens if response.usage else 0
    })
```

**Buffering logic detail (JavaScript):**

CRITICAL: Do NOT send overlapping or duplicate text to the analysis endpoint. The buffer should:
- Accumulate new transcript lines as they appear
- Track how many lines have been sent for analysis so far
- When 2-3 NEW unsent lines have accumulated, package them and send
- Track prior insight summaries (first 10 words of each) to pass as `prior` to avoid repeats
- Max one analysis request in-flight at a time (set a `_liveAssistAnalyzing` flag)
- If the script finishes while analysis is in-flight, wait for it to complete

**Acceptance for Phase 1:**
- Demo Script plays through smoothly with realistic pacing
- Transcript pane fills with timestamped, animated text
- AI Prompter generates 4-5 insight cards during a full script run
- Sentiment badges appear correctly
- No duplicate or repeated insights
- Works offline (Phi-4 Mini is local)
- Trust Receipt / tokenomics counter incremented for each analysis call

### Phase 2: Live Captions UIA Integration (bonus layer)

**Only build this after Phase 1 is solid.**

**CRITICAL: Live Captions text update behavior.**
Live Captions does NOT append text. It overwrites the CaptionsTextBlock element in-place as it refines the transcription. You will see "I'd like to open a" update to "I'd like to open a five twenty-nine plan" in the same element. The text block contains the most recent ~2-3 sentences at any time, not a running log.

This means the polling logic needs **diff detection**, not simple append:

```python
_last_caption_text = ""
_committed_sentences = []

def _poll_caption():
    global _last_caption_text
    current = get_caption_text()  # UIA call
    if current == _last_caption_text:
        return None  # no change

    # Detect what's new by comparing with last known text
    # Live Captions typically keeps 2-3 recent sentences visible
    # The new content is whatever appears AFTER the overlap with our last read
    _last_caption_text = current

    # Split into sentences and check which are truly new
    # (not seen in _committed_sentences)
    sentences = re.split(r'(?<=[.?!])\s+', current)
    new_sentences = []
    for s in sentences:
        s_clean = s.strip()
        if s_clean and s_clean not in _committed_sentences[-10:]:
            new_sentences.append(s_clean)
            _committed_sentences.append(s_clean)

    if new_sentences:
        return " ".join(new_sentences)
    return None
```

**Polling interval: 250ms, not 100ms.** UIA tree traversal is expensive. 250ms is plenty fast for a live transcript display and much better for battery/performance. Users will not notice the difference.

**Backend thread + SSE:**

```python
@app.route('/live-assist/start-live', methods=['POST'])
def start_live_captions():
    """Start the UIA listener thread."""
    # Launch Live Captions if not running
    # Start background thread polling at 250ms
    # Return success/failure

@app.route('/live-assist/stream', methods=['GET'])
def live_assist_stream():
    """SSE endpoint streaming new caption text to frontend."""
    # Same SSE pattern used by /brief-me
    # Read from internal queue, yield as SSE events
```

**Guard against analysis queue buildup.** If the customer talks fast, analysis requests (5-10s each) can queue up. Implement a max-in-flight of 1 analysis at a time. If a new chunk is ready but analysis is still running, consolidate: merge the pending chunk with the new one so when analysis finishes, it processes the combined text in one call.

**UIA dependency:**

```python
try:
    import uiautomation as auto
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False
```

If `uiautomation` is not installed, the "Connect Live Captions" button should show "Install uiautomation package to enable" and be disabled. The Demo Script button always works regardless.

**Fallback UI:** If Live Captions is not running or the CaptionsTextBlock element is not found, show: "Live Captions not detected. Press Win+Ctrl+L to enable Live Captions, then click Retry." Provide a "Retry Connection" button.

**Acceptance for Phase 2:**
- "Connect Live Captions" button finds and connects to Live Captions window
- Transcript pane shows real-time text from any audio playing or mic input
- Diff logic correctly extracts only new content (no duplicates, no re-processing)
- AI Prompter generates insights from live speech just like Demo Script mode
- Graceful fallback when Live Captions is not running
- Demo Script still works independently of Live Captions

---

## Task 2.2: Extend ID Verification with Check Scanner

**This is a low-risk extension.** Same camera, same OCR pipeline, different AI prompt.

Add a mode switcher at the top of the ID Verification tab. Two toggle buttons: "Scan ID" (default, existing behavior) and "Scan Check" (new).

**Scan Check mode:**
- Uses the identical camera capture and Tesseract OCR pipeline
- After OCR, calls a new endpoint: `POST /analyze-check`
- System prompt:

```
You are a check verification assistant. Analyze the OCR text from a scanned check image. Extract these fields as JSON: payee_name, payer_name, check_number, date, amount_numbers, amount_words, bank_name, routing_last4, account_last4, memo, signature_present (yes/no). Flag any issues: amount mismatch between numbers and words, missing signature, stale date (>180 days old), missing required fields. Return ONLY valid JSON.
```

- Display results in a styled card similar to the ID verification card, with check-specific fields and a validation section showing flags.

**Demo preset for checks:** Claude Code's feedback is correct that MICR font (the magnetic ink characters at the bottom of checks) is hard for Tesseract. For the demo, create a demo preset mode that uses a clean, pre-captured check image with known-good OCR text. Same pattern as Field Inspection's demo photo presets. The live camera path exists for real-world use, but the demo always uses the preset for reliability.

**Acceptance:**
- Mode switcher toggles cleanly between ID and Check views
- Scan Check with demo preset produces structured field extraction
- Validation flags appear for issues (test with a check that has mismatched amount words/numbers)
- Both modes share the camera pipeline without conflict
- Trust Receipt logs check scans as local operations

---

## Add to DEMO_CONFIG

```python
# In DEMO_CONFIG["tabs"], add:
"live": {"name": "Live Assist", "sub": "Transcript + AI", "icon": "&#127908;"},
```

Update the sidebar nav HTML and tab content div to include the new Live Assist tab. Follow the exact pattern used by the other tabs for nav item, tab button (hidden), and tab content div.

## Add to requirements.txt

```
uiautomation>=2.0.18    # Windows only, for Live Captions integration
```

Guard all imports with try/except. The app must start cleanly without uiautomation installed.

## Testing Checklist

- [ ] Demo Script plays through without errors, generates 4-5 insight cards
- [ ] AI Prompter shows sentiment badges (green/amber/red)
- [ ] No duplicate insights across cards
- [ ] Buffer sends correct 2-3 sentence chunks (not single words, not entire transcript)
- [ ] "Connect Live Captions" button shows appropriate state when Live Captions is not running
- [ ] If uiautomation is not installed, button is disabled with clear message
- [ ] Check Scanner mode switcher works
- [ ] Check demo preset produces correct field extraction
- [ ] Both ID and Check modes share camera without conflict
- [ ] Trust Receipts logged for all new operations
- [ ] Tokenomics counter increments correctly
- [ ] All original tabs still work
- [ ] App starts without errors even without uiautomation installed
