# GitHub Issue for badlogic/pi-mono

---

**Title:** Feature: Foundry Local NPU support for Copilot+ PCs

**Labels:** enhancement

---

**Body:**

## Feature Request

Add tool-calling support for Microsoft Foundry Local models running on Copilot+ PC NPUs (Intel Lunar Lake, Snapdragon X).

Foundry Local ships on every Copilot+ PC and provides free, offline access to Phi models via an OpenAI-compatible API at `localhost:5272`. However, the two available models can't do tool calling out of the box:

- **Phi Silica** (NPU-native, 3.8B) has `supportsToolCalling: false` -- the server strips all tool parameters from API requests
- **Phi-4-mini** supports the tool API but never actually calls tools with `tool_choice: "auto"`

## What I Built

Two new compatibility flags for the `openai-completions` provider:

**`toolsViaPrompt`** (Phi Silica): A prompt engineering shim that replaces the system prompt with a compact version containing tool definitions and `[TOOL_CALL]` output format, then parses structured markers from the model's text output. Key design decisions:

- Stateless turns (no conversation history) -- a 3.8B model fixates on older context and stops following format instructions. Stateless scored 8/8 vs 2/8 with full history.
- Schema-based argument validation strips hallucinated parameters using the tool's actual JSON schema.
- Bare-JSON fallback catches tool calls when the model omits markers.

**`forceToolChoice`** (Phi-4-mini): Injects `tool_choice: "required"` and a `__text_response` escape-hatch tool so the model can respond with text when no real tool applies.

## Results

Phi Silica on NPU: 8/8 turns passing, ~12s per tool call, $0 API cost, fully offline.

## PR Ready

I have a working implementation at [`frankcx1/pi-mono:foundry-local-npu-support`](https://github.com/badlogic/pi-mono/compare/main...frankcx1:pi-mono:foundry-local-npu-support).

**Changes:** 3 files, purely additive, zero impact on existing providers.

| File | Change |
|---|---|
| `packages/ai/src/types.ts` | Add `forceToolChoice` and `toolsViaPrompt` to `OpenAICompletionsCompat` |
| `packages/ai/src/providers/openai-completions.ts` | Auto-detection, streaming handler, post-stream parser, buildParams, convertMessages |
| `packages/ai/test/...tool-result-images.test.ts` | Add new fields to test fixture |

All checks pass (`npm run build`, `npm run check`). Happy to adjust anything based on feedback.
