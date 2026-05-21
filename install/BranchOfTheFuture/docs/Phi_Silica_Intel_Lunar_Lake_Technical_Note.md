# Technical Note: Accessing Phi Silica on Intel Lunar Lake NPU

**Hardware:** Intel Core Ultra Series 2 (Lunar Lake) – 48 TOPS NPU  
**Device tested:** Surface Laptop 7 (Intel) with Core Ultra 7 268V

---

## SDK/Runtime Stack

**Foundry Local** serves as the inference runtime, bundled with the **VS Code AI Toolkit** extension. When you load Phi Silica from the AI Toolkit's model catalog, Foundry Local spins up an OpenAI-compatible REST API on `localhost:5272`.

No separate SDK installation required—the Windows AI APIs handle NPU dispatch under the hood.

---

## Code Pattern

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:5272/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="phi-silica",
    messages=[{"role": "user", "content": "Your prompt here"}],
    stream=True,
    max_tokens=512
)
```

Standard OpenAI client library, pointed at the local endpoint. Streaming works normally. No authentication required since it's entirely on-device.

---

## Model Variant

| Identifier | Full Name | Notes |
|------------|-----------|-------|
| `phi-silica` | Phi Silica (Windows AI) | SLM optimized for NPU via Windows AI APIs |

This is the same model available on Qualcomm Snapdragon X devices—the Windows AI layer abstracts the underlying NPU architecture (Intel vs. Qualcomm).

---

## Key Dependencies

| Component | Purpose |
|-----------|---------|
| Python 3.10+ | Runtime |
| `openai` (pip) | API client library |
| VS Code + AI Toolkit | Hosts Foundry Local runtime |
| Windows 11 24H2 | Required OS (Copilot+ PC) |

---

## Quick Start

1. Install VS Code AI Toolkit extension
2. Open AI Toolkit → Catalog → Load "Phi Silica"
3. Foundry Local starts automatically on `localhost:5272`
4. Point your app's OpenAI client at the local endpoint

---

*Reference project: [surface-npu-demo](https://github.com/frankcx1/surface-npu-demo)*
