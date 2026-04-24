# Zava Advisor Extension Plan

## Purpose

This document describes the planned extension work happening across two machines. The TheBeast Claude Code session should read this to understand why the repo is being extended and what the target architecture looks like.

## The Capability

A new **"Advisor"** tab featuring **Marcus Reed**, a financial advisor persona for the fictional Zava Financial. Marcus is a Senior Wealth Advisor with a distinct communication style, knowledge specialization, and compliance guardrails.

## Why

This is a **reference implementation for enterprise persona-per-customer architecture**. It demonstrates:

1. **White-label AI personas** -- each bank customer can have their own advisor persona with domain knowledge, tone, and compliance behavior, running entirely on-device
2. **The Surface AI story** -- a Copilot+ PC that runs not just a generic SLM but a *customer-specific, persona-tuned* SLM, deployed to NPU edge devices
3. **Optional LoRA path** -- proving that a lightweight adapter can meaningfully customize a small language model's behavior, with training done on commodity GPU hardware

This extends the existing demo's value proposition from "run AI locally" to "run *your* AI locally."

## Marcus Reed Persona

| Field | Value |
|-------|-------|
| Name | Marcus Reed |
| Title | Senior Wealth Advisor |
| Company | Zava Financial |
| Specialization | Retirement planning, estate planning, college savings |
| Tone | Warm, professional, consultative |
| Compliance stance | Conservative -- always disclaims, always defers on tax/legal |

The persona is defined in YAML (`configs/personas/marcus_reed.yaml`) and used both for runtime system prompts and (if Track B proceeds) training data generation.

## Two Independent Tracks

The Zava Advisor work splits into two tracks that progress in parallel and reunite at the final integration step. This is deliberate: Track A ships demo value this week regardless of whether Track B succeeds. Track B is a research experiment with a clear validation gate before scaling.

### Track A: Advisor Tab on Surface (ships this week)

Add the Advisor tab inline to `npu_demo_flask.py` following the existing single-file architecture. Do not create an `app/advisor/` package or any new directory. Every existing tab is functions and routes in the main file; Advisor follows the same pattern.

**What gets added:**

- New `@app.route` handlers for advisor chat, session reset, metrics
- New HTML block in `HTML_TEMPLATE` for the Advisor tab UI
- New sidebar nav entry in the existing nav section
- New persona YAML: `configs/personas/marcus_reed.yaml` (loaded the same way `demo_config.yaml` is loaded)
- Inline safety gate function: `_financial_advice_gate()` that runs before any Advisor response returns. Blocks specific rate quotes, approval commitments, investment advice, tax/legal claims. Replaces flagged responses with a templated deferral to a human.
- Inline memory for session context (in-memory dict keyed by session ID for v0; SQLite persistence is a future enhancement)

**Inference path:** Use the existing `foundry_chat()` wrapper and `FoundryLocalManager`. Do NOT introduce a parallel OpenVINO GenAI pipeline. Marcus runs on stock Phi-4 Mini with a strong system prompt built from the persona YAML. Same model, same Foundry Local runtime, same reconnect logic as every other tab.

**Success criteria for Track A:**

- Advisor tab renders in the sidebar
- Marcus responds in persona to banking questions
- Safety gate blocks rate quotes and replaces with deferrals
- Works offline (airplane mode) like every other tab
- Can be demoed to a customer this week

### Track B: LoRA Training on TheBeast (research, validation-gated)

Train a custom LoRA adapter against Phi-4 Mini that captures the Marcus Reed persona from a synthetic training corpus. Run a blind A/B against the system-prompt-only version from Track A. If the LoRA is visibly better, it ships. If it isn't, Track A ships alone and we've learned something about 3.8B LoRA limits.

TheBeast is the dev and training workstation (dual RTX 3090s). TheBeast does not run the app and does not serve real traffic. It produces training artifacts.

**Pipeline stages** (all on TheBeast unless noted):

1. **Synthetic corpus generation** via Azure Foundry. Uses GPT-5.4 for scenario planning and bulk generation, Claude Opus 4.7 as quality judge. Pilot target: 800-1,200 conversations for initial A/B, scale to 5,000-6,000 only if pilot validates.

2. **LoRA fine-tuning** via PEFT + bitsandbytes on one 3090. Base model: `microsoft/Phi-4-mini-instruct`. Rank 16, nf4 quantization. 3 epochs. Expected runtime: 4-8 hours.

3. **Export to OpenVINO IR** -- merge LoRA into base weights, export via `optimum-cli`.

4. **Register as custom Foundry Local model** on the Surface. This is the correct integration pattern. It does NOT introduce a parallel inference path. The Advisor tab continues to use `foundry_chat()` with the same API, just with a different model alias in the config.

5. **Blind A/B test** on real Surface hardware. Compare LoRA-Marcus vs system-prompt-Marcus across representative queries. Decide whether to ship the LoRA or stay with system-prompt only.

**Artifacts produced on TheBeast:**

| Path | Purpose | In git? |
|------|---------|---------|
| `training/scripts/` | Reproducible pipeline code (corpus_builder, train_lora, export) | Yes |
| `training/corpus/` | JSONL training data | No (gitignored, too large) |
| `training/checkpoints/` | LoRA safetensors | No (gitignored) |
| `training/exports/phi-4-mini-zava/` | Merged OpenVINO IR | No (delivered to Surface via USB/network share/signed download) |

**Model file delivery to Surface:** Do NOT commit 2-3GB OpenVINO IR files to git. Use git-lfs, a signed manifest + download-on-first-run script, or manual copy for v0.

### Azure Foundry Deployments (LIVE as of 2026-04-23)

Two Azure Foundry model deployments are provisioned and ready for corpus generation:

| Deployment | Model | Role |
|-----------|-------|------|
| Scenario planner/generator | GPT-5.4 | Generates diverse banking advisor scenarios, client profiles, and multi-turn conversations for training data |
| Judge | Claude Opus 4.7 | Evaluates generated training pairs for quality, persona consistency, and compliance accuracy; filters low-quality samples |

Credentials are in `.azure-foundry.env` on the Surface (not in git). Transfer to TheBeast via `tailscale scp` before running the corpus pipeline. See CLAUDE.md "Azure Foundry Credentials" section for regeneration instructions.

The pilot corpus script (`corpus_builder.py`) will be written in a future session on TheBeast once the env file is transferred.

## Integration Point

Track A ships with stock Phi-4 Mini as the Advisor model (via the existing model alias pattern). If Track B validates, the config toggles from `phi-4-mini` to `phi-4-mini-zava` (the custom-registered Foundry Local model), **zero code changes required** in the Advisor route handlers. Foundry Local serves both through the same SDK and endpoint.

## What Does NOT Change

- **Existing 6 tabs** stay untouched
- **Silicon auto-detection** stays untouched
- **`foundry_chat()` wrapper** stays untouched
- **Single-file architecture** stays untouched
- **Brand configuration system** stays untouched
- **No new top-level directories in the app code** (`training/` is a dev-only directory that lives on TheBeast and is gitignored for large artifacts)

## Success Criteria

### Track A (Advisor Tab)

1. Marcus Reed responds with consistent tone and knowledge across conversations
2. Financial advice queries get appropriate disclaimers automatically via `_financial_advice_gate()`
3. The advisor tab integrates with the existing brand config system (rebrandable)
4. Works offline on Surface, no NPU contention with other tabs
5. Demo: show a bank CXO that their institution could have its own AI persona running on every branch device

### Track B (LoRA)

LoRA wins the blind A/B if at least 2 of 3 hold:

1. **Persona fidelity:** Marcus sounds distinctly more like Zava's voice and less like generic Phi-4 Mini
2. **Safety adherence:** LoRA maintains or improves refusal rate on rate-quote/commitment extraction attempts (target 95%+)
3. **Subjective quality:** Blind raters prefer LoRA responses in majority of head-to-head comparisons

If LoRA does not win, system-prompt-only Marcus ships, and the enterprise pitch shifts to "here's our reference architecture for training custom personas, here's the pipeline on TheBeast, here's what we learned about 3.8B LoRA limits." That's still a valuable artifact for Microsoft field teams.
