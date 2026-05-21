# Claude Code Prompt: Build "My Day" AI Personal Assistant Tab

## Context

I'm building an executive demo for a Super Bowl marketing event targeting CEO/CIO/GC-level decision makers. The goal is to show AI that acts as a **chief of staff** — reading email, calendar, and tasks, then **cross-referencing them** to produce an intelligent morning briefing. All running locally on the device's NPU via Foundry Local + Phi Silica. No cloud.

The existing app is at: `C:\Users\frankbu\OneDrive - Microsoft\NPU\npu_demo_flask.py`
The exec spec is at: `C:\vibe\moltbot_npu\EXEC_SUMMARY_NPU_AGENT_DEMO.md`

Read both files before starting. The Flask app already has:
- Document Analysis tab
- AI Agent tab (chat with tool calling via compact prompt + [TOOL_CALL] parsing)
- ID Verification tab
- Backend that talks to Foundry Local at localhost:5272
- Tool execution: read, write, exec, __text_response
- Safety guardrails, audit trail, connectivity check

## What to Build

### 1. "My Day" Tab — AI Personal Assistant Dashboard

Add a new tab as the **first/default tab** called "My Day" with a clean morning-dashboard layout.

**Top section — Data summary cards (3 cards in a row):**
- 📧 Email card: count of emails (15 in demo data)
- 📅 Calendar card: count of today's events (10 in demo data)
- ☐ Tasks card: count of tasks due today (7 in demo data)

**Action buttons:**
- **"☀️ Brief Me"** — the main demo button. AI reads all three data sources, cross-references them, generates an intelligent briefing
- **"🔄 Refresh"** — re-reads data sources and updates counts
- **"📧 Triage Inbox"** — just the email triage (prioritize into 🔴🟡🟢)
- **"📋 Prep for Next Meeting"** — reads calendar, finds next meeting, cross-references with relevant emails and tasks

**Results area — Two sections:**

**AI Insights section:**
- The cross-referenced intelligence (the magic part)
- Format: ⚡ bullets connecting email → calendar, tasks → meetings, etc.
- This is where Phi Silica's reasoning shines

**Timeline section:**
- Today's calendar with AI annotations
- Each meeting shows relevant warnings/prep items inline
- Example: `9:00  1:1 with CFO ⚠️ She emailed about Q4 numbers last night`

**Footer:**
- 🔒 "All data processed locally on NPU"
- ⏱️ Execution time

### 2. Pre-Staged Demo Data

Create a `C:\Users\frankbu\Documents\Demo\My_Day\` folder with:

```
My_Day/
├── calendar.ics          ← Real iCalendar format (RFC 5545) — Outlook/Google/Apple standard  
├── tasks.csv             ← Microsoft To Do / Planner export format
└── Inbox/
    ├── 001_sarah_q4_numbers.eml         ← Real RFC 5322 email format
    ├── 002_legal_nda_flag.eml
    ├── 003_sandra_event_update.eml
    ├── 004_james_liu_governance.eml
    ├── 005_alex_governance_deck.eml
    ├── 006_david_park_ea.eml
    ├── 007_driver_confirmation.eml
    ├── ...
    └── 015_newsletter.eml
```

Why real formats matter: The presenter can say "these are the same file formats your Outlook exports — .ics for calendar, .eml for email, CSV for tasks. Standard, portable, local. This AI reads what your apps already produce."

**calendar_today.ics — Real iCalendar format (.ics):**

Use proper iCalendar (RFC 5545) format. This is the universal calendar format — Outlook, Google Calendar, Apple Calendar all use it. Python can parse with the `icalendar` pip package or simple text parsing.

CRITICAL: Each VEVENT must have a rich DESCRIPTION field containing meeting agendas, pre-read references, action items, and context. This is where the AI finds cross-references. The DESCRIPTION is the intelligence goldmine.

Create this exact calendar.ics file (use date 2026-02-07 for the Saturday event):

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Microsoft//Outlook 16.0//EN
BEGIN:VEVENT
DTSTART:20260207T100000
DTEND:20260207T103000
SUMMARY:Hotel Late Checkout Deadline
LOCATION:Four Seasons Hotel
DESCRIPTION:Late checkout confirmed through concierge. Pack demo equipment and devices before checkout.\n\nREMINDER: Surface Laptop 7 and Surface Pro 11 devices for demo stations are in the hotel safe. Don't forget chargers and display adapters.
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART:20260207T113000
DTEND:20260207T123000
SUMMARY:Team Huddle — Event Prep
LOCATION:Hotel Conference Room B
ORGANIZER;CN=Sandra Mitchell:mailto:smitchell@microsoft.com
ATTENDEE;CN=Frank Buchholz:mailto:frankbu@microsoft.com
ATTENDEE;CN=Jack Rivera:mailto:jrivera@microsoft.com
ATTENDEE;CN=Kevin Park:mailto:kpark@microsoft.com
DESCRIPTION:Final walkthrough for tonight's executive event.\n\nAGENDA:\n1. Confirm demo station assignments (Frank on AI Agent station)\n2. Device lineup and giveaway logistics (10 Surface Laptop 7, 10 Surface Pro 11)\n3. Guest seating and table assignments\n4. AV check at venue — Kevin confirming projection and screen\n5. Fireside chat topic cards for dinner tables\n\nACTION: Frank — have the NPU demo app tested and ready. Sandra wants a dry run at 3 PM at the venue.\n\nNOTE: 47 confirmed RSVPs. Guest list attached to Sandra's email.
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART:20260207T140000
DTEND:20260207T150000
SUMMARY:Prep Window — Priority Items
LOCATION:Hotel Room
DESCRIPTION:Blocked time to handle outstanding items before the event.\n\nPRIORITY:\n1. Reply to Sarah Chen re: Q4 APAC numbers (she messaged last night)\n2. Read Jessica Torres' NDA flag — critical before seeing David Park tonight\n3. Skim Alex Kim's AI governance deck — James Liu RSVPed and has been asking about guardrails\n4. Review guest list — know who's at your table
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART:20260207T150000
DTEND:20260207T153000
SUMMARY:Dry Run — AI Agent Demo
LOCATION:Event Venue — Demo Station 3
ORGANIZER;CN=Sandra Mitchell:mailto:smitchell@microsoft.com
ATTENDEE;CN=Frank Buchholz:mailto:frankbu@microsoft.com
DESCRIPTION:Quick dry run of the NPU AI Agent demo at the venue.\n\nCHECKLIST:\n- Launch Flask app, verify all tabs load\n- Test "Brief Me" flow end-to-end\n- Test "Go Offline" (WiFi toggle) — make sure it works and recovers\n- Confirm projector/screen setup if doing group walkthrough\n- Verify demo files are staged in Documents\\Demo folder\n\nSandra wants to see the permission workflow demo — the "governed agent" piece.
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART:20260207T161500
DTEND:20260207T163000
SUMMARY:🚗 Driver Pickup — Hotel to Venue
LOCATION:Four Seasons Hotel — Main Lobby
ORGANIZER;CN=Travel Desk:mailto:travel@microsoft.com
DESCRIPTION:Car service confirmed.\n\nDRIVER: Michael Torres, black Suburban, license plate TBD.\nPICKUP: Main lobby entrance, 4:15 PM sharp.\nDROP-OFF: Event venue main entrance.\nDRIVE TIME: ~15 minutes (normal traffic), ~25 minutes (game day traffic).\n\nNOTE: Allow extra time for Super Bowl traffic. Driver is aware of game day routing.
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART:20260207T170000
DTEND:20260207T180000
SUMMARY:Arrival & Mingle Hour
LOCATION:Event Venue — Main Hall
DESCRIPTION:Guests arrive. Open bar and appetizers.\n\nSTRATEGY:\n- Work the room during this hour — this is when 1:1 conversations happen\n- Key people to connect with: David Park (Contoso), James Liu (board), Dr. Sarah Okafor (Meridian Health)\n- Sandra will make introductions for any guests you haven't met\n- Device lineup display is near the entrance — guests will naturally browse\n\nAVOID: Don't get pulled into a long demo during mingle hour. Save the detailed AI Agent walkthrough for the demo stations after dinner.
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART:20260207T180000
DTEND:20260207T200000
SUMMARY:Dinner & Fireside Discussion
LOCATION:Event Venue — Dining Room
DESCRIPTION:Seated dinner with fireside chat discussion prompts at each table.\n\nTABLE TOPICS (printed cards):\n- "What would change if your AI assistant couldn't leak data — by design?"\n- "Would you give an AI agent permission to act on your files? Under what rules?"\n- "What's the last thing you'd move to the cloud?"\n\nFrank is at Table 3 with: David Park (Contoso), James Liu (board member), Dr. Sarah Okafor (Meridian Health CEO), Tom Bradley (Whitfield Capital CIO).\n\nNOTE: This is the relationship-building window. Be present. Don't pitch — listen, then offer to show the demo after dinner.
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART:20260207T200000
DTEND:20260207T213000
SUMMARY:Demo Stations & Device Showcase
LOCATION:Event Venue — Demo Hall
DESCRIPTION:Three demo stations open for hands-on exploration.\n\nSTATION 1: AI Agent — "My Day" briefing + governed execution (FRANK)\nSTATION 2: ID Verification — on-device document scanning (Kevin)\nSTATION 3: Document Intelligence — PDF analysis + summarization (Jack)\n\nGUESTS BROWSE FREELY. Keep demos under 90 seconds unless they ask for more.\n\nDEVICE GIVEAWAYS: 10 Surface Laptop 7 and 10 Surface Pro 11 with 5G. Sandra handles distribution at end of evening.\n\nKILLER DEMO MOMENT: Run the AI Agent "Brief Me" → show governed execution → kill WiFi live → continue without pause.\n\nFALLBACK: If AI Agent has issues, pivot to Document Analysis or ID Verify tabs — they're reliable and still impressive.
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART:20260207T213000
DTEND:20260207T220000
SUMMARY:Wrap-Up & Device Giveaways
LOCATION:Event Venue — Main Hall
DESCRIPTION:Sandra leads brief closing remarks. Device giveaways distributed.\n\nFrank's role: Be available for follow-up conversations. Have business cards ready.\n\nANY EXEC WHO ENGAGED DEEPLY: Offer to set up a private demo at their office with their actual data scenario.
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
DTSTART:20260207T221500
DTEND:20260207T223000
SUMMARY:🚗 Return Driver — Venue to Hotel
LOCATION:Event Venue — Main Entrance
DESCRIPTION:Return car service.\n\nDRIVER: Same driver (Michael Torres).\nPICKUP: Main entrance, 10:15 PM.\nNOTE: If event runs late, driver will wait up to 30 minutes. Text to confirm.
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR
```

**tasks.csv — Microsoft To Do / Planner export format:**

CSV is the most universally recognized export format. The presenter says: "This is a task export — same as what you'd get from Microsoft To Do or Planner."

```csv
Task,Due Date,Priority,Status,List,Notes
Reply to Sarah Chen — Q4 APAC numbers,2026-02-07,High,Not Started,Work,"Sarah emailed 11:47 PM last night. She needs confirmed APAC revenue figures before Monday's earnings prep. Quick reply — numbers are in the Q4 deck slide 14."
Read NDA flag from Jessica Torres,2026-02-07,High,Not Started,Work,"URGENT: Section 7.3 non-compete clause is too broad. Must read before seeing David Park at tonight's event. 5 minutes."
Skim AI governance deck v3,2026-02-07,Medium,Not Started,Work,"Alex sent updated deck last night. James Liu (board member) RSVPed for tonight and has been asking about AI guardrails. Be ready to discuss casually."
Review guest list for tonight,2026-02-07,Medium,Not Started,Work,"Sandra sent the RSVP list. Know who's at your table and key attendees."
Test demo app — dry run at 3 PM,2026-02-07,High,Not Started,Work,"Sandra wants to see the AI Agent demo working at the venue. Launch app, test all flows, verify offline mode works."
Send thank-you note to Dr. Patel,2026-02-07,Low,Not Started,Personal,"She replied warmly to your summit thank-you. Just close the loop."
Pack demo devices from hotel safe,2026-02-07,Medium,Not Started,Work,"Surface Laptop 7 and Surface Pro 11 units plus chargers and display adapters. Before checkout."
```

**Inbox/ folder with .eml files (15 emails):**

Use real RFC 5322 .eml format with proper headers (From, To, Subject, Date, Message-ID, MIME-Version, Content-Type). Make them feel authentic — proper email signatures, realistic timestamps (overnight/early morning), executive tone.

CRITICAL REQUIREMENT: Several emails must directly cross-reference calendar events and tasks so the AI can connect dots across all three data sources. The email bodies should be realistic and substantive — not one-liners. Include proper email signatures, realistic timestamps (overnight and early morning), executive tone.

**The scenario is Super Bowl Saturday.** The exec is at a hotel, has event prep, a dry run, then the executive marketing event tonight. Emails reflect this context.

Urgent (🔴):
- `001_sarah_q4_numbers.eml` — From: Sarah Chen <schen@microsoft.com> (CFO), sent 11:47 PM Friday night. Subject: "Q4 APAC numbers — need before Monday." Body: She's prepping the Q4 earnings materials over the weekend. The APAC revenue figures haven't been finalized in the deck (slide 14). Asks you to confirm the numbers so she can update before Monday's prep meeting. Mentions "I know you're at the Super Bowl event this weekend — just a quick reply when you get a chance." Professional but slightly urgent. **Cross-refs: Q4 reply task, Sarah will be at the event tonight (guest list).**

- `002_legal_nda_flag.eml` — From: Jessica Torres <jtorres@microsoft.com> (Legal), sent 8:15 AM Saturday. Subject: "URGENT: Contoso NDA — non-compete clause in Section 7.3." Body: The latest Contoso partnership NDA draft has a non-compete clause that's significantly broader than negotiated — would restrict AI partnership activities for 24 months across all verticals. Recommends NOT signing until narrowed. Flags that she knows David Park is attending tonight's event: "Please do not discuss specific partnership terms or M&A until this is resolved. Happy to brief you by phone before the event if helpful." **Cross-refs: David Park at dinner (Table 3), Contoso agenda email, NDA task.**

- `003_sandra_event_update.eml` — From: Sandra Mitchell <smitchell@microsoft.com>, sent 7:45 AM Saturday. Subject: "Tonight — final details and guest list." Body: Confirmed 47 RSVPs. Attaches table assignments. Your table (Table 3): David Park (Contoso CEO), James Liu (board member), Dr. Sarah Okafor (Meridian Health CEO), Tom Bradley (Whitfield Capital CIO). Reminds about dry run at 3 PM. Dress code: business casual. Asks Frank to confirm demo station is ready. Mentions the device giveaway logistics (10 Surface Laptop 7, 10 Surface Pro 11). **Cross-refs: all evening events, dry run, demo test task, guest list task.**

Action Needed (🟡):
- `004_james_liu_governance.eml` — From: James Liu <jliu@board.com>, sent 9:00 AM Saturday. Subject: "Looking forward to tonight — quick question on AI governance." Body: Conversational and friendly. Says he's excited about the event, then asks: "I've been thinking about on-device AI agents for our portfolio companies. If we deploy agents on employee devices, how do we ensure they operate within defined data boundaries? What's the audit trail look like? Would love to chat about this tonight if you have a moment." **Cross-refs: AI governance deck task, dinner table assignment, demo station.**

- `005_alex_governance_deck.eml` — From: Alex Kim <akim@microsoft.com>, sent 9:22 PM Friday night. Subject: "AI governance deck v3 — updated with legal feedback." Body: v3 of the governance framework deck with Jessica Torres' data residency feedback incorporated. Lists 3 key changes from v2. Says "I hear James Liu from the board will be at your event tomorrow — this might be relevant if it comes up casually." **Cross-refs: governance deck task, James Liu email, tonight's event.**

- `006_david_park_ea.eml` — From: Lisa Wang <lwang@contoso.com> (David Park's EA), sent 8:45 AM Saturday. Subject: "Tonight's event — David looking forward to connecting." Body: David is looking forward to seeing you tonight. Lisa mentions he'd like to discuss "partnership expansion and exploring deeper strategic alignment" during the mingle hour or at dinner. Professional and warm — the "deeper strategic alignment" phrasing subtly hints at M&A. **Cross-refs: David Park at dinner table, NDA flag from legal, mingle hour schedule.**

- `007_driver_confirmation.eml` — From: Travel Desk <travel@microsoft.com>, sent 6:00 AM Saturday. Subject: "Car service confirmed — Saturday Feb 7." Body: Driver Michael Torres, black Suburban. Hotel pickup 4:15 PM (main lobby). Return pickup 10:15 PM (venue main entrance). Driver will wait up to 30 min if event runs late. Includes driver's cell number. Notes game-day traffic advisory — allow extra 10 minutes. **Cross-refs: driver calendar events.**

FYI / Can Wait (🟢):
- `008_hotel_checkout.eml` — Late checkout confirmation through 10 AM
- `009_kevin_av_setup.eml` — Kevin confirms AV equipment and projection screen are ready at venue
- `010_jack_demo_stations.eml` — Jack confirming he'll run Document Intelligence station; asks if Frank needs anything for his station
- `011_dress_code.eml` — Sandra's reminder: business casual, no ties needed
- `012_team_dinner_sunday.eml` — Team debrief dinner planned for Sunday 7 PM
- `013_flight_monday.eml` — Flight home confirmation for Monday 10:30 AM
- `014_speaker_reply.eml` — Dr. Patel replied warmly to your thank-you note from the AI summit last week. **Cross-refs: thank-you task (can mark done).**
- `015_newsletter.eml` — Weekly AI industry newsletter

### 3. The Agent Flow for "Brief Me"

When the user clicks "Brief Me", the backend should:

1. Read `calendar.ics` → parse VEVENT components, extract SUMMARY, DTSTART, LOCATION, ATTENDEES, and critically the DESCRIPTION field (this has agendas, pre-reads, context, expected questions)
2. Read `tasks.csv` → parse CSV rows, extract Task, Due Date, Priority, Notes
3. List emails in `Inbox/` → get count
4. Read the urgent and action-needed emails (read all or at least the first 7-8)
5. Send everything to Phi Silica with this system prompt approach:

**Parsing approach**: 
- **Calendar (.ics)**: Use simple Python string/regex parsing — the iCalendar format is plain text with `BEGIN:VEVENT` / `END:VEVENT` blocks and `KEY:VALUE` lines. No external packages needed. Extract SUMMARY, DTSTART, LOCATION, ATTENDEES, DESCRIPTION for each event.
- **Tasks (.csv)**: Use Python's built-in `csv` module. Dead simple. 
- **Email (.eml)**: Use Python's built-in `email` module to parse headers (From, Subject, Date) and body text.
- For the demo, pre-process all three into a clean text summary before sending to Phi Silica. Don't send raw file markup — format it as structured plain text the model can reason about easily.

**Presenter talking point about real formats:**
> "Where is this data coming from? Standard formats your devices already use. The AI reads `.ics` calendar files — same format Outlook, Google Calendar, and Apple all export. Standard `.eml` email files. And a CSV task export from Microsoft To Do. These aren't custom data structures — these are your actual file formats, parsed locally on the NPU."

```
You are an executive chief of staff preparing a morning briefing 
for a busy Saturday. Your executive is attending a high-profile 
Super Bowl executive marketing event tonight.

You have their calendar, email inbox, and task list.

YOUR OUTPUT SHOULD HAVE TWO PARTS:

PART 1 — EXECUTIVE SUMMARY (conversational, warm, 8-10 sentences):
Write like you're briefing the exec over coffee. Lead with the 
big picture of their day. Flag the most important things: who 
they'll see tonight, what they need to handle before the event, 
any landmines to avoid. Mention logistics (driver, times, venue).
Be direct and human — not a list, a narrative.

PART 2 — DETAILED BREAKDOWN (structured sections):
- TIMELINE: Today's schedule with annotations
- PEOPLE TO KNOW: Key people attending tonight, what to know 
  about each (pending issues, conversation topics, warnings)
- PRIORITY ACTIONS: What to do before leaving for the event,
  in order of importance
- EMAIL TRIAGE: Quick count (urgent/action/FYI) with one-line 
  summaries of anything urgent
- OPEN TASKS: Status of today's tasks

YOUR MOST IMPORTANT JOB: Find connections ACROSS data sources.
- Which emails relate to people they'll see tonight?
- Which tasks should be done before the event?
- What conversations might come up organically at dinner?
- What landmines should they avoid? (legal issues, pending items)

Be concise. Think like a chief of staff who knows the exec's 
full context and cares about their success tonight.
```

The result should show the cross-references clearly:
- Sarah emailed about Q4 numbers + she's on tonight's guest list = "She might bring it up at dinner — reply before the event"
- Legal flagged Contoso NDA + David Park is at your table tonight = "Do NOT discuss partnership terms with David until NDA is resolved"
- James Liu emailed about AI governance + he's at your table + Alex sent the governance deck = "Be ready to discuss casually — skim the deck during prep window"
- David Park's EA mentioned "deeper strategic alignment" + legal NDA flag = "M&A signal, but legal says hold — just build the relationship tonight"
- Driver at 4:15 + dry run at 3:00 + prep window at 2:00 = "Tight afternoon — prioritize the three must-do items before 2 PM"

### 4. Additional Quick Prompt Buttons

**"📧 Triage Inbox":**
- Reads all emails
- Sorts into 🔴 Urgent / 🟡 Action Needed / 🟢 FYI
- For each urgent/action item: one-line summary + recommended action

**"📋 Prep for Next Meeting":**
- Reads calendar, finds the next upcoming meeting
- Searches emails and tasks related to that meeting/attendees
- Generates a prep brief for just that one meeting

### 5. UI/UX Requirements

- Match the existing dark gradient + blue accent visual language
- The My Day tab should feel like a **dashboard**, not a chat
- Data cards at the top should show numbers before AI runs (just from file counts)
- "Brief Me" button should be prominent — large, centered, gradient blue
- Results stream in with the same tool execution log the Agent tab uses
- Show each tool call inline so execs can see the AI "working"

**Two-Layer Briefing Display:**
- **Layer 1 — Executive Summary**: Rendered at the top in a card with slightly larger text and a warm background. This is the conversational narrative ("Good morning. Here's your Saturday..."). Should feel like reading a note from your chief of staff. No bullet points — flowing prose, 8-10 sentences.
- **Layer 2 — Detailed Breakdown**: Below the summary, in collapsible/expandable sections:
  - 📅 TIMELINE — today's schedule with AI annotations on each event
  - 👤 PEOPLE TO KNOW — key attendees with context, warnings, talking points
  - ⚡ PRIORITY ACTIONS — numbered list of what to handle before the event
  - 📧 EMAIL TRIAGE — counts + one-line summaries of urgent items
  - ☐ TASKS — status of today's tasks

- After the AI briefing renders, show the 🔒 privacy badge and ⏱️ timing
- The briefing result should be clean and readable — not raw text dump
- Consider using cards or sections with light borders for each breakdown section
- Each section in Layer 2 should be collapsible (expanded by default on first load)

### 6. Tab Order

Reorder tabs to:
1. **My Day** (default, opens on launch)
2. AI Agent (chat with tools)
3. Documents
4. ID Verification

### 7. Don't Break Existing Functionality

- All existing tabs (AI Agent chat, Document Analysis, ID Verification) stay as-is
- Same Flask app, same `python npu_demo_flask.py` launch command
- Same Foundry Local connection (localhost:5272, phi-silica model)
- Reuse existing tool execution infrastructure (read, write, exec, parse_tool_call, execute_tool)

### 8. The Demo Script

The presenter will:
1. Open the app → "My Day" tab is showing with cards: "15 emails | 10 events | 7 tasks"
2. Say: "Let me show you what a chief of staff looks like — running on the NPU"
3. Click "Brief Me"
4. Audience watches tool calls stream in (reading calendar, emails, tasks)
5. AI briefing appears — FIRST as a warm narrative summary of the day ("Good morning. You're heading to the Super Bowl exec event tonight..."), THEN as a detailed breakdown with timeline, people to know, priority actions
6. The audience realizes: **the AI is briefing about THIS event, THESE people, THIS evening**
7. Killer line: "My calendar, my email, my tasks — all confidential. The AI connected them in 30 seconds. None of it left the device. That's your chief of staff — running on the NPU."

**Why the Saturday scenario is the right choice:** You're demoing this AT the event the AI is briefing about. The people in the room are the people in the briefing. That collapses the distance between "cool demo" and "I need this."

### 9. Stretch Goals (Only If Time)

- **"✏️ Draft Replies"** button — AI drafts responses to urgent emails (Sarah's Q4 request, Jessica's NDA flag), saves as .eml drafts locally
- **"👤 Who's at My Table?"** button — AI reads guest list and generates conversation starter notes for each person at your table
- Click on an individual email in the triage list to see full content + AI summary
- A "What did I miss?" button that focuses on overnight emails only
- **Real Outlook integration talking point**: If an exec asks "could this read my actual Outlook?", the answer is yes — Outlook can export .ics and .eml natively, and the Windows Mail app stores data locally. The demo uses pre-staged files, but the architecture is the same. The path from demo to product is: access the local Outlook data store directly.

## Key Constraints

- Phi Silica has a ~4K context window. The compact prompt + all the data needs to fit. Strategy: Parse .ics and .csv files in Python first, extract just the key fields into a compact text summary. For calendar: extract SUMMARY, DTSTART, LOCATION, ATTENDEES, and DESCRIPTION (agenda items, pre-reads, warnings). For tasks: extract Task, Priority, Notes. Don't send raw .ics markup to the model — pre-process it into clean structured text. For emails: read urgent/action ones fully, summarize FYI emails from subject lines only.
- The .ics DESCRIPTION fields are the intelligence goldmine but can be verbose. Pre-process them to extract just agenda items, pre-reads, action items, and warnings before sending to the model.
- The .csv tasks file is simple to parse with Python's built-in `csv` module. No external dependencies needed.
- Tool calls take ~12 seconds each. The "Brief Me" flow will make several tool calls — show progress so it doesn't feel stuck. Consider batching: read calendar + tasks in one step (they're small files), then read emails.
- For .ics parsing: prefer simple Python string/regex parsing over the `icalendar` pip package. Less dependency, more reliable for a demo. The iCalendar format is plain text and highly structured — `BEGIN:VEVENT` / `END:VEVENT` blocks with `KEY:VALUE` lines.
- This is a LIVE DEMO for CEOs. Reliability > features. Test the happy path thoroughly.
- No network required. Everything reads from local files.

## Start Building

Read the existing npu_demo_flask.py first, understand the current structure, then implement. Create the demo data files first so you can test as you build.
