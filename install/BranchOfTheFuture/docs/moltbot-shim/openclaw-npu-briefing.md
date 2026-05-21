# OpenClaw NPU Fork — Technical Briefing Document

## Context

This document was prepared by a Claude Code session that spent extensive time working inside the OpenClaw codebase on a Windows Server machine with dual RTX 3090s. The goal is to provide architectural knowledge for a new session that will fork OpenClaw to run on Windows Copilot+ PCs using the Snapdragon X Elite NPU with Phi Silica / Phi-3-mini ONNX.

OpenClaw version analyzed: `2026.1.29` (installed globally via npm at `C:\Users\groot\AppData\Roaming\npm\node_modules\openclaw`)

---

## 1. Architecture Overview

OpenClaw is a Node.js-based AI agent gateway. The architecture has two main layers:

### Layer 1: `@mariozechner/pi-ai` (LLM Abstraction)
- Separate npm package (v0.49.3) bundled as a dependency
- Location: `node_modules/@mariozechner/pi-ai/dist/`
- Handles ALL model inference — provider routing, streaming, message transformation
- Pure LLM logic, no OpenClaw-specific dependencies
- Originally from `badlogic/pi-mono` monorepo on GitHub (TypeScript sources compiled to JS + .d.ts)

### Layer 2: `openclaw` (Agent Framework)
- Location: `dist/`
- Agent orchestration, tool management, session state, channels (Telegram, etc.)
- Imports `streamSimple` from `@mariozechner/pi-ai` for inference
- Has its own `providers/registry.js` for **chat channels** (Telegram, Discord) — NOT LLM providers

**The LLM provider layer you need to modify is entirely within `@mariozechner/pi-ai`.**

### Key Insight
OpenClaw's config (`openclaw.json`) supports inline provider definitions. When you define a provider with `"api": "openai-completions"`, the `api` field is the dispatch key that routes to the correct provider implementation. Adding NPU support means adding a new `api` type (e.g., `"onnx-npu"`) and its corresponding provider implementation.

---

## 2. Files to Examine First (Priority Order)

### Critical Path (read these first):

1. **`@mariozechner/pi-ai/dist/stream.js`** (~200 lines)
   - THE main dispatch function — `stream()` and `streamSimple()`
   - Switch statement on `model.api` routes to provider implementations
   - `mapOptionsForApi()` translates generic options to provider-specific params
   - `streamSimple()` is the normalized interface that OpenClaw actually calls

2. **`@mariozechner/pi-ai/dist/providers/openai-completions.js`** (~700 lines)
   - Reference implementation for a provider
   - Uses `openai` npm SDK's `client.chat.completions.create()` (NOT text completions)
   - Shows the full pattern: client creation → request building → streaming → event emission
   - Handles `reasoning_content` field for reasoning models (lines 155-192)
   - Has `compat` system for provider-specific quirks (Mistral, Groq, etc.)

3. **`@mariozechner/pi-ai/dist/utils/event-stream.js`**
   - `AssistantMessageEventStream` class — the return type ALL providers must produce
   - Extends `EventStream` with async iterator protocol
   - Push-based: providers call `.push(event)` then `.end()`

4. **`@mariozechner/pi-ai/dist/types.d.ts`**
   - TypeScript interfaces for everything: `Api`, `Model`, `Message`, `StreamOptions`, `AssistantMessage`
   - The `Api` union type lists all valid provider keys
   - `ApiOptionsMap` maps each API type to its options interface

5. **`@mariozechner/pi-ai/dist/models.generated.js`** (351KB — skim, don't read fully)
   - Auto-generated model registry as a giant `MODELS` export object
   - Shows the data shape for model definitions
   - Not needed for NPU fork since you'll define models in openclaw.json

6. **`openclaw/dist/agents/pi-embedded-runner/extra-params.js`** (~70 lines)
   - How per-model params (temperature, maxTokens) flow from config to provider
   - Reads from `cfg.agents.defaults.models["provider/model"].params`
   - Wraps `streamFn` to inject extra parameters

### Secondary (read when implementing):

7. **`@mariozechner/pi-ai/dist/providers/transform-messages.js`**
   - Normalizes message arrays across providers
   - Handles tool call ID constraints (Mistral: 9 chars, OpenAI: 40 chars)
   - You'll want to use this in your NPU provider

8. **`openclaw/dist/agents/pi-embedded-runner/run.js`**
   - Agent runner entry point
   - `resolveModel()` function shows how provider/model IDs map to actual Model objects
   - Shows fallback chain logic

9. **`openclaw/dist/agents/pi-embedded-runner/run/attempt.js`**
   - Where `streamFn` is actually invoked per conversation turn
   - Shows retry logic, error handling, context overflow handling

---

## 3. The Provider Contract

Every provider must implement a function with this signature:

```typescript
(model: Model<TApi>, context: Context, options: OptionsForApi<TApi>) => AssistantMessageEventStream
```

### Input: `model`
```typescript
{
  id: string;           // "phi-3-mini-onnx"
  name: string;         // "Phi-3 Mini (NPU)"
  api: Api;             // "onnx-npu" (your new type)
  provider: string;     // "npu-local"
  baseUrl: string;      // could be model file path
  reasoning: boolean;   // false for Phi
  input: string[];      // ["text"]
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
  contextWindow: number; // 4096 or 128000 for Phi-3
  maxTokens: number;    // 2048
  headers?: Record<string, string>;
  compat?: object;      // provider-specific quirk flags
}
```

### Input: `context`
```typescript
{
  systemPrompt?: string;
  messages: Message[];   // array of {role, content} objects
  tools?: Tool[];        // function definitions for tool calling
}
```

### Input: `options`
```typescript
{
  temperature?: number;
  maxTokens?: number;
  signal?: AbortSignal;  // for cancellation
  apiKey?: string;       // not needed for local
  headers?: Record<string, string>;
  onPayload?: (payload: any) => void;  // debug hook
  // your NPU-specific options would go here
}
```

### Output: `AssistantMessageEventStream`

Must push these events in order:
```
{ type: "start", partial: AssistantMessage }
{ type: "text_start", contentIndex: 0 }
{ type: "text_delta", contentIndex: 0, delta: "token text" }  // repeat per token
{ type: "text_end", contentIndex: 0 }
{ type: "done", reason: "stop"|"length"|"toolUse", message: AssistantMessage }
```

For tool calls:
```
{ type: "toolcall_start", contentIndex: N, toolCall: { id, name } }
{ type: "toolcall_delta", contentIndex: N, argumentsDelta: "partial json" }
{ type: "toolcall_end", contentIndex: N }
```

Final `AssistantMessage` must include:
```typescript
{
  role: "assistant",
  content: [{ type: "text", text: "response" }],  // and/or tool calls
  api: "onnx-npu",
  provider: "npu-local",
  model: "phi-3-mini",
  usage: { input, output, cacheRead: 0, cacheWrite: 0, totalTokens, cost: {...} },
  stopReason: "stop",
  timestamp: Date.now()
}
```

---

## 4. Recommended Approach for Adding NPU Support

### Step 1: Fork and Setup

```bash
# Clone the pi-ai package (the LLM abstraction layer)
# Original source: https://github.com/badlogic/pi-mono
# You'll primarily modify the pi-ai subpackage

# For quick prototyping, you can patch the installed copy directly:
# node_modules/@mariozechner/pi-ai/dist/providers/onnx-npu.js
```

### Step 2: Create the ONNX-NPU Provider

Create `providers/onnx-npu.js` following the pattern from `openai-completions.js`:

```javascript
import { AssistantMessageEventStream } from "../utils/event-stream.js";

export function streamOnnxNpu(model, context, options) {
  const stream = new AssistantMessageEventStream();

  (async () => {
    try {
      // 1. Build prompt from context.systemPrompt + context.messages
      //    Use Phi-3's chat template: <|system|>\n{system}<|end|>\n<|user|>\n{user}<|end|>\n<|assistant|>

      // 2. Load/reference ONNX session
      //    For Phi Silica: use Windows.AI.MachineLearning APIs
      //    For Phi-3 ONNX: use onnxruntime-node with 'dml' execution provider (DirectML → NPU)

      // 3. Tokenize input

      // 4. Run inference, emit tokens as text_delta events

      // 5. Handle tool calls if Phi supports function calling
      //    (Phi-3-mini has limited tool call support — may need prompt engineering)

      // 6. Push "done" event with final AssistantMessage

    } catch (err) {
      stream.push({ type: "error", reason: "error", error: err });
    }
    stream.end();
  })();

  return stream;
}
```

### Step 3: Register in stream.js

Add to the switch statement:
```javascript
case "onnx-npu":
  return streamOnnxNpu(model, context, providerOptions);
```

Add to `mapOptionsForApi()`:
```javascript
case "onnx-npu":
  return { ...base };  // pass through generic options
```

### Step 4: Add Type Definitions

In `types.d.ts`, add `"onnx-npu"` to the `Api` union type and `ApiOptionsMap`.

### Step 5: Configure in openclaw.json

```json
{
  "models": {
    "providers": {
      "npu-local": {
        "baseUrl": "file:///C:/Models/phi-3-mini-4k-instruct-onnx",
        "apiKey": "not-needed",
        "api": "onnx-npu",
        "models": [
          {
            "id": "phi-3-mini",
            "name": "Phi-3 Mini (NPU)",
            "reasoning": false,
            "input": ["text"],
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "contextWindow": 4096,
            "maxTokens": 2048
          }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "npu-local/phi-3-mini"
      }
    }
  }
}
```

---

## 5. NPU-Specific Technical Considerations

### Option A: Phi Silica (Windows AI APIs)
- Uses `Windows.AI.MachineLearning` WinRT APIs
- Requires Windows 11 24H2+ on Copilot+ PC
- Automatically routes to NPU hardware
- Would need N-API/node-addon-api bridge to call WinRT from Node.js
- OR: create a small C#/Python sidecar that exposes an HTTP API (simpler)

### Option B: Phi-3 ONNX with DirectML
- Use `onnxruntime-node` npm package with DirectML execution provider
- DirectML automatically targets NPU on Snapdragon X Elite
- More portable, works on any DirectML-capable hardware
- `onnxruntime-node` supports Windows ARM64 natively
- Model files: download from Hugging Face (`microsoft/Phi-3-mini-4k-instruct-onnx`)

### Option C: HTTP Sidecar (Simplest)
- Run a small Python server using `onnxruntime-genai` (Microsoft's inference library)
- Expose OpenAI-compatible `/v1/chat/completions` endpoint
- Use existing `"api": "openai-completions"` — no provider code changes needed
- `onnxruntime-genai` has native NPU support for Snapdragon X Elite
- Trade-off: extra process, but zero changes to OpenClaw's provider layer

**Recommendation: Start with Option C** to validate the concept with zero provider changes, then build Option B for a clean native integration.

### Tokenization
- Phi-3 uses a SentencePiece tokenizer
- `onnxruntime-genai` handles tokenization internally
- If building native provider (Option B), you'll need a JS tokenizer — consider `@xenova/transformers` or bundle the tokenizer model

### Tool Calling
- Phi-3-mini has basic function calling via prompt engineering (not native)
- Phi Silica may have enhanced tool call support
- OpenClaw's agent framework heavily uses tools (exec, browser, message, cron, memory)
- **This is the biggest risk**: a 3.8B model may struggle with reliable tool call JSON generation
- Mitigation: constrained decoding / JSON mode if ONNX runtime supports it

---

## 6. Gotchas and Tightly-Coupled Dependencies

### Things That Will Bite You

1. **No plugin system** — providers are statically compiled into `stream.js` via switch statement. You must modify the source, not load plugins at runtime.

2. **`models.generated.js` is auto-generated** — don't hand-edit it. It's 351KB of compiled model data. Use openclaw.json inline provider definitions instead (they bypass the generated registry).

3. **The `compat` system** — `openai-completions.js` has a complex compatibility layer for provider quirks (lines 550-650). Your NPU provider won't need this, but be aware it exists if you base your code on the OpenAI provider.

4. **Message transformation** — `transform-messages.js` normalizes tool call IDs with provider-specific constraints. If Phi doesn't support tool calls natively, you'll need to handle tool call serialization in the prompt yourself.

5. **Streaming is mandatory** — the agent runner expects an `AssistantMessageEventStream`. Even if your NPU inference isn't streaming, you must wrap the full response in the event protocol (emit all deltas at once, then "done").

6. **AbortSignal handling** — the agent framework can cancel in-flight requests via `options.signal`. Your provider must check this and abort inference cleanly.

7. **The `reasoning` flag** — when `model.reasoning` is true, OpenClaw expects `thinking` content blocks in the response. Phi doesn't do chain-of-thought in the same way, so keep this `false`.

8. **Session state is per-agent** — stored as JSONL at `agents/main/sessions/{uuid}.jsonl`. Sessions grow fast and can blow past small context windows. The compaction system ("Pre-compaction memory flush") fires periodically. On a 4K context Phi model, compaction will fire very frequently.

9. **Context window pressure** — OpenClaw's system prompt for agents is ~14K tokens. Phi-3-mini with 4K context literally cannot fit it. You'll either need:
   - Phi-3-mini-128k variant (128K context, but slower on NPU)
   - Drastically trimmed system prompt
   - Custom agent template for NPU-constrained models

10. **Windows ARM64 compatibility** — verify that `onnxruntime-node` publishes ARM64 Windows binaries. As of 2025, it does, but check the latest. The `openai` and `@anthropic-ai/sdk` packages are pure JS and work everywhere.

---

## 7. Recommended Development Sequence

1. **Day 1**: Clone/fork, get OpenClaw running on Surface with cloud API (Anthropic) to verify base functionality
2. **Day 2**: Option C — Python sidecar with `onnxruntime-genai` serving Phi-3 on NPU, configure as `openai-completions` provider in openclaw.json
3. **Day 3**: Test agent capabilities — does Phi-3 handle tools? Can it follow the system prompt? What breaks?
4. **Day 4**: If Option C works, decide if native integration (Option B) is worth it
5. **Day 5+**: Build native `onnx-npu` provider, handle tokenization, streaming, tool call extraction

### What to Test First
- Basic chat via Telegram (does it respond at all?)
- Tool use (can it generate valid JSON for function calls?)
- Memory/compaction (does it handle the memory flush prompt without going into a loop?)
- Session management (does it work within context window limits?)

---

## 8. Code Patterns Worth Knowing

### How OpenClaw resolves inline providers (from openclaw.json)

The config's `models.providers` section creates "inline" models that bypass `models.generated.js`. The resolution chain in `run.js`:

```
1. Check models.generated.js registry
2. Check inline providers from openclaw.json  ← your NPU model enters here
3. Fallback to mock model (for testing)
```

### How extra params flow

```
openclaw.json → agents.defaults.models["provider/model"].params
    → extra-params.js resolveExtraParams()
    → wraps streamFn with temperature/maxTokens overrides
    → merged into options passed to provider
```

### How the agent runner calls the provider

```
attempt.js → agent.streamFn(model, context, options)
    → streamSimple() in stream.js
    → mapOptionsForApi() translates to provider-specific
    → stream() dispatches to provider via switch
    → provider returns AssistantMessageEventStream
    → runner iterates events, handles tool calls, builds reply
```

---

## 9. Quick Reference

| What | Where |
|------|-------|
| Provider dispatch | `@mariozechner/pi-ai/dist/stream.js` switch statement |
| Reference provider | `@mariozechner/pi-ai/dist/providers/openai-completions.js` |
| Event stream class | `@mariozechner/pi-ai/dist/utils/event-stream.js` |
| Type definitions | `@mariozechner/pi-ai/dist/types.d.ts` |
| Model registry | `@mariozechner/pi-ai/dist/models.generated.js` |
| Message normalization | `@mariozechner/pi-ai/dist/providers/transform-messages.js` |
| Agent runner | `openclaw/dist/agents/pi-embedded-runner/run.js` |
| Extra params | `openclaw/dist/agents/pi-embedded-runner/extra-params.js` |
| Config file | `~/.openclaw/openclaw.json` |
| Session storage | `~/.openclaw/agents/main/sessions/*.jsonl` |
| Memory storage | `~/.openclaw/memory/` |
| Valid API types | `openai-completions`, `openai-responses`, `anthropic-messages`, `google-generative-ai`, `google-vertex`, `bedrock-converse-stream` |

---

*Prepared 2026-02-01 by Claude Code (Opus 4.5) after extensive analysis of the OpenClaw codebase on a Windows Server machine running dual RTX 3090s.*
