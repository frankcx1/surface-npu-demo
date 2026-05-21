# Task: Add "Save Summary" Button + Meeting Transcript File

## Overview

Add a **💾 Save Summary** button to the AI Agent tab's Documents sidebar section in `npu_demo_flask.py`. This button appears after the user clicks "Summarize Doc" and the summary completes. Clicking it tells the agent to write the summary to a file on disk using the existing `write` tool. Also upgrade the Summarize Doc prompt to produce a richer meeting-focused output, and create a demo meeting transcript file.

The demo flow becomes: **Load File → Summarize → Save to Disk** — three button clicks, three distinct AI capabilities (ingest, reason, write).

## Files to Modify

- `npu_demo_flask.py` (single-file Flask app, ~2,676 lines)

## Files to Create

- `C:\Users\frankbu\Documents\Demo\Board_Strategy_Review_Transcript_Jan2026.txt`

---

## Change 1: Add the Save Summary Button (HTML)

In the Documents sidebar section (around line 1046-1048), add a new hidden button **after** the Detect PII button:

```html
<button class="sidebar-btn" id="qpSaveSummary" style="display:none;">&#128190; Save Summary</button>
```

The updated Documents section should be:
```html
<div class="sidebar-section">
  <div class="sidebar-label">Documents</div>
  <input type="file" id="agentFileInput" accept=".pdf,.docx,.txt,.md" style="display:none;">
  <button class="sidebar-btn" id="agentFileBtn">&#128194; Load File...</button>
  <span id="agentFileName" style="display:block;font-size:0.75em;opacity:0.6;padding:0 4px;"></span>
  <button class="sidebar-btn" id="qpSummarizeDoc" style="display:none;">&#128221; Summarize Doc</button>
  <button class="sidebar-btn" id="qpDetectPII" style="display:none;">&#128680; Detect PII</button>
  <button class="sidebar-btn" id="qpSaveSummary" style="display:none;">&#128190; Save Summary</button>
</div>
```

---

## Change 2: Add State Variables (JavaScript)

Near the existing `var lastUploadedFile = "";` declaration (around line 1516), add two new variables:

```javascript
var lastUploadedFile = "";
var lastAssistantResponse = "";
var pendingSummarize = false;
```

---

## Change 3: Capture Response Text in processLine (JavaScript)

Inside the `processLine` function within `sendMessage()`, in the `evt.type === "response"` handler (around line 1761-1789), add one line to capture the response text. Add this right after `var responseText = evt.text || "";` (line 1765):

```javascript
lastAssistantResponse = responseText;
```

Then in the `evt.type === "done"` handler (around line 1794-1797), add logic to show the Save button when a summarize operation completes:

```javascript
else if (evt.type === "done") {
    document.getElementById("sendBtn").disabled = false;
    document.getElementById("userInput").focus();
    // Show Save Summary button after summarize completes
    if (pendingSummarize && lastAssistantResponse) {
        document.getElementById("qpSaveSummary").style.display = "";
        pendingSummarize = false;
    }
}
```

---

## Change 4: Upgrade the Summarize Doc Prompt (JavaScript)

Change the Summarize Doc click handler (around line 1546-1550) to use a richer, meeting-focused prompt:

```javascript
document.getElementById("qpSummarizeDoc").addEventListener("click", function() {
    if (!lastUploadedFile) return;
    pendingSummarize = true;
    document.getElementById("qpSaveSummary").style.display = "none";
    document.getElementById("userInput").value = "Read the file " + lastUploadedFile + " and produce a structured meeting summary with these sections:\n\nMEETING SUMMARY (2-3 sentence overview of what was discussed)\n\nKEY IDEAS & DECISIONS (bullet the most important points and any decisions made)\n\nACTION ITEMS (list each action item with the owner's name and deadline if mentioned)\n\nKeep it concise and executive-ready.";
    sendMessage();
});
```

---

## Change 5: Wire Up the Save Summary Button Handler (JavaScript)

Add a new event listener after the existing Detect PII handler (after line 1555). This constructs a write prompt that includes the summary text as the file content. It derives the output filename from the uploaded file's name:

```javascript
document.getElementById("qpSaveSummary").addEventListener("click", function() {
    if (!lastAssistantResponse || !lastUploadedFile) return;
    // Derive a summary filename from the uploaded file path
    var baseName = lastUploadedFile.replace(/\\/g, "/").split("/").pop().replace(/\.[^.]+$/, "");
    var savePath = lastUploadedFile.replace(/\\/g, "/").split("/").slice(0, -1).join("\\\\") + "\\\\" + baseName + "_Summary.txt";
    // Use the Windows path format matching the rest of the app
    savePath = savePath.replace(/\//g, "\\");
    document.getElementById("userInput").value = "Write the following meeting summary to " + savePath + ":\n\n" + lastAssistantResponse;
    document.getElementById("qpSaveSummary").style.display = "none";
    sendMessage();
});
```

**Note on paths:** The existing app uses hardcoded Windows paths with `C:\Users\frankbu\Documents\Demo\` in the demo buttons. The `lastUploadedFile` variable already stores the full Windows path returned from `/upload-to-demo` (e.g., `C:\Users\frankbu\Documents\Demo\Board_Strategy_Review_Transcript_Jan2026.txt`). The save handler derives `Board_Strategy_Review_Transcript_Jan2026_Summary.txt` from that path, keeping everything in the same Demo folder.

---

## Change 6: Hide Save Button on Clear Chat (JavaScript)

Find the existing Clear Chat handler. It's triggered by `qpClear` and resets the chat. Add a line to hide the Save Summary button and clear the saved response. Look for the clear chat logic (search for `qpClear`) and add:

```javascript
document.getElementById("qpSaveSummary").style.display = "none";
lastAssistantResponse = "";
pendingSummarize = false;
```

---

## Change 7: Create the Meeting Transcript File

Create `C:\Users\frankbu\Documents\Demo\Board_Strategy_Review_Transcript_Jan2026.txt` with the content below. This is formatted as a Microsoft Teams Facilitator auto-generated transcript with three participants, timestamps, and natural conversational flow. The content ties into the existing demo data (Sarah Chen, Alex Kim, David Park, Q4 APAC numbers, governance framework, Heather's NPU demo).

```
Board Strategy Review — Q4 Results and 2026 Planning
Microsoft Teams Meeting Transcript
Date: January 28, 2026 — 2:00 PM – 2:47 PM PST
Meeting ID: 2026-01-28-board-strategy-q4

Participants:
- Sarah Chen, SVP Revenue Operations
- Alex Kim, VP Corporate Strategy
- Rachel Martinez, CEO Apex Dynamics (Board Advisor)

──────────────────────────────────────────────────

[00:00:12] Sarah Chen
Alright, let's get started. We have three things to cover today: the Q4 APAC revenue numbers, the 2026 strategic priorities, and the governance framework for the board presentation next week. Rachel, thanks for joining — your perspective on the Apex partnership will be really valuable here.

[00:00:31] Rachel Martinez
Happy to be here. I've reviewed the deck Alex sent over and I have some thoughts, but let's start with the numbers.

[00:00:42] Sarah Chen
So Q4 APAC came in at 847 million, which is 12% above forecast. The growth was driven primarily by three accounts — Nomura, Samsung Medical, and the Singapore government contract. However, and this is important for the board, the Singapore deal included a one-time licensing component of about 90 million that won't recur in Q1. So the run rate is closer to 757 normalized.

[00:01:18] Alex Kim
That's the number the board needs to see. If we present 847 without the normalization, we set ourselves up for a miss in Q1. I'd recommend we lead with the normalized figure and frame the 90 million as strategic validation of the government vertical.

[00:01:35] Rachel Martinez
Agreed. And from the Apex side, I can tell you that the Singapore team referenced your government deployment specifically when they renewed with us in December. There's a halo effect happening in the APAC government space that's worth calling out. It's not just revenue — it's positioning.

[00:01:58] Sarah Chen
Good point. I'll add a slide on APAC government pipeline momentum. We have three more RFPs pending — Taiwan Ministry of Digital Affairs, the Reserve Bank of India infrastructure program, and the Japan Digital Agency. Combined potential is around 200 million over 18 months.

[00:02:24] Alex Kim
Let me pivot to the 2026 strategy piece. I've restructured the deck around three pillars based on the board feedback from October. First pillar: endpoint intelligence — shifting AI workloads from cloud to device. This is the Copilot+ PC story. The hardware is ready; the model ecosystem is catching up. I think we need to be more aggressive here.

[00:02:51] Rachel Martinez
Can you define aggressive? Are we talking about engineering investment, go-to-market, partnerships?

[00:03:01] Alex Kim
All three, honestly. On engineering: we need dedicated NPU optimization teams, not just people borrowing cycles from the cloud AI group. On go-to-market: the pitch should shift from "AI-powered features" to "AI infrastructure you own." That's a fundamentally different value proposition for enterprise. And on partnerships: we should be working with ISVs in healthcare, legal, and financial services to build NPU-native applications.

[00:03:34] Sarah Chen
The healthcare angle is the one I keep coming back to. I had a conversation with the CISO at Mount Sinai last week, and his exact words were — and I wrote this down — "We will never send patient data to a cloud AI endpoint. But if you can show me an AI agent that runs on the device, we'll deploy it tomorrow." That's the buying signal we need to amplify.

[00:04:02] Rachel Martinez
I hear the same thing from our government clients at Apex. The air-gap requirement isn't going away. It's actually getting stricter. The new ITAR revisions in 2026 will expand the definition of controlled technical data, which means more workloads that literally cannot touch cloud infrastructure. This is a tailwind for local AI, not a headwind.

[00:04:28] Alex Kim
Which brings me to pillar two: governed autonomy. The board pushed back in October on the word "agent" because it sounds uncontrolled. I've reframed it as "governed delegation." The idea is that AI agents operate under explicit policy constraints — they ask for permission before accessing sensitive data, they log every action, and there's a human in the loop for high-stakes decisions. I think we need to demonstrate this, not just describe it.

[00:05:01] Sarah Chen
We actually have a working prototype of exactly this. Heather on my team built an agent runtime on Phi Silica over a weekend that does governed tool-calling with an approval gate and audit trail. It runs entirely on the NPU — no cloud. I've seen it work. It's early, but the architecture is right.

[00:05:22] Rachel Martinez
That's impressive. Can we show that to the board? Not as a product announcement, but as a proof point. "Here's what's possible today on hardware you're already shipping." That's a much stronger argument than a roadmap slide.

[00:05:38] Alex Kim
I love that idea. If we can do a live demo during the board session — even 90 seconds — it would land ten times harder than any slide. Sarah, can Heather have it demo-ready by the Super Bowl weekend event?

[00:05:52] Sarah Chen
She's already working on it. The demo has three moments: the AI reads files and creates documents, it asks for permission before multi-file access, and then you put it in airplane mode and it keeps working. That last part is the closer — proves data never left the device.

[00:06:14] Rachel Martinez
That's the story. "Intelligence with custody, not intelligence on loan." Write that down, Alex.

[00:06:22] Alex Kim
Already writing. OK, third pillar: ecosystem acceleration. We need to make it dramatically easier for third-party developers to build NPU-native applications. Right now the tooling is fragmented — Foundry Local is powerful but the developer experience needs work. Tool-calling support is missing from the API, which means every developer has to build their own shim layer. That's a barrier.

[00:06:51] Sarah Chen
Heather's patch is literally 549 lines of prompt engineering to work around that gap. If we shipped native tool-calling in Foundry Local, that entire shim goes away and every ISV can build what she built in a weekend.

[00:07:08] Rachel Martinez
That's your developer story right there. "What took 549 lines of workaround code becomes zero lines of native API." Ship that and the ecosystem moves.

[00:07:21] Alex Kim
I'll make sure that's in the engineering priorities section. Now on governance for the board deck itself — I want to be transparent about limitations. The current NPU model is 3.8 billion parameters. It's reliable for single-turn tool-calling in stateless mode, but multi-turn workflows degrade. We should present this honestly: the architecture is proven, the hardware is shipping, and model capability improves automatically as we release larger NPU-optimized models.

[00:07:56] Sarah Chen
That's the right framing. "The ceiling rises with every model generation, but the floor is already useful." Don't oversell. The board respects honesty more than hype.

[00:08:09] Rachel Martinez
One more thing before we wrap. On the Apex partnership specifically — David Park has been asking about exclusive early access to the NPU agent SDK. I've been noncommittal because I wanted to check with you first. My recommendation is we offer technical preview access, not exclusivity. If we lock this to one partner, we lose the ecosystem story Alex just described.

[00:08:35] Sarah Chen
Agree. Technical preview with a case study commitment — they get early access, we get a publishable reference customer. That's fair value exchange.

[00:08:46] Alex Kim
I'll draft the partnership terms. Rachel, can you float that framing to David before the dinner on Saturday? We don't want that conversation to go sideways at the vineyard.

[00:08:57] Rachel Martinez
I'll call him tomorrow. Better to set expectations before wine is involved.

[00:09:05] Sarah Chen
Smart. OK, let me summarize where we are. Alex, you're updating the board deck with normalized Q4 numbers, the three-pillar strategy, and the honest limitations framing. I'll coordinate with Heather on the live demo for Super Bowl weekend. Rachel, you're pre-briefing David Park on the partnership terms. And we all need to review the final deck by Thursday EOD.

[00:09:28] Alex Kim
One last thing — the governance deck. James Liu from legal flagged that we need explicit language about data residency guarantees in the local AI positioning. He sent me a memo with proposed language. I'll incorporate it and circulate by Wednesday.

[00:09:43] Rachel Martinez
Makes sense. If we're telling the board "data never leaves the device," legal needs to have blessed that claim.

[00:09:51] Sarah Chen
Agreed. Alright, I think we're in good shape. Same time next Tuesday for final review?

[00:09:58] Alex Kim
Works for me.

[00:10:01] Rachel Martinez
I'll be there. Good session, everyone.

[00:10:05] Sarah Chen
Thanks, all. Talk Tuesday.

──────────────────────────────────────────────────
End of transcript
Meeting duration: 10 minutes 5 seconds
Auto-generated by Microsoft Teams Facilitator
```

---

## Summary of All Changes

| # | What | Where | Lines Changed |
|---|------|-------|---------------|
| 1 | Add `💾 Save Summary` button HTML | Documents sidebar section (~line 1047) | +1 line |
| 2 | Add `lastAssistantResponse` and `pendingSummarize` vars | Near `lastUploadedFile` (~line 1516) | +2 lines |
| 3 | Capture response text + show button on done | `processLine` in `sendMessage` (~lines 1765, 1794) | +5 lines |
| 4 | Upgrade Summarize Doc prompt | `qpSummarizeDoc` click handler (~line 1546) | Modified existing |
| 5 | Add Save Summary click handler | After Detect PII handler (~line 1555) | +9 lines |
| 6 | Hide Save button on Clear Chat | Clear chat handler (search `qpClear`) | +3 lines |
| 7 | Create transcript file | `Documents\Demo\` | New file |

**Total: ~20 new lines of JavaScript, 1 new HTML element, 1 modified prompt, 1 new file.**

## Expected Demo Flow

1. **Click `+` button** → file picker opens → select `Board_Strategy_Review_Transcript_Jan2026.txt`
2. **SEE:** Chat shows "Loaded Board_Strategy_Review_Transcript_Jan2026.txt (X words)" — Summarize Doc and Detect PII buttons appear
3. **Click `📝 Summarize Doc`** → agent reads the transcript file, generates structured summary
4. **SEE:** Chat shows meeting summary with sections: MEETING SUMMARY, KEY IDEAS & DECISIONS, ACTION ITEMS with names and deadlines — `💾 Save Summary` button appears
5. **Click `💾 Save Summary`** → agent writes summary to `Board_Strategy_Review_Transcript_Jan2026_Summary.txt` in the Demo folder
6. **SEE:** Tool card shows write() executed, file saved to disk, audit trail updated

Three clicks. Three capabilities. Ingest → Reason → Write. All local.

## Testing

1. Verify the transcript file is in `C:\Users\frankbu\Documents\Demo\`
2. Start the app, go to AI Agent tab, click `+`, select the transcript
3. Click Summarize Doc — verify the summary includes named action items (Sarah Chen, Alex Kim, Rachel Martinez)
4. Click Save Summary — verify file appears on disk in the Demo folder
5. Click Clear Chat — verify Save Summary button hides
6. Repeat steps 2-4 in airplane mode — verify everything works offline
