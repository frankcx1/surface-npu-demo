# Blog Draft: Vibe Coding for the NPU — Building On-Device AI Apps on Copilot+ PCs

**Target publication:** Microsoft Surface IT Pro Blog
**Audience:** IT Pros, 200-300 level technical
**Tone:** Practitioner-to-practitioner, "here's how I actually built this"
**Status:** Raw brain dump — refine voice/structure in editing pass

---

## The Hook

What if you could build a fully functional AI application — one that does speech-to-text, vision classification, document analysis, report generation, and translation — that runs entirely on-device, never touches the cloud, and draws about 5 watts from the NPU? And what if you could build it by describing what you wanted to an AI coding assistant, without writing most of the code by hand?

That's what vibe coding for the NPU looks like in 2026. This post walks through the platform, the tools, the gotchas, and the actual process of building a 10,000-line demo app on Surface Copilot+ PCs — from first experiment to MWC Barcelona demo stage.

---

## What Is Vibe Coding?

Vibe coding is building software by describing intent to an AI coding assistant and iterating on the output. You're the architect and QA engineer. The AI writes the implementation. You test, give feedback, and steer.

The tools for this:
- **GitHub Copilot CLI** — Microsoft's AI coding assistant, integrates with VS Code and the terminal
- **Claude Code** — Anthropic's CLI tool, reads and edits your codebase directly from the terminal
- **OpenAI Codex / ChatGPT with code interpreter** — conversational coding with file handling
- **Cursor, Windsurf, etc.** — IDE-integrated AI coding environments

The common pattern: you describe a feature, the assistant writes code, you run it, you report back what worked and what didn't, the assistant fixes it. Repeat. The AI handles the boilerplate, the API lookups, the CSS layout math, the regex. You handle the architecture decisions, the "does this actually work on the hardware" testing, and the product taste.

For NPU development specifically, vibe coding is powerful because the AI assistants know the OpenAI SDK patterns cold — and Foundry Local speaks OpenAI-compatible API. So you describe what you want, the assistant writes standard OpenAI SDK code, and it just works against the local NPU runtime without modification.

---

## The Origin Story

This project started in the VS Code AI Toolkit. I opened the extension, browsed the Model Catalog, found Phi Silica, loaded it in the Playground, and typed a message. It responded. On-device. No API key. No cloud endpoint. Just the NPU.

The immediate thought: if you can chat with an AI model through a local interface, you can build a full application around it — the same way LM Studio exposes models via a local port. Foundry Local does exactly this: it serves models on a localhost port with an OpenAI-compatible API. So any code that works with the OpenAI SDK works with Foundry Local. You just change the `base_url`.

The first version was built through copy-paste iteration: write code in Claude on the web, download it, test on the Surface, paste error messages back, iterate. Eventually moved to Claude Code (Anthropic's CLI tool), which could read and edit the codebase directly on the device. That's when things accelerated — from a simple chat interface to five full tabs with tool-calling, governed AI agents, vision classification, pen annotation, and a complete field inspection workflow.

10,000 lines of Python/HTML/CSS/JS later, built primarily through conversation with an AI coding assistant, running entirely on-device.

---

## Platform Requirements

### Hardware: What You Need

Any **Copilot+ PC** with an NPU. The two silicon families:

| Silicon | NPU | Example Devices |
|---------|-----|----------------|
| **Intel Core Ultra** (Lunar Lake) | Intel AI Boost NPU, OpenVINO runtime | Surface Laptop 7 (Intel), Surface Pro 11 (Intel) |
| **Qualcomm Snapdragon X** (Elite/Plus) | Hexagon NPU, QNN runtime | Surface Laptop 7 (ARM), Surface Pro 11 (ARM) |

The app auto-detects silicon at startup and selects the right model:
- **Intel:** Phi-4 Mini 3.8B (OpenVINO NPU variant)
- **Qualcomm:** Qwen 2.5 7B (QNN NPU variant)

Why different models? Phi-4 Mini's QNN variant was unstable on Snapdragon at time of development. Qwen 2.5 7B ran reliably. Foundry Local's model catalog handles this — you pick an alias, it pulls the right hardware-optimized variant.

### Software Stack

| Component | What It Is | Install |
|-----------|-----------|---------|
| **Windows 11 24H2+** | OS with NPU driver support and Windows AI APIs | Windows Update |
| **Foundry Local** | Microsoft's local AI runtime — serves models on localhost with OpenAI-compatible API | `winget install Microsoft.FoundryLocal` |
| **Python 3.10+** | App runtime | `winget install Python.Python.3.11` |
| **foundry-local-sdk** | Python SDK for Foundry Local (manages runtime, model download, endpoint discovery) | `pip install foundry-local-sdk` |
| **OpenAI Python SDK** | Standard client library — same one you'd use for GPT-4, pointed at localhost instead | `pip install openai` |
| **Flask** | Web framework (or whatever you prefer — Django, FastAPI, etc.) | `pip install flask` |

**Important:** The pip package `foundry-local` (v0.0.1) is a **squatted fake**. The real SDK is `foundry-local-sdk`. This tripped us up early. If your import fails with a cryptic error, check the package name.

### For Phi Silica Vision (Optional, Advanced)

If you want to access Phi Silica's vision capabilities (image classification, description), you need additional infrastructure:

| Component | Why |
|-----------|-----|
| **Windows App SDK 1.8** | Provides the `Microsoft.Windows.AI.Imaging` namespace |
| **MSIX-packaged app** | Phi Silica APIs require `systemAIModels` restricted capability, only available to packaged apps |
| **LAF token** | Limited Access Feature token from Microsoft, tied to your app's Package Family Name |
| **VS Code AI Toolkit** | Used once to provision (download) the Phi Silica model on-device |

More on this in the Phi Silica section below.

---

## Getting Started: Your First NPU App in 15 Minutes

Here's the minimal path from zero to "AI running on my NPU":

### 1. Install the Runtime

```powershell
winget install Microsoft.FoundryLocal
pip install foundry-local-sdk openai flask
```

### 2. Write the App

This is where the vibe coding starts. Open your AI coding assistant and tell it:

> "Build me a Flask app that serves a chat interface on localhost:5000. The backend should use the OpenAI Python SDK pointed at a local Foundry Local runtime. Use the foundry-local-sdk to initialize the runtime and get the endpoint URL. The model alias is 'phi-4-mini'. Make it a single-file app with the HTML inline."

The AI assistant will generate something close to this:

```python
from flask import Flask, request, jsonify
from openai import OpenAI
from foundry_local import FoundryLocalManager

# Start Foundry Local and get the endpoint
manager = FoundryLocalManager("phi-4-mini")
client = OpenAI(base_url=manager.endpoint, api_key=manager.api_key)
model_id = manager.get_model_info("phi-4-mini").id

app = Flask(__name__)

@app.route("/chat", methods=["POST"])
def chat():
    user_msg = request.json["message"]
    response = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_msg}
        ],
        max_tokens=512
    )
    return jsonify({"reply": response.choices[0].message.content})
```

That's it. Standard OpenAI SDK, pointed at localhost. The model runs on the NPU at ~5W. No API key, no cloud, no egress.

### 3. Run It

```powershell
python app.py
# First run downloads the model (~3 GB), subsequent starts are instant
# Open http://localhost:5000
```

### 4. Iterate with the AI Assistant

Now you have a working base. Start describing features:

> "Add a sidebar with tabs. First tab is the chat. Second tab should read .eml files from a folder and have the AI summarize my inbox."

> "Add a camera capture button that uses getUserMedia. Send the captured photo to the backend for analysis."

> "The model keeps hanging on the second API call in my agent loop. Can you make dedicated single-step endpoints instead?"

This is the vibe coding loop: describe, generate, test, feedback. The AI assistant handles the Flask routes, the JavaScript, the CSS layout. You handle the testing on actual hardware and the "this doesn't work on the NPU" feedback.

---

## Cross-Platform Gotchas (Intel vs. Qualcomm)

Building for both silicon families surfaces real differences. Things we learned:

### Architecture Detection Is Unreliable

On Windows-on-ARM, Python x64 runs under emulation. `platform.machine()` reports `AMD64`. `PROCESSOR_ARCHITECTURE` reports `X64`. Both are wrong.

**The fix:** Use WMI to get the actual CPU name:

```python
result = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "(Get-CimInstance Win32_Processor).Name"],
    capture_output=True, text=True, timeout=5,
)
cpu = result.stdout.strip().lower()
if "qualcomm" in cpu or "snapdragon" in cpu:
    return "qualcomm"
```

This is the only reliable method. Any app that needs to behave differently per silicon should use this pattern.

### Model Compatibility Varies

Not every model variant works on every NPU. At time of writing:
- Phi-4 Mini: stable on Intel (OpenVINO NPU), QNN variant crashes on Snapdragon
- Phi-3.5 Mini: QNN variant also unstable on Snapdragon
- Qwen 2.5 7B: stable on Snapdragon (QNN NPU)
- Both work on GPU fallback across platforms

Foundry Local's model catalog handles the hardware-specific variants. You request `phi-4-mini` or `qwen2.5-7b` by alias; Foundry pulls the right optimized build (OpenVINO for Intel, QNN for Qualcomm).

### Lifecycle Differences

Intel and Qualcomm NPU runtimes behave differently under load:

- **Intel:** Model warmup on launch works well, keepalive pings every 3 minutes prevent cold starts. Standard retry logic.
- **Qualcomm:** Warmup and keepalive pings destabilize the QNN runtime. Skip them. Let the first real request trigger model load. Use aggressive auto-reconnect instead (the Foundry port can change if the service restarts).

```python
if SILICON == "qualcomm":
    # Skip warmup — QNN is unstable with rapid reconnection attempts
    print("Skipping warmup on Qualcomm (first request will load model)...")
else:
    # Intel: warmup + keepalive for consistent latency
    warmup_model()
    start_keepalive_thread(interval=180)
```

### NPU to GPU Fallback

Some Intel devices (specific Lunar Lake driver versions) fail NPU inference but work fine on GPU. Build a fallback chain:

```python
try:
    manager = FoundryLocalManager("phi-4-mini")  # NPU first
except Exception:
    try:
        from foundry_local.api import DeviceType
        manager = FoundryLocalManager("phi-4-mini", device=DeviceType.GPU)  # GPU fallback
    except Exception:
        client = OpenAI(base_url="http://localhost:5272/v1", api_key="not-needed")  # Manual
```

---

## The Token Budget Reality

Small Language Models on NPUs have real constraints. Phi-4 Mini has ~4K context window. That means:

- **Input + output combined** must stay under ~4K tokens
- A "Brief Me" query that cross-references calendar + emails + tasks uses ~1,884 tokens
- Marketing document review: ~1,300 tokens (Intel), ~2,850 tokens on Qualcomm (larger model = more headroom)
- You must actively manage context: compress data payloads, strip base64 from photos before report generation, keep system prompts lean

**Design implication:** Don't build chatbots that accumulate conversation history. Build single-shot endpoints that do one thing well. Our app learned this the hard way — the model hangs when you ask it to make a tool-calling decision AND generate a follow-up summary in the same context. Solution: dedicated single-step endpoints that bypass the agent loop.

---

## Phi Silica: On-Device Vision (The Hard Part)

Phi Silica is Microsoft's on-device multimodal model, accessed through the Windows App SDK. It can describe images, classify objects, and extract text — all on the NPU. Getting access to it is the most involved part of the stack.

### Why It's Harder Than Foundry Local

Foundry Local gives you an OpenAI-compatible REST API. Standard SDK, standard patterns.

Phi Silica is a **Windows API**. It requires:

1. **MSIX packaging** — your app must be a packaged Windows app to declare the `systemAIModels` restricted capability
2. **A LAF (Limited Access Feature) token** — a cryptographic attestation from Microsoft that authorizes your specific app (by Package Family Name) to use the API
3. **Model provisioning** — the Phi Silica model must be downloaded to the device before any app can use it

### The Practical Solution: A Sidecar Microservice

We built a small C# ASP.NET Core service, MSIX-packaged, that wraps Phi Silica behind REST endpoints:

```
Flask app (localhost:5000)  →  Vision Service (localhost:5100)  →  Phi Silica on NPU
                                     ↑
                              MSIX packaged
                              systemAIModels capability
                              LAF token
```

The Vision Service exposes `/health`, `/classify`, `/describe`, and `/extract-text`. The Flask app calls these like any HTTP API. The MSIX packaging, LAF token, and Windows App SDK complexity are encapsulated in the sidecar.

### Provisioning Phi Silica

Before any app can use Phi Silica, the model must be provisioned on-device. The most reliable method we found:

1. Install VS Code with the AI Toolkit extension
2. Open Model Catalog → find Phi Silica → open in Playground
3. Send a test message and get a response

This triggers `EnsureReadyAsync()` under the hood, which downloads and registers the model. After this, any packaged app calling `ImageDescriptionGenerator.GetReadyState()` will find it available. You only need to do this once per device.

### The LAF Token

The Limited Access Feature token is the gatekeeper. Key things IT Pros should know:

- The token is tied to a **Package Family Name (PFN)** — change your signing certificate and the PFN changes and the token is invalid
- Microsoft issues tokens per-app — you request one for your specific PFN
- On **Windows Insider dev channel**, Phi Silica may work without a valid token (useful for development)
- On **retail Windows builds**, the token is required

```csharp
// In your packaged app's initialization:
var access = Windows.ApplicationModel.LimitedAccessFeatures
    .TryUnlockFeature(
        "com.microsoft.windows.ai.languagemodel",  // Feature ID
        "YOUR_TOKEN_HERE",                            // Issued by Microsoft
        "your_pfn has registered their use of...");   // Attestation string
```

---

## The Three-Tier Fallback Pattern

The single most important architecture pattern for NPU apps: **never let the demo fail.**

Every AI operation in the app has three tiers:

1. **Preferred path** — the full AI pipeline (Phi Silica vision, Phi-4 Mini text, etc.)
2. **Fallback path** — a simpler AI approach (text model instead of vision model, filename hints instead of actual image analysis)
3. **Hardcoded safe default** — pre-baked response that's always correct for demo scenarios

```
Photo Classification:
  Tier 1: Phi Silica Vision (real image analysis)     → preferred
  Tier 2: Phi-4 Mini with filename hints (text only)  → degraded but functional
  Tier 3: Hardcoded classification per demo photo      → always works
```

This isn't cheating — it's production resilience. NPU drivers update. Models get redeployed. Services crash. The LAF token might not be accepted. For a live demo at a trade show, the hardcoded fallback is the difference between "let me restart" and a smooth walkthrough.

---

## What We Built: 10K Lines, 7 AI Tasks, Zero Cloud

The final app runs seven distinct on-device AI tasks across five tabs:

| Capability | AI System | NPU Power |
|-----------|-----------|-----------|
| Speech-to-text (Fluid Dictation) | Windows system service | ~5W |
| Structured field extraction from voice | Phi-4 Mini via Foundry Local | ~5W |
| Photo classification | Phi Silica via Vision Service | ~5W |
| Pen annotation + handwriting extraction | Phi Silica + Phi-4 Mini pipeline | ~5W |
| Inspection report generation | Phi-4 Mini via Foundry Local | ~5W |
| Report translation (English → Spanish) | Phi-4 Mini via Foundry Local | ~5W |
| Escalation routing decision | Local logic (no model needed) | ~0W |

**Closing dashboard:** 7 local AI tasks, 0 cloud tasks, ~520 tokens consumed, $0.00 cost, 0 bytes transmitted.

The entire app — with all five tabs, all demo data, the Vision Service MSIX, and the setup script — fits in a GitHub repo that you can clone, run one script, and have working on any Copilot+ PC.

---

## Lessons Learned

### For IT Pros Evaluating On-Device AI

1. **The NPU is real and it works.** 5W sustained for inference that would cost $0.01-0.10 per call in the cloud. For repetitive, high-volume, privacy-sensitive workloads, the economics are compelling.

2. **Model constraints are real too.** ~4K context window means you're building focused, single-task endpoints — not general-purpose chatbots. Design around the constraint.

3. **Cross-platform isn't free.** Intel and Qualcomm NPUs behave differently. Test on both. Use WMI for detection. Build fallback chains.

4. **Phi Silica access has ceremony.** MSIX packaging, LAF tokens, model provisioning. Worth it for vision capabilities, but plan for the setup overhead.

5. **Airplane mode is the killer demo.** Turn off Wi-Fi, run the app, watch the room react. Zero cloud dependency is the strongest proof point.

### For Vibe Coders Building NPU Apps

1. **Start with Foundry Local + OpenAI SDK.** It's the fastest path. Standard patterns, huge knowledge base in AI assistants.

2. **Use an AI coding assistant from the start.** The boilerplate-to-logic ratio in web apps is high. Let the AI handle Flask routes, HTML layout, CSS grid, JavaScript event handlers. Focus your energy on the NPU-specific behavior.

3. **Test on hardware early.** The gap between "works in theory" and "works on the NPU" is where the real debugging lives. Model hangs, context overflows, driver quirks — you only find these on the actual device.

4. **Build single-step endpoints.** Don't try to chain multiple model calls in one request. Small models get confused. One call, one job, one response.

5. **Hardcode fallbacks for everything.** Not optional. Not lazy. Professional.

---

## Getting Started Today

```powershell
# 1. Install the runtime
winget install Microsoft.FoundryLocal

# 2. Install Python deps
pip install foundry-local-sdk openai flask

# 3. Clone the demo to see a working example
git clone https://github.com/frankcx1/surface-npu-demo.git
cd surface-npu-demo
.\setup.ps1

# 4. Run it
python npu_demo_flask.py
# Open http://localhost:5000

# 5. Or start from scratch with an AI coding assistant:
# "Build me a Flask app that uses Foundry Local to serve
#  Phi-4 Mini on the NPU with an OpenAI-compatible API..."
```

The NPU is a new compute target. Vibe coding is a new development workflow. Together they lower the bar dramatically: describe what you want, test on the hardware, iterate. The 10,000-line app in this repo was built primarily through conversation with an AI assistant, by someone who hadn't used a CLI in years.

The NPU is ready. The tools are ready. Start building.

---

*Built on Surface Copilot+ PCs with Claude Code. Repo: https://github.com/frankcx1/surface-npu-demo*
