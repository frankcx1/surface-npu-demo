# Adding a New Capability

This guide explains how to add a new tab, AI-backed feature, persona, or brand to the NPU demo app, with references to actual code patterns in `npu_demo_flask.py`.

## Overview

Every capability in this app follows the same pattern:

1. **HTML tab content** -- a `<div>` block in the inline `HTML_TEMPLATE`
2. **Sidebar nav entry** -- an `<a>` tag in the sidebar navigation
3. **Flask route(s)** -- one or more `@app.route` endpoints
4. **AI call** -- a `foundry_chat()` call with system prompt + collected data
5. **(Optional) Config-driven labels** -- template variables injected from `demo_config.yaml`

---

## Adding a New Tab

### Step 1: Register the Tab in the Sidebar

The sidebar navigation is defined in the `HTML_TEMPLATE` string. Each tab is an `<a>` tag with a `data-tab` attribute that matches the tab content div's ID prefix:

```html
<a class="sidebar-nav-item" data-tab="field">
    <span class="nav-icon">{{TAB_FIELD_ICON}}</span>
    <span class="sidebar-label">{{TAB_FIELD_NAME}}<span class="sidebar-nav-sub">{{TAB_FIELD_SUB}}</span></span>
</a>
```

Insert a new `<a>` tag in the `<nav class="sidebar-nav">` block. The `data-tab` value must match your content div's ID (e.g., `data-tab="advisor"` matches `id="advisor-tab"`).

You also need a hidden `<button>` in the `.tabs` div for backward-compatible `switchToTab()` calls:

```html
<button class="tab-btn" id="advisorTabBtn">Advisor</button>
```

### Step 2: Add the Tab Content HTML

Tab content blocks are `<div id="KEY-tab" class="tab-content">` elements inside `<main>`. Follow any existing tab as a template:

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

**Tab switching is automatic.** The JavaScript click handler handles `data-tab` attributes generically — no additional JS wiring needed.

### Step 3: Add Flask Route(s)

Routes are defined after the `HTML_TEMPLATE` string (which ends around line 10380). All 69 existing routes are `@app.route` decorators on functions in the same file.

**Pattern for an AI-backed endpoint:**

```python
@app.route('/advisor/analyze', methods=['POST'])
def advisor_analyze():
    """Your new capability endpoint."""
    model = DEFAULT_MODEL  # Always use DEFAULT_MODEL (auto-detected)
    data = request.json or {}

    user_input = (data.get('query') or '').strip()

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

    return jsonify({"result": result})
```

**Key conventions:**
- Always use `DEFAULT_MODEL` — never hardcode a model name
- Always use `foundry_chat()` — the wrapper handles reconnection
- Always call `_track_model_call()` after inference to update the savings widget
- Keep system prompts concise — the model has ~4K context total
- Compress data payloads to <3,600 chars (see `compress_for_briefing()` for an example)

### Step 4: Config-Driven Labels (Optional)

If the new tab should be rebrandable, add entries to `demo_config.yaml`:

```yaml
tabs:
  advisor:
    name: "Advisor"
    sub: "Wealth Planning"
    icon: '<svg ...>...</svg>'
```

Then add template variables and `.replace()` calls in the `index()` function:

```python
.replace("{{TAB_ADVISOR_NAME}}", _tabs["advisor"]["name"])
.replace("{{TAB_ADVISOR_SUB}}", _tabs["advisor"]["sub"])
.replace("{{TAB_ADVISOR_ICON}}", _tabs["advisor"]["icon"])
```

Also add the tab key to the hardcoded `DEMO_CONFIG` fallback dict.

### Step 5: Tests

Tests are in `tests/` and mock the Foundry Local connection:

1. Tests import `npu_demo_flask` after patching `openai.OpenAI`
2. Use Flask's test client: `app_module.app.test_client()`
3. Verify routes return expected status codes and JSON structures
4. Verify HTML template contains expected elements

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

### New Tab Checklist

- [ ] Sidebar nav `<a>` with `data-tab="KEY"` in `HTML_TEMPLATE`
- [ ] Hidden `.tab-btn` button for backward compat
- [ ] Tab content `<div id="KEY-tab" class="tab-content">`
- [ ] Flask route(s) using `foundry_chat()` and `_track_model_call()`
- [ ] Model calls use `DEFAULT_MODEL` (never hardcode)
- [ ] Data payloads compressed to <3,600 chars
- [ ] Security: user input validated, file ops use `_path_in_demo_dir()`
- [ ] Config entries in `demo_config.yaml` and hardcoded `DEMO_CONFIG` fallback
- [ ] Template variables and `.replace()` calls in `index()`
- [ ] Tests added to `tests/`

---

## Adding a New Persona

The persona system allows domain-specialized AI characters with distinct knowledge, tone, compliance guardrails, and a safety gate. Marcus Reed (Senior Wealth Advisor) is the reference implementation.

### Step 1: Create the Persona YAML

Create `configs/personas/<name>.yaml`:

```yaml
name: Alex Rivera
title: Commercial Lending Officer
company: Zava Financial

specializations:
  - Commercial real estate lending
  - SBA loans and government programs
  - Business acquisition financing

tone: direct, knowledgeable, efficient

style_notes:
  - Explains complex loan structures in plain English
  - Uses concrete examples with realistic numbers
  - Asks about business fundamentals before discussing terms
  - Always names both sides of a trade-off

compliance:
  stance: conservative
  disclaimer_style: |
    Vary phrasing. Embed disclaimers in reasoning, don't stamp them.
  always_defers_on:
    - Specific interest rate commitments
    - Legal document review
    - Tax implications of loan structures
  never_does:
    - Guarantee loan approval
    - Quote specific rates or terms
    - Make binding commitments on behalf of the bank
    - Give legal or tax advice

system_prompt: |
  You are Alex Rivera, a Commercial Lending Officer at Zava Financial...
  (detailed behavioral instructions here)
```

**Structure reference:** See `configs/personas/marcus_reed.yaml` for the complete 72-line example.

### Step 2: Add Loading Code

Add a loading block parallel to Marcus Reed's (lines 659-671):

```python
_ALEX_AVAILABLE = False
_ALEX_SYSTEM_PROMPT = ""
_ALEX_PERSONA_PATH = os.path.join(_APP_ROOT, "configs", "personas", "alex_rivera.yaml")

if _yaml and os.path.exists(_ALEX_PERSONA_PATH):
    try:
        with open(_ALEX_PERSONA_PATH, 'r', encoding='utf-8') as _af:
            _alex_persona = _yaml.safe_load(_af)
        _ALEX_SYSTEM_PROMPT = _alex_persona.get("system_prompt", "")
        _ALEX_AVAILABLE = True
        print(f"  Alex persona loaded: {_alex_persona.get('name', '?')}")
    except Exception as _pe:
        print(f"  Warning: Alex persona YAML failed: {_pe}")
```

### Step 3: Add a Chat Function

Create a `_alex_chat()` function parallel to `_marcus_chat()` (line 710):

```python
def _alex_chat(user_message, history=None):
    if not _ALEX_AVAILABLE:
        return "Alex Rivera persona is not configured.", 0.0

    messages = [{"role": "system", "content": _ALEX_SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    _call_start = _time.time()
    response = foundry_chat(
        model=DEFAULT_MODEL,
        messages=messages,
        max_tokens=600,
        temperature=0.3,
    )
    elapsed = _time.time() - _call_start
    _track_model_call(response, elapsed)

    result = (response.choices[0].message.content or "").strip()

    # Apply safety gate
    is_safe, filtered = _financial_advice_gate(result)
    return filtered, elapsed
```

### Step 4: Add Safety Gate Rules (if needed)

The existing `_financial_advice_gate()` (lines 674-707) handles common financial compliance rules. If your persona has domain-specific safety requirements, either:

- **Extend the existing gate** with additional regex patterns
- **Create a domain-specific gate** function (e.g., `_lending_advice_gate()`) and apply it in your chat function

Safety gate categories to consider:
| Category | What to block | Example deflection |
|----------|---------------|-------------------|
| Rate quotes | Specific APR/APY percentages | "Let me pull current rates for you" |
| Projections | Dollar amount outcomes | "The actual number depends on several factors" |
| Commitments | Approval guarantees | "I'll need to run this through our underwriting team" |
| Legal/tax | Specific legal or tax advice | "You'd want to talk to your attorney/CPA" |

### Step 5: Route Persona in `/chat`

In the `/chat` route (line 12137), add routing logic:

```python
if _ALEX_AVAILABLE and persona == "alex":
    alex_response, elapsed = _alex_chat(message, history)
    # ... return response
```

The persona can be selected via:
- **Persona switcher** in the sidebar (configured in `demo_config.yaml` under `personas:`)
- **Brand config** (persona automatically active when a specific brand is loaded)
- **Explicit parameter** in the chat request

### Step 6: Register in Brand Config

Add the persona to `demo_config.yaml` under `personas:`:

```yaml
personas:
  - name: "Alex"
    role: "Lending Officer"
    tabs: ["chat", "auditor"]
  - name: "Marcus"
    role: "Branch Manager"
    tabs: ["auditor", "id"]
```

The `tabs` array controls which sidebar tabs are visible when this persona is selected.

### New Persona Checklist

- [ ] YAML file in `configs/personas/<name>.yaml` with system prompt and compliance rules
- [ ] Loading block at module level (parallel to Marcus Reed block)
- [ ] Chat function (parallel to `_marcus_chat()`)
- [ ] Safety gate (extend existing or create domain-specific)
- [ ] Routing in `/chat` endpoint
- [ ] Entry in `demo_config.yaml` under `personas:`
- [ ] Test coverage for persona route and safety gate

---

## Adding a New Brand

Brands control the visual identity, advisor details, tab labels, demo script, and product catalog.

### Step 1: Create Brand Directory

```
configs/
  newbank/
    demo_config.yaml
    product_catalog.yaml    (optional -- falls back to root catalog)
```

### Step 2: Create demo_config.yaml

Copy an existing brand's config and customize:

```yaml
app_title: "Branch of the Future"
app_subtitle: "Powered by Surface + On-Device AI"

brand:
  primary: "#f0f0f0"           # sidebar background
  primary_end: "#e0e0e0"       # sidebar gradient end
  accent: "#1a5276"            # active states, links
  accent_rgb: "26,82,118"      # for rgba() usage
  hover: "#2e86c1"             # hover color
  theme: "light"               # "light" or omit for dark theme
  logo: "newbank-logo.png"     # logo file in repo root
  company_name: "New Bank"

advisor:
  name: "Jane Smith"
  title: "Senior Relationship Manager"
  company: "New Bank"
  phone: "(555) 123-4567"
  email: "jane.smith@newbank.com"
  branch: "Downtown Branch"

tabs:
  chat: {name: "AI Assistant", sub: "Tools & Knowledge", icon: "<svg .../>"}
  # ... (all 6 tabs)

customer:
  name: "Demo Customer"
  full_name: "Demo J. Customer"
  d365_contact_id: ""

# ... (see configs/zava/demo_config.yaml for complete structure)
```

**Key fields:**
- `brand.theme: "light"` activates the Urbanist font and light color palette
- `brand.logo` must be a file in the repo root (served via `/logos/<filename>`)
- Tab icons are inline SVG strings — match the stroke color to `brand.accent`
- `demo_script` is the 19-turn conversation for Live Assist's demo mode

### Step 3: Create product_catalog.yaml (Optional)

If the new brand needs different products, copy and customize `product_catalog.yaml`:

```yaml
categories:
  - name: Deposits
    products:
      - id: basic_checking
        name: "Basic Checking"
        type: checking
        description: "..."
        monthly_fee: "$0"
        talk_track: "..."
  # ... (see root product_catalog.yaml for complete structure)

cross_sell_triggers:
  - signal: has_checking_no_savings
    products: [savings_account]
    priority: high
    talk_track: "..."
  # ...

penetration_tiers:
  - name: New
    min_products: 0
    max_products: 1
    color: "#..."
    action: "..."
  # ...
```

### Step 4: Add Logo File

Place the brand logo (PNG, WebP, or AVIF) in the repo root. The `/logos/<filename>` route serves it.

### Step 5: Test Brand Switching

```cmd
switch-brand.cmd newbank
python npu_demo_flask.py
```

### New Brand Checklist

- [ ] `configs/newbank/demo_config.yaml` with all required fields
- [ ] `configs/newbank/product_catalog.yaml` (if different products)
- [ ] Logo file in repo root
- [ ] Tab icon SVGs with brand-appropriate stroke colors
- [ ] Demo script customized for the brand's customer scenario
- [ ] Test `switch-brand.cmd newbank` and verify all tabs render correctly
- [ ] Verify light/dark theme renders correctly

---

## Common Patterns

### The PowerShell Collector Pattern

Several features (Device Health, Security Audit) collect live system data via PowerShell before sending it to the model:

1. Define a list of check dicts with `id`, `name`, `icon`, `cmd` (PowerShell command)
2. Run each via `subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd], ...)`
3. Pre-compute numerical ratings in Python (don't ask the AI to do math)
4. Concatenate results as text, truncate to fit token budget
5. Send to model with a system prompt that says "use these pre-computed ratings exactly"

**Security rule:** If your capability runs PowerShell commands from user input, add the allowed cmdlets to `_ALLOWED_COMMANDS`. The allowlist is checked in `execute_tool()`.

### Silicon Detection

Your new capability doesn't need to call `detect_silicon()` directly. Module-level variables are set at startup:

- `DEFAULT_MODEL` -- the model ID to pass to `foundry_chat()`
- `SILICON` -- `"intel"`, `"qualcomm"`, or `"arm64"`
- `CHIP_LABEL` -- display string like `"Intel Core Ultra NPU"`
- `MODEL_LABEL` -- display string like `"Phi-4 Mini"`

### Static Assets

There are no `/static` or `/templates` directories. Static assets are served by dedicated Flask routes:

| Asset Type | Location | Served via |
|-----------|----------|-----------|
| Logos, favicon | Repo root (`.png`, `.avif`) | `GET /logos/<filename>` |
| Fonts | `fonts/` | `GET /fonts/<filename>` |
| Demo photos | `demo_data/` | `GET /demo-assets/<filename>` |
| Tesseract.js | `tesseract/` | `GET /tesseract/<filename>` |

If your new feature needs static assets, either add a new serving route (with path traversal prevention) or place files in an existing served directory.

### D365 Integration Pattern

To add a new D365-backed feature:
1. Use `_d365_get_token()` to get a Bearer token
2. Call `_d365_api_get()` or `_d365_api_post()` with the Dataverse OData path
3. Always provide demo fallback data for offline operation
4. Log activities via `_d365_api_post()` to the customer timeline

### Graph Integration Pattern

To add a new Graph-backed feature:
1. Use `_graph_get_token()` to get a Bearer token
2. Make requests to Microsoft Graph API with the token
3. Always provide local file fallback for offline operation
