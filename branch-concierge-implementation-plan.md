# Branch Concierge: VIP Client Arrival Awareness
## Implementation plan for Claude Code

---

## 1. Context and reframe

**What Flagstar asked for:** Sensor-based detection of high-profile clients entering a branch so they can be personally greeted at any branch location.

**What we're actually building and why:** Based on project feedback from the Nicole / Sergei on-device AI sync, a facial-recognition-at-the-door approach is a non-starter for regulated industries. BIPA, state biometric laws, consent frameworks, and ORA Sensitive Use triggers make ambient biometric sensing a dealbreaker for a bank CISO.

**Compatibility:** This feature slots into the config layer, so it works in both the Flagstar fork and the BofA reskin. Switch `bank_name` and the tier labels/colors, everything else is shared.

The reframe: **Branch Concierge**. The banker gets a heads-up with relevant account context so the conversation starts smarter. Same customer outcome (personalized greeting, relationship continuity across branches), completely different architecture and narrative. The banker is the hero, not the system.

Three consent-based arrival signals replace biometric detection:

1. **Mobile app check-in** ... the Flagstar (or BofA) mobile app has an opt-in "Notify my branch when I arrive" toggle in user settings. When the customer is within the branch's geofence AND that toggle is on, the app sends an arrival signal. For the demo this is aspirational product (the banks don't ship this feature today), and we frame it as "here's what becomes possible with on-device AI and a modest mobile app update."
2. **Appointment-driven arrival window** ... D365 appointment plus the same opt-in from the mobile app. Window opens 15 min before scheduled meeting.
3. **Teller-initiated propagation** ... when any teller scans an ID or pulls up a customer, if the customer is flagged VIP, that context propagates to the branch manager's device automatically. No sensors, no biometrics, just good data routing.

**Zero biometric inference. Zero ambient sensing. Zero PII leaving the device.** All three signals are things the customer either explicitly triggered (1 and 2) or that were triggered by a normal human interaction (3).

---

## 2. Feature scope in the demo kit

Add a new panel to **Anna's Branch Manager workflow** called "Arrivals." Structure:

### Arrivals feed (left pane)

Live-updating list of who is currently at the branch. Each arrival card shows:

- Client name and photo (from D365 profile, not a captured image)
- Tier badge: Private / Premier / Business / Retail
- Arrival source icon: App check-in / Appointment / Identified at teller
- Relationship Manager name and extension
- Dwell time ("arrived 3 min ago")
- Quick action buttons: "Greet now" / "Page RM" / "Mark met"

### Greeting brief (right pane)

When Anna taps a card, Phi-4 Mini generates a short personalized greeting brief using only local D365 data:

- Last interaction summary ("Last met with Sam on March 12 about a 529 plan for her daughter")
- Open threads ("She was deciding between age-based and static allocations")
- Life event hooks ("Daughter Maya turns 18 next month")
- Conversation starter (one sentence, warm, non-creepy)
- Do-not-mention list (declined offers, sensitive topics from declined_offers field)

### Trust Receipt integration

Every arrival event logs:
- Source of consent (app check-in token, appointment ID, or teller event ID)
- Data sources accessed (all local)
- Model used (Phi-4 Mini, local)
- Zero cloud calls
- Retention policy (arrival records purged at end of day)

---

## 3. Technical architecture

Single-file Flask preserved. New module-level sections added, no new files.

### Data model additions

```python
# In-memory arrival registry (resets on app restart, demo-appropriate)
arrivals = {
    "arrival_id": {
        "client_id": "D365 GUID",
        "arrived_at": datetime,
        "source": "app_checkin" | "appointment" | "teller_identified",
        "source_token": str,  # consent artifact
        "tier": "private" | "premier" | "business" | "retail",
        "status": "waiting" | "being_greeted" | "met",
        "assigned_rm": "RM name or null"
    }
}
```

### New Flask routes

- `GET /arrivals` ... returns current arrivals feed as JSON
- `POST /arrivals/checkin` ... simulates mobile app check-in (demo control)
- `POST /arrivals/appointment` ... simulates D365 appointment arrival
- `POST /arrivals/teller-identified` ... triggered by the existing ID Verify flow when a VIP-flagged customer is scanned
- `GET /arrivals/<arrival_id>/brief` ... generates the Phi-4 Mini greeting brief
- `POST /arrivals/<arrival_id>/status` ... updates status (greeted, met, etc.)

### D365 integration via MCP

- Pull customer profile, last interaction, open opportunities, declined_offers from the existing MCP wrapper
- Tier is NOT a real D365 field. For the demo we simulate it in `demo_data/customers.json` with a `vip_tier` property per customer profile. The MCP wrapper returns it alongside the normal profile data. Note this in demo narration: "in production this would be a D365 field or a derived attribute from AUM."
- Log greeting event back to D365 timeline as an activity (reuse existing timeline posting logic, cleaned up from the Flagstar demo hiccup)

### Config layer (repeatable for BofA)

Add to the config file:

```python
CONCIERGE_CONFIG = {
    "bank_name": "Flagstar",
    "tiers": {
        "private": {"label": "Private Client", "color": "#8B6F47", "threshold_aum": 5000000},
        "premier": {"label": "Premier", "color": "#1E3A5F", "threshold_aum": 250000},
        "business": {"label": "Business Banking", "color": "#2D5F3F"},
        "retail": {"label": "Retail", "color": "#6B7280"}
    },
    "arrival_sources": {
        "app_checkin": {"enabled": True, "label": "App Check-in"},
        "appointment": {"enabled": True, "label": "Scheduled Appointment"},
        "teller_identified": {"enabled": True, "label": "Identified at Teller"}
    },
    "greeting_brief": {
        "max_tokens": 200,
        "include_declined_offers": False,  # redact per Flagstar feedback
        "tone": "warm_professional"
    }
}
```

For BofA reskin: change `bank_name`, tier thresholds, colors, and tone. No code changes.

---

## 4. Sequenced Claude Code prompts

Feed these to Claude Code in order. Chunk deliberately; each should run, be tested in the demo flow, and committed before the next.

### Prompt 1: Config layer, demo data, and arrivals backend

```
I want to add a new "Branch Concierge" feature to the surface-npu-demo app. 
This is an arrivals panel for Anna the Branch Manager that shows clients who
have arrived at the branch through three consent-based signals: mobile app
check-in, scheduled appointment arrival, and teller-initiated identification.

Start with the foundation only. Do not build UI yet.

1. Add CONCIERGE_CONFIG to the config section near the top of app.py using the
   structure I'll paste below.
2. In demo_data/customers.json (create if it doesn't exist, otherwise extend),
   add a "vip_tier" property to 4-5 existing customer profiles. Use values
   "private", "premier", "business", or "retail". Make Jackie Rodriguez
   "premier" and create one "private" tier customer named Marcus Chen for
   the big-deal demo moment.
3. Add an in-memory arrivals dict at module scope.
4. Add four new Flask routes: GET /arrivals, POST /arrivals/checkin, 
   POST /arrivals/appointment, POST /arrivals/teller-identified.
5. Each POST route should accept a client_id and simulate the arrival by
   adding to the arrivals dict with a UUID arrival_id. Pull vip_tier from
   the customer profile via the existing MCP wrapper.
6. Every arrival should create a Trust Receipt entry with the source, 
   consent token, and timestamp. Use the existing trust_receipt_log 
   function pattern.
7. Return JSON only. No UI work in this prompt.

Preserve the single-file Flask architecture. No em dashes anywhere in 
strings or comments. Use ellipses or commas instead.

[paste CONCIERGE_CONFIG block from the plan]
```

### Prompt 2: Arrivals feed UI

```
Now add the Arrivals panel UI. Two-pane layout, left pane is the live feed,
right pane is the greeting brief (empty for this prompt, we'll build it next).

1. Add a new tab to Anna's Branch Manager workflow called "Arrivals".
2. Left pane: vertical list of arrival cards. Each card shows client name,
   tier badge (color from CONCIERGE_CONFIG), arrival source icon, RM name,
   and dwell time ("arrived 3 min ago"). Cards auto-sort by arrival time,
   newest on top.
3. Poll /arrivals every 5 seconds to update the feed. Show a subtle pulse
   animation on new cards when they appear.
4. Add three "Simulate arrival" buttons at the top of the pane for demo
   control: "App check-in", "Appointment arrival", "ID verified at teller".
   Each hits the corresponding POST route with a demo client_id.
5. Use the existing CSS variables and component patterns from the rest of the
   app. Tier badge styling should be distinct and readable.
6. Dwell time should update every 10 seconds in the UI.

Reuse the existing Trust Receipt log display. No new layout framework.
```

### Prompt 3: Greeting brief generation

```
Now wire up the greeting brief in the right pane.

1. When an arrival card is clicked, call GET /arrivals/<arrival_id>/brief.
2. That endpoint should pull the client profile from D365 via MCP (reuse the
   existing MCP client wrapper). Fetch: last 3 interactions, open 
   opportunities, and any declined_offers.
3. Build a prompt for Phi-4 Mini via Foundry Local that generates a greeting
   brief with these sections: Recent Context (1-2 sentences), Open Threads
   (bullet list, max 3), Life Event Hooks (if any in the profile data),
   Conversation Starter (one warm sentence).
4. IMPORTANT: Filter declined_offers OUT of the prompt entirely. Do not
   include them in the brief and do not mention them to the model. This
   matches the "do not ask again" feedback from the Flagstar EBC.
5. Stream the response into the right pane with a typewriter effect.
6. Add a prominent "Local AI" badge at the top of the brief that shows the
   token count and "$0.00 cloud cost". This is part of the Trust Receipt
   narrative.
7. Log the brief generation event to the Trust Receipt with: model name,
   token count, data sources accessed (all local), cloud calls (zero).

Keep the tone warm and professional, never creepy or surveillance-y. If the 
brief generation produces anything that sounds like "the system knows...", 
rewrite. The banker is the hero here, not the AI.
```

### Prompt 4: Teller-to-Branch-Manager propagation

```
Now connect the existing ID Verify flow to the Arrivals panel. This is the
third consent-based arrival signal: when a teller scans a client ID, if that
client is flagged VIP in D365, an arrival event should automatically
propagate to Anna's Arrivals panel.

1. In the existing ID Verify flow, after a successful scan, check the
   customer's vip_tier field from D365.
2. If tier is "private" or "premier", POST to /arrivals/teller-identified
   with the client_id and the teller's station ID as the consent token.
3. The arrival should appear on Anna's Arrivals panel within 5 seconds.
4. Show a subtle toast on the teller's screen confirming the branch manager
   has been notified. Keep this understated, it's a normal operational event.
5. Update the Trust Receipt on BOTH the teller device and the branch manager
   device to reflect the cross-device handoff. Both entries should reference
   the same event_id.

This proves out the "personal greeting at any branch" narrative without any
biometric or ambient sensing. The trigger is a normal teller interaction.
```

### Prompt 5: Status lifecycle and polish

```
Last piece. Handle the full arrival lifecycle and polish the flow.

1. Add status transitions: waiting -> being_greeted -> met. "Greet now" 
   button moves the arrival to being_greeted. "Mark met" moves to met and
   hides from the active feed (archived in Trust Receipt).
2. "Page RM" button: if the assigned Relationship Manager is at the branch
   but not currently logged into a Surface device shown in Arrivals, show a
   mock Teams DM being sent ("Your client Jackie Rodriguez just arrived...").
3. Add a 30-minute auto-expire on arrival records. After 30 min with no
   status change, archive automatically.
4. End-of-day Trust Receipt export for Arrivals: include every arrival, 
   source consent token, data accessed, model usage, and zero cloud calls.
   This is a compliance artifact the bank can hand to their risk team.
5. Add a demo reset button that clears all arrivals. Useful for walk-through
   repeat runs during exec demos.

After this prompt, walk through the full flow with me on localhost:5000 and
catch any UX hiccups before the BofA reskin.
```

---

## 5. Demo flow for executives

Three-minute sequence you can drop into Anna's walkthrough:

1. **Setup the scene (20 sec):** "Jackie Rodriguez is a Premier client. She normally banks at the Troy branch but she's traveling and stops into a Flagstar branch in Ann Arbor. How does this branch give her the relationship experience without turning the lobby into a surveillance system?"
2. **Trigger app check-in (15 sec):** Click "Simulate app check-in." Arrival card appears on Anna's screen. "She opted in through the mobile app. That's consent. No biometrics, no ambient sensing."
3. **Tap the card, show the brief (45 sec):** Greeting brief streams in. "Phi-4 Mini generated this locally from our D365 profile. Token counter shows $0.00 cloud cost. Trust Receipt logs every source."
4. **Show the teller path (30 sec):** Switch to teller view, scan Marcus Chen's ID (Private tier). Watch the arrival appear on Anna's Arrivals panel with the Private Client badge. "Normal teller interaction, no sensors, cross-device handoff still works. Marcus gets the white-glove greeting because the teller scan propagated context, not because a camera identified his face."
5. **Tokenomics close (30 sec):** "Anna does this 40 times a day. 8,000 of these devices across your branches. At zero cloud cost per greeting. Every arrival logged as a compliance artifact."

---

## 6. RAI and compliance talking points (keep in back pocket)

- **No biometric data is captured, stored, or inferred.** The arrival signal is either customer-initiated (app check-in), calendar-driven (appointment), or operationally-triggered (teller ID scan, which is already a compliant interaction).
- **All three signals are consent-linked.** The consent artifact (app token, appointment ID, teller station ID) is logged in the Trust Receipt.
- **No data leaves the device.** Greeting briefs are generated by Phi-4 Mini on the NPU. D365 access is authenticated MCP calls to the bank's own tenant.
- **Declined offers are redacted from the brief.** Directly addresses Flagstar's "if they said no, don't ask again" feedback from the EBC.
- **End-of-day compliance artifact is exportable.** Every arrival, consent token, data access, and model call is in one signed Trust Receipt bundle.
- **BIPA posture:** Because no biometric identifiers are collected or used, BIPA and similar state laws are not implicated. This is defensible to a bank CISO in a first conversation.
- **ORA path:** This version should not require a Sensitive Use review. If Branch Concierge moves from concept demo to customer-committed feature, loop Ray Sims in for confirmation. The likely item he'd flag is the AI-generated greeting brief, which is easy to mitigate with standard content filters and a human-in-the-loop gate (the banker reviews the brief before greeting).

---

## 7. Decisions locked in

- **Mobile app:** aspirational. The banks have mobile apps but not the opt-in arrival check-in feature. Demo narration will say "here's what becomes possible with a small mobile app update" and keep it honest.
- **VIP tier:** simulated in `demo_data/customers.json` with a `vip_tier` property. Not a real D365 field. Demo narration mentions this would be a D365 field or AUM-derived attribute in production.
- **Arrival trigger:** "Simulate arrival" buttons only. No geofence simulation. Keeps the demo control crisp.
- **RAI pre-clearance:** skipped for this concept demo. If this feature graduates from demo to customer-committed build, loop Ray Sims in before the first external pitch uses it as a commitment.
- **BofA reskin:** already done. This feature ships into the current kit driven by CONCIERGE_CONFIG so both the Flagstar and BofA versions get it with different tier labels and colors.

---

## 8. Known risks

- **Phi-4 Mini greeting brief quality.** Small model, short prompts, mixed context. Spend time on the prompt template in Prompt 3. Have 2-3 canned profiles with carefully tuned D365 data for the exec demo.
- **MCP latency for D365 lookups.** If a brief takes more than 2 seconds to generate, the demo drags. Consider pre-warming the cache for known demo clients.
- **Tab-to-tab polling overhead.** Polling /arrivals every 5 sec on multiple devices is fine for demo scale, would need to go WebSocket for production pitch language.
- **BofA will ask about cross-branch data residency.** Have an answer ready: all arrival data is tied to the specific branch's D365 tenant scope and doesn't replicate to other branches except through the normal CRM sync.
