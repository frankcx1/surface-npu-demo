# Zava Advisor Extension Plan

## Purpose

This document describes the planned extension work happening on **TheBeast** (dual RTX 3090 workstation). The TheBeast Claude Code session should read this to understand why the repo is being extended and what the target architecture looks like.

## The Capability

A new **"Advisor"** tab featuring **Marcus Reed**, a financial advisor persona for the fictional Zava Financial. Marcus is a Senior Wealth Advisor with a distinct communication style, knowledge specialization, and compliance guardrails -- all trained into a LoRA adapter on top of Phi-4 Mini.

## Why

This is a **reference implementation for enterprise LoRA-per-persona architecture**. It demonstrates:

1. **White-label AI personas** -- each bank customer can have their own advisor persona with trained-in domain knowledge, tone, and compliance behavior, running entirely on-device
2. **LoRA on Copilot+ hardware** -- proving that a lightweight adapter (~50-100MB) can meaningfully customize a small language model's behavior without cloud fine-tuning
3. **The Surface AI story** -- a Copilot+ PC that runs not just a generic SLM but a *customer-specific, persona-tuned* SLM, with training done on commodity GPU hardware and deployment to NPU edge devices

This extends the existing demo's value proposition from "run AI locally" to "run *your* AI locally."

## What Changes

### New Files/Directories

| Path | Purpose |
|------|---------|
| `app/advisor/` | Advisor module: routes, persona logic, safety gates |
| `app/advisor/advisor_service.py` | Loads Phi-4 Mini with dynamic LoRA adapter via OpenVINO GenAI LLMPipeline |
| `app/advisor/persona.yaml` | Marcus Reed persona definition: name, role, tone, knowledge domains, compliance rules |
| `app/advisor/safety.py` | Financial advice deferral gates (detects investment advice, tax guidance, etc. and inserts appropriate disclaimers) |
| `models/` | LoRA adapter files (`.safetensors`) + compiled OpenVINO IR for `phi-4-mini-zava` |
| `training/` | Training pipeline (TheBeast only, not shipped to Surface) |
| `training/corpus_builder.py` | Builds training corpus from persona definition + financial domain sources |
| `training/train_lora.py` | LoRA fine-tuning script (PEFT/LoRA on Phi-4 Mini, runs on dual 3090s) |
| `training/export_to_openvino.py` | Exports merged model to OpenVINO IR format for NPU deployment |

### Modified Files

| File | Change |
|------|--------|
| `npu_demo_flask.py` | New sidebar nav entry, new `<div id="advisor-tab">`, new routes (`/advisor/*`), import of `advisor_service` |
| `demo_config.yaml` | New `tabs.advisor` entry with name/sub/icon |
| Product catalog or persona config may get additional fields |

### What Does NOT Change

- **Existing tabs** stay untouched -- Advisor Assistant, Morning Briefing, PII Guard, ID & Check Verify, Live Assist, Meeting Notes all remain as-is
- **Silicon detection** (`detect_silicon()`, line 533) stays untouched
- **Foundry Local integration** stays untouched -- the base model still loads via `FoundryLocalManager`
- **The PowerShell collector pattern** is extended, not replaced -- if the Advisor tab needs system data, it follows the same subprocess + pre-compute + model call pattern
- **Security measures** stay in place -- file jailing, PowerShell allowlist, PII redaction
- **Brand configuration system** stays untouched -- the YAML config layer continues to work

## Training Pipeline

The training pipeline lives in `/training/` and exists **only on TheBeast**. It is never shipped to the Surface or committed to the production branch.

### Azure Foundry Deployments (LIVE as of 2026-04-23)

Two Azure Foundry model deployments are provisioned and ready for corpus generation:

| Deployment | Model | Role |
|-----------|-------|------|
| Scenario planner/generator | GPT-5.4 | Generates diverse banking advisor scenarios, client profiles, and multi-turn conversations for training data |
| Judge | Claude Opus 4.7 | Evaluates generated training pairs for quality, persona consistency, and compliance accuracy; filters low-quality samples |

Credentials are in `.azure-foundry.env` on the Surface (not in git). Transfer to TheBeast via `tailscale scp` before running the corpus pipeline. See CLAUDE.md "Azure Foundry Credentials" section for regeneration instructions.

The pilot corpus script (`corpus_builder.py`) will be written in a future session on TheBeast once the env file is transferred.

### Pipeline Steps

1. **`corpus_builder.py`** -- Generates training data from:
   - Azure Foundry deployments (GPT-5.4 as generator, Claude Opus 4.7 as judge)
   - Marcus Reed persona definition (tone, knowledge domains, example interactions)
   - Financial domain knowledge (529 Plans, IRA rules, estate planning, insurance products)
   - Compliance guardrails (what to defer, how to disclaim, when to escalate)
   - Output: JSONL file of (instruction, response) pairs

2. **`train_lora.py`** -- Trains the LoRA adapter:
   - Base model: Phi-4 Mini (HuggingFace weights)
   - Method: PEFT/LoRA (rank 16-32, alpha 32-64)
   - Hardware: Dual RTX 3090s (48GB combined VRAM)
   - Output: LoRA adapter weights (`.safetensors`)

3. **`export_to_openvino.py`** -- Exports for NPU deployment:
   - Merges LoRA weights into base model
   - Converts to OpenVINO IR format (`.xml` + `.bin`)
   - Optimizes for INT4/INT8 quantization for NPU
   - Output: Compiled model files in `/models/phi-4-mini-zava/`

### Training Location

LoRA training happens on TheBeast's dual 3090s, **never on the Surface**. The Surface receives only the compiled deployment artifacts via git.

## Deployment Artifacts

The artifacts that ship from TheBeast to Surface:

| File | Location | Size (est.) |
|------|----------|-------------|
| LoRA adapter | `models/phi-4-mini-zava/adapter.safetensors` | ~50-100MB |
| OpenVINO IR | `models/phi-4-mini-zava/openvino_model.xml` + `.bin` | ~2-3GB |

These are committed to git and pulled to the Surface. The `advisor_service.py` module loads them at startup.

## Runtime Integration

`advisor_service.py` loads Phi-4 Mini with the LoRA adapter via OpenVINO GenAI's `LLMPipeline`:

```python
# Conceptual -- actual implementation TBD
from openvino_genai import LLMPipeline

pipeline = LLMPipeline(model_path="models/phi-4-mini-zava/")
# Pipeline runs on NPU with LoRA weights baked in
```

The advisor routes in `npu_demo_flask.py` call `advisor_service` for inference instead of the generic `foundry_chat()` path. The base Foundry Local model is still used for all other tabs.

## Safety Gating

The `safety.py` module implements financial advice deferral:

- Detects queries that constitute investment advice, tax guidance, or insurance recommendations
- Inserts appropriate disclaimers ("This is for informational purposes only...")
- Escalation path: flags queries that exceed the persona's knowledge domain for human advisor review
- Compliance logging: all advisor interactions logged to audit trail

This is critical for the banking demo -- the AI must never give specific investment advice without disclaimers.

## Marcus Reed Persona

| Field | Value |
|-------|-------|
| Name | Marcus Reed |
| Title | Senior Wealth Advisor |
| Company | Zava Financial |
| Specialization | Retirement planning, estate planning, college savings |
| Tone | Warm, professional, consultative |
| Compliance stance | Conservative -- always disclaims, always defers on tax/legal |

The persona is defined in YAML and used both for training data generation and runtime system prompts.

## Success Criteria

1. Marcus Reed responds with consistent tone and knowledge across conversations
2. Financial advice queries get appropriate disclaimers automatically
3. The LoRA adapter loads on Intel Core Ultra NPU without degrading existing tab performance
4. The advisor tab integrates with the existing brand config system (rebrandable)
5. Demo: show a bank CXO that their institution could have its own trained AI persona running on every branch device
