# Copilot+ PC NPU Demo Script
## Super Bowl Executive Marketing Event

**Setup**: OpenClaw TUI running on Surface with Phi Silica. WiFi OFF (airplane mode icon visible).

---

## Opening Hook (30 seconds)

> "See this? Airplane mode. No internet. What I'm about to show you runs entirely on this device's neural processor. Your data never leaves the machine."

---

## Demo Flow (3-4 minutes)

### Demo 1: Personal Productivity — Meeting Prep
**Say to the device:**
```
Create a file called C:\Users\frankbu\Documents\board_meeting_prep.txt with an agenda for tomorrow's board meeting covering Q4 results, 2026 strategy, and executive compensation
```

**What happens**: Phi Silica generates a professional agenda and writes it to disk locally.

**Exec hook**: *"I just created a board meeting agenda. Zero cloud. If you're a CEO, your comp discussions never touched a server."*

---

### Demo 2: File Intelligence — Read and Summarize
**Pre-stage**: Have a 1-page document ready (could be a sanitized earnings summary, strategy doc, or even a fake "confidential M&A memo")

**Say to the device:**
```
Read the file C:\Users\frankbu\Documents\strategy_2026.txt and give me the three key takeaways
```

**What happens**: Model reads file, synthesizes key points.

**Exec hook**: *"Imagine you're a healthcare exec with patient data, or GC reviewing a contract. This never leaves your laptop."*

---

### Demo 3: System Awareness — "What's on my machine?"
**Say to the device:**
```
List the files in C:\Users\frankbu\Documents
```

**What happens**: PowerShell `Get-ChildItem` runs, returns directory listing.

**Exec hook**: *"It has hands. It can see your files, run commands, actually do things — not just chat."*

---

### Demo 4: Quick Edit — Modify a Document
**Say to the device:**
```
Edit the file C:\Users\frankbu\Documents\board_meeting_prep.txt and add a section about AI governance
```

**What happens**: Model reads file, adds new section, saves.

**Exec hook**: *"That edit just happened locally on the NPU. 12 seconds, no API call, no cloud bill."*

---

### Demo 5: Conversational Intelligence (No Tools)
**Say to the device:**
```
What are three questions a board might ask about AI strategy?
```

**What happens**: Pure text response — demonstrates the model can think, not just execute.

**Exec hook**: *"This is a 3.8 billion parameter model running on a chip the size of your thumbnail."*

---

## Closing (30 seconds)

> "Everything you just saw — file creation, reading, editing, system commands, conversation — happened on-device. No cloud latency, no API costs, no data leaving the machine. That's what the NPU in a Copilot+ PC enables."

---

## Backup Demos (If Questions Come Up)

| If they ask about... | Demo this |
|---------------------|-----------|
| "What about code?" | `Create a Python script that calculates compound interest and save it to C:\Users\frankbu\Documents\interest.py` |
| "Can it search?" | `What date is it today?` (uses `Get-Date` internally) |
| "How fast?" | Time a file read with your phone stopwatch — ~12 seconds |
| "What's the catch?" | Be honest: 4 tools max, no multi-turn memory, 3.8B model limits. NPU models will improve. |

---

## Pre-Flight Checklist

- [ ] Airplane mode ON (visible in taskbar)
- [ ] OpenClaw TUI running: `npx openclaw tui --session superbowl-demo`
- [ ] Stage files in `C:\Users\frankbu\Documents`:
  - `strategy_2026.txt` (fake strategy doc, 1 page)
  - Delete any sensitive files from demo folder
- [ ] Test all 5 demos once before showtime
- [ ] Phone charged (for timing if asked)
- [ ] Backup: Have the `--local` one-liner ready if TUI crashes

```powershell
npx openclaw agent --local --session-id backup --message "YOUR PROMPT HERE" --json
```

---

## What NOT to Demo

❌ Multi-turn memory (stateless mode, won't remember context)  
❌ Complex reasoning chains (3.8B model limits)  
❌ Web browsing or external APIs (we're proving LOCAL value)  
❌ Anything requiring >4 tools in sequence  

---

## Objection Handling

**"Why not just use ChatGPT?"**
> "ChatGPT requires internet, sends your data to OpenAI servers, and costs per query. This is zero marginal cost, works offline, and your board comp discussions stay on your device."

**"Is this production ready?"**
> "The software pattern is proven — 8/8 tool reliability. The 3.8B model has limits today, but NPU-optimized models are improving fast. The point: when they arrive, the software is ready."

**"Can I get this?"**
> "Right now it's a developer preview. But any Copilot+ PC has the hardware. The software side is catching up."

---

## The Vision Slide (If You Get 2 Extra Minutes)

The real pitch isn't the demo. It's what comes next.

> "Everything I just showed you — reading files, creating documents, running commands, editing code — none of that requires a 200 billion parameter model in the cloud. What it requires is **tool calling**. The ability for a model to use hands, not just talk."

> "Today's 3.8B model on this NPU can do it with a prompt shim I wrote over the weekend. Imagine what happens when Microsoft — or Anthropic, or others — ship models **native** tool calling support, fine-tuned for agentic workflows."

> "The hardware is here. The NPU in every Copilot+ PC is ready. The runtime is proven — 8 out of 8 tool calls succeeded. The only bottleneck is model capability, and that's improving fast."

> "What you're looking at isn't a demo of what's possible today. It's proof that the **infrastructure is ready** for what's coming. When small local models catch up on tool calling, the agentic future doesn't require the cloud. Your sensitive data stays on your device. Your API bill goes to zero. And your AI actually does things instead of just chatting about them."

**The one-liner if you only get 10 seconds:**
> "The agent runtime is ready. The NPU hardware is ready. We're just waiting for the models to catch up on tool calling — and that's happening fast."
