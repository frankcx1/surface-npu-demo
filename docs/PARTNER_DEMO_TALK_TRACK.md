# Branch of the Future -- Partner Demo Talk Track

**Audience:** Surface Partner Advisors demoing to their customers
**Key message:** Data is king. This is why you trust Microsoft -- local AI keeps every byte of customer data in the customer's data sphere while delivering real enterprise value.

> **Tip:** This demo drives its own talk track -- the conversation should work exactly like the app reacts. Walk through the Zava app naturally, let the features speak, and layer in the "why it matters" as you go.

---

## How to Use This Guide

**Full demo (~20 min):** Walk all 5 scenarios in order -- they tell a complete story from morning prep through end-of-day CRM, capped by the governance view that shows IT how it's all controlled.

**Hero demo (~5 min):** Pick **one** scenario and go deep. Best bets:
- **Prep Next Client** if the audience cares about advisor productivity and cross-sell
- **Meeting Notes** if the audience cares about workflow automation and multi-model AI
- **Live Assist** if the audience is cross-industry (healthcare, insurance, customer service)
- **Agent 365 Governance** if the audience is IT leadership, CISOs, or compliance -- this is the "how do you govern it?" answer

**Deck integration:** Each scenario has a "Slide Notes" callout box -- short enough to paste into speaker notes on a partner deck slide.

---

## The Line That Wins the Room

From a Surface Partner Executive Advisory Board member (2026-05-12):

> **"You're finally showing me what AI can do besides chat."**

That's the bar. Everyone's seen a chatbot. Everyone's typed into Copilot. This demo shows **agentic AI** -- an AI that doesn't just answer questions but chains together multiple tools, services, and models to do real work. Calendar + CRM + product catalog + cross-sell + synthesis in one action. That's not chat. That's an agent.

If you land nothing else, land this distinction: *this isn't a chatbot with a banking skin -- it's a workflow engine that happens to use AI.*

---

## Setting the Stage (30 seconds)

> "What you're looking at is a Surface Copilot+ PC running a local AI model -- Phi-4 Mini through Microsoft Foundry Local. This is a Microsoft-approved model that runs entirely on the NPU in this device. No cloud. No API calls. No data leaving the laptop.
>
> The app is called Branch of the Future. It's a working prototype that shows what a bank advisor's workstation looks like when you bring AI to the edge -- inside the customer's data sphere, where Microsoft's trust framework keeps it."

**Why "data sphere":** Frank uses this phrase naturally -- it resonates with execs because it implies a boundary, not just a policy. The data stays *inside* something.

**Why "Microsoft trust":** As Chauncey put it -- "that's why you trusted Microsoft." The trust angle is the anchor. Foundry Local is a Microsoft runtime. The model is Microsoft-approved. The device is Surface. This isn't a third-party bolt-on.

---

## Demo 1: Prep Next Client (Advisor Assistant Tab)

**What to click:** Advisor Assistant tab > type "Prep Next Client" or click the suggestion chip

> **Slide Notes:** Advisor asks the AI to prep for their next client. In ~10 seconds, the local AI reads the live Outlook calendar (Work IQ / Microsoft Graph), pulls the customer profile from Dynamics 365 via MCP, scans a 27-product catalog for cross-sell gaps, and synthesizes a complete prep brief -- all on-device. No customer data leaves the laptop.

### Talk Track

> "An advisor walks into the branch. They sit down, open the app, and say 'Prep Next Client.' Watch what happens.
>
> This looks like a simple response, but the AI just did six things on this device in about ten seconds:
>
> First, it read the advisor's **live Outlook calendar** -- what we call Work IQ, powered by Microsoft Graph -- and found the next client meeting. It's smart enough to skip the morning huddle, compliance training, lunch -- it finds the actual client appointment.
>
> Then it made an **MCP call into Dynamics 365** -- that's Microsoft's Model Context Protocol, a secure way for the AI to talk to the bank's CRM -- and pulled back the client's full profile. Contact info, account history, recent activity.
>
> But here's where it gets really interesting. The AI scanned the bank's **product catalog -- 27 products** across deposits, lending, investments, insurance -- and compared what this client *has* against what they *don't have*. It checked **13 cross-sell triggers**: Does she have checking but no savings? Kids but no 529 plan? An old 401k sitting at a previous employer?
>
> Each gap maps to a specific product recommendation with a **talk track the advisor can use word-for-word** in the meeting. The AI even calculates a penetration tier -- New, Growth, Established, or Private -- so the advisor instantly knows the relationship strategy.
>
> All of that just happened locally. The client's financial profile, account balances, product gaps -- the AI processed it all, and none of it left this device. For a bank, that's not a nice-to-have. Data is king here."

### What to point out on screen
- The product recommendations with talk tracks (scroll down in the response)
- Product gap count and penetration tier
- Inference time in the response footer
- Work IQ and MCP mentioned naturally -- these are Microsoft platform capabilities

---

## Demo 2: ID & Check Verify (ID & Check Verify Tab)

**What to click:** ID & Check Verify tab > Demo Preset: Driver's License > Verify

> **Slide Notes:** Client hands over a driver's license. The device camera captures it, the NPU runs OCR and AI validation locally, extracts 7 structured fields, checks for fraud signals, then makes an MCP call to D365 to match or create the customer record. The ID image and PII never leave the device.

### Talk Track

> "Now the client is sitting across from the advisor. First step in any new account opening -- verify their identity.
>
> The advisor points the camera at the driver's license. The AI runs **OCR and document analysis right on the NPU** -- it extracts name, address, date of birth, license number, expiration, state, class. Seven structured fields from an image.
>
> Then it *reasons* about what it found. Is the ID expired? Do the fields look consistent? Any red flags? In this case -- Valid. Jackie Rodriguez, Michigan license, current.
>
> Now the verified identity flows into an **MCP call to Dynamics 365** to pull up or create the customer record. No retyping. No copy-paste errors. Camera to CRM in seconds.
>
> The important part: **the driver's license photo, the PII, the date of birth -- none of that went to a cloud endpoint.** The image was processed locally, the AI validated it locally, and only the verified result connected to the system of record. That's compliance by architecture, not by policy.
>
> This pattern applies anywhere you verify identity and protect PII -- banking, healthcare, insurance, government. The AI does the extraction, the device keeps the data local, and MCP handles the secure connection to the backend."

### Optional: fraud detection
> "If you want a fun moment in the demo -- try the McLovin preset. The AI catches the expired date, the single name, the address mismatch. It's not just reading fields, it's reasoning about them."

---

## Demo 3: Live Assist (Live Assist Tab)

**What to click:** Live Assist tab > Start Demo Script (or live mic if you're comfortable)

> **Slide Notes:** AI monitors a live advisor-client conversation in real-time. Generates sentiment analysis and actionable insight cards every 2-3 exchanges -- specific financial guidance like 529 contribution limits, Roth conversion opportunities. Speech-to-text and analysis run entirely on-device. Applies across industries: banking, healthcare, insurance, customer service, legal.

### Talk Track

> "Now the advisor is in a live conversation with Jackie. This is where local AI becomes a real-time copilot.
>
> I'll start the demo -- this simulates a real conversation between an advisor and a client. Watch the right side of the screen.
>
> The AI is listening to every exchange and doing three things at once:
>
> **Sentiment** -- is the customer positive, neutral, cautious? Watch when Jackie mentions fees at her last bank -- the AI picks up on that shift.
>
> **Actionable insights** -- not generic advice. When Jackie mentions her kids' ages, the AI surfaces the 2026 529 contribution limit: $18,000 per beneficiary. When she mentions an old 401k, it flags the Roth conversion opportunity. Specific numbers, specific products, right when the advisor needs them.
>
> **Cross-sell signals** -- the AI recognizes product opportunities as they come up naturally in conversation, giving the advisor confidence to make the right recommendation at the right moment.
>
> Now here's the architecture point that matters: **the audio never leaves this device.** In a cloud conversation-intelligence product, you're streaming customer audio -- financial details, account numbers, personal information -- to a third-party API. Here, the speech-to-text and the analysis all happen on the NPU.
>
> And think about where this applies beyond banking:
>
> - **Healthcare** -- a doctor's visit where the AI surfaces drug interactions and flags coverage questions, without patient data leaving the clinic
> - **Insurance** -- a claims call where the AI pulls up policy details and suggests next steps
> - **Customer service** -- any call center where agents need real-time coaching without routing sensitive data through a cloud transcription service
> - **Legal** -- client consultations where attorney-client privilege means conversation content can never touch a third-party server
>
> The pattern is the same: **a human conversation, enriched by AI, zero data egress.** That's not a feature. That's an architecture that solves compliance at the infrastructure level."

---

## Demo 4: Meeting Notes (Meeting Notes Tab)

**What to click:** Walk through Voice Capture > Camera/Classify > Generate Report > Post to D365

> **Slide Notes:** Full post-meeting workflow chaining 5 AI inference calls across 2 models (Phi-4 Mini + Phi Silica Vision), connecting to 2 backend services (Vision Service + D365), producing a complete client meeting summary with action items, follow-up email, and CRM posting -- all on-device. Zero bytes transmitted.

### Talk Track

> "This is where everything comes together. Meeting Notes chains multiple AI functions and backend services into a complete post-meeting workflow -- all inside the customer's data sphere.
>
> **Voice Capture** -- the advisor speaks their meeting notes. The AI does field extraction: client name, location, date, products discussed, referral source. All pulled from unstructured speech. That's AI call number one.
>
> **Document Classification** -- the advisor captured a photo of Jackie's retirement statement during the meeting. Now a *second* AI model kicks in -- **Phi Silica Vision** -- running on the same NPU. It classifies the document: 403(b) retirement statement, 94% confidence, with a plain-English explanation. Two different AI models, both local, both contributing to the same workflow.
>
> **Report Generation** -- the AI synthesizes everything into a **Client Meeting Summary**: narrative recap, client action items, advisor follow-up tasks, a draft follow-up email, and D365 task entries. That's the heaviest AI call -- 800 tokens of structured output.
>
> **Post to D365** -- one click and the meeting notes flow into the customer's timeline in Dynamics 365 via MCP. The CRM stays current without the advisor spending 20 minutes on data entry.
>
> **Translation** -- if the bank serves multilingual communities, one click translates the full report to Spanish. Still on-device.
>
> So count it up: **5 AI calls, 2 models, 2 backend services, one complete CRM-ready deliverable.** And the session stats at the bottom? Zero bytes of customer data transmitted. That's what 'AI at the edge' actually looks like in production. Not a chatbot -- a workflow engine."

---

## Demo 5: Agent 365 Governance (Persona Switcher > Jason)

**What to click:** In the sidebar persona switcher, click **Jason (IT Admin)** -- the app navigates to the Governance Pane. Then walk through the three beats: governed agent, shadow AI alert, tokenomics.

> **Slide Notes:** Three-act governance story. Act 1: The IT admin sees every advisor action logged, timestamped, and policy-evaluated -- local NPU agent in green, Microsoft 365 Copilot in blue, all governed through Agent 365. Act 2: Shadow AI alert fires -- an employee used ChatGPT with a Company Confidential document. Admin investigates, sees the full chain (Entra Internet Access + Purview DLP + Defender), blocks in one click. Act 3: Token economics -- 14,200 tokens processed locally at $0.00, $35.50 saved vs. cloud. The CISO gets compliance, the CFO gets cost savings, the CTO gets architectural proof.

### Talk Track

**Beat 1: The Governed Agent (2 min)**

> "Everything you just saw -- the prep brief, the ID scan, the live assist insights, the meeting notes -- all happened from the advisor's perspective. Now let's see the same agent through the eyes of the IT admin who has to govern it.
>
> I'm clicking over to **Jason.** Same app, same device. One click and we're in the **Agent 365 Governance** view.
>
> Let me start with the most important thing on this screen: the **agent registry** in the left panel. See the color coding?
>
> **Green is local.** Our Branch Concierge Agent runs entirely on the NPU in this device. Phi-4 Mini through Foundry Local. Every token it processes stays on this SSD. It has an **Entra identity**, scoped permissions, approved tools -- it's registered and governed the same way you govern a user or an app in your tenant today.
>
> **Blue is cloud.** Microsoft 365 Copilot -- also governed, also compliant. Your data stays within the M365 compliance boundary. Copilot doesn't train on your data. It inherits your existing permissions, respects your sensitivity labels, and every action is auditable through Purview. 64% of the Fortune 500 are running Copilot today, and financial services leads adoption at 71% -- precisely because of these trust guarantees.
>
> These two agents -- local and cloud -- are the **green lights.** Registered. Governed. Audited. The IT admin sees them, controls them, and can prove compliance to any regulator.
>
> Now look at the **Activity Timeline** in the center. Every action the advisor just performed is here. Click any entry and the left panel shows the full investigation detail -- timestamp, user, tools invoked, data accessed, token count, and the policy evaluation across all four domains: Conditional Access, DLP, Purview, Defender. All green. All compliant.
>
> The **auth flow** colors matter too. **Blue is On-Behalf-Of** -- the advisor asked the agent to do something, and it acted within her delegated permissions. **Purple is Agentic** -- the agent acted autonomously. A VIP arrival detection. A DLP redaction. A Purview retention label. These are the actions an IT admin needs to see most, because the agent made the decision, not the user.
>
> And the **Sovereignty Summary** at the bottom of the policy panel: *All AI processing governed by Agent 365. Zero data egress. Full audit trail.* That's the line that closes the deal for a CISO."

**Beat 2: Shadow AI -- The Red Light (2 min)**

*[Press Ctrl+Shift+A to trigger the Shadow AI alert]*

> "Now here's the scenario that keeps every CISO up at night.
>
> A Defender alert just fired. Look at the Defender card -- it went from green to red. **Shadow AI detected.**
>
> Let me click **Investigate** to see what happened.
>
> *[Click Investigate -- left panel shows the threat detail]*
>
> An employee on a branch device -- not this one, a different workstation -- just connected to `api.openai.com`. They opened a document marked **Company Confidential** in Purview, and the DLP endpoint agent detected that sensitivity-labeled content was in the clipboard headed for an unsanctioned AI tool.
>
> This is the **red light.** An unregistered, ungoverned AI endpoint. No Entra identity. No permission scoping. No audit trail. And the employee was about to paste proprietary client portfolio data into a consumer AI service that may retain it, may use it for training, and certainly isn't bound by your compliance framework.
>
> Microsoft sees this everywhere. 73% of organizations have detected unauthorized AI tool usage. 68% of employees have used shadow AI with corporate data. In financial services, where every byte of client data is regulated, this is an existential compliance risk.
>
> But here's what Agent 365 gives you -- **one click.**
>
> *[Click Block & Report]*
>
> The endpoint is blocked. The device is isolated through Intune. The user's session is revoked through Entra. A Purview incident is created for the compliance team. The MDCA catalog marks the app as unsanctioned org-wide. And the whole chain is in the timeline -- purple Agentic entry, timestamped, auditable.
>
> That's the contrast this dashboard is built to show:
>
> - **Green** -- local NPU agent. Data never leaves the device. Governed by Agent 365.
> - **Blue** -- Microsoft 365 Copilot. Data stays in your tenant. Governed by the same policies.
> - **Red** -- shadow AI. Data goes to a consumer endpoint. No governance. No compliance. No control.
>
> The question isn't whether your employees will use AI. They already are. The question is whether you can see it, govern it, and stop the red lights before proprietary data walks out the door."

**Beat 3: The Economics of Local AI (30 sec)**

> "One more thing. Look at the metrics row -- the last two cards.
>
> **14,200 tokens processed in 30 days. Local AI cost: $0.00.**
>
> If those same tokens went through a cloud LLM -- Azure OpenAI at enterprise rates -- that's $35.50 for one advisor at one branch. Multiply that across every advisor, every branch, every day, and the math gets real fast.
>
> With local AI, the hardware is the investment. **The inference is free. Forever.** No per-token billing. No API metering. No surprise invoices. And the compliance team doesn't have to review a single data processing agreement because the data never left the building."

*[Click Marcus or Sarah in the persona switcher to return to the advisor view]*

> "And one click, we're back to the advisor. Same agent, same device. The advisor sees a productivity tool. The IT admin sees a governed, audited, compliant system. The CFO sees zero marginal cost. **They're all looking at the same thing.**"

### What to point out on screen
- **Agent registry color coding** -- green (Local NPU), blue (Copilot), red (Shadow) -- the whole story in three colors
- **Click a timeline entry** to show investigation detail in the left panel -- makes it feel like a real SOC tool
- **Ctrl+Shift+A** for the Shadow AI alert -- the dramatic moment. Practice the timing.
- **Investigate button** opens the threat detail. **Block & Report** resolves it. Two clicks, full incident response.
- **Token/cost cards** -- $0.00 in green is the CFO closer
- **Sovereignty Summary** -- "Zero data egress. Full audit trail" is the CISO closer
- **Persona switcher** -- the one-click transition reinforces multi-persona, same-device story

### Key stats to weave in (all sourced)
- 73% of organizations have detected unauthorized AI tool usage (Microsoft, 2026)
- 68% of employees have used shadow AI with corporate data (enterprise surveys, 2026)
- 64% of Fortune 500 have active Copilot deployments; financial services leads at 71%
- Copilot data is not used to train models, stays within the M365 compliance boundary
- Agent 365 discovers 18 agent types including Claude Code and GitHub Copilot CLI (June 2026)
- Purview-encrypted documents cannot be decrypted by third-party AI tools -- hard block

### The governance pitch in one sentence
> "Green for local, blue for Copilot, red for shadow -- Agent 365 governs every AI agent in your enterprise the same way Entra governs every user and app today."

---

## Closing: Tokenomics and Carbonomics (Session Stats)

**What to point at:** Session stats widget in the sidebar. Optionally Ctrl+Shift+M for the live performance overlay.

> **Slide Notes:** Every AI call ran at $0.00 per token (vs. $2.50-$10/M tokens for cloud). NPU draws 5W during inference vs. 0.4 Wh per cloud query. CO2 savings are measurable and ESG-reportable. Three advantages no cloud-only solution delivers: data sovereignty, zero marginal cost, sustainability.

### Talk Track

> "One more thing before we wrap -- the business case. Look at the session stats from everything we just did.
>
> **Tokenomics.** Every token we used -- the prep brief, the ID verification, the live assist insights, the meeting report -- all ran locally. If those same calls went to a cloud LLM at Azure enterprise pricing, you'd be paying per million tokens with enterprise overhead. One advisor, one morning. Now multiply across a branch, a region, the whole bank. With local AI, the token cost is **zero.** The hardware is the investment. The inference is free forever.
>
> **Carbonomics.** Every cloud API call burns about 0.4 watt-hours at the data center. Our NPU draws **5 watts sustained** during inference. The CO2 difference is real and measurable -- grams avoided, based on US grid averages. For a bank running thousands of AI operations a day, that's material for ESG reporting. Real watts. Real grams. Real math.
>
> *[Ctrl+Shift+M if time allows]*
>
> And the live performance view -- CPU, GPU, NPU in real time. Watch the NPU spike during inference and drop right back. Purpose-built silicon doing AI work in a fraction of the power envelope.
>
> **So here's the pitch:** A Surface Copilot+ PC with Foundry Local gives your customer three things no cloud-only solution can:
>
> 1. **Data sovereignty** -- customer PII, financial records, voice conversations -- all stay in the customer's data sphere. This is why you trust Microsoft.
> 2. **Zero marginal cost** -- no per-token billing, no API metering, no surprise invoices.
> 3. **Sustainability** -- measurable carbon reduction that shows up in ESG reporting.
>
> That's Branch of the Future. Local AI. Real workflows. Data is king."

---

## Quick Reference: Demo Flow Cheat Sheet

| # | Tab | What to Click | Time | One-Line Value |
|---|-----|---------------|------|----------------|
| 0 | -- | Set the stage | 30s | Foundry Local, Microsoft-approved model, on-device |
| 1 | Advisor Assistant | "Prep Next Client" | ~15s | Calendar + D365 + product catalog + cross-sell -- 6 ops in 10 seconds |
| 2 | ID & Check Verify | Demo Preset: DL | ~5s | Camera to OCR to AI validation to D365 -- zero PII egress |
| 3 | Live Assist | Start Demo Script | ~90s | Real-time sentiment + insights, multi-industry value |
| 4 | Meeting Notes | Full workflow | ~60s | 5 AI calls, 2 models, 2 backends, complete CRM deliverable |
| 5 | Governance | Persona: Jason | ~60s | Agent 365: registered, governed, audited -- the CISO answer |
| 6 | Session Stats | Sidebar widget | ~30s | $0 tokens, CO2 savings, NPU power |

**Full demo:** ~4-5 min per scenario, ~20-25 min total
**Hero demo:** Pick one scenario, go deep, ~5-7 min including the close

---

## Bonus: "How Did You Build This?" (The Vibe Coding Story)

This comes up every time. Partners ask, execs ask, developers ask. The answer is the most powerful part of the demo because it makes the whole thing feel *accessible*.

> **Slide Notes:** This 17,000-line app was built by one PM through "vibe coding" -- describing features to an AI coding assistant (Claude Code) and iterating on the output. No engineering team. If you can talk about it, AI can build it. Partners can start building their own industry-specific apps today.

### Talk Track

> "People always ask me: 'How did you build this? How big is your dev team?'
>
> The answer is: **I vibe coded it.** This entire app -- 17,000 lines, six tabs, two AI models, live integrations with Outlook, D365, and a vision service -- was built by one person having a conversation with an AI coding assistant.
>
> Here's what vibe coding actually looks like: you install a coding AI -- Claude Code, GitHub Copilot CLI, Cursor, whatever you prefer -- and you start describing what you want. 'I need a Flask app that connects to Foundry Local and runs Phi-4 Mini on the NPU.' The AI writes the code. You run it. You say 'that works, but now add a tab for document classification.' It writes that too. You test, you give feedback, it iterates.
>
> **If you can talk about it, AI can build it.**
>
> The hardest part isn't the coding -- it's the first 10 minutes. Install the CLI, open a terminal, and have a conversation about what you want to build. That's the barrier. Once you're past that, you're off and running.
>
> I've written a blog post that walks through exactly how I built this app -- the tools, the platform, the gotchas, the iteration loop. You can literally copy that blog post, paste it as a prompt into one of these coding assistants, add your own idea on top, and start building. You could have a working prototype by end of day.
>
> That's the meta-story here: **the same local AI that powers this app for bank advisors is the same kind of AI that built the app in the first place.** AI building AI workflows. And it's not limited to banking -- if you can describe an industry workflow in plain English, you can build it."

### If they want to try it themselves
- Point them to the blog: `docs/BLOG_DRAFT_VIBECODING_NPU.md` in the repo (or the published version when live)
- The starting prompt is simple: *"Build a Flask app that connects to Foundry Local on a Copilot+ PC and runs Phi-4 Mini on the NPU"*
- From there, describe features in conversation -- the AI handles Flask routes, JavaScript, CSS, API integration
- The whole app was built through: describe -> generate -> test on hardware -> feedback -> iterate

---

## Objection Handling

| They Say | You Say |
|----------|---------|
| "We already use cloud AI" | "Cloud AI is great for batch analytics. But for real-time, PII-heavy workflows at the point of customer contact, local AI eliminates the compliance risk and the per-query cost. They're complementary -- and this is the piece that's been missing." |
| "Is the local model as good as GPT-4?" | "For these domain-specific workflows -- field extraction, classification, sentiment -- a purpose-built model on dedicated silicon matches or beats a general-purpose cloud model. And it responds in seconds with zero network latency." |
| "What about model updates?" | "Foundry Local manages model updates through Windows Update. Same deployment channel as drivers -- no retraining, no redeployment." |
| "Does it work offline?" | "Yes. Everything except D365 and Graph works in airplane mode -- AI, OCR, document classification, all fully offline. D365 and calendar fall back gracefully to local data." |
| "What hardware?" | "Any Copilot+ PC with an NPU -- Intel Core Ultra, Qualcomm Snapdragon X. Surface Laptop, Surface Pro, and a growing set of partner devices." |
| "How do I set it up?" | "We'll walk you through it on the device. It takes about 15 minutes -- install Foundry Local, clone the app, run the setup script. We can do it together today." |
| "How did you build this?" | "Vibe coded it. One person, an AI coding assistant, and a conversation. If you can describe the workflow, AI can build the app. I have a blog post you can literally paste as a prompt and start from." |
| "Could we build something like this for our customers?" | "That's the point. This isn't a product you license -- it's a pattern you replicate. Pick an industry, describe the workflows, and the same AI coding tools that built this can build yours. Banking, healthcare, insurance, manufacturing -- the pattern is the same." |

---

## Key Phrases to Weave In

These phrases tested well in live demos -- use them naturally, don't force them:

- **"Data is king here"** -- the anchor message, use it to punctuate any data sovereignty point
- **"That's why you trust Microsoft"** -- after explaining Foundry Local, MCP, or Graph
- **"Inside the customer's data sphere"** -- instead of "on-device" when talking to execs
- **"Compliance by architecture, not by policy"** -- the single most resonant line with bank CXOs
- **"Work IQ"** -- when referencing Microsoft Graph calendar/email integration
- **"MCP"** -- when explaining the D365 connection; it shows Microsoft's platform investment in secure AI-to-service communication
- **"The hardware is the investment; the inference is free forever"** -- the tokenomics closer
- **"If you can talk about it, AI can build it"** -- the vibe coding hook; makes the whole thing feel replicable, not magic
- **"Vibe coded it"** -- when they ask how it was built; one person, AI assistant, conversation
