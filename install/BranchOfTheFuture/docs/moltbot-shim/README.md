# Moltbot NPU: AI Agent on Copilot+ PC

Run [Moltbot/OpenClaw](https://openclaw.ai) entirely on-device using Microsoft Foundry
Local and the Copilot+ PC NPU. No cloud, no API keys, no cost per token.

> *"Moltbot is an open-source AI agent that runs your computer"* -- Scientific American

This project adds tool-calling support to Phi Silica, the NPU-native model that
ships with every Copilot+ PC but has no built-in tool-calling capability.

| | |
|---|---|
| **Model** | Phi Silica 3.8B (NPU) |
| **Latency** | ~12s per tool call |
| **Reliability** | 8/8 turns passing |
| **API cost** | $0 |
| **Network** | Not required |

## Requirements

- **Hardware:** Copilot+ PC with Intel Lunar Lake or Snapdragon X NPU
- **OS:** Windows 11 24H2+
- **Foundry Local:** Install via [AI Toolkit](https://marketplace.visualstudio.com/items?itemName=ms-windows-ai-studio.windows-ai-studio) for VS Code
- **Model:** `phi-silica` (auto-available on Copilot+ PCs)
- **OpenClaw:** v2026.1.30+ (`npm install -g openclaw`)

## Quick Start

### Option A: Use the branch (recommended)

Clone the patched fork and build from source:

```bash
git clone https://github.com/frankcx1/pi-mono.git
cd pi-mono
git checkout foundry-local-npu-support
npm install
npm run build
```

Then configure OpenClaw to use the built provider.

### Option B: Apply the JS patch

If you have OpenClaw already installed globally:

```bash
cd %APPDATA%\npm\node_modules\openclaw\node_modules\@mariozechner\pi-ai\dist\providers

# Back up the original
copy openai-completions.js openai-completions.js.orig

# Apply patch (from Git Bash or WSL)
patch -p1 < /path/to/openai-completions-foundry-local.patch
```

### Configure Foundry Local

Add to `~/.openclaw/openclaw.json`:

```json
{
  "models": {
    "providers": {
      "foundry-local": {
        "baseUrl": "http://localhost:5272/v1",
        "apiKey": "not-needed",
        "api": "openai-completions",
        "models": [{ "id": "phi-silica", "name": "Phi Silica (NPU)" }]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": { "primary": "foundry-local/phi-silica" }
    }
  }
}
```

### Start Foundry Local

Open VS Code with AI Toolkit, or start Foundry Local manually. Verify:

```bash
curl http://localhost:5272/v1/models
```

### Test

```bash
npx openclaw agent --local --session-id npu-test --json \
  --message "read C:\Users\%USERNAME%\.openclaw\workspace\HEARTBEAT.md"
```

## What Works

| Tool | Example | Status |
|---|---|---|
| `read` | "read HEARTBEAT.md" | Verified |
| `write` | "create a file /tmp/test.txt with content: hello" | Verified |
| `exec` | "run the command: powershell -c Get-Date" | Verified |
| `edit` | "edit file.txt and change X to Y" | Verified |
| Text response | "write a haiku about silicon" | Verified |

8/8 turns passing in stateless mode across all tool types.

## How It Works

Phi Silica has `supportsToolCalling: false` in Foundry Local -- the server strips
all `tools`, `tool_choice`, and `tool_calls` parameters. The `toolsViaPrompt` shim
works around this:

1. **Compact system prompt** (~1K chars) replaces OpenClaw's default prompt with
   tool definitions, RULES for disambiguation, and worked examples in `[TOOL_CALL]`
   format
2. **Stateless turns** -- only the current turn's messages are sent (no conversation
   history). A 3.8B model fixates on older context after ~3 turns. Stateless scored
   8/8 vs 2/8 with full history.
3. **Post-stream parser** buffers the model's text output, regex-extracts
   `[TOOL_CALL]...[/TOOL_CALL]` markers, converts to native tool call events
4. **Schema-based validation** strips hallucinated parameters (unknown keys, type
   mismatches) using the tool's actual JSON schema
5. **Bare-JSON fallback** catches tool calls when the model omits markers
6. **Format reinforcement** wraps assistant text responses in `[TOOL_CALL]` format
   in conversation history so the model sees consistent examples

## Limitations

- **No cross-turn memory.** Stateless mode means each turn is independent. Required
  for reliable tool calling with a 3.8B model.
- **4-tool cap.** Only read, write, edit, and exec are exposed. More tools degrade
  selection accuracy.
- **Semantic confusion.** The model may occasionally misinterpret ambiguous requests
  (e.g., "write a haiku" as a file write). Mitigated with disambiguation rules.
- **No parallel tool calls.** Single tool call per turn.
- **~12s latency.** Usable for demos, not for interactive coding.

## Links

- **PR:** [badlogic/pi-mono#compare](https://github.com/badlogic/pi-mono/compare/main...frankcx1:pi-mono:foundry-local-npu-support)
- **Branch:** [frankcx1/pi-mono:foundry-local-npu-support](https://github.com/frankcx1/pi-mono/tree/foundry-local-npu-support)
- **OpenClaw:** [openclaw.ai](https://openclaw.ai)
- **Foundry Local:** [AI Toolkit for VS Code](https://marketplace.visualstudio.com/items?itemName=ms-windows-ai-studio.windows-ai-studio)

## Files in This Repo

| File | Description |
|---|---|
| `README.md` | This file |
| `CHANGELOG.md` | Detailed patch documentation |
| `GITHUB_ISSUE.md` | Issue text for badlogic/pi-mono |
| `GITHUB_PR.md` | PR description |
| `LINKEDIN_POST.md` | LinkedIn post (business audience) |
| `REDDIT_POST.md` | Reddit post (r/LocalLLaMA, technical audience) |
| `openai-completions-foundry-local.patch` | JS patch file (549 lines) |
| `openclaw.json` | OpenClaw config for Foundry Local |

## Performance

| Approach | Turns Passing |
|---|---|
| Full history | 2/8 |
| 6-message sliding window | 6/8 |
| 6-msg + format reminder | 5/8 |
| **Stateless (current turn only)** | **8/8** |

## License

Patch code follows the license of the upstream project
([pi-mono](https://github.com/badlogic/pi-mono)).
