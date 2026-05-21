# Reddit Post (r/LocalLLaMA)

---

**Title:** Got tool-calling working on Phi Silica (3.8B) via Intel NPU -- 8/8 turns, ~12s latency, $0 API cost

---

**Body:**

I patched OpenClaw/Moltbot (open-source AI agent framework) to run tool-calling on Phi Silica via the Intel Lunar Lake NPU through Microsoft Foundry Local. Phi Silica has `supportsToolCalling: false` in Foundry Local -- the server literally strips all tool parameters from API requests. So I built a prompt-engineering shim to work around it.

PR: https://github.com/badlogic/pi-mono/compare/main...frankcx1:pi-mono:foundry-local-npu-support

## The Problem

Phi Silica on Foundry Local:
- No `tools` parameter support (server strips it)
- No `tool_calls` in responses
- No `tool_choice` parameter
- ~10-11K effective context (despite claiming 128K)
- Returns empty responses above that threshold

## The Solution: `toolsViaPrompt` Shim

TypeScript patch to the `openai-completions` provider (3 files, purely additive):

1. **Replace system prompt** with a compact ~1K char version containing 4 curated tools (read, write, edit, exec), parameter names, disambiguation RULES, and worked examples in `[TOOL_CALL]` format

2. **Stateless turns** -- this was the key insight. With any conversation history, the model degrades rapidly:

   | Approach | Turns Passing (out of 8) |
   |----------|-------------------------|
   | Full history (no fix) | 2/8 |
   | 6-message sliding window | 6/8 |
   | 6-msg + format reminder | 5/8 |
   | 4-msg + reminder + truncation | 6/8 |
   | **Stateless (current turn only)** | **8/8** |

   A 3.8B model fixates on older context and stops following format instructions. The fix: don't send history at all. Each turn sees only system prompt + current user message + any tool result from the current turn.

3. **Post-stream parsing** -- buffer the model's text output, regex-extract `[TOOL_CALL]{"name":"...","arguments":{...}}[/TOOL_CALL]`, convert to native `toolcall_start/delta/end` events

4. **Schema-based argument validation** -- the model hallucinates parameters (e.g., `env: "normal"` on exec). The parser looks up the tool's actual JSON schema from the framework and strips:
   - Arguments not in the schema
   - Type mismatches (string value for object-type param)
   - Null/null-string values

5. **Bare-JSON fallback** -- sometimes the model outputs `{"name":"__text_response","arguments":{"text":"..."}}` without the `[TOOL_CALL]` markers. Secondary parser catches this.

6. **Format reinforcement** -- assistant text responses are wrapped in `[TOOL_CALL]` format in intra-turn history so the model sees consistent examples after its own tool calls.

## Test Results

All on Phi Silica, Intel Lunar Lake NPU:

| Turn | Prompt | Result | Latency |
|------|--------|--------|---------|
| 1 | `read HEARTBEAT.md` | Pass | ~11s |
| 2 | "what is your name?" | Pass ("My name is Phi.") | ~5s |
| 3 | `exec echo turn-three` | Pass | ~10s |
| 4 | "write a haiku about silicon" | Pass (haiku via text) | ~6s |
| 5 | `exec powershell -c Get-Date` | Pass | ~12s |
| 6 | `write /tmp/test.txt` | Pass (file verified on disk) | ~12s |
| 7 | `read /tmp/test.txt` | Pass | ~11s |
| 8 | `exec echo final-turn` | Pass | ~10s |

## Honest Limitations

- **No cross-turn memory.** Stateless mode = each turn is independent. The model can't reference anything from previous turns. For tool demos this is fine; for multi-step reasoning chains it's a dealbreaker.
- **4-tool cap.** Adding more tools increases prompt size and tanks selection accuracy.
- **Occasional semantic confusion.** "write a haiku" sometimes triggers the `write` file tool instead of text response. Mitigated with explicit RULES in the prompt but not eliminated.
- **No parallel tool calls.** Single tool call per turn.
- **12s latency.** Usable for demos, not for interactive coding.

## Hardware

- Surface Copilot+ PC (Intel Lunar Lake)
- Windows 11 24H2
- Foundry Local via AI Toolkit
- Phi Silica 3.8B on NPU

## Code

PR against OpenClaw's upstream repo (badlogic/pi-mono):
https://github.com/badlogic/pi-mono/compare/main...frankcx1:pi-mono:foundry-local-npu-support

3 files changed, 406 insertions, purely additive. All existing provider behavior untouched. `npm run build` and `npm run check` pass.

Happy to answer questions about the implementation. If anyone has a Copilot+ PC (Intel or Snapdragon) and wants to test, the branch is ready to clone.

---

*Edit: Also built a `forceToolChoice` shim for Phi-4-mini on CPU (~340s per turn -- proves the protocol works but too slow for interactive use).*
