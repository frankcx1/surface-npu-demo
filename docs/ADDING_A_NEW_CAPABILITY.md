# Adding a New Capability

This guide explains how to add a new tab or AI-backed feature to the NPU demo app, with references to actual code patterns in `npu_demo_flask.py`.

## Overview

Every capability in this app follows the same pattern:

1. **HTML tab content** -- a `<div>` block in the inline `HTML_TEMPLATE`
2. **Sidebar nav entry** -- an `<a>` tag in the sidebar navigation
3. **Flask route(s)** -- one or more `@app.route` endpoints
4. **AI call** -- a `foundry_chat()` call with system prompt + collected data
5. **(Optional) Config-driven labels** -- template variables injected from `demo_config.yaml`

## Step 1: Register the Tab in the Sidebar

The sidebar navigation is defined in the `HTML_TEMPLATE` string, starting at line 3432. Each tab is an `<a>` tag with a `data-tab` attribute that matches the tab content div's ID prefix:

```html
<!-- npu_demo_flask.py, ~line 3459 -->
<a class="sidebar-nav-item" data-tab="field">
    <span class="nav-icon">{{TAB_FIELD_ICON}}</span>
    <span class="sidebar-label">{{TAB_FIELD_NAME}}<span class="sidebar-nav-sub">{{TAB_FIELD_SUB}}</span></span>
</a>
```

To add a new tab, insert a new `<a>` tag in the `<nav class="sidebar-nav">` block (after line 3432). The `data-tab` value must match your content div's ID (e.g., `data-tab="advisor"` matches `id="advisor-tab"`).

You also need a hidden `<button>` in the `.tabs` div (line 3495) for backward-compatible `switchToTab()` calls:

```html
<!-- npu_demo_flask.py, ~line 3501 -->
<button class="tab-btn" id="advisorTabBtn">Advisor</button>
```

## Step 2: Add the Tab Content HTML

Tab content blocks are `<div id="KEY-tab" class="tab-content">` elements inside the `<main>` section. The existing tabs are defined between lines 3505 and 3997.

Example structure (follow the Meeting Notes tab at line 3997 as a template):

```html
<div id="advisor-tab" class="tab-content">
    <div class="auditor-header">
        <!-- Icon SVG + title -->
    </div>
    <!-- Your UI content here -->
    <div class="tab-footer">
        <span class="poc-banner">{{POC_FOOTER}}</span>
    </div>
</div>
```

**Tab switching is automatic.** The JavaScript click handler (around line 4323) handles `data-tab` attributes generically -- no additional JS wiring is needed for basic tab switching.

## Step 3: Add Flask Route(s)

Routes are defined after the `HTML_TEMPLATE` string (which ends around line 10215). All 69 existing routes are `@app.route` decorators on functions in the same file.

**Pattern for an AI-backed endpoint:**

```python
# npu_demo_flask.py -- add after existing routes

@app.route('/advisor/analyze', methods=['POST'])
def advisor_analyze():
    """Your new capability endpoint."""
    model = DEFAULT_MODEL  # Always use DEFAULT_MODEL (auto-detected)
    data = request.json or {}

    # 1. Collect/parse input data
    user_input = (data.get('query') or '').strip()

    # 2. Call the model via foundry_chat() wrapper
    _call_start = _time.time()
    response = foundry_chat(
        model=model,
        messages=[
            {"role": "system", "content": "You are a ..."},
            {"role": "user", "content": user_input},
        ],
        max_tokens=512,  # Budget: max ~1,536
        temperature=0.3,
    )
    _track_model_call(response, _time.time() - _call_start)

    result = (response.choices[0].message.content or "").strip()

    # 3. Return JSON
    return jsonify({"result": result})
```

**Key conventions:**
- Always use `DEFAULT_MODEL` (line 593), never hardcode a model name
- Always use `foundry_chat()` (line 643), not `client.chat.completions.create()` directly -- the wrapper handles reconnection
- Always call `_track_model_call()` (line 838) after inference to update the savings widget
- Keep system prompts concise -- the model has ~4K context total
- Compress data payloads to <3,600 chars (see `compress_for_briefing()` at line 1007 for an example)

## Step 4: The PowerShell Collector Pattern

Several tabs (Device Health, Security Audit) collect live system data via PowerShell before sending it to the model. The pattern:

1. Define a list of check dicts with `id`, `name`, `icon`, `cmd` (PowerShell command)
2. Run each via `subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd], ...)`
3. Pre-compute numerical ratings in Python (don't ask the AI to do math)
4. Concatenate results as text, truncate to fit token budget
5. Send to model with a system prompt that says "use these pre-computed ratings exactly"

Example: `demo_device_health()` at line 10918 (9 PowerShell checks + AI summary).

**Security rule:** If your capability runs PowerShell commands from user input, add the allowed cmdlets to `_ALLOWED_COMMANDS` (line 1051). The allowlist is checked in `execute_tool()` at line 1128.

## Step 5: Silicon Detection Consumption

Your new capability doesn't need to call `detect_silicon()` directly. The module-level variable `SILICON` (line 559) is set at startup and the correct model is already loaded. Just use:

- `DEFAULT_MODEL` -- the model ID to pass to `foundry_chat()`
- `SILICON` -- `"intel"`, `"qualcomm"`, or `"arm64"` if you need conditional behavior
- `CHIP_LABEL` -- display string like `"Intel Core Ultra NPU"`
- `MODEL_LABEL` -- display string like `"Phi-4 Mini"`

## Step 6: Static Assets

There are no `/static` or `/templates` directories. Static assets are served by dedicated Flask routes:

| Asset Type | Location | Served via |
|-----------|----------|-----------|
| Logos, favicon | Repo root (`.png`, `.avif`) | `GET /logos/<filename>` (line 10216) |
| Fonts | `fonts/` | `GET /fonts/<filename>` (line 10239) |
| Demo photos | `demo_data/` | `GET /demo-assets/<filename>` (line 10258) |
| Tesseract.js | `tesseract/` | `GET /tesseract/<filename>` (line 10280) |

If your new tab needs static assets (images, JS libraries), either:
- Add a new serving route following the pattern at line 10216 (with path traversal prevention)
- Or place files in an existing served directory

## Step 7: Config-Driven Labels (Optional)

If the new tab should be rebrandable, add entries to `demo_config.yaml`:

```yaml
tabs:
  advisor:
    name: "Advisor"
    sub: "LoRA Persona"
    icon: '<svg ...>...</svg>'
```

Then add template variables and `.replace()` calls in the `index()` function (line 10771):

```python
.replace("{{TAB_ADVISOR_NAME}}", _tabs["advisor"]["name"])
.replace("{{TAB_ADVISOR_SUB}}", _tabs["advisor"]["sub"])
.replace("{{TAB_ADVISOR_ICON}}", _tabs["advisor"]["icon"])
```

Also add the tab key to the hardcoded `DEMO_CONFIG` fallback dict (line 508).

## Step 8: Tests

Tests are in `tests/` and mock the Foundry Local connection. The pattern:

1. Tests import `npu_demo_flask` after patching `openai.OpenAI` (see `tests/test_phase1.py`, lines 1-28)
2. Use Flask's test client: `app_module.app.test_client()`
3. Verify routes return expected status codes and JSON structures
4. Verify HTML template contains expected elements (CSS classes, div IDs, button text)

Example test:

```python
def test_advisor_route_exists(self):
    client = app_module.app.test_client()
    resp = client.post('/advisor/analyze',
                       json={'query': 'test'},
                       content_type='application/json')
    self.assertIn(resp.status_code, [200, 500])

def test_advisor_tab_html(self):
    client = app_module.app.test_client()
    resp = client.get('/')
    self.assertIn(b'advisor-tab', resp.data)
```

## Checklist for Adding a New Tab

- [ ] Sidebar nav `<a>` with `data-tab="KEY"` (in `HTML_TEMPLATE`, after line 3432)
- [ ] Hidden `.tab-btn` button (after line 3495)
- [ ] Tab content `<div id="KEY-tab" class="tab-content">` (after line 3997)
- [ ] Flask route(s) using `foundry_chat()` and `_track_model_call()`
- [ ] Model calls use `DEFAULT_MODEL` (never hardcode)
- [ ] Data payloads compressed to <3,600 chars
- [ ] Security: user input validated, file ops use `_path_in_demo_dir()`
- [ ] Config entries in `demo_config.yaml` and hardcoded `DEMO_CONFIG` fallback
- [ ] Template variables and `.replace()` calls in `index()` (line 10771)
- [ ] Tests added to `tests/`
