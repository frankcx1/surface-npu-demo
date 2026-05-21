# Phase 1 Implementation: Two-Brain Escalation Engine

## Context

You are adding a "Two-Brain Escalation Engine" to an existing Flask app (`npu_demo_flask.py`, ~6120 lines). The app is a local AI demo running Phi-4 Mini via Foundry Local on an Intel Core Ultra NPU. It currently has four tabs: AI Agent (chat + tool calling), My Day (chief of staff briefing), Clean Room Auditor (NDA review + PII detection), and ID Verification (camera + OCR).

The goal of this feature is to make the "80% local / 20% frontier" AI strategy into a live, experiential decision moment. When a user analyzes a document or asks a complex question, the system attempts to answer locally first, searches local documents for supporting context, then presents a single "Decision Card" showing whether the answer is sufficient or whether frontier (cloud) reasoning might help. If escalation is offered, the user sees exactly what data would leave the device (with PII redacted) and the estimated cloud cost, then explicitly approves or declines. Declining is treated as the "heroic path" — visually celebrated with a lock animation and Trust Receipt.

**Read the entire file first before making any changes.** The app is a single-file Flask app with inline HTML/CSS/JS in a large `HTML_TEMPLATE` string. All model calls use `client.chat.completions.create()` pointed at a local Foundry Local endpoint. All streaming endpoints use `Response(generate(), mimetype='text/plain')` with `yield json.dumps({...}) + "\n"` for SSE-style streaming.

---

## Part A: Local Knowledge Index (Backend)

Build a lightweight keyword search index over local documents that feeds into the Router's decision-making. This is NOT a standalone feature — it exists to help the Router answer questions with citations, often preventing escalation entirely.

### A1. Document Indexing

Add a module-level index that builds on app startup:

```python
# --- Local Knowledge Index ---
KNOWLEDGE_INDEX = {}  # {filename: {"text": str, "keywords": dict}}
```

**Indexing function:**

- Scan `DEMO_DIR` recursively for `.txt`, `.pdf`, `.docx`, `.md` files
- Use the existing `extract_text()` function (line ~458) which already handles PDF/DOCX/TXT
- For each file, store: full text, filename, word count
- Build a simple TF-IDF-style keyword map: for each file, count term frequencies (lowercased, stripped of punctuation, excluding common stopwords)
- Call this function at startup (after `DEMO_DIR` is created, after demo NDA file is written) and expose a `/knowledge/refresh` POST endpoint to rebuild on demand

**Pattern to follow:** Look at how `DEMO_DIR` is set up (line ~41) and how demo files are created at module level (lines 44-127). The index build should happen in the same initialization section.

```python
def build_knowledge_index():
    """Scan DEMO_DIR and build keyword index for Local Knowledge search."""
    global KNOWLEDGE_INDEX
    index = {}
    stopwords = {'the','a','an','and','or','but','in','on','at','to','for','of','is','it','that','this','with','as','by','from','be','was','were','are','been','being','have','has','had','do','does','did','will','would','shall','should','may','might','can','could'}
    
    for root, dirs, files in os.walk(DEMO_DIR):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ('.txt', '.pdf', '.docx', '.md'):
                continue
            filepath = os.path.join(root, fname)
            try:
                text = extract_text(filepath)
                if text and not text.startswith("Error"):
                    words = re.findall(r'[a-z]+', text.lower())
                    term_freq = {}
                    for w in words:
                        if w not in stopwords and len(w) > 2:
                            term_freq[w] = term_freq.get(w, 0) + 1
                    index[fname] = {
                        "text": text,
                        "path": filepath,
                        "word_count": len(words),
                        "terms": term_freq,
                    }
            except Exception:
                continue
    KNOWLEDGE_INDEX = index
    print(f"  Local Knowledge: indexed {len(index)} documents in {DEMO_DIR}")
```

### A2. Search Function

```python
def search_knowledge(query, top_k=3):
    """Search the local knowledge index. Returns list of {filename, snippet, score}."""
    if not KNOWLEDGE_INDEX:
        return []
    
    query_terms = set(re.findall(r'[a-z]+', query.lower()))
    results = []
    
    for fname, data in KNOWLEDGE_INDEX.items():
        score = sum(data["terms"].get(t, 0) for t in query_terms)
        if score > 0:
            # Extract best matching snippet (find densest region of query terms)
            text = data["text"]
            best_snippet = _extract_best_snippet(text, query_terms, max_len=500)
            results.append({
                "filename": fname,
                "snippet": best_snippet,
                "score": score,
                "word_count": data["word_count"],
            })
    
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _extract_best_snippet(text, query_terms, max_len=500):
    """Find the text region with highest density of query terms."""
    words = text.split()
    if len(words) <= 60:
        return text[:max_len]
    
    window = 60  # ~60 words window
    best_score = 0
    best_start = 0
    
    for i in range(len(words) - window):
        chunk = ' '.join(words[i:i+window]).lower()
        score = sum(1 for t in query_terms if t in chunk)
        if score > best_score:
            best_score = score
            best_start = i
    
    snippet = ' '.join(words[best_start:best_start+window])
    return snippet[:max_len]
```

### A3. Endpoint

```python
@app.route('/knowledge/search', methods=['POST'])
def knowledge_search():
    """Search local knowledge index."""
    query = (request.json or {}).get('query', '')
    results = search_knowledge(query)
    return jsonify({"results": results, "total_indexed": len(KNOWLEDGE_INDEX)})

@app.route('/knowledge/refresh', methods=['POST'])
def knowledge_refresh():
    """Rebuild the local knowledge index."""
    build_knowledge_index()
    return jsonify({"indexed": len(KNOWLEDGE_INDEX)})
```

Call `build_knowledge_index()` at startup — place it right after the demo NDA file creation block (after line ~127), before `AGENT_AUDIT_LOG = []`.

---

## Part B: Two-Brain Router (Backend)

This is the core endpoint. It receives a document or question, attempts a local answer with Local Knowledge context, assesses confidence, and returns a structured Decision Card.

### B1. Router Endpoint

Add a new route `/router/analyze` that implements the full flow:

```python
# --- Two-Brain Router ---
ROUTER_LOG = []  # Structured trust receipt log

@app.route('/router/analyze', methods=['POST'])
def router_analyze():
    """Two-Brain Router: local attempt → knowledge search → decision card → optional escalation consent."""
    data = request.json
    text = data.get('text', '')           # Document text or question
    query = data.get('query', '')         # What the user wants to know
    filename = data.get('filename', '')   # Source document name
    model = DEFAULT_MODEL

    def generate():
        start = _time.time()

        # Step 1: Search Local Knowledge for relevant context
        yield json.dumps({"type": "status", "message": "Searching Local Knowledge..."}) + "\n"
        
        search_query = query if query else text[:200]
        knowledge_results = search_knowledge(search_query)
        
        knowledge_context = ""
        sources_used = []
        if knowledge_results:
            for kr in knowledge_results:
                knowledge_context += f"\n--- From {kr['filename']} ---\n{kr['snippet']}\n"
                sources_used.append({"filename": kr["filename"], "score": kr["score"], "word_count": kr["word_count"]})
        
        yield json.dumps({
            "type": "knowledge",
            "sources": sources_used,
            "total_indexed": len(KNOWLEDGE_INDEX),
        }) + "\n"

        # Step 2: Local analysis with knowledge context
        yield json.dumps({"type": "status", "message": "Analyzing locally with Phi-4 Mini..."}) + "\n"
        
        system_prompt = (
            "You are an analyst running locally on an NPU. Answer the user's question using the document and any local knowledge context provided.\n\n"
            "After your answer, assess your confidence:\n"
            "- CONFIDENCE: HIGH / MEDIUM / LOW\n"
            "- REASONING: one sentence explaining your confidence level\n"
            "- FRONTIER_BENEFIT: one sentence on what a more powerful model might add (or 'None — local answer is complete')\n\n"
            "If local knowledge sources were provided, cite them inline like: (Source: filename.txt)"
        )
        
        user_content = ""
        if text:
            user_content += f"DOCUMENT ({filename}):\n{text[:2500]}\n\n"
        if knowledge_context:
            user_content += f"LOCAL KNOWLEDGE:\n{knowledge_context}\n\n"
        user_content += f"QUESTION: {query}" if query else "Provide a comprehensive analysis of this document."
        
        try:
            _call_start = _time.time()
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=800,
                temperature=0.3,
            )
            _track_model_call(response, _time.time() - _call_start)
            ai_response = (response.choices[0].message.content or "").strip()
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
            return
        
        analysis_time = round(_time.time() - start, 1)
        
        # Step 3: Parse confidence from response
        confidence = "HIGH"
        reasoning = ""
        frontier_benefit = "None — local answer is complete"
        
        for line in ai_response.split('\n'):
            line_stripped = line.strip()
            line_upper = line_stripped.upper()
            if line_upper.startswith('CONFIDENCE:'):
                val = line_stripped.split(':', 1)[1].strip().upper()
                if val in ('HIGH', 'MEDIUM', 'LOW'):
                    confidence = val
            elif line_upper.startswith('REASONING:'):
                reasoning = line_stripped.split(':', 1)[1].strip()
            elif line_upper.startswith('FRONTIER_BENEFIT:'):
                frontier_benefit = line_stripped.split(':', 1)[1].strip()
        
        # Clean the analysis text (remove the confidence metadata lines from display)
        display_text = '\n'.join(
            line for line in ai_response.split('\n')
            if not line.strip().upper().startswith(('CONFIDENCE:', 'REASONING:', 'FRONTIER_BENEFIT:'))
        ).strip()
        
        # Step 4: Yield the Decision Card data
        yield json.dumps({
            "type": "decision_card",
            "analysis": display_text,
            "confidence": confidence,  # HIGH, MEDIUM, LOW
            "reasoning": reasoning,
            "frontier_benefit": frontier_benefit,
            "sources_used": sources_used,
            "analysis_time": analysis_time,
        }) + "\n"

        # Step 5: If confidence is not HIGH, prepare escalation data
        if confidence in ("MEDIUM", "LOW"):
            # Run PII scan on the text that would be sent
            pii_findings = _scan_pii(text) if text else []
            redacted_text = _redact_text(text, pii_findings) if text else ""
            
            # Estimate token cost for frontier
            redacted_tokens = len(redacted_text.split()) * 1.3  # rough word-to-token ratio
            # GPT-4o pricing: $2.50/1M input, $10.00/1M output, 1.5x enterprise overhead
            estimated_input_tokens = int(redacted_tokens + 200)  # +200 for system prompt
            estimated_output_tokens = 400
            estimated_cost = (estimated_input_tokens * 2.50 / 1e6 + estimated_output_tokens * 10.00 / 1e6) * 1.5
            
            yield json.dumps({
                "type": "escalation_available",
                "pii_found": len(pii_findings),
                "pii_details": pii_findings,
                "original_preview": text[:800] if text else "",
                "redacted_preview": redacted_text[:800] if redacted_text else "",
                "estimated_tokens": estimated_input_tokens + estimated_output_tokens,
                "estimated_cost": round(estimated_cost, 4),
            }) + "\n"
        
        total_time = round(_time.time() - start, 1)
        yield json.dumps({"type": "complete", "total_time": total_time}) + "\n"

    return Response(generate(), mimetype='text/plain')
```

### B2. PII Scanning and Redaction Helpers

Reuse and extend the existing PII detection logic from the auditor (lines ~5146-5170). Add a redaction function:

```python
def _scan_pii(text):
    """Scan text for PII. Returns list of findings with type, value, position."""
    findings = []
    # SSN
    for match in re.finditer(r'\b(\d{3})-(\d{2})-(\d{4})\b', text):
        findings.append({"type": "SSN", "value": match.group(0), "start": match.start(), "end": match.end(), "severity": "high"})
    # Email
    for match in re.finditer(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text):
        findings.append({"type": "Email", "value": match.group(0), "start": match.start(), "end": match.end(), "severity": "medium"})
    # Phone
    for match in re.finditer(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text):
        findings.append({"type": "Phone", "value": match.group(0), "start": match.start(), "end": match.end(), "severity": "medium"})
    # Sort by position (reverse) for safe redaction
    findings.sort(key=lambda f: f["start"], reverse=True)
    return findings


def _redact_text(text, pii_findings):
    """Redact PII from text. Returns redacted copy."""
    redacted = text
    for finding in pii_findings:
        mask = f"[REDACTED {finding['type']}]"
        redacted = redacted[:finding["start"]] + mask + redacted[finding["end"]:]
    return redacted
```

### B3. Escalation Decision Endpoint

Handle the user's approve/decline response:

```python
@app.route('/router/decide', methods=['POST'])
def router_decide():
    """Record the user's escalation decision and generate Trust Receipt."""
    data = request.json
    decision = data.get('decision', 'decline')  # 'approve' or 'decline'
    context = data.get('context', {})  # metadata from the analysis
    
    # Build Trust Receipt
    receipt = {
        "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "decision": decision,
        "model_used": DEFAULT_MODEL,
        "offline": not _check_network(),
        "pii_detected": context.get('pii_found', 0),
        "pii_types": [f["type"] for f in context.get('pii_details', [])],
        "estimated_cost_if_escalated": context.get('estimated_cost', 0),
        "estimated_tokens_if_escalated": context.get('estimated_tokens', 0),
        "confidence": context.get('confidence', 'unknown'),
        "sources_consulted": [s["filename"] for s in context.get('sources_used', [])],
        "data_sent": decision == 'approve',
    }
    
    # Build counterfactual line
    if decision == 'decline':
        receipt["counterfactual"] = (
            f"If escalated: ~{receipt['estimated_tokens_if_escalated']} tokens to Azure endpoint, "
            f"est. ${receipt['estimated_cost_if_escalated']:.4f}, "
            f"payload would have contained {receipt['pii_detected']} PII item(s) "
            f"({', '.join(set(receipt['pii_types'])) if receipt['pii_types'] else 'none detected'})"
        )
    
    ROUTER_LOG.append(receipt)
    
    # Also add to AGENT_AUDIT_LOG for unified audit trail
    AGENT_AUDIT_LOG.append({
        "timestamp": _time.strftime("%H:%M:%S"),
        "tool": "router",
        "arguments": {"decision": decision, "confidence": receipt["confidence"]},
        "success": True,
        "time": 0,
    })
    
    return jsonify(receipt)


def _check_network():
    """Quick check if network is up."""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-NetAdapter -Name 'Wi-Fi' -ErrorAction SilentlyContinue).Status"],
            capture_output=True, text=True, timeout=3
        )
        return "Up" in (proc.stdout or "")
    except Exception:
        return False
```

### B4. Trust Receipt Log Endpoint

```python
@app.route('/router/log', methods=['GET'])
def router_log():
    """Return the full Router decision log (Trust Receipts)."""
    return jsonify(ROUTER_LOG)
```

---

## Part C: Router UI (Frontend)

The Router needs a new sidebar tab and a frontend UI that renders the Decision Card, consent screen, and Trust Receipt. All frontend code lives inside the `HTML_TEMPLATE` string in the Flask file.

### C1. Add Sidebar Nav Item

Find the sidebar nav section (around line 1709). Add a new nav item **between** "AI Agent" and "My Day":

```html
<a class="sidebar-nav-item" data-tab="router">
    <span class="nav-icon">&#129504;</span>
    <span class="sidebar-label">Two-Brain<span class="sidebar-nav-sub">Local vs. Frontier Router</span></span>
</a>
```

Also add a corresponding hidden tab button in the `<div class="tabs">` section (around line 1757):

```html
<button class="tab-btn" id="routerTabBtn">Two-Brain Router</button>
```

And update the tab mapping in the JavaScript `sidebarNavItems` click handler (search for `data-tab` handlers around lines 2118 and 2201) to include `router: { tabId: "router-tab", btnId: "routerTabBtn", toast: "Two-Brain Router — local vs. frontier" }`.

### C2. Add Router Tab HTML

Add a new tab content div. Place it **after** the chat-tab div (after line ~1920, before the auditor-tab div). Follow the same pattern as the auditor tab:

```html
<!-- Two-Brain Router Tab -->
<div id="router-tab" class="tab-content">
    <div class="auditor-header">&#129504; TWO-BRAIN ROUTER</div>

    <!-- State 1: Input Zone -->
    <div id="routerInputZone">
        <div class="auditor-dropzone" id="routerDropzone">
            <div class="dropzone-icon">&#129504;</div>
            <div class="dropzone-title">Drop a document or ask a question</div>
            <div class="dropzone-subtitle">Local AI attempts first. You control what (if anything) goes to the cloud.</div>
            <input type="file" id="routerFileInput" accept=".pdf,.docx,.txt,.md" style="display:none;">
            <button class="auditor-upload-btn" id="routerUploadBtn">Select File</button>
            <div class="dropzone-formats">PDF • DOCX • TXT • MD</div>
        </div>
        <div style="text-align:center;margin:16px 0 8px;opacity:0.5;font-size:0.9em;">— or —</div>
        <div style="max-width:600px;margin:0 auto;">
            <div class="input-area">
                <input type="text" id="routerQueryInput" placeholder="Ask a question about your local documents..." style="flex:1;padding:10px 14px;border:none;background:transparent;color:#fff;font-size:1em;outline:none;">
                <button class="send-btn" id="routerAskBtn">&#10148;</button>
            </div>
        </div>
        <div class="auditor-demo-section" style="margin-top:20px;">
            <div style="opacity:0.6;font-size:0.9em;margin-bottom:8px;">Quick demo:</div>
            <button class="auditor-demo-btn" id="routerDemoBtn">&#128196; Analyze Demo NDA with Router</button>
        </div>
    </div>

    <!-- State 2: Decision Card -->
    <div id="routerDecision" style="display:none;">
        <!-- Status messages stream here -->
        <div id="routerStatusArea" class="processing-log">
            <div class="processing-log-header">&#129504; ROUTER PROCESSING</div>
            <div class="processing-log-content" id="routerStatusLog"></div>
        </div>

        <!-- Decision Card -->
        <div id="routerDecisionCard" style="display:none;">
            <div class="decision-card">
                <div class="decision-card-header">LOCAL DECISION</div>
                <div class="decision-card-row">
                    <span class="decision-card-label">Answered locally:</span>
                    <span id="dcConfidence" class="decision-card-value"></span>
                </div>
                <div class="decision-card-row">
                    <span class="decision-card-label">Local Knowledge sources:</span>
                    <span id="dcSources" class="decision-card-value"></span>
                </div>
                <div class="decision-card-row">
                    <span class="decision-card-label">Escalation benefit:</span>
                    <span id="dcFrontierBenefit" class="decision-card-value"></span>
                </div>
            </div>

            <!-- Analysis result -->
            <div class="router-analysis" id="routerAnalysisText"></div>

            <!-- Escalation Consent (shown only if confidence is MEDIUM/LOW) -->
            <div id="escalationConsent" style="display:none;">
                <div class="escalation-header">&#9888;&#65039; ESCALATION AVAILABLE — Consult Expert (Frontier AI)</div>
                <div class="escalation-subtext">Review exactly what would leave the device:</div>

                <div class="redaction-diff">
                    <div class="diff-col">
                        <div class="diff-col-header">Original (stays on device)</div>
                        <div class="diff-col-body" id="diffOriginal"></div>
                    </div>
                    <div class="diff-col">
                        <div class="diff-col-header">Sanitized payload (would be sent)</div>
                        <div class="diff-col-body diff-redacted" id="diffRedacted"></div>
                    </div>
                </div>

                <div class="escalation-cost">
                    <span>PII redacted: <strong id="escPiiCount">0</strong> items</span>
                    <span>Estimated tokens: <strong id="escTokens">0</strong></span>
                    <span>Estimated cost: <strong id="escCost">$0.0000</strong></span>
                </div>

                <div class="escalation-buttons">
                    <button class="escalation-btn decline" id="btnDeclineEsc">&#128274; Stay Local — Send Nothing</button>
                    <button class="escalation-btn approve" id="btnApproveEsc">&#9729;&#65039; Send Sanitized to Frontier</button>
                </div>
            </div>

            <!-- Stayed Local Celebration (shown on decline) -->
            <div id="stayedLocalBanner" style="display:none;">
                <div class="stayed-local-banner">
                    <div class="stayed-local-icon" id="stayedLocalLockIcon">&#128274;</div>
                    <div class="stayed-local-title">Stayed Local</div>
                    <div class="stayed-local-detail" id="stayedLocalDetail"></div>
                </div>
            </div>

            <!-- Trust Receipt (shown after decision) -->
            <div id="routerTrustReceipt" style="display:none;">
                <div class="trust-receipt">
                    <div class="trust-receipt-header">&#128203; TRUST RECEIPT</div>
                    <div class="trust-receipt-body" id="trustReceiptBody"></div>
                </div>
            </div>

            <!-- Actions after decision -->
            <div id="routerPostActions" style="display:none;">
                <button class="auditor-action-btn" onclick="resetRouter()">&#129504; Analyze Another Document</button>
            </div>
        </div>
    </div>

    <div class="tab-footer">Microsoft Surface + Copilot+ PC — Phi-4 Mini on Intel Core Ultra NPU — All processing happens locally</div>
</div>
```

### C3. CSS for Router Components

Add these styles inside the `<style>` block (after the existing auditor styles, around line ~1500):

```css
/* Decision Card */
.decision-card {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(0,188,242,0.3);
    border-radius: 12px;
    padding: 18px 22px;
    margin: 16px auto;
    max-width: 640px;
}
.decision-card-header {
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    opacity: 0.5;
    margin-bottom: 12px;
    font-weight: 600;
}
.decision-card-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 6px 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    font-size: 0.92em;
}
.decision-card-row:last-child { border-bottom: none; }
.decision-card-label { opacity: 0.7; }
.decision-card-value { font-weight: 600; text-align: right; max-width: 60%; }
.confidence-high { color: #00CC6A; }
.confidence-medium { color: #FFB900; }
.confidence-low { color: #FF4444; }

/* Router analysis text */
.router-analysis {
    background: rgba(255,255,255,0.04);
    border-radius: 10px;
    padding: 16px 20px;
    margin: 16px auto;
    max-width: 640px;
    font-size: 0.92em;
    line-height: 1.6;
    white-space: pre-wrap;
}

/* Escalation Consent */
.escalation-header {
    font-size: 1.05em;
    font-weight: 600;
    color: #FFB900;
    margin: 20px 0 4px;
    text-align: center;
}
.escalation-subtext {
    text-align: center;
    opacity: 0.6;
    font-size: 0.88em;
    margin-bottom: 16px;
}

/* Redaction Diff */
.redaction-diff {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin: 16px auto;
    max-width: 640px;
}
.diff-col {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 10px;
    overflow: hidden;
}
.diff-col-header {
    padding: 8px 12px;
    font-size: 0.78em;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    opacity: 0.5;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    font-weight: 600;
}
.diff-col-body {
    padding: 12px;
    font-size: 0.82em;
    line-height: 1.5;
    max-height: 250px;
    overflow-y: auto;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    white-space: pre-wrap;
}
.diff-redacted { color: rgba(255,255,255,0.9); }

/* Highlight redacted spans */
.pii-redacted {
    background: rgba(255, 68, 68, 0.25);
    color: #FF6B6B;
    padding: 1px 4px;
    border-radius: 3px;
    font-weight: 600;
}

/* Escalation cost bar */
.escalation-cost {
    display: flex;
    justify-content: center;
    gap: 24px;
    margin: 14px 0;
    font-size: 0.85em;
    opacity: 0.8;
}

/* Escalation buttons */
.escalation-buttons {
    display: flex;
    gap: 12px;
    justify-content: center;
    margin: 20px 0;
}
.escalation-btn {
    padding: 12px 24px;
    border-radius: 10px;
    border: 2px solid;
    font-size: 0.95em;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
}
.escalation-btn.decline {
    background: rgba(0, 204, 106, 0.1);
    border-color: rgba(0, 204, 106, 0.4);
    color: #00CC6A;
}
.escalation-btn.decline:hover {
    background: rgba(0, 204, 106, 0.25);
    border-color: #00CC6A;
}
.escalation-btn.approve {
    background: rgba(255, 185, 0, 0.08);
    border-color: rgba(255, 185, 0, 0.3);
    color: #FFB900;
}
.escalation-btn.approve:hover {
    background: rgba(255, 185, 0, 0.2);
    border-color: #FFB900;
}

/* Stayed Local celebration */
.stayed-local-banner {
    text-align: center;
    padding: 24px;
    margin: 20px auto;
    max-width: 500px;
    background: linear-gradient(135deg, rgba(0,204,106,0.1) 0%, rgba(0,204,106,0.03) 100%);
    border: 1px solid rgba(0,204,106,0.3);
    border-radius: 14px;
}
.stayed-local-icon {
    font-size: 2.5em;
    margin-bottom: 8px;
    animation: lockPulse 0.6s ease-out;
}
@keyframes lockPulse {
    0% { transform: scale(0.5); opacity: 0; }
    50% { transform: scale(1.2); }
    100% { transform: scale(1); opacity: 1; }
}
.stayed-local-title {
    font-size: 1.3em;
    font-weight: 700;
    color: #00CC6A;
    margin-bottom: 6px;
}
.stayed-local-detail {
    font-size: 0.9em;
    opacity: 0.8;
}

/* Trust Receipt */
.trust-receipt {
    background: rgba(0,188,242,0.06);
    border: 1px solid rgba(0,188,242,0.2);
    border-radius: 12px;
    padding: 18px 22px;
    margin: 16px auto;
    max-width: 640px;
}
.trust-receipt-header {
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    opacity: 0.5;
    margin-bottom: 10px;
    font-weight: 600;
}
.trust-receipt-body {
    font-size: 0.88em;
    line-height: 1.7;
}
.trust-receipt-line {
    padding: 2px 0;
}
.trust-receipt-line.highlight {
    color: #00CC6A;
    font-weight: 600;
}
```

### C4. JavaScript for Router

Add the JavaScript inside the existing `<script>` block. Follow the same patterns used by the auditor: event listeners for buttons, `fetch()` calls to streaming endpoints, line-by-line JSON parsing with `reader.read()`.

**Key behaviors to implement:**

1. **File upload / drag-drop** — Follow the exact same pattern as the auditor file upload (search for `auditorDropzone` and `auditorFileInput` event handlers around lines 3191+). The router should upload to the same `/upload-to-demo` endpoint, then extract text client-side or server-side.

2. **Demo button** — Loads the same demo NDA doc via `/auditor-demo-doc` (reuse existing endpoint).

3. **Query-only mode** — If the user types a question without uploading a file, POST to `/router/analyze` with just the `query` field. The router will search Local Knowledge and answer from indexed documents.

4. **Streaming response handler** — Follow the exact same SSE parsing pattern used by the auditor analysis (search for `runAuditorAnalysis` function around lines 3300+). Read the stream line by line, parse each JSON object, and handle by `type`:

   - `"status"` → append to the processing log
   - `"knowledge"` → update the "Local Knowledge sources" count in the Decision Card
   - `"decision_card"` → populate and show the Decision Card. Set confidence color class. Show/hide escalation consent based on confidence level.
   - `"escalation_available"` → populate the redaction diff (original vs redacted), PII count, token estimate, cost estimate. Show the escalation consent section. In the redacted preview, wrap `[REDACTED ...]` spans with `<span class="pii-redacted">` for visual highlighting.
   - `"complete"` → update timing

5. **Decline button** (`#btnDeclineEsc`):
   - Hide the escalation consent section
   - Animate in the Stayed Local banner (the CSS `lockPulse` animation handles this automatically on display)
   - Set the detail text: e.g., "2 SSNs and 1 email address never left this device. $0.00 spent."
   - POST to `/router/decide` with `decision: "decline"` and the escalation context
   - Render the Trust Receipt from the response
   - Show post-action buttons
   - Update the savings widget via the existing `refreshSavingsWidget()` function (search for it in the JS)

6. **Approve button** (`#btnApproveEsc`):
   - For the demo, simulate the escalation (show a "Sending to Frontier..." status, pause briefly, then show "Frontier response would appear here")
   - POST to `/router/decide` with `decision: "approve"`
   - Render the Trust Receipt showing data was sent + cost
   - Show post-action buttons

7. **Trust Receipt rendering** — Build HTML from the receipt JSON:
   ```
   Timestamp: {timestamp}
   Decision: {decision}
   Model: {model_used}
   Offline: {offline}
   PII detected: {pii_detected} ({pii_types joined})
   Local Knowledge sources: {sources_consulted joined}
   Confidence: {confidence}
   [If declined]: {counterfactual}
   [Always]: Network calls: 0 • Data transmitted: 0 bytes (or actual if approved)
   ```

8. **Reset function** — `resetRouter()` hides all result states, shows the input zone again.

**Important JS patterns to reuse from the existing codebase:**

- Streaming fetch with line-by-line parsing: search for `getReader()` usage around lines 3300-3500 in the auditor analysis handler
- Tab switching: search for `switchToTab` function around line 2100
- Savings widget refresh: search for `refreshSavingsWidget` around line 2750
- Toast notifications: search for `showTabToast` around line 2170

---

## Part D: Startup and Wiring

### D1. Startup Sequence

In the `if __name__ == '__main__':` block (line ~6031), after the model warmup completes and before `app.run()`:

1. Call `build_knowledge_index()` 
2. Print the indexed document count

```python
# Build Local Knowledge index
build_knowledge_index()
```

Update the startup banner (around line 6053) to include the Router:

```python
print("Features:")
print("  - Two-Brain Router (Local vs. Frontier escalation)")
print("  - My Day (calendar, email, tasks briefing)")
print("  - AI Agent (tool calling, file ops, system commands)")
print("  - Clean Room Auditor (confidential document analysis)")
print("  - ID Verification (Camera + OCR + AI)")
print(f"  - Local Knowledge ({len(KNOWLEDGE_INDEX)} documents indexed)")
```

### D2. Integration Points

The Router should also be accessible from the **Agent Chat** tab. Add a new suggestion chip:

```html
<button class="suggestion-chip" data-action="two-brain">
    <span class="chip-icon">&#129504;</span>
    <span>Two-Brain Analysis</span>
</button>
```

When clicked, switch to the Router tab:
```javascript
} else if (action === "two-brain") {
    switchToTab("router-tab", "routerTabBtn");
}
```

Update the suggestion grid from 5 columns to 6 (`grid-template-columns: repeat(6, 1fr)`) or keep at 5 and replace one of the less-used chips.

---

## Summary of Changes

**New backend components:**
- `KNOWLEDGE_INDEX` dict + `build_knowledge_index()` + `search_knowledge()` + `_extract_best_snippet()`
- `_scan_pii()` + `_redact_text()` (refactored from auditor's inline PII logic)
- `/knowledge/search` POST endpoint
- `/knowledge/refresh` POST endpoint
- `/router/analyze` POST endpoint (streaming)
- `/router/decide` POST endpoint
- `/router/log` GET endpoint
- `ROUTER_LOG` list
- `_check_network()` helper

**New frontend components:**
- Sidebar nav item for "Two-Brain" tab
- Full Router tab HTML (input zone → decision card → consent screen → celebration → trust receipt)
- CSS for decision card, redaction diff, escalation buttons, stayed-local banner, trust receipt
- JavaScript: file upload, demo button, query input, streaming response handler, decline/approve handlers, trust receipt renderer, reset function

**Modified existing components:**
- Startup banner updated to list Router + Local Knowledge
- `build_knowledge_index()` called at startup
- Suggestion chip grid updated with "Two-Brain Analysis" chip
- Tab switching logic updated to include router tab

**No changes to:**
- Existing auditor, chat, My Day, or ID verification functionality
- Model configuration or Foundry Local setup
- Session stats tracking (Router calls will be tracked via existing `_track_model_call`)
- Savings widget (auto-updates from session stats)
