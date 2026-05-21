# MoltBot NPU — Changelog

## What This Is

Patches to OpenClaw's `openai-completions.js` provider that enable tool-calling
on Intel Lunar Lake NPU via Microsoft Foundry Local. These patches make two
small Phi models — **Phi Silica** (NPU-native, no built-in tool calling) and
**Phi-4-mini** (CPU/NPU, has tool calling but won't autonomously select tools) —
work as full agentic backends inside OpenClaw.

**Target hardware:** Surface Copilot+ PC (Intel Lunar Lake), Windows 11
**Foundry Local endpoint:** `http://localhost:5272/v1`
**OpenClaw version:** 2026.1.30
**Patched file:** `@mariozechner/pi-ai/dist/providers/openai-completions.js`

---

## Shim 1: `forceToolChoice` (Phi-4-mini CPU/NPU)

**Problem:** Phi-4-mini supports the OpenAI tool-calling API (`tool_calls` in
responses, `tools` in requests), but with `tool_choice: "auto"` or omitted it
never actually calls a tool — it always responds with plain text.

**Solution:** When Foundry Local is detected (`localhost:5272`), force
`tool_choice: "required"` on the first turn and inject a synthetic
`__text_response` escape-hatch tool so the model can still respond with text
when no real tool applies.

**Key details:**
- `tool_choice: "required"` only on the first user turn; after tool results the
  model is allowed to respond freely (prevents infinite loops)
- `__text_response` tool call is intercepted in the streaming handler and
  converted to a normal text event — OpenClaw never sees it as a tool call
- Raw `<|tool_call|>`/`<|/tool_call|>` tokens leaked by Foundry Local in the
  `content` field are suppressed via a `_suppressToolContent` state flag

**Performance:** ~340 seconds per round-trip on CPU. Too slow for interactive
use, but confirms the protocol works.

---

## Shim 2: `toolsViaPrompt` (Phi Silica NPU)

**Problem:** Phi Silica has `supportsToolCalling: false` in Foundry Local — the
server strips all `tools`, `tool_choice`, and `tool_calls` parameters. The model
has no native tool-calling capability at the API level.

**Solution:** Prompt engineering approach that:
1. Replaces OpenClaw's system prompt with a compact ~1K-char version containing
   tool names, parameter names, and a `[TOOL_CALL]` output format
2. Deletes `tools` and `tool_choice` from the API request
3. Buffers the model's text output during streaming
4. Post-stream, parses `[TOOL_CALL]...[/TOOL_CALL]` markers via regex
5. Converts matched JSON to native `toolcall_start/delta/end` events
6. Converts tool results in conversation history to `[TOOL_RESULT]` user messages

**Key details:**
- Phi Silica returns empty responses when the prompt exceeds ~10-11K chars, so
  the system prompt must be replaced (not appended to)
- Only 4 curated tools (read, write, edit, exec) are listed to keep prompt small
  and prevent wrong-tool selection
- Includes worked examples (read, write, exec, text reply) to ground the format
- Explicit RULES section: "Use write to CREATE files, read to VIEW files",
  "For exec, ONLY provide command", "If user asks to write text, use __text_response"
- Schema-based argument validation: strips unknown params and type mismatches
  (e.g. `env: "normal"` on exec) using the tool's actual JSON schema
- Bare-JSON fallback parser: when model omits `[TOOL_CALL]` markers and outputs
  raw `{"name":"...","arguments":{...}}`, the parser detects and handles it
- **Stateless turns**: only the current turn's messages are sent to the model (no
  conversation history). Tested all 3 approaches — stateless (7-8/8), sliding
  window (6/8), format reminder (5/8). Stateless wins because the 3.8B model
  fixates on older context instead of following instructions for the current turn.
  Trade-off: no conversation memory between turns.
- **Format reinforcement**: all assistant text responses in conversation history
  are wrapped in `[TOOL_CALL]` `__text_response` format (still useful when the
  model calls a tool and receives a result within the same turn)
- **Message ID stripping**: `[message_id: ...]` suffixes added by TUI/gateway are
  stripped from user messages to avoid confusing the model about marker syntax
- Handles both `[TOOL_CALL]` and `[TOOL_RESPONSE]` markers (model sometimes
  uses the latter on the second turn)

**Performance:** ~12 seconds per round-trip on NPU. Usable for interactive demos.

---

## Compatibility Flags

Two new fields added to the compat system (`detectCompat` / `getCompat`):

| Flag | Auto-detected when | Effect |
|---|---|---|
| `forceToolChoice` | `baseUrl` contains `localhost:5272` AND model is NOT `phi-silica` | Injects `__text_response` + `tool_choice: "required"` |
| `toolsViaPrompt` | Model ID is `phi-silica` on Foundry Local | Replaces system prompt, parses `[TOOL_CALL]` from text |

Both can be overridden via `model.compat` in `openclaw.json`.

---

## Files Modified

| File | Change |
|---|---|
| `openai-completions.js` | All 7 patch areas (see patch file) |
| `openclaw.json` | Primary model set to `phi-silica`; three Foundry Local models configured |
| `~/.openclaw/workspace/*.md` | System prompt files trimmed to fit Phi Silica's effective context |

## Patch Summary (openai-completions.js)

1. **`detectCompat`** — Added `isFoundryLocal`, `isPhiSilica` detection; returns
   `forceToolChoice` and `toolsViaPrompt` flags
2. **`getCompat`** — Passes through new compat fields with fallback to detected
3. **`buildParams` (forceToolChoice)** — Injects `__text_response` tool,
   conditionally sets `tool_choice: "required"`
4. **`buildParams` (toolsViaPrompt)** — Replaces system prompt with compact
   version containing explicit tool descriptions, RULES, and 4 worked examples;
   deletes native `tools`/`tool_choice`
5. **`convertMessages`** — Converts assistant tool calls to `[TOOL_CALL]` text
   and tool results to `[TOOL_RESULT]` user messages for prompt-based models
6. **Streaming handler** — Content suppression, `__text_response` interception,
   `_viaPromptBuffer` accumulation, post-stream `[TOOL_CALL]` regex parsing,
   schema-based argument validation (strips unknown params + type mismatches),
   bare-JSON fallback parser (handles missing `[TOOL_CALL]` markers)
7. **`convertMessages` (stateless + format reinforcement)** — Stateless turns
   (only current user message + tool interaction sent); wraps plain text assistant
   responses in `[TOOL_CALL]` `__text_response` format for intra-turn history;
   strips `[message_id: ...]` from user messages

## TUI Usage

The TUI connects to the OpenClaw gateway via WebSocket. **You must restart the
gateway after applying the patch** for it to pick up the changes:

```bash
# Stop the running gateway (Ctrl+C or kill the process)
# Then restart:
npx openclaw gateway

# In another terminal:
npx openclaw tui --session npu-demo
```

If you see raw `[TOOL_CALL]` or `[TOOL_RESULT]` markers in the TUI, restart the
gateway first — it's using the old unpatched provider code.

## Known Limitations

### Fixable in shim (mitigated)

- **Wrong tool selection:** The 3.8B model sometimes picks the wrong tool (e.g.
  `read` instead of `write` for "write a haiku"). Mitigated with explicit RULES
  in the compact prompt and a write example. Not fully eliminable.
- **Hallucinated arguments:** Model adds params not in the tool schema (e.g.
  `env: "normal"` on exec). Now stripped via schema-based validation.
- **Missing markers:** Model sometimes outputs bare JSON without `[TOOL_CALL]`
  wrappers. Now caught by the bare-JSON fallback parser.
- **Null-string params:** Model outputs `"null"` (string) for optional params.
  Stripped by the argument validator.

### Inherent 3.8B model limitations (not fixable)

- **No conversation memory:** Stateless turns mean the model cannot reference
  previous turns. Each turn is independent. This is the necessary trade-off for
  reliable tool calling — with any history, the 3.8B model fixates on older
  context and stops following format instructions.
- **4-tool cap:** Only read, write, edit, and exec are exposed. Other OpenClaw
  tools (browser, nodes, message, etc.) are invisible to the model. Adding more
  tools increases prompt size and causes worse tool selection accuracy.
- **No multi-tool calls:** The `[TOOL_CALL]` parser only extracts the first
  match. Parallel tool calls are not supported.
- **Semantic confusion:** The model may misinterpret ambiguous requests (e.g.
  "write a haiku" = creative writing, not file writing). The compact prompt
  includes disambiguation rules but a 3.8B model will still get confused.

## Test Results

| Test | Model | Result | Time |
|---|---|---|---|
| `read` tool (HEARTBEAT.md) | Phi-4-mini CPU | Pass | ~340s |
| `read` tool (HEARTBEAT.md) | Phi Silica NPU | Pass | ~12s |
| `exec` tool (`echo hello`) | Phi Silica NPU | Pass (after null-strip fix) | ~12s |
| `read` tool (post-TUI fix) | Phi Silica NPU | Pass | ~8s |
| "write a haiku" → `__text_response` | Phi Silica NPU | Pass (correct tool selection) | ~12s |
| `exec` (`powershell -c Get-Date`) | Phi Silica NPU | Pass (clean args, no env/workdir) | ~11s |
| `read` (HEARTBEAT.md, post-prompt fix) | Phi Silica NPU | Pass | ~9s |
| `write` (create /tmp/npu_test.txt) | Phi Silica NPU | Pass (correct tool + args) | ~11s |
| `write` (explicit "use write tool") | Phi Silica NPU | Pass (correct tool + args) | ~11s |
| `exec` via gateway fallback | Phi Silica NPU | Pass | ~10s |
| Stateless T1: `read` HEARTBEAT | Phi Silica NPU | Pass | ~11s |
| Stateless T2: text reply | Phi Silica NPU | Pass ("My name is Phi.") | ~5s |
| Stateless T3: `exec` echo | Phi Silica NPU | Pass | ~10s |
| Stateless T4: "write a haiku" | Phi Silica NPU | Pass (haiku via __text_response) | ~6s |
| Stateless T5: `exec` Get-Date | Phi Silica NPU | Pass | ~12s |
| Stateless T6: `write` file | Phi Silica NPU | Pass (file verified) | ~12s |
| Stateless T7: `read` written file | Phi Silica NPU | Pass ("test passed") | ~11s |
| Stateless T8: `exec` echo | Phi Silica NPU | Pass | ~10s |

---

*Patch file:* `openai-completions-foundry-local.patch` (549 lines, unified diff)
