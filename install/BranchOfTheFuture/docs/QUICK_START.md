# Quick Start Guide — Surface NPU Demo

No coding experience needed. This guide walks you through installing and running the demo on any Copilot+ PC.

---

## What You Need

- A **Copilot+ PC** running **Windows 11** (Surface Pro, Surface Laptop, or any device with an Intel Core Ultra or Snapdragon X processor)
- **Windows 11 24H2 or newer** (check: Settings > System > About)
- **Internet connection** for the initial setup (the demo itself runs fully offline after that)

---

## Setup (One Time)

### Step 1: Download the Project

1. Go to **https://github.com/frankcx1/surface-npu-demo**
2. Click the green **Code** button, then click **Download ZIP**
3. Extract the ZIP to a folder you can find easily (e.g., `C:\NPU-Demo`)

### Step 2: Allow PowerShell Scripts

Windows blocks scripts by default on new devices. Open **PowerShell** and run:

```
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Type **Y** when prompted. You only need to do this once.

### Step 3: Run the Setup Script

1. Open the folder where you extracted the project
2. Find the file called **`setup.ps1`**
3. Right-click it and select **Run with PowerShell**
   - If Windows asks for permission, click **Yes** or **Run anyway**
4. The script will automatically install everything:
   - Python (the programming language the app runs on)
   - Foundry Local (Microsoft's local AI runtime)
   - The AI model (Phi-4 Mini, ~3 GB download on first run)
   - All required libraries
   - The Vision Service for photo analysis (Field Inspection tab)

Let the script finish. It will print a green **Setup Complete** message when done.

### Step 4: Provision Phi Silica (For Vision Features)

This step makes the on-device vision AI model available. You only need to do it once per device.

1. Install **VS Code** from https://code.visualstudio.com (free)
2. Open VS Code, click the **Extensions** icon on the left sidebar (looks like four squares)
3. Search for **AI Toolkit** and install it
4. Click the **AI Toolkit** icon that appears in the left sidebar
5. Go to **Model Catalog**, find **Phi Silica**
6. Click **Playground**, type anything in the chat box (e.g., "hello"), and hit Enter
7. Wait for a response — this confirms the model is downloaded and working
8. You can close VS Code. You won't need it again.

---

## Running the Demo

### Start the App

1. Open the project folder
2. Double-click **`run.bat`**
   - A black terminal window will appear — this is normal
   - Wait until you see: **`Open http://localhost:5000 in your browser`**
3. Open your web browser (Edge, Chrome) and go to **http://localhost:5000**

### Start the Vision Service (For Field Inspection Photos)

This is only needed if you want to use real photo classification in the Field Inspection tab:

1. Open PowerShell
2. Run: `powershell -File "C:\NPU-Demo\vision-service\scripts\launch-vision.ps1"`
   - (Replace `C:\NPU-Demo` with wherever you extracted the project)

### Stop the App

Close the black terminal window, or press **Ctrl+C** in it.

---

## Using the Demo

The app has five tabs in the left sidebar:

| Tab | What It Does |
|-----|-------------|
| **AI Agent** | Chat with the AI, run governed tools (file read/write, system commands) with approval gates |
| **My Day** | Get an executive morning briefing from calendar, email, and task data |
| **Auditor** | Analyze contracts for risk or review marketing materials for compliance |
| **ID Verification** | Scan a driver's license using the camera — OCR + AI, fully offline |
| **Field Inspection** | Full inspection workflow: voice capture, photo classification, pen annotation, report generation |

### The "Airplane Mode" Moment

The most impactful demo move:
1. Show any feature working normally
2. **Turn on Airplane Mode** (click the Wi-Fi icon in the taskbar, toggle Airplane Mode on)
3. Run the same feature again
4. **It still works** — the AI never needed the cloud

### Field Inspection Demo (The Full Workflow)

1. Click **Field Inspection** in the sidebar
2. Click **Use Scripted Input** (fills in a sample voice transcript)
3. Click **Extract Fields** — watch the form fill itself from the transcript
4. Click **Demo Photo** to cycle through sample inspection photos
5. Watch the AI classify each photo with category, severity, and confidence
6. Click **Generate Report** — the AI writes a full inspection report
7. Click **Translate to Spanish** — instant translation, still no cloud
8. If a photo has 60-74% confidence, you'll see the **escalation dialog** — choose "Keep Local"
9. Click **Show Summary** to see the dashboard: 7 local AI tasks, 0 cloud tasks, $0.00 cost

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `setup.ps1` won't run | Right-click > Run with PowerShell. If blocked, run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` in an admin PowerShell first |
| "Python not found" | Reboot after running setup.ps1, then try again — Python needs a PATH refresh |
| App says "Connection refused" | The AI model is still loading. Wait 15-30 seconds and refresh the browser |
| First run is very slow | Normal — the model (~3 GB) downloads on first launch. After that it starts in seconds |
| Vision Service won't start | First launch takes 30-60s to initialize Phi Silica -- use `vision-service\scripts\launch-vision.ps1` which polls and reports when ready. If `/health` returns `phi_silica_available: false` after startup, Phi Silica isn't on this build (rare on 24H2 26100+). Developer Mode must be on: Settings > For developers > toggle on |
| Field Inspection photos say "text_model_fallback" | The Vision Service isn't running. Launch it (see "Start the Vision Service" above) |
| Camera doesn't work | Allow camera permission in the browser. Try a different camera from the dropdown |
| Everything works but you want to demo offline | Good — turn on Airplane Mode. The app is designed for this |

---

## If You Get Stuck

Copy and paste the following prompt into **Copilot**, **Claude**, **ChatGPT**, or any AI assistant:

> I'm trying to set up the Surface NPU Demo app on my Copilot+ PC. It's a Python Flask app that runs AI models locally on the device's NPU using Microsoft Foundry Local. The app has five tabs (AI Agent, My Day, Auditor, ID Verification, and Field Inspection). The project is from https://github.com/frankcx1/surface-npu-demo.
>
> Here's my issue: [DESCRIBE WHAT'S GOING WRONG]
>
> My device info:
> - Device: [e.g., Surface Laptop 7, Surface Pro 11]
> - Processor: [e.g., Intel Core Ultra 7 258V, Snapdragon X Elite]
> - Windows version: [e.g., Windows 11 24H2, build 26100]
>
> The setup involves:
> 1. Running setup.ps1 to install Python, Foundry Local, and dependencies
> 2. Running run.bat or "python npu_demo_flask.py" to start the app
> 3. Opening http://localhost:5000 in a browser
> 4. For vision features: provisioning Phi Silica via VS Code AI Toolkit, then launching the Vision Service MSIX (localhost:5100)
>
> Key technical details in case they help:
> - The AI model is Phi-4 Mini running on the NPU via Foundry Local
> - The Vision Service is a C# MSIX app wrapping Phi Silica (Windows App SDK 1.8)
> - The Vision Service needs a self-signed cert trusted on the machine and a LAF token
> - The real Foundry pip package is "foundry-local-sdk" (NOT "foundry-local" which is a fake)
>
> Can you help me troubleshoot this step by step?

---

## Updating the Demo

If a new version is available:

1. Go to **https://github.com/frankcx1/surface-npu-demo**
2. Download the ZIP again (or if you used `git clone`, run `git pull`)
3. Run `setup.ps1` again — it will skip anything already installed and only update what's needed
4. Run the app as usual with `run.bat`
