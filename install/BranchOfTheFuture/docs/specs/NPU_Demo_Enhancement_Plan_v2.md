# Surface NPU Demo — Enhancement Plan (v2)

## Overview

The Surface NPU Demo Flask app already demonstrates local AI processing across four pillars: AI Agent (chat + tool calling), My Day (chief of staff briefing), Clean Room Auditor (NDA review + PII detection), and ID Verification (camera + OCR). The savings widget tracks tokens, cost, energy, and CO₂ in real time.

The enhancements below turn the app from a collection of local AI demos into a single, cohesive proof of the *Stop Waiting. Start Building* narrative — specifically the Two-Brain Strategy, the 80/20 Rule, and Tokenomics. The goal is to make the audience *experience* these concepts rather than hear about them.

Three phases, each building on the last. Each phase has a named story arc for internal alignment:

- **Phase 1: "Trust at the Moment of Decision"** — Two-Brain Escalation Engine
- **Phase 2: "Economics at Automation Scale"** — Batch Automation Runner
- **Phase 3: "Privacy in Everyday Work"** — My Day Smart Reply Composer

---

## Phase 1: Two-Brain Escalation Engine

*Story arc: "Trust at the Moment of Decision"*

This is the hero feature. It makes the 80/20 split between local and frontier AI into a live decision moment rather than a slide.

### How It Works

The Router is event-driven, not a toggle. The flow plays out in sequence every time the user asks for help with a document or complex question:

1. **Local attempt.** Phi processes the request entirely on-device — summarizing, classifying, extracting risks, answering questions — using all available local context.

2. **Local Knowledge search (integrated, not separate).** Before surfacing any results, the Router checks a lightweight document index across the Demo folder. If relevant internal documents exist, it pulls excerpts and attempts to answer with citations. Every time Local Knowledge prevents an escalation, the 80/20 ratio proves itself in real time. This is not a standalone tab — it's the mechanism that keeps things local. (Note: the architecture may refer to this as the "Vault" internally; in the UI it is always labeled "Local Knowledge" or "On-Device Sources" to avoid confusion with security storage concepts.)

3. **Decision Card.** The audience sees a single, scannable card — not a multi-step sequence. The card contains three fields:
   - **Answered locally:** ✅ (sufficient) or ⚠️ (partial) with a one-line reason
   - **Local sources used:** N documents (click to expand citations)
   - **Escalation benefit:** one sentence on what frontier reasoning might add (or "None — local answer is complete")

   This keeps the mechanics intact but makes the moment readable in roughly two seconds. Less explanation from the presenter, more "oh, I get it" from the audience.

4. **Escalation offer (only if ⚠️).** If the local model's confidence is partial and Local Knowledge didn't resolve the gap, the Decision Card includes a button: **"Consult Expert (Frontier AI)"**. Nothing happens automatically.

5. **Consent screen with redacted diff.** Clicking the escalation button reveals a side-by-side: original content on the left, sanitized/redacted payload on the right. PII is masked (SSNs, emails, phone numbers, names as applicable). A token count and estimated cloud cost are displayed. Nothing is sent without explicit approval. This is the "Anonymization Gate" — the NPU acts as guardian, proving that even when you use the cloud for the 20%, the NPU ensures sensitive data stays local.

6. **User decides.** Two paths, both valuable:
   - **Decline (the heroic path):** The redacted payload dims/grays out. A lock icon or "Stayed Local" badge animates in. One Trust Receipt highlight surfaces inline (e.g., "2 SSNs never left device"). This makes declining feel like an intentional win, not a passive choice. The UI confirms: "Completed locally. 0 data sent. $0.00 cost."
   - **Accept:** The sanitized payload would route to a frontier model (simulated or live via optional env var). The UI shows the actual token cost and round-trip time, reinforcing the contrast.

7. **Trust Receipt.** Every interaction — whether escalated or not — generates a logged receipt containing:
   - Offline/online status at time of processing
   - Model used
   - PII detected and redacted (count + types)
   - What the sanitized payload would have contained
   - Estimated cost if escalated
   - User's decision (declined/approved)
   - Counterfactual line: "If escalated: ~847 tokens to Azure endpoint, est. $0.008, payload would have contained 2 SSNs and 1 email address"

### Local Knowledge Index (Router Fuel)

The Local Knowledge layer is a lightweight search over the Demo folder that feeds directly into the Router's Decision Card:

- **Indexing:** On app startup (and on-demand refresh), scan all documents in `DEMO_DIR` — TXT, PDF, DOCX — and build a simple keyword/TF-IDF index. No embeddings or vector DB required for the demo.
- **Search:** When the Router processes a query, it runs the query against the index and retrieves the top matching excerpts with source filenames.
- **Citation:** If relevant hits are found, the local model incorporates them into its answer with inline citations ("Per `contract_nda_vertex_pinnacle.txt`, Section 4.2..."). This grounded, cited answer often makes escalation unnecessary.
- **Proactive cross-referencing:** During My Day briefings, the Local Knowledge layer cross-references calendar entries against indexed documents. Example: "Your 9 AM meeting is with Vertex Dynamics. I found 3 related NDAs in your local files; one expires in 12 days." This turns passive search into active chief-of-staff behavior.
- **UI:** A "Local Knowledge" panel shows which documents were consulted, reinforcing the "knows your context / data never leaves" narrative.

### What This Proves to the Audience

- The 80/20 split is real and automatic — most tasks complete locally.
- Privacy isn't a policy claim; it's a visible, auditable decision boundary.
- The cost difference is concrete: $0.00 vs. a specific dollar amount, shown at the moment of decision.
- "Rent the genius. Own the workhorse." becomes experiential.

---

## Phase 2: Batch Automation Runner

*Story arc: "Economics at Automation Scale"*

This feature turns "local AI is free" from a data point into a story. One call at $0.00 is trivia. A thousand calls at $0.00 while a cloud cost ticker climbs is a narrative.

### How It Works

A new panel (accessible from the sidebar or as an Agent suggestion chip) that runs high-volume local AI tasks and streams progress to the savings widget in real time.

1. **Hero Batch, front and center.** One default batch is preselected: "Scan 500 contracts for risk + PII." The Run button is prominent. Other recipes (triage 300 emails, summarize 100 notes, classify 500 documents) live behind a secondary "Change job" action. No choice paralysis — the presenter clicks Run and the demo begins.

2. **Scale slider.** A slider lets the user adjust batch size: 50 / 200 / 500 / 1000. This is the "computer-to-computer: 1000s of calls/day" moment from the PDF made visible.

3. **Live execution with streaming progress.** The batch runs using the existing SSE/streaming pattern (same as device health checks). Each completed item updates:
   - Calls completed / total
   - Tokens processed
   - Cloud cost avoided (running total)
   - Calls per minute throughput
   - Elapsed time

4. **Router integration.** Some batch items trigger "would escalate" classifications while most stay local. As the batch runs, the UI visually demonstrates the 80/20 split: ~80% processed locally and completed, ~20% flagged as potential escalation candidates. The savings widget becomes a live scoreboard for the ratio.

5. **Completion summary.** When the batch finishes:
   - The 80/20 ratio freezes into a persistent badge: e.g., "82% Local / 18% Escalation Candidates." This gives the audience a clean takeaway number.
   - A single projection sentence leads the summary: **"At this volume, cloud cost: ~$X/month. Local: $0."** Detailed per-call math is available in a collapsible section for IT buyers who want it.

6. **Savings widget integration.** The existing sidebar savings widget updates in real time throughout the batch run. Calls, tokens, cost avoided, energy saved, and CO₂ avoided all tick upward visibly. At the end of a 1000-call batch, the widget shows a meaningful cumulative number.

### What This Proves to the Audience

- Token-based API costs compound fast at automation scale. Local costs stay flat.
- The NPU handles sustained, high-throughput workloads — it's not just for one-off questions.
- The 80/20 ratio holds across hundreds of documents, not just one demo NDA.
- "Always-on automation (free)" is a real operational capability, not a bullet point.

---

## Phase 3: My Day Smart Reply Composer

*Story arc: "Privacy in Everyday Work"*

This phase broadens the demo beyond security and compliance into everyday productivity. Email reply drafting is universally relatable and immediately understood by any audience.

### How It Works

An extension of the existing My Day tab's Triage Inbox feature:

1. **Draft Reply button.** After running "Triage Inbox," each email in the results gets a "Draft Reply" button alongside the existing triage classification.

2. **Context-aware drafting.** Clicking the button sends the email subject, body, and sender to Phi locally. The model generates a reply draft that accounts for tone, urgency, and content. The draft streams in real time, same as existing model responses.

3. **Router language, consistently applied.** Each draft shows a small tag: **"Routed locally (no escalation needed)"** — reinforcing that the same Two-Brain system powers everything, not a separate productivity tool. Optionally, a "Why stayed local?" link reveals a one-line explanation.

4. **Privacy echo.** Below the draft, a subtle contextual line: e.g., "This email includes compensation and vendor terms. Processed locally." This echoes the Phase 1 privacy story without adding UI weight or consent complexity.

5. **Edit and copy.** The draft appears in an editable text area. The user can refine it, copy to clipboard, or dismiss. No email is actually sent — this is a composition tool.

6. **Airplane mode proof.** The feature works identically offline. Toggling airplane mode and drafting a reply to a sensitive email is a clean demo moment.

### What This Proves to the Audience

- Local AI isn't just for security edge cases — it handles the most common daily task (email).
- The "chief of staff" metaphor becomes tangible: the AI reads your inbox, triages it, and drafts responses.
- Privacy applies to routine work, not just classified documents.
- The entire app runs on one unified system (the Router), not disconnected features.

---

## Canonical Demo Path

For presenters. This ensures every demo hits the same narrative beats in the same order.

1. **Open a document that _almost_ escalates.** Use a complex NDA or contract. The Decision Card shows ⚠️ partial confidence, but Local Knowledge finds relevant docs and resolves it locally. Decline escalation. Watch the lock icon animate. Read the Trust Receipt highlight.

2. **Run the Hero Batch.** Click Run on the 500-contract scan. Watch the savings widget climb, the 80/20 ratio form in real time, and the completion badge freeze at ~82% Local. Read the one-sentence projection.

3. **Draft a sensitive email offline.** Toggle airplane mode. Open My Day, triage the inbox, click Draft Reply on an email with compensation or vendor terms. Watch Phi compose the reply locally. Read the "Routed locally" tag and privacy echo.

4. **Close with the savings widget.** The cumulative session shows total calls, tokens, cost avoided, and CO₂ savings across all three demo moments.

---

## What We're Not Building (Yet)

These ideas surfaced during analysis and are worth preserving, but they're deferred to keep the build focused:

- **Enterprise Savings Report (downloadable PDF after batch run).** The data exists after Phase 2; rendering it into a polished PDF template is a bounded fast-follow task once the runner is solid.

- **Power-Aware Execution Provider (NPU ↔ GPU ↔ CPU switching).** Only worth building with visible instrumentation showing live latency/energy delta. Without that, it's a claim, not a demo.

- **Clipboard Interceptor (pre-scan for PII before pasting to cloud).** Compelling concept, but Windows clipboard monitoring introduces UAC prompts and permission friction that can derail a live demo. Stretch goal.

- **Tokenomics Calculator (standalone interactive tab).** The Batch Automation Runner accomplishes the same narrative goal more viscerally. Revisit only if the Runner proves insufficient.

- **Vibe Coding Studio / Tool Maker.** The existing Agent chat with `exec` tool calling demonstrates the concept. If revisited, the right shape is: user describes a PowerShell automation → Phi writes it → new custom button appears in the UI.

---

## Architecture Notes

All three phases build on existing infrastructure:

- **Streaming/SSE pattern:** The batch runner and smart reply composer use the same `Response(generate(), mimetype='text/plain')` streaming pattern already used by device health, briefing, and auditor endpoints.

- **Session stats tracking:** `_track_model_call()` and `SESSION_STATS` already capture calls, tokens, and inference time. The batch runner just exercises this at volume. The savings widget already renders in the sidebar.

- **Document extraction:** `extract_text()` already handles PDF, DOCX, and TXT. The Local Knowledge index builds on this.

- **PII detection:** The auditor's PII regex + model-assisted detection pipeline is reused for the Router's redaction/consent screen (the Anonymization Gate).

- **Audit logging:** `AGENT_AUDIT_LOG` already exists. Trust Receipts extend this with structured decision records.

- **Tool framework:** The sandboxed `read/write/exec` tool system with allowlists and path restrictions stays unchanged.

- **Foundry Local + OpenAI client:** All new features use the same `client.chat.completions.create()` pattern pointed at the local endpoint. No new model dependencies.

No new external dependencies are required for any phase. Everything runs on the existing Phi-4 Mini model via Foundry Local on the Intel Core Ultra NPU.

## UI Label Conventions

- Escalation button: **"Consult Expert (Frontier AI)"** — not "Send to Cloud"
- Local Knowledge panel: **"Local Knowledge"** or **"On-Device Sources"** — not "Vault"
- Status indicators and savings widget: **Keep factual and neutral** ("$0.00 saved vs cloud," "Processed locally," "0 network calls"). Avoid marketing-heavy labels like "NPU Dividend" or "Secured by NPU" — the audience is technical enough to find these off-putting.
- Router tags on all features: **"Routed locally (no escalation needed)"** — consistent across Agent, Auditor, My Day, and Batch Runner.
