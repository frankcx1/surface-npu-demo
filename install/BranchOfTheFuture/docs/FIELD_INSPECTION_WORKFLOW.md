# Field Inspection Copilot — On-Device AI Workflow

## Overview

The Field Inspection tab is a seven-milestone feature inside the NPU Demo Flask application that demonstrates a complete field inspection workflow — from voice capture through final report — running entirely on-device with zero cloud dependencies. Every AI task executes on the local NPU at ~5W sustained power draw. The feature was built for live demo at MWC Barcelona (March 2-5, 2026) on Intel Core Ultra (Lunar Lake) hardware.

The workspace is a four-panel CSS Grid layout: a form panel (left), photo/camera panel (center), findings log and report panel (right), and a status bar (bottom) tracking cumulative token usage and cost ($0.00 throughout).

Three on-device AI systems collaborate across the workflow:

| AI System | Type | Role |
|-----------|------|------|
| **Windows Fluid Dictation** | System service (Win+H) | Speech-to-text on NPU |
| **Phi-4 Mini** (3.8B params) | SLM via Foundry Local | Text: field extraction, report gen, translation |
| **Phi Silica** | On-device vision model | Image: classification, description, handwriting extraction |

---

## Step 1: Voice Capture via Fluid Dictation

**The problem:** An inspector arrives on-site and needs to log basic details — who they are, where they are, what was reported, and when. Typing on a tablet in the field is slow and awkward.

**The solution:** Windows Fluid Dictation (Win+H), a system-level voice typing service that runs on-device via the NPU. The app programmatically triggers it by sending a `Win+H` keystroke through PowerShell's `keybd_event` P/Invoke via the `/inspection/fluid-dictation` endpoint. This opens the Windows Voice Typing overlay, which transcribes speech directly into the app's textarea in real time — no microphone API wrangling, no audio blob uploads, no third-party speech model.

The inspector speaks naturally:

> *"Inspector Sarah Chen at Building C, second floor, north corridor. Date March 3rd, 2026 at 10:15 AM. Reported issue: water staining on ceiling tiles near the elevator bank. Source: property manager report from last Friday."*

The transcript populates in the textarea as they speak. When done, a "Scripted Input" fallback button is available for demo reliability — it pre-fills a canned transcript so the demo never stalls on ambient noise or mic issues.

**AI component:** Windows Fluid Dictation — system-level NPU-accelerated speech-to-text. No application code needed for the transcription itself; the app just opens and closes the system overlay.

---

## Step 2: Phi-4 Mini Field Extraction (Voice to Structured Form)

**The problem:** The transcript is free-form spoken text. The inspection form needs discrete structured fields.

**The solution:** The "Extract Fields" button sends the raw transcript to `POST /inspection/transcribe`, which passes it to **Phi-4 Mini** running on the NPU via Foundry Local. The system prompt constrains the model to a strict JSON schema:

```json
{
  "inspector_name": "Sarah Chen",
  "location": "Building C, 2nd Floor, North Corridor",
  "datetime": "2026-03-03T10:15:00",
  "reported_issue": "Water Staining",
  "source": "Property Manager Report"
}
```

The model parses natural language into structured data — "Building C, second floor, north corridor" becomes the `location` field, "March 3rd, 2026 at 10:15 AM" becomes an ISO datetime, etc.

On the frontend, the extracted fields animate into the form sequentially with a 200ms stagger — each field fading in one by one with a green highlight. This is the "it understood me" moment: the inspector spoke freely and the form filled itself without a single keystroke.

**AI component:** Phi-4 Mini on NPU via Foundry Local — constrained JSON extraction from natural language. ~300 tokens, 5-10 seconds.

---

## Step 3: Camera Capture + Photo Classification

**The problem:** The inspector needs to photograph the issue and get an immediate AI assessment of what they're looking at.

**The solution:** The center panel provides a live camera preview via `getUserMedia()` with front/rear camera toggle. The inspector captures a photo (or cycles through five demo preset photos for reliability: water damage, structural crack, mold, electrical hazard, trip hazard).

Classification follows a **three-tier fallback architecture**:

### Tier 1: Phi Silica Vision (Preferred Path)

The captured image is sent to `POST /inspection/classify`, which forwards it to a **custom C# microservice** running on `localhost:5100`. This service wraps **Phi Silica** — Microsoft's on-device vision model available through the Windows App SDK 1.8.

#### Why a Separate MSIX Service?

Phi Silica is a Windows API, not a standard REST model. Accessing it requires:

1. **A packaged MSIX application** with the `systemAIModels` restricted capability declared in its manifest. Unpackaged apps cannot access Phi Silica.

2. **A LAF (Limited Access Feature) token** — a cryptographic attestation issued by Microsoft that authorizes a specific Package Family Name (PFN) to use the `com.microsoft.windows.ai.languagemodel` feature. The token is tied to the app's PFN (`Microsoft.NPUDemo.VisionService_r0xr04974zwaa`) and must be unlocked at runtime via `Windows.ApplicationModel.LimitedAccessFeatures.TryUnlockFeature()`.

3. **Windows App SDK 1.8** with the `Microsoft.Windows.AI.Imaging` namespace, which provides `ImageDescriptionGenerator` — the API that sends images to the on-device Phi Silica model.

The vision service (C# ASP.NET Core 8.0) converts uploaded JPEG bytes into a `SoftwareBitmap`, wraps it in an `ImageBuffer.CreateForSoftwareBitmap()`, and calls `_generator.DescribeAsync()` with `DetailedDescription` kind. The raw description is then mapped to constrained inspection categories via a keyword-scoring algorithm — each category has a curated keyword list, and the highest-scoring category wins. Confidence is derived from match strength and severity maps from category + confidence (e.g., Electrical Hazard at >=70% confidence maps to Critical).

See [Vision Service Architecture](#vision-service-architecture) below for full technical details.

### Tier 2: Phi-4 Mini Text Fallback

If the Vision Service is unavailable (not running, LAF token issue, etc.), the Flask backend falls back to Phi-4 Mini with filename hints. The model receives textual context about the image and generates a classification from that. Less accurate than actual vision, but keeps the demo flowing.

### Tier 3: Hardcoded Demo Presets

If both AI paths fail, hardcoded classifications return immediately with realistic confidence values:

| Demo Photo | Category | Severity | Confidence |
|-----------|----------|----------|------------|
| water_damage | Water Damage | Moderate | 82% |
| structural_crack | Structural Crack | High | 72% |
| mold | Mold | High | 88% |
| electrical_hazard | Electrical Hazard | Critical | 91% |
| trip_hazard | Trip Hazard | Low | 85% |

**The result** is a classification card showing category (color-coded), severity badge (Low/Moderate/High/Critical), a confidence bar (green >=75%, amber 60-74%, red <60%), a one-line explanation, and the analysis source. The finding is stored for report generation. Confidence values in the amber zone (60-74%) trigger the escalation dialog in Step 7.

**AI components:** Phi Silica Vision on NPU (via MSIX + LAF token) with Phi-4 Mini text fallback. ~1.5 seconds for demo presets, variable for live classification.

---

## Step 4: Pen Annotation + Handwriting Extraction

**The problem:** The inspector wants to circle a problem area, draw an arrow, and scribble a note directly on the photo — the way they'd mark up a paper printout.

**The solution:** Tapping the annotate button on any photo thumbnail opens a full-screen lightbox with two stacked canvas layers: a base canvas (the photo) and a transparent ink canvas on top. The Pointer Events API captures pen, touch, and mouse input — including Surface Pen with pressure sensitivity. Strokes render in red (#ef4444) at 7px width for visibility. A toolbar provides Undo, Clear, Done, and Cancel actions.

When the inspector taps **Done**:

1. Both canvases are composited into a single JPEG (photo + ink overlay baked together)
2. The composite is sent to `POST /inspection/annotate`
3. **Tier 1 (Phi Silica):** The endpoint forwards the image to the Vision Service's `/describe` endpoint, which uses Phi Silica to generate a detailed description of the annotated photo. That description is then post-processed by Phi-4 Mini to extract any handwritten text mentions from the vision output.
4. **Tier 2 (Phi-4 Mini text):** If the Vision Service is down, Phi-4 Mini generates a plausible inspector note based on the finding context (e.g., "Moisture detected around window frame").
5. **Tier 3 (Hardcoded):** Fallback returns "Check pipe above - possible leak source."

The extracted text is stored in the finding's annotations, displayed as an "Inspector Note" in the findings log, and rendered as a blockquote in the final report. The thumbnail updates to show the annotated version with a red pen badge.

**AI components:** Phi Silica Vision (image description) + Phi-4 Mini (text extraction from description). Two-model pipeline for handwriting extraction.

---

## Step 5: Report Generation

**The problem:** All the data has been collected — voice transcript, structured fields, photo classifications, pen annotations. It needs to become a professional inspection report.

**The solution:** The "Generate Report" button (active once at least one finding exists) sends all collected data to `POST /inspection/report`. Photo base64 data is stripped to stay within the ~4K token context window.

**Phi-4 Mini** generates a complete HTML report with:
- **Header block** — inspector name, location, date, reported issue
- **Executive summary** — 2-3 sentence overview
- **Finding details** — each finding with severity badge, confidence, explanation, and inspector notes rendered as blockquotes
- **Overall risk rating** — Low / Moderate / High / Critical (derived from findings)
- **Recommended next steps** — 2-4 actionable bullets

The report renders in the right panel as a styled HTML document. A "Regenerate Report" button allows iteration. If the model fails, a hardcoded fallback generates a basic report from the raw findings data — the demo never dead-ends.

**AI component:** Phi-4 Mini on NPU — report synthesis from structured + unstructured inputs. Temperature 0.3 for consistency. ~500 tokens, 10-20 seconds.

---

## Step 6: Translation

**The problem:** Inspection teams work across language boundaries. A report generated in English needs to be immediately available in Spanish for local contractors or regulatory bodies.

**The solution:** After report generation, a "Translate to Spanish" button appears. Clicking it sends the report HTML to `POST /inspection/translate`, where **Phi-4 Mini** translates the complete document while preserving HTML structure, section organization, and professional construction/inspection terminology.

The UI plays a brief 500ms side-by-side animation (EN | ES split) before settling on the Spanish version. The button toggles to "Switch to English" for instant back-and-forth — no re-inference needed for the cached version. A status message confirms: "no cloud API call."

If translation fails, the original report is wrapped with a Spanish header: *"Traduccion automatica no disponible."*

**AI component:** Phi-4 Mini on NPU — document translation with structure preservation. ~450 tokens, 10-20 seconds.

---

## Step 7: Escalation Router + Dashboard Tally

### Escalation Decision

**The trigger:** Any finding with confidence between 60-74% (the amber zone) automatically triggers an escalation dialog. The structural crack demo photo at 72% confidence is purpose-built to demonstrate this.

A modal presents two side-by-side options:

| Escalate to Cloud | Keep Local (Recommended) |
|---|---|
| Send photo to a frontier vision model | Proceed with local classification |
| Payload: 1 photo (XXX KB) | Data leaving device: **None** |
| Withheld: transcript, annotations, report | Cost: **$0.00** |
| Requires connectivity | Flag for manual expert review |

**"Keep Local"** (the demo path): A lock animation plays, a banner confirms "Inspection completed locally," and the finding is flagged for on-site expert review. The "Show Summary" button appears.

**"Escalate to Cloud"**: In airplane mode (the demo scenario), this gracefully fails with "No connectivity - keeping data local" and falls back to the same local path. This is deliberate — it demonstrates offline resilience.

### Dashboard Tally

The final screen is a full-overlay summary showing every AI task completed during the inspection:

```
+----------------------------+----------------------------+
|   LOCAL AI TASKS           |   CLOUD TASKS              |
|   [check] Speech-to-text   |                            |
|   [check] Field extraction  |         0                  |
|   [check] Vision classif.  |                            |
|   [check] Pen annotation   |                            |
|   [check] Report generation|                            |
|   [check] Translation      |                            |
|   [check] Routing logic    |                            |
+----------------------------+----------------------------+
| Total tokens: ~520 | Cost: $0.00 | Data transmitted: 0B |
+------------------------------------------------------------+
```

This is the closing visual — photographable from 15 feet away at a trade show — that makes the point: seven distinct AI tasks, two different on-device models, zero cloud calls, zero cost, zero data egress.

---

## Vision Service Architecture

The Phi Silica Vision Service is a standalone C# ASP.NET Core 8.0 microservice, packaged as an MSIX and running on `localhost:5100`.

### Why MSIX Packaging Is Required

Phi Silica is accessed through the Windows App SDK's `Microsoft.Windows.AI.Imaging` namespace. This API has two hard requirements:

1. **`systemAIModels` capability** — declared in `Package.appxmanifest`. Only MSIX-packaged apps can declare restricted capabilities.
2. **LAF (Limited Access Feature) token** — a signed attestation from Microsoft granting a specific PFN access to `com.microsoft.windows.ai.languagemodel`. Without this, the API calls may fail on retail Windows builds (works without it on Windows Insider dev channel).

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Returns service status + Phi Silica availability |
| `/classify` | POST | Image classification for inspection findings |
| `/describe` | POST | General image description (used for annotation text extraction) |
| `/extract-text` | POST | Handwritten text extraction from annotated photos |

### Key Namespaces

```csharp
using Microsoft.Graphics.Imaging;           // ImageBuffer
using Microsoft.Windows.AI.Imaging;         // ImageDescriptionGenerator
using Microsoft.Windows.AI.ContentSafety;   // ContentFilterOptions
using Windows.Graphics.Imaging;             // SoftwareBitmap, BitmapDecoder
```

### Image Processing Pipeline

1. Raw bytes from POST upload -> `InMemoryRandomAccessStream`
2. `BitmapDecoder` decodes JPEG/PNG
3. Convert to `SoftwareBitmap` with `Bgra8` pixel format
4. Wrap in `ImageBuffer.CreateForSoftwareBitmap()`
5. `_generator.DescribeAsync(imageBuffer, descKind, contentFilterOptions)`
6. Map free-text description to constrained category via keyword scoring

### Classification Algorithm

The `MapToInspectionCategory()` method scores Phi Silica's free-text description against keyword lists for each category:

- **Water Damage:** water, moisture, leak, stain, discoloration, puddle, seepage
- **Structural Crack:** crack, fracture, settlement, foundation, wall, fissure
- **Mold:** mold, fungus, spore, mildew, growth, organic
- **Electrical Hazard:** wire, outlet, spark, panel, exposed, burn, voltage
- **Trip Hazard:** trip, uneven, raised, loose, threshold, floor, gap

The highest-scoring category wins. Confidence scales from match strength (score >=5 maps to 70-95%, score >=3 maps to 65-80%). Severity is derived from category + confidence.

### Build and Deploy

The MSIX is built, signed, and installed via `vision-service/scripts/rebuild-msix.ps1`:

1. `dotnet publish -c Release` with MSIX generation
2. Sign with self-signed cert `CN=FrankBu` (thumbprint: `D105059461CAEB607A40723E92CBDFB91917A570`)
3. Install Windows App Runtime 1.8 dependency
4. Install the signed MSIX package

The cert must be trusted on the target machine (imported to `Cert:\LocalMachine\TrustedPeople`) before the MSIX will install.

### Pre-Built Package

A pre-built MSIX is included in the repo at `vision-service/AppPackages/` for quick deployment to new devices without rebuilding from source. The `setup.ps1` script handles installation automatically.

---

## New Device Setup

To transfer the complete demo to a new Copilot+ PC, run the unified setup script:

```powershell
.\setup.ps1
```

This handles:
1. Python 3.11 installation (winget, auto-detects x64 vs ARM64)
2. Foundry Local installation (`winget install Microsoft.FoundryLocal`)
3. Python dependencies (Flask, OpenAI SDK, foundry-local-sdk)
4. Demo data verification
5. Foundry Local SDK validation
6. Model availability check (Phi-4 Mini ~3GB download on first run)
7. Vision Service certificate trust + MSIX installation

### Prerequisites for Vision Service

- **Windows 11** with Copilot+ PC features (NPU required)
- **Windows App SDK 1.8** runtime (installed automatically with MSIX)
- **Phi Silica** -- available out-of-box on 24H2 26100+; first launch takes 30-60s (see below)
- On retail Windows builds, the LAF token must match the MSIX signing certificate's PFN

### Phi Silica Startup Behavior

Phi Silica is a Windows-managed on-device model. On Copilot+ PCs running Windows 11 24H2 (build 26100+), it is typically available out of the box -- no manual provisioning needed.

**First launch takes 30-60s:** Vision Service initializes Phi Silica Vision and TextRewriter on cold start. Use the updated `launch-vision.ps1` which polls `/health` and reports when ready. Don't kill the process during this window -- it looks stuck but is working.

**If `/health` returns `phi_silica_available: false` after full startup:** Phi Silica genuinely isn't provisioned on this build. This is rare on retail Copilot+ PCs. To fix:

1. Check: Settings > Privacy & security > AI components > confirm Phi Silica is toggled on
2. If the toggle isn't there, install **VS Code** with the **AI Toolkit** extension, open Model Catalog, find **Phi Silica**, and send a test message in the Playground -- this triggers `EnsureReadyAsync()` to download and deploy the model
3. After provisioning, restart Vision Service

**Diagnostic log:** `C:\temp\vision-service-init.log` shows exact init state if you need to investigate.

### Known Constraints

| Constraint | Impact | Workaround |
|-----------|--------|------------|
| LAF token is PFN-locked | Different signing cert = different PFN = token invalid | Use provided cert, or works without token on Insider dev channel |
| Phi Silica model download | System-managed, not bundled | Available out-of-box on 24H2 26100+; first launch takes 30-60s; see "Phi Silica Startup Behavior" above |
| Self-signed cert trust | Requires admin on target machine | `setup.ps1` handles this with elevation prompt |

---

## Architecture Summary

| Layer | Technology | Role |
|-------|-----------|------|
| **Frontend** | Vanilla JS IIFEs, Canvas API, Pointer Events, getUserMedia | UI, camera, pen input |
| **Flask Backend** | Python on localhost:5000 | Orchestration, Phi-4 Mini inference via Foundry Local |
| **Foundry Local** | Microsoft runtime (dynamic port) | Hosts Phi-4 Mini on Intel NPU (~5W) |
| **Vision Service** | C# ASP.NET Core MSIX on localhost:5100 | Wraps Phi Silica via Windows App SDK 1.8 |
| **Phi-4 Mini** | 3.8B parameter SLM | Text: field extraction, report gen, translation |
| **Phi Silica** | On-device vision model (Windows AI) | Image: classification, description, text extraction |
| **Fluid Dictation** | Windows system service (Win+H) | Speech-to-text on NPU |

Every component runs on `127.0.0.1`. The three-tier fallback pattern (preferred AI path -> alternate AI path -> hardcoded safe default) ensures the demo never fails, even if individual services are unavailable. The entire workflow completes in airplane mode with zero network calls.

---

## How This Project Started

This project began with a simple observation: chatting with Phi Silica in the VS Code AI Toolkit playground and realizing that if you can talk to an on-device model through a local interface, you can build a full application around it — the same way LM Studio exposes models via a local port for any app to consume.

The question was: why not wrap Phi Silica access in a Flask app and see what's possible with a local-only AI stack?

The first iterations were built through back-and-forth with Claude on the web — write code, download it, test on the Surface, paste feedback, iterate. Eventually the workflow moved to Claude Code (Anthropic's CLI tool), which could read and edit the codebase directly. From there the project grew rapidly: a single-file Flask app expanding from a simple chat interface to five full tabs with tool-calling shims, governed AI agents, voice capture, camera integration, pen annotation, vision classification, report generation, and translation — all running on-device at ~5W on the NPU.

The Vision Service and its MSIX packaging came from needing to access Phi Silica's vision capabilities, which require a packaged app with a `systemAIModels` capability and a LAF (Limited Access Feature) token from Microsoft. Working through the Windows App SDK documentation, the MSIX signing requirements, and the LAF token attestation process was one of the more involved pieces of the build.

The result is ~10,000 lines of code in a single Flask file, a companion C# vision microservice, and a complete demo that runs seven distinct AI tasks with zero cloud calls, zero cost, and zero data leaving the device.
