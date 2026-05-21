# Qualcomm Snapdragon X Plus - Test Results

**Date:** February 13, 2026
**Device:** Surface with Snapdragon X Plus (ARM64)
**Model:** qwen2.5-7b-instruct-qnn-npu:2
**Runtime:** Foundry Local (QNN NPU)
**Flask App:** npu_demo_flask.py (latest with all Qwen changes)

## Bug Fix: Learn More Buttons Triggering Tool Calls

**Problem:** Qwen 2.5 7B is more action-oriented than Phi — when Device Health
"Learn More" buttons sent security questions (e.g., SMB port risks) through the
agent chat, the model tried to run commands (`Get-ServiceName`, `Disable-NetAdapter`)
instead of answering from knowledge. These commands either don't exist or aren't
in the allowlist, causing visible errors.

**Root cause:** The Learn More buttons injected questions into the agent chat input
and called `sendMessage()`, which routes through `/chat` with full tool access.

**Fix:**
1. Added `/knowledge` endpoint — pure AI explanation, no tools, IT-expert system prompt
2. Updated Learn More button handlers to call `/knowledge` instead of `sendMessage()`
3. Added stronger guidance in agent system prompt for knowledge questions

**Verified:** Both SMB and firewall questions now produce clean, detailed explanations
(35-40s) with no tool call attempts.

## End-to-End Test Results - All Passing

### Tab 1: AI Agent
| Test | Endpoint | Result | Time |
|------|----------|--------|------|
| Basic chat | `POST /chat` ("What is 2+2?") | "2 + 2 is 4." | 3.9s |
| Tool calling | `POST /chat` ("List files in documents") | Correct `[TOOL_CALL]` JSON emitted | 5.4s |
| Doc summarization | `POST /summarize-doc` (NDA contract) | Detailed NDA summary with key ideas, decisions, action items | 46.5s |
| List documents | `POST /demo/list-documents` | Listed 1 file with AI description | 4.1s |

### Tab 2: My Day
| Test | Endpoint | Result | Time |
|------|----------|--------|------|
| Counts | `GET /my-day-counts` | Returns {emails:0, events:0, tasks:0} (no demo data) | instant |
| Brief Me | `POST /brief-me` | Full morning briefing generated (summary, actions, people, warnings) | 26.1s |

### Tab 3: Auditor (via Device Health)
| Test | Endpoint | Result | Time |
|------|----------|--------|------|
| Device Health | `POST /demo/device-health` | All 9 checks ran, AI analysis with ratings and findings | 35.1s |
| PII Detection | `POST /detect-pii` (NDA contract) | Found names, emails, addresses, phone numbers correctly | 36.0s |

### Tab 4: ID Verification
- Not API-testable (requires camera/image upload in browser)
- OCR is client-side (Tesseract.js), AI analysis uses same `foundry_chat()` path

### Infrastructure
| Test | Endpoint | Result |
|------|----------|--------|
| Health check | `GET /health` | model: qwen2.5-7b-instruct-qnn-npu:2, ready: True |
| Session stats | `GET /session-stats` | 7 calls, 6300 tokens, 143.4s inference |
| UI rendering | `GET /` | "Chat & Tooling with Qwen 2.5 7B" (MODEL_LABEL substituted correctly) |
| Security jail | `POST /detect-pii` (bad path) | "Security Policy: file outside approved folder." |

## Changes Made for Qualcomm Support

### npu_demo_flask.py
1. **Model selection** (line ~69): `qwen2.5-7b` on Qualcomm, `phi-4-mini` on Intel
2. **Auto-reconnect** (lines ~96-121): `foundry_chat()` wrapper + `_reconnect_foundry()` for port changes
3. **System prompt** (line ~312): "You are Phi" -> "You are a helpful AI assistant running locally"
4. **Sidebar UI** (line ~2108): "with Phi" -> "with {{MODEL_LABEL}}" (dynamically substituted)
5. **Token limits**: Silicon-conditional char limits:
   - `compress_for_briefing`: 3600 (Qualcomm) vs 1200 (Intel)
   - Document summarization: 8000 vs 2500
   - Contract analysis: 6000 vs 2000
6. **Warmup skip** (line ~6842): No warmup on Qualcomm (prevents QNN crash loop)
7. **Keepalive skip** (line ~6916): No keepalive on Qualcomm
8. All 18 `client.chat.completions.create()` calls replaced with `foundry_chat()`

### setup.ps1
- Qualcomm: `qwen2.5-7b` / "Qwen 2.5 7B"
- ARM64 fallback: Also uses `qwen2.5-7b` (was incorrectly defaulting to phi-4-mini)
- Intel: Unchanged (`phi-4-mini` / "Phi-4 Mini")

## NPU Model Compatibility Matrix (Snapdragon X Plus)

| Model | Variant | Status | Notes |
|-------|---------|--------|-------|
| phi-3-mini-4k | qnn-npu:2 | CRASH | Service dies on inference, connection error |
| phi-3.5-mini | qnn-npu | CRASH | Service dies on inference |
| phi-4-mini | generic-cpu:5 | WORKS (CPU) | No QNN NPU variant available |
| qwen2.5-1.5b | qnn-npu:2 | WORKS (NPU) | Fast but too small for complex tasks |
| qwen2.5-7b | qnn-npu:2 | WORKS (NPU) | Chosen for demo - reliable, good quality |
| deepseek-r1-7b | qnn-npu:1 | FAIL | QNN context load error (code 1011) |

## What to Test on Intel

Run the same endpoints on the Intel device to confirm nothing broke:
```
POST /chat {"message":"What is 2+2?"}
POST /chat {"message":"List the files in my documents folder"}
POST /brief-me {}
POST /demo/device-health {}
POST /detect-pii {"path":"C:/Users/{user}/Documents/Demo/contract_nda_vertex_pinnacle.txt"}
POST /summarize-doc {"path":"C:/Users/{user}/Documents/Demo/contract_nda_vertex_pinnacle.txt"}
POST /demo/list-documents {}
GET /health
GET /session-stats
GET / (check sidebar says "Chat & Tooling with Phi-4 Mini")
```

Also run the test suite:
```
python test_phase1.py
python test_phase2.py
```
