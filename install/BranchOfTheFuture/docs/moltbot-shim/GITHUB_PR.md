# GitHub PR/Issue Draft for badlogic/pi-mono

---

## Title

feat: Add Foundry Local NPU support (toolsViaPrompt + forceToolChoice)

## Summary

Adds tool-calling support for Microsoft Foundry Local models running on
Intel Lunar Lake NPU. Two new compatibility flags enable models that lack
native tool-calling support to work as agentic backends in OpenClaw.

- **`toolsViaPrompt`** (Phi Silica): Prompt engineering shim for models
  with `supportsToolCalling: false`. Replaces system prompt, parses
  `[TOOL_CALL]` markers from text output, validates arguments against
  tool schemas.
- **`forceToolChoice`** (Phi-4-mini): Injects `tool_choice: "required"`
  + `__text_response` escape-hatch for models that support the tool API
  but never autonomously select tools.

## Motivation

Foundry Local ships on every Copilot+ PC and provides free, offline access
to Phi models via an OpenAI-compatible API at `localhost:5272`. However:

- Phi Silica (NPU-native) has `supportsToolCalling: false` -- the server
  strips all tool parameters
- Phi-4-mini supports the tool API but never calls tools with
  `tool_choice: "auto"`

This patch enables both models as OpenClaw backends, with Phi Silica on
NPU being the primary target (~12s per tool call, 8/8 turn reliability).

## Implementation

### 7 patch areas in `openai-completions.js`:

1. **`detectCompat`** -- Auto-detect Foundry Local (`localhost:5272`) and
   Phi Silica; set `forceToolChoice` / `toolsViaPrompt` flags

2. **`getCompat`** -- Pass through new compat fields with fallback to
   auto-detected values

3. **`buildParams` (forceToolChoice)** -- Inject `__text_response` tool +
   `tool_choice: "required"` on first turn

4. **`buildParams` (toolsViaPrompt)** -- Replace system prompt with compact
   version containing 4 curated tools, RULES, and worked examples; delete
   native `tools`/`tool_choice`

5. **`convertMessages`** -- Stateless turns (only current turn sent);
   format reinforcement (wrap assistant text in `[TOOL_CALL]` format);
   strip `[message_id: ...]` suffixes; convert tool calls to `[TOOL_CALL]`
   text and tool results to `[TOOL_RESULT]` user messages

6. **Streaming handler** -- Buffer text in `_viaPromptBuffer`; suppress
   raw `<|tool_call|>` tokens; intercept `__text_response` tool calls

7. **Post-stream parser** -- Regex extraction of `[TOOL_CALL]` markers;
   schema-based argument validation; bare-JSON fallback; marker stripping
   in error paths

### Key design decisions:

- **Stateless turns:** Tested 4 approaches for multi-turn coherence.
  Stateless (no history) scored 8/8 vs 2/8 with full history. A 3.8B
  model fixates on older context and stops following format instructions.

- **Schema-based validation:** Instead of simple null-string stripping,
  the parser looks up the tool's actual JSON schema from `context.tools`
  and strips unknown parameters and type mismatches.

- **Curated 4-tool list:** Only read, write, edit, exec are exposed.
  Listing more tools increases prompt size and degrades selection accuracy
  on a 3.8B model.

## Test Results

| Test | Model | Result | Latency |
|------|-------|--------|---------|
| 8-turn stateless sequence | Phi Silica NPU | 8/8 pass | ~10s avg |
| `read` tool | Phi Silica NPU | Pass | ~11s |
| `write` tool (file verified) | Phi Silica NPU | Pass | ~12s |
| `exec` tool (Get-Date) | Phi Silica NPU | Pass | ~12s |
| `__text_response` (haiku) | Phi Silica NPU | Pass | ~6s |
| `read` tool | Phi-4-mini CPU | Pass | ~340s |

## Compatibility

- Both flags can be overridden via `model.compat` in `openclaw.json`
- No changes to existing behavior for non-Foundry-Local models
- Auto-detection keyed on `baseUrl` containing `localhost:5272`

## Patch Stats

- **549 lines** (unified diff)
- **0 new dependencies**
- **0 breaking changes** to existing providers

## Known Limitations

- No cross-turn memory (stateless mode required for reliability)
- 4-tool cap (prompt size constraint)
- No parallel tool calls
- ~12s latency on NPU (acceptable for demos, not interactive coding)
- Phi-4-mini CPU path is ~340s (proof of concept only)
