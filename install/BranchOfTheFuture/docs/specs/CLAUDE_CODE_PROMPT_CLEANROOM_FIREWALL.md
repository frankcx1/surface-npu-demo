# Task: Add Clean Room Auditor Tab + Agentic Firewall Enhancement

## Context

You are modifying `npu_demo_flask.py` (~2,676 lines, single-file Flask app) that runs an executive AI demo on a Copilot+ PC. The app talks to Foundry Local (`localhost:5272`) running Phi Silica (3.8B) on the Intel NPU. Everything runs on-device, zero cloud.

**Current tabs:** My Day | AI Agent | ID Verification

**After this task:** My Day | AI Agent | 🔒 Auditor | ID Verification

Read `TECHNICAL_GUIDE.md` for full architecture details. This prompt tells you exactly what to build.

---

## CRITICAL CONSTRAINTS

1. **ZERO DEPRECATION.** Every existing tab, endpoint, button, feature, and demo flow must continue working identically after all changes. Do not remove, rename, or alter any existing functionality. If you need to refactor shared code, extract it — do not modify the original call sites.

2. **Single file.** Everything stays in `npu_demo_flask.py`. Same launch command: `python npu_demo_flask.py`

3. **Same Foundry Local connection.** `localhost:5272`, `phi-silica` model, OpenAI SDK.

4. **Stateless AI calls.** Phi Silica performs best with stateless single-turn prompts. Never send conversation history for the Auditor analysis calls. Each chunk analysis is independent.

5. **This is a LIVE DEMO for CEOs.** Reliability > features. If anything feels fragile, add a fallback. Graceful degradation everywhere.

6. **Phi Silica context window is ~4K tokens.** Each prompt (system + user content + expected output) must fit within ~1,900 input tokens. Design prompts accordingly.

7. **Test everything** after implementation. Run the full Agent demo flow (Meeting Agenda → List Documents → Analyze Strategy → Review & Summarize with approval → Audit Log), then Brief Me, then the new Auditor tab, then ID Verify. All must work.

---

## FEATURE 1: Clean Room Auditor Tab

### What It Is

A new tab for analyzing confidential documents (contracts, NDAs, compliance docs) entirely on-device. Unlike the Documents sidebar in the Agent tab (which does general summarization), the Auditor performs **risk-first analysis**: it tells you what's wrong, what's unusual, and what you'd miss if you skimmed it.

The name "Clean Room" references M&A and compliance terminology — executives already know this means "this is where you bring the stuff you can't let anyone else see."

### Tab Button

Add a new tab button between AI Agent and ID Verification:

```
🔒 Auditor
```

Tab transition toast (same pattern as existing toasts):
"Same local AI — now in clean room mode"

### Tab Layout

The Auditor tab has a single-column layout (no sidebar). Three states:

---

#### STATE 1: Upload Zone (initial state)

A prominent secure-feeling upload area. Visually distinct from the Documents sidebar — this should feel like a secure intake facility, not a file picker.

```
┌─────────────────────────────────────────────────────────┐
│  🔒  CLEAN ROOM AUDITOR                                │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │                                                   │   │
│  │        🛡️  Drop a confidential document          │   │
│  │                                                   │   │
│  │    Analysis runs entirely on this device.         │   │
│  │    No data egress. No cloud calls.                │   │
│  │                                                   │   │
│  │         [ Select File ]                           │   │
│  │                                                   │   │
│  │    PDF • DOCX • TXT • MD — Max 16MB              │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  Pre-staged:  contract_nda_vertex_pinnacle.txt          │
│               [ Load Demo Document ]                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Upload zone styling:**
- Background: `rgba(255,255,255,0.03)` with border `2px dashed rgba(0,188,242,0.3)`
- Border-radius: `15px`, padding: `40px`
- Shield icon prominent, centered
- "No data egress" text in the same green accent as the offline badge (`#00CC6A`)

**"Load Demo Document" button:**
- Loads the pre-staged `contract_nda_vertex_pinnacle.txt` from `DEMO_DIR` without requiring file upload
- Styled subtly — secondary button, not primary
- This is the "safe path" for the live demo so you never need to fumble with a file picker

**File upload:**
- Reuse the existing upload logic pattern from the Documents sidebar
- Accept: `.pdf`, `.docx`, `.txt`, `.md`
- Same `secure_filename()` + 16MB limit
- Extract text server-side (reuse existing `extract_text()` function)
- On success, transition to State 2

---

#### STATE 2: Document Staged (ready to analyze)

Show the document details and analysis options. Don't auto-analyze — let the operator click.

```
┌─────────────────────────────────────────────────────────┐
│  🔒  CLEAN ROOM AUDITOR                                │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  📄 contract_nda_vertex_pinnacle.txt             │   │
│  │     3 pages  •  1,847 words  •  Loaded locally   │   │
│  │                                                   │   │
│  │  Preview:                                         │   │
│  │  ┌─────────────────────────────────────────────┐ │   │
│  │  │ MUTUAL NON-DISCLOSURE AGREEMENT              │ │   │
│  │  │ Between: Vertex Dynamics, Inc...             │ │   │
│  │  │ And: Pinnacle Solutions Group...             │ │   │
│  │  └─────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐   │
│  │ ⚠️ Risk Scan │ │ 📋 Extract   │ │ 🔐 PII       │   │
│  │              │ │ Obligations  │ │ Detection    │   │
│  └──────────────┘ └──────────────┘ └──────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │              🔍 Full Audit                        │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  [ ← Load Different Document ]                          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Document card styling:**
- Background: `rgba(255,255,255,0.08)`, border-radius: `12px`, padding: `20px`
- File icon, name, word count (compute from extracted text: `len(text.split())`)
- Page count: estimate as `max(1, word_count // 500)`
- Text preview: first 200 characters in a monospace box with slight opacity reduction

**Analysis buttons:**
- Three individual buttons + one "Full Audit" button that runs all three
- Individual buttons: same styling as the Agent tab sidebar buttons
- "Full Audit" button: wider, uses the primary blue gradient (`linear-gradient(90deg, #0078D4, #00BCF2)`)
- For the demo, you'll almost always click "Full Audit" — but having individual buttons shows these are distinct capabilities

**"Load Different Document" link:**
- Resets back to State 1
- Styled as a subtle text link, not a prominent button

**Button actions:**
- "⚠️ Risk Scan" → calls `POST /auditor-analyze` with `mode=risk`
- "📋 Extract Obligations" → calls `POST /auditor-analyze` with `mode=obligations`
- "🔐 PII Detection" → calls `POST /auditor-analyze` with `mode=pii`
- "🔍 Full Audit" → calls `POST /auditor-analyze` with `mode=full`
- All buttons disabled while any analysis is running
- All transition to State 3

---

#### STATE 3: Analysis Results (progressive display)

Results appear progressively as each analysis phase completes. This is a streaming display — results fill in from top to bottom as the backend processes each chunk.

```
┌─────────────────────────────────────────────────────────┐
│  🔒  CLEAN ROOM AUDITOR                                │
│                                                         │
│  📄 contract_nda_vertex_pinnacle.txt                    │
│  ─────────────────────────────────────────────────────  │
│                                                         │
│  PROCESSING                                             │
│  ✅ Document ingested (3 pages, 1,847 words)            │
│  ✅ PII scan complete — 3 instances found               │
│  ✅ Clause analysis: Section 1-3 (NPU)                  │
│  🔄 Clause analysis: Section 4-6 (NPU)...              │
│  ⏳ Clause analysis: Section 7-9                        │
│  ⏳ Executive summary                                   │
│  ─────────────────────────────────────────────────────  │
│                                                         │
│  🔐 PII DETECTED                                       │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 🔴 SSN: XXX-XX-3847 — Page 3, Signature block  │   │
│  │ 🟡 Email: j.morrison@vertexdyn.com — Page 1     │   │
│  │ 🟡 Phone: (415) 555-0142 — Page 3               │   │
│  │                                                   │   │
│  │ ⚡ Recommendation: Redact before external sharing │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ⚠️ RISK ASSESSMENT                                    │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 🔴 HIGH — Unlimited indemnification (Sec 4.2)   │   │
│  │    "Covers all consequential, incidental, and    │   │
│  │     indirect damages with no cap. Non-standard   │   │
│  │     for mutual NDA. Recommend capping at         │   │
│  │     contract value or 2x fees."                  │   │
│  │                                                   │   │
│  │ 🟡 MEDIUM — Broad IP assignment (Sec 7.1)       │   │
│  │    "Work product clause extends to pre-existing  │   │
│  │     IP created prior to agreement date. Could    │   │
│  │     capture unrelated inventions."               │   │
│  │                                                   │   │
│  │ 🟡 MEDIUM — Aggressive non-compete (Sec 9)      │   │
│  │    "24-month global restriction. May be          │   │
│  │     unenforceable in CA, NY. Narrow scope or     │   │
│  │     reduce to 12 months."                        │   │
│  │                                                   │   │
│  │ 🟢 LOW — Standard confidentiality (Sec 1-3)     │   │
│  │    "Boilerplate mutual NDA terms. No unusual     │   │
│  │     provisions noted."                           │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  📋 KEY OBLIGATIONS                                     │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Obligation          │ Deadline       │ Penalty  │   │
│  │  ──────────────────  │ ─────────────  │ ──────── │   │
│  │  Confidentiality     │ 5 yrs from     │ Breach   │   │
│  │  period              │ termination    │ damages  │   │
│  │  Return materials    │ 30 days after  │ Must     │   │
│  │                      │ termination    │ certify  │   │
│  │  Non-compete         │ 24 months      │ Injunc-  │   │
│  │                      │ global         │ tive     │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  📝 EXECUTIVE SUMMARY                                   │
│  ┌─────────────────────────────────────────────────┐   │
│  │ This is a mutual NDA between Vertex Dynamics     │   │
│  │ and Pinnacle Solutions dated Jan 15, 2026.       │   │
│  │ While standard in structure, it contains an      │   │
│  │ unlimited indemnification clause (Sec 4.2) that  │   │
│  │ significantly favors the disclosing party, and   │   │
│  │ an IP assignment clause (Sec 7.1) that may       │   │
│  │ capture pre-existing work product. The 24-month  │   │
│  │ global non-compete is likely unenforceable in    │   │
│  │ several jurisdictions. Recommend legal review    │   │
│  │ of Sections 4.2, 7.1, and 9 before execution.   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  🔒 AUDIT STAMP                                        │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Clean Room Audit Complete                         │   │
│  │ Analyzed: contract_nda_vertex_pinnacle.txt        │   │
│  │ Time: 47 seconds total                            │   │
│  │ PII scan: regex (local) — 0.2s                    │   │
│  │ Clause analysis: Phi Silica (NPU) — 38s (3 pass) │   │
│  │ Summary: Phi Silica (NPU) — 9s                    │   │
│  │ Network calls: 0 • Data transmitted: 0 bytes      │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  [ 🔍 Run Another Audit ]  [ 📄 Load Different Doc ]   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Result card styling:**

Each section is a separate card with:
- Background: `rgba(255,255,255,0.06)`, border-radius: `12px`, padding: `20px`
- Section header bold with emoji prefix
- Spacing between cards: `15px` margin

**Risk severity colors:**
- 🔴 HIGH: Left border `4px solid #D41C00`, background tint `rgba(212,28,0,0.06)`
- 🟡 MEDIUM: Left border `4px solid #FFB900`, background tint `rgba(255,185,0,0.06)`
- 🟢 LOW: Left border `4px solid #107C10`, background tint `rgba(16,124,16,0.06)`

**PII card styling:**
- Background: `rgba(255,185,0,0.08)` with border `1px solid rgba(255,185,0,0.3)`
- Each PII finding on its own line with severity dot
- SSNs partially masked: show only last 4 digits
- Recommendation line at bottom in slightly dimmer text

**Audit stamp styling:**
- Background: `rgba(16,124,16,0.08)` with border `1px solid rgba(16,124,16,0.3)`
- Same visual language as the Agent tab's trust receipt
- Each line shows what ran, where, and how long

**Bottom buttons:**
- "Run Another Audit": Re-runs the same analysis on the same document (reset to State 2)
- "Load Different Doc": Returns to State 1 upload zone

---

### Backend: New Endpoint

#### `POST /auditor-analyze`

Streaming JSONL response (same pattern as `/brief-me`).

**Request body:**
```json
{
  "text": "full document text",
  "filename": "contract_nda_vertex_pinnacle.txt",
  "mode": "full"  // or "risk", "obligations", "pii"
}
```

**Response:** Stream of JSONL events:

```jsonl
{"type": "progress", "step": "ingest", "status": "complete", "detail": "3 pages, 1847 words"}
{"type": "progress", "step": "pii", "status": "complete", "detail": "3 instances found"}
{"type": "pii", "findings": [{"severity": "high", "type": "SSN", "value": "XXX-XX-3847", "location": "Page 3, Signature block"}, ...]}
{"type": "progress", "step": "clause_1", "status": "complete", "detail": "Sections 1-3 analyzed"}
{"type": "progress", "step": "clause_2", "status": "running", "detail": "Sections 4-6 analyzing..."}
{"type": "risk", "findings": [{"severity": "high", "section": "4.2", "type": "Indemnification", "finding": "...", "recommendation": "..."}]}
{"type": "progress", "step": "clause_2", "status": "complete", "detail": "Sections 4-6 analyzed"}
{"type": "risk", "findings": [{"severity": "medium", "section": "7.1", "type": "IP Assignment", "finding": "...", "recommendation": "..."}]}
{"type": "progress", "step": "clause_3", "status": "complete", "detail": "Sections 7-9 analyzed"}
{"type": "risk", "findings": [{"severity": "medium", "section": "9", "type": "Non-Compete", "finding": "...", "recommendation": "..."}, {"severity": "low", "section": "1-3", "type": "Confidentiality", "finding": "...", "recommendation": "..."}]}
{"type": "obligations", "findings": [{"obligation": "Confidentiality period", "deadline": "5 years from termination", "consequence": "Breach damages"}, ...]}
{"type": "progress", "step": "summary", "status": "running", "detail": "Generating executive summary..."}
{"type": "summary", "text": "This is a mutual NDA between..."}
{"type": "progress", "step": "summary", "status": "complete", "detail": "Executive summary complete"}
{"type": "audit", "total_time": 47.2, "pii_time": 0.2, "clause_time": 38.1, "clause_passes": 3, "summary_time": 8.9, "network_calls": 0}
{"type": "done"}
```

### Backend: Analysis Pipeline

The pipeline has three phases. Each runs independently. For `mode=full`, run all three in sequence. For individual modes, run only the requested phase.

#### Phase 1: PII Detection (regex, no AI)

Run immediately. No model call needed. This is instant and 100% reliable.

```python
import re

def scan_pii(text):
    """Scan document text for PII using regex. Returns list of findings."""
    findings = []
    
    # SSN patterns
    for match in re.finditer(r'\b(\d{3})-(\d{2})-(\d{4})\b', text):
        findings.append({
            "severity": "high",
            "type": "SSN",
            "value": f"XXX-XX-{match.group(3)}",  # mask first 5 digits
            "location": _estimate_location(text, match.start()),
            "raw_match": match.group(0)
        })
    
    # Credit card patterns (basic)
    for match in re.finditer(r'\b(?:\d{4}[-\s]?){3}\d{4}\b', text):
        findings.append({
            "severity": "high",
            "type": "Credit Card",
            "value": f"XXXX-XXXX-XXXX-{match.group(0)[-4:]}",
            "location": _estimate_location(text, match.start())
        })
    
    # Email addresses
    for match in re.finditer(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text):
        findings.append({
            "severity": "medium",
            "type": "Email",
            "value": match.group(0),
            "location": _estimate_location(text, match.start())
        })
    
    # Phone numbers
    for match in re.finditer(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text):
        findings.append({
            "severity": "medium",
            "type": "Phone",
            "value": match.group(0),
            "location": _estimate_location(text, match.start())
        })
    
    return findings

def _estimate_location(text, char_pos):
    """Estimate page and context from character position."""
    # Rough estimate: 500 words per page, ~6 chars per word
    chars_per_page = 3000
    page = (char_pos // chars_per_page) + 1
    
    # Get surrounding context for section identification
    start = max(0, char_pos - 100)
    end = min(len(text), char_pos + 100)
    context = text[start:end]
    
    # Try to find section headers nearby
    section_match = re.search(r'(?:Section|SECTION|Article|ARTICLE)\s+(\d+(?:\.\d+)?)', context)
    if section_match:
        return f"Page {page}, Section {section_match.group(1)}"
    
    # Check for signature block indicators
    if any(word in context.lower() for word in ['signature', 'signed', 'witness', 'notary', 'authorized']):
        return f"Page {page}, Signature block"
    
    return f"Page {page}"
```

#### Phase 2: Clause Analysis (chunked AI calls)

Split the document into chunks and send each to Phi Silica with a focused classification prompt. **Each call is stateless** — no conversation history.

**Chunking strategy:**
```python
def chunk_document(text, max_chunk_words=600):
    """Split document into chunks at section boundaries."""
    # Try to split on section headers first
    sections = re.split(r'(?=(?:Section|SECTION|Article|ARTICLE)\s+\d)', text)
    
    chunks = []
    current_chunk = ""
    
    for section in sections:
        if len((current_chunk + section).split()) > max_chunk_words and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = section
        else:
            current_chunk += "\n" + section
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    # If no section headers found, fall back to word-count splitting
    if len(chunks) <= 1 and len(text.split()) > max_chunk_words:
        words = text.split()
        chunks = []
        for i in range(0, len(words), max_chunk_words):
            chunks.append(" ".join(words[i:i + max_chunk_words]))
    
    return chunks
```

**Clause analysis prompt (for each chunk):**

```python
CLAUSE_ANALYSIS_SYSTEM = """You are a contract analyst. Analyze this clause and respond in EXACTLY this format, one finding per block. If the clause is standard/unremarkable, say so. Be specific about what makes a clause non-standard.

RISK_LEVEL: [HIGH/MEDIUM/LOW]
CLAUSE_TYPE: [indemnification/IP/confidentiality/termination/liability/non-compete/non-solicitation/governing-law/other]
SECTION: [section number if identifiable, or "N/A"]
FINDING: [One sentence: what is notable or unusual about this clause]
RECOMMENDATION: [One sentence: what action to take]

If multiple clauses are present, output multiple blocks separated by a blank line."""

CLAUSE_ANALYSIS_USER = """Analyze these contract clauses for risk:

{chunk_text}"""
```

**Important:** Keep the system prompt under 200 tokens. Keep each chunk under 600 words (~800 tokens). Total input per call: ~1,000 tokens. Output budget: 400 tokens. This fits within Phi Silica's ~4K window with headroom.

**Model call for each chunk:**
```python
response = client.chat.completions.create(
    model=DEFAULT_MODEL,
    messages=[
        {"role": "system", "content": CLAUSE_ANALYSIS_SYSTEM},
        {"role": "user", "content": CLAUSE_ANALYSIS_USER.format(chunk_text=chunk)}
    ],
    max_tokens=400,
    temperature=0.3  # Low temperature for consistent structured output
)
```

**Parse the response** into structured findings:
```python
def parse_clause_findings(response_text):
    """Parse structured clause analysis output into findings list."""
    findings = []
    blocks = re.split(r'\n\s*\n', response_text.strip())
    
    for block in blocks:
        finding = {}
        for line in block.strip().split('\n'):
            line = line.strip()
            if line.startswith('RISK_LEVEL:'):
                level = line.split(':', 1)[1].strip().upper()
                if level in ('HIGH', 'MEDIUM', 'LOW'):
                    finding['severity'] = level.lower()
            elif line.startswith('CLAUSE_TYPE:'):
                finding['type'] = line.split(':', 1)[1].strip()
            elif line.startswith('SECTION:'):
                finding['section'] = line.split(':', 1)[1].strip()
            elif line.startswith('FINDING:'):
                finding['finding'] = line.split(':', 1)[1].strip()
            elif line.startswith('RECOMMENDATION:'):
                finding['recommendation'] = line.split(':', 1)[1].strip()
        
        if finding.get('severity') and finding.get('finding'):
            findings.append(finding)
    
    return findings
```

**Fallback:** If the model doesn't produce the structured format (it's a 3.8B model), try to extract any useful information from the raw text. If extraction fails entirely, return a single "MEDIUM" finding with the raw response as the finding text. The demo must never show an error state — always show something useful.

#### Phase 3: Executive Summary (aggregation AI call)

After all clause analyses complete, send one final prompt with the aggregated findings:

```python
SUMMARY_SYSTEM = """You are a contract analyst writing an executive summary. Be concise — 3 to 5 sentences maximum. State: what type of document this is, who the parties are, the most significant risk, and your top recommendation. Do not repeat individual findings. Write for a CEO who has 30 seconds."""

SUMMARY_USER = """Write an executive summary based on these contract analysis findings:

Document: {filename}
Word count: {word_count}

Risk findings:
{formatted_risk_findings}

PII detected: {pii_count} instances

Obligations extracted:
{formatted_obligations}"""
```

**Max tokens for summary:** 300. Temperature: 0.3.

#### Phase 2b: Obligations Extraction (optional separate AI call)

If mode is `full` or `obligations`, add one more AI call to extract structured obligations:

```python
OBLIGATIONS_SYSTEM = """You are a contract analyst. Extract all obligations, deadlines, and penalties from this text. Respond in EXACTLY this format, one per block:

OBLIGATION: [what must be done]
DEADLINE: [when, or "ongoing"]
CONSEQUENCE: [what happens if missed]

Output one block per obligation. Be specific about dates and terms."""
```

This call can be made on the full document text if it's short enough (<600 words), or on the concatenated "non-LOW" sections from the clause analysis. Keep input under 800 tokens.

**Parse into structured table data.** Same fallback strategy — if parsing fails, show raw text.

---

### Backend: Pre-staged Demo Document Endpoint

#### `GET /auditor-demo-doc`

Returns the pre-staged NDA document text. The frontend calls this when "Load Demo Document" is clicked.

```python
@app.route('/auditor-demo-doc')
def auditor_demo_doc():
    demo_file = os.path.join(DEMO_DIR, 'contract_nda_vertex_pinnacle.txt')
    if os.path.exists(demo_file):
        with open(demo_file, 'r', encoding='utf-8') as f:
            text = f.read()
        return jsonify({
            "filename": "contract_nda_vertex_pinnacle.txt",
            "text": text,
            "word_count": len(text.split())
        })
    return jsonify({"error": "Demo document not found"}), 404
```

---

### Frontend: JavaScript

The Auditor tab needs its own JavaScript section. Key functions:

**`loadAuditorDemo()`** — Fetches demo doc from `/auditor-demo-doc`, transitions to State 2.

**`startAudit(mode)`** — Called by the four analysis buttons. Posts to `/auditor-analyze` and processes the streaming JSONL response. Updates the progress indicator and result cards as events arrive.

**`renderPiiCard(findings)`** — Renders the PII detection results card.

**`renderRiskCard(findings)`** — Renders risk assessment findings with color-coded severity.

**`renderObligationsCard(findings)`** — Renders the obligations table.

**`renderSummaryCard(text)`** — Renders the executive summary.

**`renderAuditStamp(audit_data)`** — Renders the final audit stamp card.

**`resetAuditor()`** — Returns to State 1.

**JSONL processing:** Use the same `EventSource` / `fetch` + `ReadableStream` pattern already used for `/brief-me`. Process each line as it arrives, update the progressive display.

---

### Pre-staged Demo Document

Create this file at `DEMO_DIR/contract_nda_vertex_pinnacle.txt` on app startup (same pattern as other demo files — only create if it doesn't already exist):

```python
AUDITOR_DEMO_NDA = """MUTUAL NON-DISCLOSURE AGREEMENT

Effective Date: January 15, 2026
Agreement Number: NDA-2026-VD-PS-0847

BETWEEN:

Vertex Dynamics, Inc.
1200 Innovation Drive, Suite 400
San Jose, CA 95134
Contact: James Morrison, VP Corporate Development
Email: j.morrison@vertexdyn.com
Phone: (415) 555-0142

AND:

Pinnacle Solutions Group, LLC
8900 Enterprise Boulevard
Austin, TX 78759
Contact: Sarah Chen, General Counsel

RECITALS

WHEREAS, the parties wish to explore a potential business relationship involving the evaluation of technology licensing and joint development opportunities (the "Purpose"); and

WHEREAS, in connection with the Purpose, each party may disclose to the other certain confidential and proprietary information;

NOW, THEREFORE, in consideration of the mutual covenants contained herein, the parties agree as follows:

SECTION 1. DEFINITION OF CONFIDENTIAL INFORMATION

1.1 "Confidential Information" means any and all non-public, proprietary, or confidential information disclosed by either party to the other, whether orally, in writing, electronically, or by inspection of tangible objects. This includes, without limitation: trade secrets, patents, inventions, technical data, designs, algorithms, software source code, business plans, financial information, customer lists, marketing strategies, and employee information.

1.2 Confidential Information shall not include information that: (a) is or becomes publicly available through no fault of the receiving party; (b) was known to the receiving party prior to disclosure; (c) is independently developed by the receiving party without use of the disclosing party's Confidential Information; or (d) is lawfully obtained from a third party without restriction.

SECTION 2. OBLIGATIONS OF RECEIVING PARTY

2.1 The receiving party shall hold all Confidential Information in strict confidence and shall not disclose such information to any third party without the prior written consent of the disclosing party.

2.2 The receiving party shall use the Confidential Information solely for the Purpose and shall not use it for any other purpose, including for its own benefit or the benefit of any third party.

2.3 The receiving party shall limit access to Confidential Information to those employees, agents, and advisors who have a need to know and who are bound by obligations of confidentiality at least as protective as those contained herein.

SECTION 3. TERM AND DURATION

3.1 This Agreement shall remain in effect for a period of two (2) years from the Effective Date, unless earlier terminated by either party upon thirty (30) days' written notice.

3.2 The obligations of confidentiality set forth in Section 2 shall survive termination of this Agreement for a period of five (5) years from the date of termination.

SECTION 4. INDEMNIFICATION AND LIABILITY

4.1 Each party shall indemnify and hold harmless the other party from and against any claims arising from a breach of this Agreement, subject to the limitations set forth herein.

4.2 NOTWITHSTANDING ANY OTHER PROVISION OF THIS AGREEMENT, THE DISCLOSING PARTY SHALL BE ENTITLED TO FULL INDEMNIFICATION FOR ALL DAMAGES, INCLUDING BUT NOT LIMITED TO CONSEQUENTIAL, INCIDENTAL, INDIRECT, SPECIAL, AND PUNITIVE DAMAGES, ARISING FROM ANY BREACH OR THREATENED BREACH OF THIS AGREEMENT BY THE RECEIVING PARTY. THE RECEIVING PARTY ACKNOWLEDGES THAT SUCH DAMAGES MAY BE DIFFICULT TO CALCULATE AND AGREES THAT THIS PROVISION SHALL NOT BE SUBJECT TO ANY CAP OR LIMITATION. THE RECEIVING PARTY WAIVES ANY DEFENSE BASED ON THE FORSEEABILITY OF SUCH DAMAGES.

SECTION 5. RETURN OF MATERIALS

5.1 Upon termination of this Agreement or upon request by the disclosing party, the receiving party shall promptly return or destroy all Confidential Information and any copies thereof within thirty (30) days.

5.2 The receiving party shall provide written certification of destruction within ten (10) business days of completing such destruction.

SECTION 6. REMEDIES

6.1 The parties acknowledge that a breach of this Agreement may cause irreparable harm for which monetary damages would be insufficient. Accordingly, the non-breaching party shall be entitled to seek injunctive relief in addition to any other remedies available at law or in equity.

SECTION 7. INTELLECTUAL PROPERTY

7.1 ALL WORK PRODUCT, INVENTIONS, DISCOVERIES, IMPROVEMENTS, AND INNOVATIONS, WHETHER OR NOT PATENTABLE, CONCEIVED, DEVELOPED, OR REDUCED TO PRACTICE BY EITHER PARTY DURING THE TERM OF THIS AGREEMENT, INCLUDING ANY WORK PRODUCT CREATED PRIOR TO THE EFFECTIVE DATE THAT IS USED IN CONNECTION WITH THE PURPOSE, SHALL BE DEEMED THE SOLE AND EXCLUSIVE PROPERTY OF THE DISCLOSING PARTY. The receiving party hereby assigns and agrees to assign all right, title, and interest in such work product to the disclosing party.

7.2 The receiving party shall execute all documents and take all actions reasonably necessary to perfect the disclosing party's rights under this Section.

SECTION 8. NON-SOLICITATION

8.1 During the term of this Agreement and for a period of twelve (12) months following termination, neither party shall directly or indirectly solicit, recruit, or hire any employee of the other party with whom it has had contact in connection with the Purpose.

SECTION 9. NON-COMPETITION

9.1 During the term of this Agreement and for a period of twenty-four (24) months following termination, the receiving party shall not, directly or indirectly, engage in, own, manage, operate, finance, or participate in any business that competes with the disclosing party's business anywhere in the world.

9.2 The receiving party acknowledges that this restriction is reasonable in scope, duration, and geographic area given the nature of the Confidential Information disclosed hereunder.

SECTION 10. GOVERNING LAW AND JURISDICTION

10.1 This Agreement shall be governed by and construed in accordance with the laws of the State of Delaware, without regard to its conflict of laws principles.

10.2 Any disputes arising under this Agreement shall be resolved exclusively in the state or federal courts located in Delaware.

SECTION 11. MISCELLANEOUS

11.1 This Agreement constitutes the entire agreement between the parties with respect to the subject matter hereof and supersedes all prior negotiations, representations, and agreements.

11.2 This Agreement may not be amended except by a written instrument signed by both parties.

11.3 If any provision of this Agreement is found to be unenforceable, the remaining provisions shall remain in full force and effect.

IN WITNESS WHEREOF, the parties have executed this Agreement as of the Effective Date.

VERTEX DYNAMICS, INC.

By: _________________________
Name: James A. Morrison
Title: VP Corporate Development
SSN (for notarization): 478-93-3847
Date: January 15, 2026

PINNACLE SOLUTIONS GROUP, LLC

By: _________________________
Name: Sarah L. Chen
Title: General Counsel
Date: January 15, 2026
"""
```

**Why this document works for the demo:**

The NDA is designed with deliberate issues the Auditor should catch:

| Section | Issue | Expected Severity | Why It's A Problem |
|---------|-------|-------------------|--------------------|
| 4.2 | Unlimited indemnification, waived damages cap, consequential damages | 🔴 HIGH | One-sided, non-standard for mutual NDA, unlimited financial exposure |
| 7.1 | IP assignment includes pre-existing work product | 🟡 MEDIUM | Could capture unrelated inventions created before the agreement |
| 9 | 24-month global non-compete | 🟡 MEDIUM | Likely unenforceable in CA (where Vertex is based), overly broad |
| 1-3 | Standard boilerplate | 🟢 LOW | Normal mutual NDA language |
| Sig block | SSN embedded (478-93-3847) | 🔴 PII | Should never be in a contract document |
| Header | Email, phone number | 🟡 PII | Contact info that could be redacted |

Create this file in the `create_demo_files()` function (or equivalent startup logic). Check if it exists before creating:

```python
nda_path = os.path.join(DEMO_DIR, 'contract_nda_vertex_pinnacle.txt')
if not os.path.exists(nda_path):
    with open(nda_path, 'w', encoding='utf-8') as f:
        f.write(AUDITOR_DEMO_NDA)
```

---

## FEATURE 2: Agentic Firewall Enhancement

### What It Is

An enhancement to the **existing AI Agent tab** that adds plain-English security explanations to tool calls and the approval gate. This makes the Agent feel like it has a "Chief of Security" reviewing its actions before execution.

Two levels:

1. **Inline tool explanations** (every tool call) — deterministic, instant, template-based
2. **Security assessment in approval card** (Review & Summarize) — deterministic, computed from the plan text

### DO NOT BREAK: Existing Agent Behavior

Everything in the Agent tab must continue to work as-is. The firewall is purely additive:
- Same tool execution flow
- Same approval gate flow
- Same audit trail
- Same sidebar buttons
- Same chat interface

---

### Level 1: Inline Tool Explanations

When the agent executes a tool call, add a **security explanation line** to the tool execution log (the visual step-by-step display). This appears BEFORE the "Executing..." step.

**Current flow:**
```
🤔 Thinking... "I'll read the strategy document"
⚡ Executing: read(strategy_2026.txt)
✅ Complete: File read (2,847 chars)
```

**Enhanced flow:**
```
🤔 Thinking... "I'll read the strategy document"
🛡️ Security: Reading file "strategy_2026.txt". Read-only, no modifications. Within approved folder.
⚡ Executing: read(strategy_2026.txt)
✅ Complete: File read (2,847 chars)
```

**The security explanations are DETERMINISTIC — no AI call needed.** Use a template map:

```javascript
function getSecurityExplanation(toolName, args) {
    switch(toolName) {
        case 'read':
            return 'Reading file "' + args.path + '". Read-only, no modifications. Within approved folder.';
        case 'write':
            return 'Creating file "' + args.path + '" in approved demo folder. No existing files modified.';
        case 'exec':
            var cmd = (args.command || '').toLowerCase().trim();
            if (cmd.startsWith('get-childitem')) {
                return 'Listing directory contents. Read-only operation, no files affected.';
            } else if (cmd.startsWith('get-date')) {
                return 'Retrieving system date/time. No system changes.';
            } else if (cmd.startsWith('disable-netadapter')) {
                return 'Disabling network adapter(s). Device will go offline. Re-enable available.';
            } else if (cmd.startsWith('enable-netadapter')) {
                return 'Enabling network adapter(s). Restoring network connectivity.';
            } else if (cmd.startsWith('get-content')) {
                return 'Reading file contents via PowerShell. Read-only operation.';
            } else {
                return 'Running approved PowerShell command within allowlisted cmdlet set.';
            }
        default:
            return 'Executing approved tool within security policy.';
    }
}
```

**Styling for the security line:**
- Icon: 🛡️
- Text color: slightly dimmer than normal tool steps — `rgba(255,255,255,0.7)`
- Font size: same as other tool steps
- Background: none (it's part of the tool execution log flow)
- CSS class: `tool-step security` (new class)

**Implementation:** In the `updateToolLog()` function (or wherever tool steps are rendered), inject the security step between "Thinking" and "Executing". This can be done in the frontend when constructing the steps array — add a security step after every "thinking" step and before every "executing" step.

---

### Level 2: Security Assessment in Approval Card

Enhance the existing approval card (from Review & Summarize) with a security assessment section.

**Current approval card:**
```
┌─────────────────────────────────────────────────────┐
│ 🔒 This action requires approval                    │
│                                                      │
│ I plan to read the following files:                  │
│ - strategy_2026.txt — extract key themes             │
│ - board_compensation.txt — review for risks          │
│ - loan_application_sample.txt — check for PII        │
│                                                      │
│ [ ✅ Approve ]  [ ❌ Deny ]                          │
│                                                      │
│ Read-only within approved folder. All actions logged. │
└─────────────────────────────────────────────────────┘
```

**Enhanced approval card:**
```
┌─────────────────────────────────────────────────────┐
│ 🔒 This action requires approval                    │
│                                                      │
│ I plan to read the following files:                  │
│ - strategy_2026.txt — extract key themes             │
│ - board_compensation.txt — review for risks          │
│ - loan_application_sample.txt — check for PII        │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🛡️ Security Review                              │ │
│ │ • 3 files requested — all within approved folder │ │
│ │ • Read-only access — no files will be modified   │ │
│ │ • No system commands — no PowerShell execution   │ │
│ │ • Results stay on-device — no network calls      │ │
│ └─────────────────────────────────────────────────┘ │
│                                                      │
│ [ ✅ Approve ]  [ ❌ Deny ]                          │
│                                                      │
│ Read-only within approved folder. All actions logged. │
└─────────────────────────────────────────────────────┘
```

**The Security Review section is DETERMINISTIC** — not AI-generated. Compute it from the plan text:

```javascript
function generateSecurityReview(planText) {
    var lines = [];
    
    // Count files mentioned (look for file patterns in the plan)
    var fileMatches = planText.match(/[\w_-]+\.\w{2,4}/g) || [];
    var uniqueFiles = [...new Set(fileMatches)];
    
    if (uniqueFiles.length > 0) {
        lines.push(uniqueFiles.length + ' file' + (uniqueFiles.length > 1 ? 's' : '') + ' requested — all within approved folder');
    }
    
    // Determine access type
    var hasWrite = /\b(write|create|save|modify|edit|update)\b/i.test(planText);
    var hasExec = /\b(run|execute|command|powershell)\b/i.test(planText);
    
    if (hasWrite) {
        lines.push('Read and write access — files may be created or modified');
    } else {
        lines.push('Read-only access — no files will be modified');
    }
    
    if (hasExec) {
        lines.push('System commands requested — limited to approved PowerShell cmdlets');
    } else {
        lines.push('No system commands — no PowerShell execution');
    }
    
    lines.push('Results stay on-device — no network calls');
    
    return lines;
}
```

**Security Review box styling:**
- Background: `rgba(0,188,242,0.06)` with border `1px solid rgba(0,188,242,0.2)`
- Border-radius: `8px`, padding: `12px`
- Header "🛡️ Security Review" in slightly smaller bold text
- Each line prefixed with • (bullet)
- Placed between the plan text and the Approve/Deny buttons

**Implementation:** In the existing frontend code that renders the approval card (where `[PLAN]` markers are detected), add the Security Review box after the plan body and before the buttons. Use `generateSecurityReview()` to compute the content from the plan text.

---

### Audit Trail Enhancement

Add the security explanations to the audit trail entries:

When logging a tool call to the audit trail, include the security explanation:

**Current audit entry format:**
```
✅ [12:34:56] READ — strategy_2026.txt (2,847 chars) — 8.2s
```

**Enhanced audit entry format:**
```
🛡️ [12:34:56] SECURITY CHECK — read(strategy_2026.txt): Read-only, within approved folder
✅ [12:34:56] READ — strategy_2026.txt (2,847 chars) — 8.2s
```

This makes the audit trail show that every action was security-checked before execution, even the simple ones. For the demo, this is powerful — the audit log becomes evidence of governance, not just activity logging.

**Implementation:** In the backend where audit log entries are created (in the chat/tool execution loop), add a security check entry before each tool execution entry. The security explanation text uses the same templates as the frontend (replicate in Python or pass from frontend).

---

## TESTING CHECKLIST

After all changes, verify:

### Existing Functionality (NO REGRESSION)
- [ ] My Day tab: Brief Me produces structured briefing with cross-references
- [ ] My Day tab: Data cards expand/collapse correctly
- [ ] My Day tab: Triage Inbox works
- [ ] My Day tab: Prep for Next Meeting works
- [ ] Agent tab: Meeting Agenda creates file
- [ ] Agent tab: Analyze Strategy reads and summarizes
- [ ] Agent tab: List Documents shows directory
- [ ] Agent tab: Review & Summarize shows approval card
- [ ] Agent tab: Approve → agent reads files and produces summary
- [ ] Agent tab: Deny → "Action denied" message, no files accessed
- [ ] Agent tab: AI Action Log shows trust receipt + AI summary
- [ ] Agent tab: Load File (+) uploads and extracts text
- [ ] Agent tab: Summarize Doc works on loaded file
- [ ] Agent tab: Detect PII works on loaded file
- [ ] Agent tab: Clear Chat resets everything
- [ ] ID Verify tab: Camera capture works
- [ ] ID Verify tab: OCR + AI analysis produces result card
- [ ] Header: Go Offline / Go Online buttons work
- [ ] Header: Connectivity status updates correctly
- [ ] Tab transition toasts appear for all tabs

### New: Clean Room Auditor
- [ ] Tab button appears between AI Agent and ID Verification
- [ ] Tab transition toast: "Same local AI — now in clean room mode"
- [ ] Upload zone accepts PDF, DOCX, TXT, MD
- [ ] "Load Demo Document" loads the pre-staged NDA
- [ ] Document staging card shows filename, word count, preview
- [ ] "Full Audit" button runs all three analysis phases
- [ ] PII detection finds: SSN, email, phone in demo NDA
- [ ] Risk scan flags: Section 4.2 (HIGH), Section 7.1 (MEDIUM), Section 9 (MEDIUM)
- [ ] Obligations extraction finds: confidentiality, return materials, non-compete
- [ ] Executive summary is coherent and mentions key risks
- [ ] Progressive display shows results as they arrive
- [ ] Audit stamp shows correct timing and zero network calls
- [ ] "Run Another Audit" returns to State 2
- [ ] "Load Different Doc" returns to State 1
- [ ] Individual buttons (Risk Scan, Obligations, PII) work independently

### New: Agentic Firewall
- [ ] Inline security explanations appear in tool execution log for all tool types
- [ ] Security explanations are correct for: read, write, exec (each cmdlet variant)
- [ ] Approval card shows "🛡️ Security Review" section
- [ ] Security review correctly counts files and access types
- [ ] Audit trail shows security check entries before tool execution entries
- [ ] None of this breaks the existing approval flow

### Full Demo Flow (End-to-End)
- [ ] Agent: Meeting Agenda → List Documents → Analyze Strategy → Review & Summarize (with approval) → Audit Log
- [ ] Auditor: Load Demo Doc → Full Audit → all results display correctly
- [ ] My Day: Brief Me → complete briefing with cross-references
- [ ] Go Offline → Run Agent command → still works → Go Online
- [ ] ID Verify: Camera → Capture → Analyze (if camera available)

---

## IMPLEMENTATION ORDER

1. **Create the pre-staged NDA file** in the demo files setup logic — 2 min, zero risk
2. **Add the Auditor tab button** and empty tab content — 5 min, zero risk, confirms tab switching works
3. **Build Auditor State 1** (upload zone + Load Demo Doc) — 15 min
4. **Build Auditor State 2** (staging card + analysis buttons) — 15 min
5. **Build PII regex scanner** (backend) — 10 min, no AI dependency
6. **Build clause analysis pipeline** (backend, chunked AI calls) — 30 min, test each call individually
7. **Build obligations extraction** (backend) — 15 min
8. **Build summary aggregation** (backend) — 15 min
9. **Build Auditor State 3** (progressive result display) — 30 min
10. **Build the `/auditor-analyze` streaming endpoint** that ties it all together — 20 min
11. **Add inline security explanations** to Agent tab tool log — 15 min, low risk
12. **Add Security Review section** to approval card — 15 min, low risk
13. **Add security check entries** to audit trail — 10 min, low risk
14. **Full regression test** — run every tab, every button, every flow

**Total estimated effort:** ~3-4 hours

---

## WHAT NOT TO DO

- Do NOT modify any existing endpoint signatures or response formats
- Do NOT change the existing tab order (My Day is still first, ID Verify still last)
- Do NOT add new Python dependencies — use only what's already imported (Flask, OpenAI, re, json, os, etc.)
- Do NOT change the Foundry Local connection or model
- Do NOT add conversation history to Auditor AI calls — keep them stateless
- Do NOT make the Security Review section AI-generated — keep it deterministic and instant
- Do NOT auto-run analysis on file upload — always wait for button click (demo reliability)
- Do NOT remove the existing "Detect PII" button in the Agent tab's Documents sidebar — the Auditor's PII scan is separate and more visual, but the Agent's version should keep working
- Do NOT change the existing approval card markers ([PLAN]/[/PLAN]) — the firewall enhances the card, not replaces it
