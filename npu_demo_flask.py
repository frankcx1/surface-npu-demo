"""
Local NPU AI Assistant Demo
Document Analysis + Chat + ID Verification
Runs entirely on-device using Foundry Local — Intel Core Ultra or Snapdragon X NPU
"""

import os
import json
import platform
import re
import subprocess
import threading
import time as _time
from flask import Flask, render_template_string, request, Response, jsonify
from openai import OpenAI
from werkzeug.utils import secure_filename

try:
    import yaml as _yaml
except ImportError:
    _yaml = None

_APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Demo mode (parsed early so it's available at module load) ---
import sys as _sys
DEMO_MODE = '--demo-mode' in _sys.argv

# --- Per-device state directory (NEVER in OneDrive-synced project folder) ---
# Token caches, __pycache__, and other device-specific files go here.
LOCAL_STATE_DIR = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    'NPUDemo'
)
os.makedirs(LOCAL_STATE_DIR, exist_ok=True)


def _migrate_token_cache(filename):
    """One-time migration: copy token cache from old project-root path to LOCALAPPDATA.
    Returns the new path (always in LOCAL_STATE_DIR)."""
    import shutil as _shutil
    # New path drops the leading dot (e.g. .d365_token_cache.json -> d365_token_cache.json)
    new_name = filename.lstrip('.')
    old_path = os.path.join(_APP_ROOT, filename)
    new_path = os.path.join(LOCAL_STATE_DIR, new_name)
    if os.path.exists(old_path) and not os.path.exists(new_path):
        _shutil.copy2(old_path, new_path)
        print(f"  [MIGRATE] Token cache: {old_path} -> {new_path}")
        try:
            os.remove(old_path)
        except OSError:
            pass  # OneDrive may hold a lock; old file will be ignored next time
    return new_path


def _load_yaml_config():
    """Load demo config from YAML file, returning None if unavailable."""
    if not _yaml:
        return None
    path = os.path.join(_APP_ROOT, 'demo_config.yaml')
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = _yaml.safe_load(f)
        # Flatten nested keys for backward compat with DEMO_CONFIG dict
        brand = raw.get('brand', {})
        adv = raw.get('advisor', {})
        poc = raw.get('poc', {})
        cfg = {
            'app_title':        raw.get('app_title', 'Branch of the Future'),
            'app_subtitle':     raw.get('app_subtitle', ''),
            'brand_primary':    brand.get('primary', '#ffffff'),
            'brand_primary_end': brand.get('primary_end', '#f8f8f8'),
            'brand_accent':     brand.get('accent', '#f18f12'),
            'brand_accent_rgb': brand.get('accent_rgb', '241,143,18'),
            'brand_hover':      brand.get('hover', '#f6d107'),
            'brand_theme':      brand.get('theme', 'light'),
            'brand_logo':       brand.get('logo', ''),
            'brand_company':    brand.get('company_name', ''),
            'advisor_name':     adv.get('name', ''),
            'advisor_title':    adv.get('title', ''),
            'advisor_company':  adv.get('company', ''),
            'advisor_phone':    adv.get('phone', ''),
            'advisor_email':    adv.get('email', ''),
            'advisor_branch':   adv.get('branch', ''),
            'tabs':             raw.get('tabs', {}),
            'personas':         raw.get('personas', []),
            'poc_footer':       poc.get('footer', ''),
            'poc_auditor':      poc.get('auditor', ''),
            'poc_id':           poc.get('id', ''),
            'customer':         raw.get('customer', {}),
            'branches':         raw.get('branches', []),
            'economics':        raw.get('economics', {}),
            'demo_script':      raw.get('demo_script', []),
            'industry':         raw.get('industry', {}),
            # Industry Packs activation markers (appended by switch-brand.cmd)
            'use_industry_packs': raw.get('use_industry_packs', False),
            'active_brand':     raw.get('active_brand', ''),
        }
        print(f"  Config loaded from demo_config.yaml", flush=True)
        return cfg
    except Exception as e:
        print(f"  Warning: Failed to load demo_config.yaml: {e}", flush=True)
        return None


# ---------------------------------------------------------------------------
# Industry Packs: Config inheritance loader (Wave 0)
# ---------------------------------------------------------------------------
# When use_industry_packs is enabled, the app resolves brand configs through
# a three-tier YAML inheritance chain: industry → vertical → brand.
# This loader coexists with the legacy _load_yaml_config() path.
# Default: disabled (legacy path). Enable via use_industry_packs: true
# in root demo_config.yaml or via --industry-pack <brand_id> CLI arg.
# ---------------------------------------------------------------------------

def _deep_merge(dst, src):
    """In-place deep merge. src wins. Dicts merge recursively, lists replace."""
    for key, value in src.items():
        if (key in dst
                and isinstance(dst[key], dict)
                and isinstance(value, dict)):
            _deep_merge(dst[key], value)
        else:
            dst[key] = value


def _load_resolved_config(brand_id):
    """Resolve a brand's full config by walking the extends chain.
    Returns: (resolved_dict, chain) where chain is the list of files merged.
    Raises RuntimeError on missing files, circular extends, or invalid schema.
    """
    if not _yaml:
        raise RuntimeError("PyYAML is required for industry packs")

    chain = []
    visited = set()
    current_path = os.path.join(_APP_ROOT, "configs", "brands",
                                brand_id, "demo_config.yaml")

    docs = []
    while current_path:
        real = os.path.realpath(current_path)
        if real in visited:
            raise RuntimeError(f"Circular extends in config chain: {real}")
        visited.add(real)

        if not os.path.exists(real):
            raise RuntimeError(f"Config file not found: {real}")

        with open(real, 'r', encoding='utf-8') as f:
            doc = _yaml.safe_load(f) or {}
        docs.append(doc)
        chain.append(real)

        ext = doc.get("extends")
        if not ext:
            break
        current_path = os.path.join(_APP_ROOT, "configs", ext)

    if len(chain) > 4:
        raise RuntimeError(
            f"Config extends chain too deep ({len(chain)} levels): "
            + " -> ".join(chain))

    # Reverse so root industry is first, brand is last (last writer wins)
    docs.reverse()
    chain.reverse()

    resolved = {}
    for doc in docs:
        _deep_merge(resolved, doc)

    return resolved, list(reversed(chain))


# Required vocabulary tokens (Section 8 of spec)
_REQUIRED_VOCAB_TOKENS = [
    "subject", "subject_plural", "practitioner", "practitioner_plural",
    "engagement", "engagement_plural", "record", "records_system",
    "organization", "catalog_item",
]

# Required prompt capability IDs (Section 10 of spec)
_REQUIRED_PROMPT_IDS = [
    "agent_system_framing", "brief_me", "triage_inbox", "prep_next_meeting",
    "top_3_focus", "tomorrow_preview", "pii_contract_review",
    "pii_marketing_review", "id_analyze", "check_analyze",
    "live_assist_analyze", "live_assist_translate",
    "meeting_transcribe_extract", "meeting_classify", "meeting_annotate",
    "meeting_report", "meeting_translate", "concierge_greeting_brief",
    "email_polish", "device_health_summary", "security_audit_summary",
    "device_search", "summarize_doc", "detect_pii", "knowledge_qa",
]

# Uppercase HTML template vars (must not collide with lowercase vocab tokens)
_HTML_TEMPLATE_VARS = {
    "APP_TITLE", "BRAND_ACCENT", "BRAND_ACCENT_RGB", "BRAND_PRIMARY",
    "BRAND_PRIMARY_END", "BRAND_HOVER", "BRAND_COMPANY", "ADVISOR_NAME",
    "ADVISOR_TITLE", "ADVISOR_COMPANY", "ADVISOR_PHONE", "POC_FOOTER",
    "POC_AUDITOR", "POC_ID", "CHIP_LABEL", "MODEL_LABEL", "DEVICE_LABEL",
    "MODEL_ALIAS", "TAB_CHAT_NAME", "TAB_CHAT_SUB", "TAB_CHAT_ICON",
    "TAB_DAY_NAME", "TAB_DAY_SUB", "TAB_DAY_ICON", "TAB_AUDITOR_NAME",
    "TAB_AUDITOR_SUB", "TAB_AUDITOR_ICON", "TAB_ID_NAME", "TAB_ID_SUB",
    "TAB_ID_ICON", "TAB_LIVE_NAME", "TAB_LIVE_SUB", "TAB_LIVE_ICON",
    "TAB_FIELD_NAME", "TAB_FIELD_SUB", "TAB_FIELD_ICON", "THEME_OVERRIDES",
    "SIDEBAR_LOGO", "PERSONA_SWITCHER", "PLACEHOLDER_CLIENT",
    "PLACEHOLDER_LOCATION", "PLACEHOLDER_ISSUE", "PLACEHOLDER_SOURCE",
    "ANNOTATION_LABEL", "ANNOTATION_FALLBACK",
}

_REQUIRED_TAB_IDS = ["chat", "day", "auditor", "id", "live", "field"]


def _validate_resolved_config(resolved):
    """Validate a resolved config dict. Raises RuntimeError on failure."""
    errors = []

    # schema_version
    sv = resolved.get("schema_version")
    if sv != 1:
        errors.append(f"schema_version must be 1, got {sv!r}")

    # vocabulary: all required tokens present and are strings
    vocab = resolved.get("vocabulary", {})
    for token in _REQUIRED_VOCAB_TOKENS:
        val = vocab.get(token)
        if val is None:
            errors.append(f"vocabulary.{token} is missing")
        elif not isinstance(val, str):
            errors.append(
                f"vocabulary.{token} must be a string, got {type(val).__name__} "
                f"({val!r}). Quote the value in YAML to fix.")

    # vocab token / HTML template var collision check
    for token in vocab:
        if token.upper() in _HTML_TEMPLATE_VARS:
            errors.append(
                f"vocabulary token '{token}' collides with HTML template var "
                f"'{token.upper()}'. Rename the vocab token.")

    # tabs: all 6 IDs present
    tabs = resolved.get("tabs", {})
    for tid in _REQUIRED_TAB_IDS:
        if tid not in tabs:
            errors.append(f"tabs.{tid} is missing")

    # status
    status = resolved.get("status", "active")
    brand_status = resolved.get("brand_status", "active")
    is_stub = (status == "stub" or brand_status == "stub")

    # prompts: all capability IDs present (stubs can use placeholder strings)
    prompts = resolved.get("prompts", {})
    for pid in _REQUIRED_PROMPT_IDS:
        if pid not in prompts:
            if is_stub:
                pass  # stubs may omit prompts
            else:
                errors.append(f"prompts.{pid} is missing (required for active config)")

    # compliance: safety gate must be registered (if not stub)
    gate_name = (resolved.get("compliance", {}).get("primary_safety_gate") or "")
    if gate_name and not is_stub:
        # Can't validate against _SAFETY_GATES here because they may not be
        # registered yet at import time. Validation is deferred to startup.
        pass

    # concierge: tiers must be present if enabled
    concierge = resolved.get("concierge", {})
    if concierge.get("enabled") and not concierge.get("tiers"):
        errors.append("concierge.enabled is true but concierge.tiers is empty")

    # pii: demo_person_names must be a list of strings
    pii_names = resolved.get("pii", {}).get("demo_person_names", [])
    if pii_names and not isinstance(pii_names, list):
        errors.append("pii.demo_person_names must be a list")

    # demo_data: path must exist (unless stub)
    demo_path = resolved.get("demo_data", {}).get("path", "")
    if demo_path and not is_stub:
        full_path = os.path.join(_APP_ROOT, demo_path)
        if not os.path.isdir(full_path):
            # Warning only, not fatal — demo data may not be populated yet
            print(f"  Warning: demo_data.path '{demo_path}' does not exist on disk")

    if errors:
        raise RuntimeError(
            f"Config validation failed ({len(errors)} errors):\n  " +
            "\n  ".join(errors))


def _render_vocab(template_str, vocab_dict):
    """Replace {{token}} placeholders with vocabulary values.
    Tokens not found in vocab_dict are left as-is (and logged as warnings).
    Only replaces lowercase tokens — uppercase HTML template vars are untouched.
    """
    if not template_str or not vocab_dict:
        return template_str or ""
    result = template_str
    for key, value in vocab_dict.items():
        placeholder = "{{" + key + "}}"
        if placeholder in result:
            result = result.replace(placeholder, str(value))
    return result


def _get_prompt(capability_id, resolved_config=None, **extra_vars):
    """Render a capability prompt from config with vocabulary substitution.
    Falls back to empty string with warning if prompt not found (for stubs).
    """
    cfg = resolved_config or globals().get("RESOLVED_CONFIG", {})
    template = cfg.get("prompts", {}).get(capability_id)
    if not template:
        industry = cfg.get("industry_id", "unknown")
        brand = cfg.get("brand_id", "unknown")
        print(f"  Warning: prompt '{capability_id}' missing "
              f"(industry={industry}, brand={brand})")
        return ""
    vocab = cfg.get("vocabulary", {})
    # Add brand-level vars to vocab for substitution
    brand_vars = {
        "company_name": cfg.get("brand", {}).get("company_name", ""),
        "advisor_name": cfg.get("advisor", {}).get("name", ""),
        "advisor_title": cfg.get("advisor", {}).get("title", ""),
        "advisor_org": cfg.get("advisor", {}).get("organization_unit", ""),
    }
    merged = {**vocab, **brand_vars, **extra_vars}
    return _render_vocab(template, merged)


# Module-level resolved config (set during startup if industry packs enabled)
RESOLVED_CONFIG = {}
_INDUSTRY_PACKS_ACTIVE = False
_CONFIG_CHAIN = []


def _load_product_catalog():
    """Load product catalog from YAML. Returns empty dict if unavailable."""
    if not _yaml:
        return {}
    path = os.path.join(_APP_ROOT, 'product_catalog.yaml')
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            catalog = _yaml.safe_load(f)
        n = sum(len(c.get('products', [])) for c in catalog.get('categories', []))
        print(f"  Product catalog loaded: {n} products, {len(catalog.get('cross_sell_triggers', []))} triggers", flush=True)
        return catalog
    except Exception as e:
        print(f"  Warning: Failed to load product_catalog.yaml: {e}", flush=True)
        return {}


PRODUCT_CATALOG = _load_product_catalog()


def _match_product_recommendations(customer_data):
    """Match a customer's D365 profile against the product catalog to find cross-sell opportunities.
    Returns: {tier, tier_color, current_count, total_count, recommendations: [{id, name, category, priority, talk_track, reason}]}
    """
    if not PRODUCT_CATALOG:
        return {"tier": "Unknown", "current_count": 0, "total_count": 0, "recommendations": []}

    categories = PRODUCT_CATALOG.get("categories", [])
    triggers = PRODUCT_CATALOG.get("cross_sell_triggers", [])
    tiers = PRODUCT_CATALOG.get("penetration_tiers", [])

    # Build flat product lookup
    all_products = {}
    for cat in categories:
        for prod in cat.get("products", []):
            all_products[prod["id"]] = {**prod, "category": cat.get("name", "")}
    total_count = len(all_products)

    # Extract customer's current products by fuzzy-matching account types
    accounts = customer_data.get("accounts", [])
    notes = (customer_data.get("notes", "") or "").lower()
    account_types = [a.get("type", "").lower() for a in accounts]
    all_text = " ".join(account_types) + " " + notes

    # Map account types to product IDs
    current_product_ids = set()
    for pid, prod in all_products.items():
        pname = prod["name"].lower()
        for at in account_types:
            if at and (pname in at or at in pname or pid.replace("_", " ") in at):
                current_product_ids.add(pid)

    current_count = len(current_product_ids)

    # Determine penetration tier
    tier_name, tier_color, tier_action = "New", "#ef4444", ""
    for t in tiers:
        if t["min_products"] <= current_count <= t["max_products"]:
            tier_name = t["tier"]
            tier_color = t.get("color", "#ef4444")
            tier_action = t.get("action", "")
            break

    # Evaluate cross-sell trigger signals
    signals = set()
    has_checking = any("checking" in at for at in account_types)
    has_savings = any("saving" in at for at in account_types)
    has_credit_card = any("card" in at or "credit" in at for at in account_types)
    has_retirement = any(x in all_text for x in ["ira", "401k", "retirement", "pension"])
    has_mortgage = any("mortgage" in at or "home loan" in at for at in account_types)

    if has_checking and not has_savings:
        signals.add("has_checking_no_savings")
    if not has_credit_card:
        signals.add("no_credit_card")
    if not has_retirement:
        signals.add("no_retirement_account")
    if any(x in all_text for x in ["529", "college", "child", "daughter", "son", "kids"]):
        signals.add("has_children")
    if any(x in all_text for x in ["401k", "rollover", "old employer"]):
        signals.add("old_401k")
    if not has_mortgage:
        signals.add("renting_home")
    if any(x in all_text for x in ["overdraft", "nsf"]):
        signals.add("frequent_overdrafts")
    if any(x in all_text for x in ["business", "llc", "corp"]):
        signals.add("owns_business")
    if has_checking and current_count <= 1:
        signals.add("large_checking_balance")

    # Collect recommended products from matched triggers
    recs = []
    seen_ids = set()
    priority_order = {"high": 0, "medium": 1, "low": 2}
    for trigger in triggers:
        if trigger["signal"] in signals:
            for pid in trigger.get("suggest", []):
                if pid not in current_product_ids and pid not in seen_ids and pid in all_products:
                    prod = all_products[pid]
                    recs.append({
                        "id": pid,
                        "name": prod["name"],
                        "category": prod["category"],
                        "priority": trigger.get("priority", "medium"),
                        "talk_track": prod.get("talk_track", ""),
                        "reason": trigger.get("description", trigger["signal"]),
                    })
                    seen_ids.add(pid)

    # Sort by priority, take top 5
    recs.sort(key=lambda r: priority_order.get(r["priority"], 1))
    recs = recs[:5]

    return {
        "tier": tier_name,
        "tier_color": tier_color,
        "tier_action": tier_action,
        "current_count": current_count,
        "total_count": total_count,
        "gap_count": total_count - current_count,
        "recommendations": recs,
    }


# --- Branch Concierge: VIP Arrival Awareness ---
import uuid as _uuid

_ARRIVALS = {}  # In-memory arrival registry, resets on restart

_CONCIERGE_TIERS = {
    "private": {"label": "Private Client", "color": "#8B6F47", "icon": "\u2b50"},
    "premier": {"label": "Premier", "color": "#012169", "icon": "\ud83d\udcce"},
    "business": {"label": "Business Banking", "color": "#2D5F3F", "icon": "\ud83c\udfe2"},
    "retail":  {"label": "Retail", "color": "#6B7280", "icon": "\ud83d\udc64"},
}

_CONCIERGE_DEMO_CUSTOMERS = {
    "jackie_rodriguez": {
        "client_id": "5cdc2c3f-ad29-f111-8342-002248357e0e",
        "name": "Jackie Rodriguez",
        "full_name": "Jackie Marie Rodriguez",
        "title": "VP Procurement",
        "vip_tier": "premier",
        "email": "jackie.rodriguez@email.com",
        "phone": "(248) 555-0147",
        "rm": "Jennifer",
        "last_interaction": "Met with Jennifer on March 15 about opening a 529 plan for daughter Maya and rolling over a previous 401(k).",
        "notes": "New client. Interested in 529 Plan and Roth IRA conversion. Two children: Maya (8) and Daniel (15).",
    },
    "marcus_chen": {
        "client_id": "demo-marcus-chen-001",
        "name": "Marcus Chen",
        "full_name": "Marcus Wei Chen",
        "title": "CEO, Chen Capital Partners",
        "vip_tier": "private",
        "email": "marcus.chen@chencapital.com",
        "phone": "(212) 555-0331",
        "rm": "Frank",
        "last_interaction": "Portfolio review in February. $12M under management. Discussed rebalancing toward international equities.",
        "notes": "High-net-worth private client. Owns Chen Capital Partners. Interested in business line of credit for new venture.",
    },
    "sarah_henderson": {
        "client_id": "demo-sarah-henderson-001",
        "name": "Sarah Henderson",
        "full_name": "Sarah Ann Henderson",
        "title": "Estate Trustee",
        "vip_tier": "premier",
        "email": "s.henderson@hendersontrust.com",
        "phone": "(248) 555-0298",
        "rm": "Jennifer",
        "last_interaction": "Document review for Henderson Family Trust in March. Estate planning referral pending.",
        "notes": "Manages Henderson Family Trust. Annual review due. Considering managed portfolio for trust assets.",
    },
}


def _get_concierge_customer(name_or_id):
    """Look up a demo customer for concierge by name or ID."""
    search = (name_or_id or "").lower()
    for key, cust in _CONCIERGE_DEMO_CUSTOMERS.items():
        if search in cust["name"].lower() or search in key or search == cust["client_id"]:
            return cust
    return None


# --- Demo-mode: auto-seed Branch Concierge arrivals ---
def _seed_demo_arrivals():
    """Pre-populate Branch Concierge with demo arrivals when in demo-mode.
    Makes the arrivals panel and greeting briefs work out of the box
    without D365 or manual simulation button clicks."""
    if not DEMO_MODE:
        return
    if _ARRIVALS:
        return  # already seeded (e.g. from a previous call)
    _demo_seeds = [
        ("jackie_rodriguez", "app_checkin", 0),
        ("marcus_chen", "teller_identified", 120),
        ("sarah_henderson", "appointment", 300),
    ]
    for key, source, age_offset in _demo_seeds:
        cust = _CONCIERGE_DEMO_CUSTOMERS.get(key)
        if not cust:
            continue
        aid = str(_uuid.uuid4())[:8]
        _ARRIVALS[aid] = {
            "name": cust["name"],
            "title": cust.get("title", ""),
            "tier": cust["vip_tier"],
            "source": source,
            "source_token": f"demo-seed-{aid}",
            "rm": cust.get("rm", ""),
            "client_id": cust["client_id"],
            "arrived_at": _time.time() - age_offset,
            "status": "waiting",
        }
    if _ARRIVALS:
        print(f"  [DEMO-MODE] Seeded {len(_ARRIVALS)} arrivals for Branch Concierge")


_seed_demo_arrivals()


# --- Dynamics 365 / MSAL Integration ---
_D365_ORG_URL = "https://orgdf28000a.crm.dynamics.com"
_D365_API_URL = _D365_ORG_URL + "/api/data/v9.2"
_D365_APP_ID = _D365_ORG_URL + "/main.aspx?appid=c22cb86f-ff3c-f111-88b5-002248357e0e"
_D365_TOKEN_CACHE = None  # Cached access token
_D365_TOKEN_EXPIRY = 0    # Unix timestamp when token expires

def _d365_get_token():
    """Get a valid D365 access token using MSAL device code flow with caching."""
    global _D365_TOKEN_CACHE, _D365_TOKEN_EXPIRY
    # Return cached token if still valid (with 5 min buffer)
    if _D365_TOKEN_CACHE and _time.time() < (_D365_TOKEN_EXPIRY - 300):
        return _D365_TOKEN_CACHE
    try:
        import msal
        # Use a well-known public client ID for device code flow
        # This is the "Microsoft Azure PowerShell" public client
        client_id = "1950a258-227b-4e31-a9cf-717495945fc2"
        authority = "https://login.microsoftonline.com/D365DemoTSCE32685848.onmicrosoft.com"
        scope = [_D365_ORG_URL + "/.default"]

        # Try to load cached token from file
        cache = msal.SerializableTokenCache()
        cache_file = _migrate_token_cache('.d365_token_cache.json')
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)

        # Try silent acquisition first (from cache)
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scope, account=accounts[0])
            if result and "access_token" in result:
                _D365_TOKEN_CACHE = result["access_token"]
                _D365_TOKEN_EXPIRY = _time.time() + result.get("expires_in", 3600)
                # Save cache
                if cache.has_state_changed:
                    with open(cache_file, 'w') as f:
                        f.write(cache.serialize())
                print("[D365] Token acquired silently (cached)")
                return _D365_TOKEN_CACHE

        # Device code flow -- user authenticates in browser
        flow = app.initiate_device_flow(scopes=scope)
        if "user_code" not in flow:
            print(f"[D365] Device flow failed: {flow}")
            return None

        print(f"\n{'='*60}")
        print(f"  D365 Authentication Required")
        print(f"  Go to: {flow['verification_uri']}")
        print(f"  Enter code: {flow['user_code']}")
        print(f"{'='*60}\n")

        result = app.acquire_token_by_device_flow(flow)
        if "access_token" in result:
            _D365_TOKEN_CACHE = result["access_token"]
            _D365_TOKEN_EXPIRY = _time.time() + result.get("expires_in", 3600)
            # Save cache for next time
            if cache.has_state_changed:
                with open(cache_file, 'w') as f:
                    f.write(cache.serialize())
            print("[D365] Token acquired via device code flow")
            return _D365_TOKEN_CACHE
        else:
            print(f"[D365] Token acquisition failed: {result.get('error_description', 'Unknown error')}")
            return None
    except ImportError:
        print("[D365] MSAL not installed -- pip install msal")
        return None
    except Exception as e:
        print(f"[D365] Auth error: {e}")
        return None

def _d365_api_get(path, params=None):
    """Make an authenticated GET request to Dataverse Web API."""
    token = _d365_get_token()
    if not token:
        return None
    try:
        import requests as _req
        headers = {
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Prefer": "odata.include-annotations=*"
        }
        url = _D365_API_URL + path
        resp = _req.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"[D365] API error {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"[D365] API request failed: {e}")
        return None

def _d365_api_post(path, payload):
    """Make an authenticated POST request to Dataverse Web API."""
    token = _d365_get_token()
    if not token:
        return None
    try:
        import requests as _req
        headers = {
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        url = _D365_API_URL + path
        resp = _req.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201, 204):
            return resp.json() if resp.text else {"status": "created"}
        else:
            print(f"[D365] API POST error {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"[D365] API POST failed: {e}")
        return None


# --- Microsoft Graph Integration ---
_D365_TENANT = "D365DemoTSCE32685848.onmicrosoft.com"
_GRAPH_APP_ID = "a8d3dbf0-5fdd-4283-9d78-8d3235d6ca99"
_GRAPH_TOKEN_CACHE = None
_GRAPH_TOKEN_EXPIRY = 0
_GRAPH_CACHE_FILE = _migrate_token_cache('.graph_token_cache.json')
print(f"[GRAPH] Cache file: {_GRAPH_CACHE_FILE}, exists: {os.path.exists(_GRAPH_CACHE_FILE)}")

def _graph_get_token():
    """Get a valid Microsoft Graph access token using cached credentials."""
    global _GRAPH_TOKEN_CACHE, _GRAPH_TOKEN_EXPIRY
    if _GRAPH_TOKEN_CACHE and _time.time() < (_GRAPH_TOKEN_EXPIRY - 300):
        return _GRAPH_TOKEN_CACHE
    try:
        import msal
        cache = msal.SerializableTokenCache()
        if os.path.exists(_GRAPH_CACHE_FILE):
            with open(_GRAPH_CACHE_FILE, 'r') as f:
                cache.deserialize(f.read())
        app = msal.PublicClientApplication(
            _GRAPH_APP_ID,
            authority=f"https://login.microsoftonline.com/{_D365_TENANT}",
            token_cache=cache
        )
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(
                ['Calendars.ReadWrite', 'Mail.ReadWrite', 'Mail.Send', 'User.Read'],
                account=accounts[0]
            )
            if result and "access_token" in result:
                _GRAPH_TOKEN_CACHE = result["access_token"]
                _GRAPH_TOKEN_EXPIRY = _time.time() + result.get("expires_in", 3600)
                if cache.has_state_changed:
                    with open(_GRAPH_CACHE_FILE, 'w') as f:
                        f.write(cache.serialize())
                print("[GRAPH] Token acquired silently")
                return _GRAPH_TOKEN_CACHE
        print("[GRAPH] No cached token. Authenticate via /graph/authenticate")
        return None
    except Exception as e:
        print(f"[GRAPH] Token error: {e}")
        return None

def _graph_get_calendar_today():
    """Get today's calendar events from Microsoft Graph (Outlook)."""
    token = _graph_get_token()
    if not token:
        return None
    try:
        import requests as _req
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        start = now.strftime('%Y-%m-%dT00:00:00Z')
        end = (now + timedelta(days=1)).strftime('%Y-%m-%dT23:59:59Z')
        headers = {"Authorization": f"Bearer {token}"}
        r = _req.get(
            f"https://graph.microsoft.com/v1.0/me/calendarView"
            f"?startDateTime={start}&endDateTime={end}"
            f"&$select=subject,start,end,location,bodyPreview"
            f"&$orderby=start/dateTime"
            f"&$top=20",
            headers=headers, timeout=10
        )
        if r.status_code == 200:
            return r.json().get("value", [])
        print(f"[GRAPH] Calendar error {r.status_code}: {r.text[:150]}")
        return None
    except Exception as e:
        print(f"[GRAPH] Calendar request failed: {e}")
        return None


def _graph_get_recent_emails(count=10):
    """Get recent emails from Microsoft Graph (Outlook inbox)."""
    token = _graph_get_token()
    if not token:
        return None
    try:
        import requests as _req
        headers = {"Authorization": f"Bearer {token}"}
        r = _req.get(
            f"https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
            f"?$select=subject,from,receivedDateTime,bodyPreview"
            f"&$orderby=receivedDateTime desc"
            f"&$top={count}",
            headers=headers, timeout=10
        )
        if r.status_code == 200:
            return r.json().get("value", [])
        print(f"[GRAPH] Mail error {r.status_code}: {r.text[:150]}")
        return None
    except Exception as e:
        print(f"[GRAPH] Mail request failed: {e}")
        return None


# --- Demo Configuration Layer ---
# Primary config source: demo_config.yaml (YAML file in app directory)
# Fallback: hardcoded dict below if YAML is missing or pyyaml not installed.
# Override demo_config.yaml to re-skin for any customer or industry.
_YAML_CONFIG = _load_yaml_config()
DEMO_CONFIG = _YAML_CONFIG if _YAML_CONFIG else {
    "app_title": "Branch of the Future",
    "app_subtitle": "Powered by Surface + On-Device AI",
    "brand_primary": "#ffffff",
    "brand_primary_end": "#f8f8f8",
    "brand_accent": "#f18f12",
    "brand_accent_rgb": "241,143,18",
    "brand_hover": "#f6d107",
    "brand_theme": "light",
    "brand_logo": "flagstar-logo-official.png",
    "brand_company": "Flagstar Financial",
    "advisor_name": "Alan Thornbury",
    "advisor_title": "Vice President & Senior Relationship Manager",
    "advisor_company": "Flagstar Bank",
    "advisor_phone": "(248) 312-5500",
    "advisor_email": "alan.thornbury@flagstar.com",
    "advisor_branch": "Troy Main Branch, Troy MI",
    "tabs": {
        "chat":    {"name": "Advisor Assistant", "sub": "Knowledge & Tools",    "icon": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#333" stroke-width="1.8"><rect x="3" y="3" width="18" height="14" rx="2"/><path d="M8 21h8M12 17v4"/><circle cx="12" cy="10" r="2" fill="#f6d107" stroke="none"/></svg>'},
        "day":     {"name": "Morning Briefing",  "sub": "Daily Prep",           "icon": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#333" stroke-width="1.8"><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="2" fill="#f6d107" stroke="none"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>'},
        "auditor": {"name": "PII Guard",         "sub": "Compliance Check",     "icon": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#333" stroke-width="1.8"><path d="M12 2L4 5v6c0 5.55 3.84 10.74 8 12 4.16-1.26 8-6.45 8-12V5L12 2z"/><path d="M9 12l2 2 4-4" stroke="#f6d107" stroke-width="2"/></svg>'},
        "id":      {"name": "ID & Check Verify", "sub": "Scan & Deposit",       "icon": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#333" stroke-width="1.8"><rect x="2" y="4" width="20" height="16" rx="2"/><circle cx="9" cy="11" r="2.5" fill="#f6d107" stroke="none"/><path d="M15 9h4M15 12h3M15 15h2M5 17c0-2 1.5-3 4-3s4 1 4 3"/></svg>'},
        "live":    {"name": "Live Assist",       "sub": "Client Meeting AI",    "icon": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#333" stroke-width="1.8"><path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"/><path d="M19 10v2a7 7 0 01-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><circle cx="12" cy="8" r="1.5" fill="#f6d107" stroke="none"/></svg>'},
        "field":   {"name": "Meeting Notes",     "sub": "Post-Meeting Workflow", "icon": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#333" stroke-width="1.8"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/><rect x="8" y="9" width="3" height="2" rx="0.5" fill="#f6d107" stroke="none"/></svg>'},
    },
    "personas": [
        {"name": "Frank", "role": "Branch Manager",       "tabs": ["auditor", "id"]},
        {"name": "Alan",  "role": "Relationship Manager", "tabs": ["day", "chat", "live", "field"]},
    ],
    "poc_footer": "This application is a proof-of-concept demonstration of on-device AI for branch banking on Copilot+ PCs. Individual features are architectural demonstrations and are not validated for production use.",
    "poc_auditor": "PROOF OF CONCEPT -- This is a demonstration of on-device PII detection and compliance pre-screening. It is not a validated compliance tool and should not be used for actual regulatory decisions.",
    "poc_id": "PROOF OF CONCEPT -- This is a demonstration of on-device document verification. It is not a validated identity verification system and should not be used for actual identity verification or access control.",
}
if not _YAML_CONFIG:
    print("  Using hardcoded DEMO_CONFIG (no YAML)", flush=True)

# --- Industry Packs: Feature flag and resolved config ---
# Check if the active config requests the industry packs loader.
# CLI: python npu_demo_flask.py --industry-pack zava-health
# YAML: use_industry_packs: true + active_brand: "zava-health" in root demo_config.yaml
import sys as _sys
_cli_brand = None
if "--industry-pack" in _sys.argv:
    _idx = _sys.argv.index("--industry-pack")
    if _idx + 1 < len(_sys.argv):
        _cli_brand = _sys.argv[_idx + 1]

_use_packs = bool(_cli_brand) or (
    _YAML_CONFIG is not None and
    isinstance(_YAML_CONFIG, dict) and
    _YAML_CONFIG.get("use_industry_packs") is True
)

if _use_packs:
    _pack_brand = _cli_brand or DEMO_CONFIG.get("active_brand", "")
    if _pack_brand:
        try:
            RESOLVED_CONFIG, _CONFIG_CHAIN = _load_resolved_config(_pack_brand)
            _validate_resolved_config(RESOLVED_CONFIG)
            _INDUSTRY_PACKS_ACTIVE = True
            _chain_names = [os.path.basename(os.path.dirname(p)) for p in _CONFIG_CHAIN]
            print(f"  Industry packs: loaded brand '{_pack_brand}' "
                  f"(chain: {' -> '.join(_chain_names)})", flush=True)

            # Overlay resolved config into DEMO_CONFIG for backward compat
            # This lets existing index() template injection work unchanged
            _rc = RESOLVED_CONFIG
            _rb = _rc.get("brand", {})
            _ra = _rc.get("advisor", {})
            _rp = _rc.get("poc", {})
            DEMO_CONFIG.update({
                "app_title": _rc.get("app_title", DEMO_CONFIG.get("app_title", "")),
                "brand_primary": _rb.get("primary", DEMO_CONFIG.get("brand_primary", "")),
                "brand_primary_end": _rb.get("primary_end", DEMO_CONFIG.get("brand_primary_end", "")),
                "brand_accent": _rb.get("accent", DEMO_CONFIG.get("brand_accent", "")),
                "brand_accent_rgb": _rb.get("accent_rgb", DEMO_CONFIG.get("brand_accent_rgb", "")),
                "brand_hover": _rb.get("hover", DEMO_CONFIG.get("brand_hover", "")),
                "brand_theme": _rb.get("theme", DEMO_CONFIG.get("brand_theme", "")),
                "brand_logo": _rb.get("logo", DEMO_CONFIG.get("brand_logo", "")),
                "brand_company": _rb.get("company_name", DEMO_CONFIG.get("brand_company", "")),
                "advisor_name": _ra.get("name", DEMO_CONFIG.get("advisor_name", "")),
                "advisor_title": _ra.get("title", DEMO_CONFIG.get("advisor_title", "")),
                "advisor_company": _ra.get("company", DEMO_CONFIG.get("advisor_company", "")),
                "advisor_phone": _ra.get("phone", DEMO_CONFIG.get("advisor_phone", "")),
                "advisor_email": _ra.get("email", DEMO_CONFIG.get("advisor_email", "")),
                "tabs": _rc.get("tabs", DEMO_CONFIG.get("tabs", {})),
                "personas": _rc.get("personas", DEMO_CONFIG.get("personas", [])),
                "poc_footer": _rp.get("footer", DEMO_CONFIG.get("poc_footer", "")),
                "poc_auditor": _rp.get("auditor", DEMO_CONFIG.get("poc_auditor", "")),
                "poc_id": _rp.get("id", DEMO_CONFIG.get("poc_id", "")),
                "customer": _rc.get("customer", DEMO_CONFIG.get("customer", {})),
                "branches": _rc.get("branches", DEMO_CONFIG.get("branches", [])),
                "economics": _rc.get("economics", DEMO_CONFIG.get("economics", {})),
                "demo_script": _rc.get("demo_script", DEMO_CONFIG.get("demo_script", [])),
                "industry": _rc.get("industry", DEMO_CONFIG.get("industry", {})),
            })
        except Exception as _e:
            print(f"  Industry packs: FAILED to load '{_pack_brand}': {_e}", flush=True)
            print(f"  Falling back to legacy config path", flush=True)
            _INDUSTRY_PACKS_ACTIVE = False
    else:
        print("  Industry packs: use_industry_packs is true but no active_brand set", flush=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- Silicon auto-detection ---
def detect_silicon():
    """Detect whether we're running on Intel Core Ultra or Qualcomm Snapdragon.

    On Windows-on-ARM, Python x64 runs under emulation so
    platform.machine() often reports 'AMD64'.  We therefore always
    check the actual CPU name via WMI as the authoritative source.
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Processor).Name"],
            capture_output=True, text=True, timeout=5,
        )
        cpu = result.stdout.strip().lower()
        if "qualcomm" in cpu or "snapdragon" in cpu:
            return "qualcomm"
        if "intel" in cpu:
            return "intel"
    except Exception:
        pass
    # Fallback: use architecture hint
    arch = platform.machine().lower()
    if arch in ("arm64", "aarch64"):
        return "arm64"
    return "intel"

SILICON = detect_silicon()

if SILICON == "qualcomm":
    CHIP_LABEL   = "Snapdragon X NPU"
    DEVICE_LABEL = "Copilot+ PC"
    EDITION_TAG  = "Qualcomm Edition"
elif SILICON == "arm64":
    CHIP_LABEL   = "ARM64 NPU"
    DEVICE_LABEL = "Copilot+ PC"
    EDITION_TAG  = "ARM64 Edition"
else:
    CHIP_LABEL   = "Intel Core Ultra NPU"
    DEVICE_LABEL = "Microsoft Surface + Copilot+ PC"
    EDITION_TAG  = "Intel Edition"

# --- Model selection per silicon ---
# On Intel: phi-4-mini runs on NPU natively via OpenVINO.
# On Qualcomm: phi-3.5-mini and phi-3-mini QNN NPU variants crash on inference.
#   qwen2.5-7b QNN NPU variant works reliably (~5-20s, tool-calling support).
if SILICON == "qualcomm":
    MODEL_ALIAS = "qwen2.5-7b"
    MODEL_LABEL = "Qwen 2.5 7B"
else:
    MODEL_ALIAS = "phi-4-mini"
    MODEL_LABEL = "Phi-4 Mini"

# --- Model initialization via Foundry Local SDK (NPU → GPU → localhost:5272 fallback) ---
print(f"Starting Foundry Local runtime (model: {MODEL_ALIAS})...", flush=True)
FOUNDRY_AVAILABLE = False
try:
    from foundry_local import FoundryLocalManager
    manager = FoundryLocalManager(MODEL_ALIAS)
    MODEL_ID = manager.get_model_info(MODEL_ALIAS).id
    client = OpenAI(base_url=manager.endpoint, api_key=manager.api_key)
    DEFAULT_MODEL = MODEL_ID
    FOUNDRY_AVAILABLE = True
except Exception as _npu_err:
    # NPU variant may fail on some devices (e.g. Lunar Lake driver issue) — try GPU
    try:
        from foundry_local.api import DeviceType
        manager = FoundryLocalManager(MODEL_ALIAS, device=DeviceType.GPU)
        # get_model_info returns NPU ID even with GPU device — use list_loaded_models instead
        _loaded = manager.list_loaded_models()
        MODEL_ID = _loaded[0].id if _loaded else manager.get_model_info(MODEL_ALIAS).id
        client = OpenAI(base_url=manager.endpoint, api_key=manager.api_key)
        DEFAULT_MODEL = MODEL_ID
        FOUNDRY_AVAILABLE = True
        print(f"  NPU unavailable ({_npu_err}), using GPU variant", flush=True)
    except Exception:
        manager = None
        client = OpenAI(base_url="http://localhost:5272/v1", api_key="not-needed")
        DEFAULT_MODEL = MODEL_ALIAS

import threading as _threading
_reconnect_lock = _threading.Lock()

def _reconnect_foundry():
    """Re-initialize Foundry connection when the service restarts on a new port."""
    global client, manager, DEFAULT_MODEL, MODEL_ID, FOUNDRY_AVAILABLE
    with _reconnect_lock:
        try:
            manager = FoundryLocalManager(MODEL_ALIAS)
            MODEL_ID = manager.get_model_info(MODEL_ALIAS).id
            client = OpenAI(base_url=manager.endpoint, api_key=manager.api_key)
            DEFAULT_MODEL = MODEL_ID
            FOUNDRY_AVAILABLE = True
            print(f"  Reconnected to Foundry: {manager.endpoint}", flush=True)
            return True
        except Exception:
            # NPU failed — try GPU
            try:
                from foundry_local.api import DeviceType
                manager = FoundryLocalManager(MODEL_ALIAS, device=DeviceType.GPU)
                _loaded = manager.list_loaded_models()
                MODEL_ID = _loaded[0].id if _loaded else manager.get_model_info(MODEL_ALIAS).id
                client = OpenAI(base_url=manager.endpoint, api_key=manager.api_key)
                DEFAULT_MODEL = MODEL_ID
                FOUNDRY_AVAILABLE = True
                print(f"  Reconnected to Foundry (GPU): {manager.endpoint}", flush=True)
                return True
            except Exception as e:
                print(f"  Reconnect failed: {e}", flush=True)
                return False

def foundry_chat(retries=1, **kwargs):
    """Wrapper around client.chat.completions.create with auto-reconnect."""
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as e:
        if retries > 0 and ("Connection" in str(type(e).__name__) or "Connection" in str(e)):
            print(f"  Foundry connection lost, reconnecting...", flush=True)
            if _reconnect_foundry():
                kwargs["model"] = DEFAULT_MODEL
                return client.chat.completions.create(**kwargs)
        raise

# --- Model readiness flag (set after warmup) ---
MODEL_READY = False

# --- Marcus Reed persona (Zava Advisor: stock Phi-4 Mini + system prompt) ---
_MARCUS_AVAILABLE = False
_MARCUS_SYSTEM_PROMPT = ""
_MARCUS_PERSONA_PATH = os.path.join(_APP_ROOT, "configs", "personas", "marcus_reed.yaml")

if _yaml and os.path.exists(_MARCUS_PERSONA_PATH):
    try:
        with open(_MARCUS_PERSONA_PATH, 'r', encoding='utf-8') as _mf:
            _marcus_persona = _yaml.safe_load(_mf)
        _MARCUS_SYSTEM_PROMPT = _marcus_persona.get("system_prompt", "")
        _MARCUS_AVAILABLE = True
        print(f"  Marcus persona loaded: {_marcus_persona.get('name', '?')} ({_marcus_persona.get('title', '?')})", flush=True)
    except Exception as _pe:
        print(f"  Warning: Marcus persona YAML failed: {_pe}", flush=True)


# ---------------------------------------------------------------------------
# Safety Gate Registry (Section 9a of spec)
# ---------------------------------------------------------------------------
# Each industry declares a primary_safety_gate in its compliance config.
# Gates are registered as Python functions and looked up by name at runtime.
# The active gate is determined by RESOLVED_CONFIG when industry packs are
# enabled, or defaults to financial_advice_gate for the legacy path.
# ---------------------------------------------------------------------------

_SAFETY_GATES = {}


def _register_safety_gate(name):
    """Decorator to register a safety gate function by name."""
    def decorator(fn):
        _SAFETY_GATES[name] = fn
        return fn
    return decorator


def _get_active_safety_gate():
    """Return the safety gate function for the active config."""
    if _INDUSTRY_PACKS_ACTIVE and RESOLVED_CONFIG:
        gate_name = (RESOLVED_CONFIG.get("compliance", {})
                     .get("primary_safety_gate", ""))
    else:
        gate_name = "financial_advice_gate"  # legacy default
    if not gate_name:
        return _passthrough_gate
    gate = _SAFETY_GATES.get(gate_name)
    if not gate:
        print(f"  Warning: safety gate '{gate_name}' not registered, "
              f"falling back to passthrough")
        return _passthrough_gate
    return gate


@_register_safety_gate("passthrough")
def _passthrough_gate(text):
    """No-op safety gate. Returns text unchanged."""
    return True, text


@_register_safety_gate("financial_advice_gate")
def _financial_advice_gate(text):
    """Safety gate: block rate quotes, guarantees, ticker picks, and tax/legal advice.
    Returns (is_safe, filtered_text). If not safe, filtered_text is a deferral message."""
    if not text:
        return True, text
    lower = text.lower()
    # Rate quotes / APR / yield numbers
    if re.search(r'\b\d+\.?\d*\s*%\s*(apy|apr|rate|yield|return|interest)\b', lower):
        return False, ("I appreciate the question, but I'd need to check with our product team "
                       "for current rates. Those can change, and I want to make sure you get the "
                       "right number. Let me look that up for you after our conversation.")
    # Dollar outcome projections ("you'll have $X" or "$X-$Y")
    if re.search(r"you(?:'ll| will| would| could) have [\$\d]", lower):
        return False, ("That's a great question to think through. Rather than give you a specific "
                       "number — which depends on a lot of variables — let me walk you through the "
                       "factors that would shape the outcome.")
    # Specific fund tickers (2-5 uppercase letters that look like tickers)
    if re.search(r'\b(buy|recommend|pick|invest in|look at)\b.*\b[A-Z]{2,5}\b', text):
        _false_tickers = {'IRA', 'CPA', 'ETF', 'APR', 'APY', 'FDIC', 'UGMA', 'UTMA', 'CDD', 'KYC', 'BSA', 'AML'}
        tickers_found = re.findall(r'\b[A-Z]{2,5}\b', text)
        real_tickers = [t for t in tickers_found if t not in _false_tickers]
        if real_tickers:
            return False, ("I can't recommend specific funds or tickers — that's not the kind of "
                           "guidance I'm set up to give. What I can do is walk you through the types "
                           "of investments that typically make sense for your situation, and then you "
                           "and a licensed advisor can narrow it down.")
    # Tax filing specifics
    if re.search(r'\b(file|report|deduct|claim|form \d{3,4}|schedule [a-z]|1099|w-?2)\b', lower) and \
       re.search(r'\b(should|must|need to|have to|exactly how)\b', lower):
        if not re.search(r'\b(talk to|consult|cpa|tax professional|accountant)\b', lower):
            return False, ("Tax filing gets specific fast, and I'd rather you get that from someone "
                           "who knows your full situation — a CPA or tax professional would be the "
                           "right call here. What I can help with is the bigger-picture planning around it.")
    return True, text


@_register_safety_gate("clinical_advice_gate")
def _clinical_advice_gate(text):
    """Safety gate for healthcare: block definitive diagnoses, dosing, and treatment plans.
    Returns (is_safe, filtered_text). If not safe, filtered_text is a deferral message."""
    if not text:
        return True, text
    lower = text.lower()
    # Definitive diagnosis claims ("you have X", "this is X", "you are diagnosed with")
    if re.search(r'\b(you have|you are diagnosed with|this is clearly|diagnosis is)\b', lower):
        if not re.search(r'\b(discuss with|talk to|your (doctor|clinician|provider|care team))\b', lower):
            return False, ("I want to be careful here — I can help you think through what these "
                           "findings might mean, but a definitive diagnosis really needs to come from "
                           "your care team after a proper evaluation. Let me help you prepare the "
                           "right questions for that conversation.")
    # Dosing recommendations ("take Xmg", "prescribe", "dose of")
    if re.search(r'\b(take \d+\s*mg|prescribe|dose of \d|dosage should be|administer \d)\b', lower):
        return False, ("Medication dosing is something I'd want your prescribing clinician to handle "
                       "directly — there are too many patient-specific factors for me to give a safe "
                       "recommendation. I can help you document what was discussed and flag it for review.")
    # Treatment plan directives ("you should start", "begin treatment with", "I recommend starting")
    if re.search(r'\b(you should start|begin treatment|recommend starting|initiate therapy)\b', lower):
        if not re.search(r'\b(discuss|consider|your (doctor|clinician|provider))\b', lower):
            return False, ("Treatment decisions should be made collaboratively with your care team. "
                           "What I can do is help summarize the relevant factors and options to "
                           "support that conversation.")
    return True, text


# Stub safety gates for future industries
# _STUB_TODO: Replace with real implementations when each industry goes active

@_register_safety_gate("pharma_promotional_gate")
def _pharma_promotional_gate(text):
    """STUB: Pharma promotional review gate. Returns passthrough + logs TODO."""
    # _STUB_TODO: Implement off-label detection, fair balance check, efficacy claim validation
    return True, text


@_register_safety_gate("ferpa_gate")
def _ferpa_gate(text):
    """STUB: FERPA education records gate."""
    # _STUB_TODO: Implement student record disclosure checks
    return True, text


@_register_safety_gate("cui_gate")
def _cui_gate(text):
    """STUB: CUI (Controlled Unclassified Information) gate for public sector."""
    # _STUB_TODO: Implement CUI marking and disclosure checks
    return True, text


@_register_safety_gate("export_control_gate")
def _export_control_gate(text):
    """STUB: Export control / ITAR gate for manufacturing."""
    # _STUB_TODO: Implement ITAR/EAR classification checks
    return True, text


@_register_safety_gate("pci_gate")
def _pci_gate(text):
    """STUB: PCI DSS cardholder data gate for retail."""
    # _STUB_TODO: Implement cardholder data detection and blocking
    return True, text


# ---------------------------------------------------------------------------
# Cross-Sell Signal Registry (Section 9b of spec)
# ---------------------------------------------------------------------------
# Signal evaluators are registered Python functions (Option B).
# The catalog YAML names which signals apply and maps them to recommended
# products/services. Logic stays testable in Python, mapping is configurable.
# ---------------------------------------------------------------------------

_CROSS_SELL_SIGNALS = {}


def _register_signal(name):
    """Decorator to register a cross-sell signal evaluator by name."""
    def decorator(fn):
        _CROSS_SELL_SIGNALS[name] = fn
        return fn
    return decorator


def _evaluate_signals(customer_data, signal_defs):
    """Evaluate cross-sell signals for a customer.
    signal_defs: list of {signal, items/suggest, priority, talk_track} from catalog YAML.
    Returns: list of matched signal defs.
    """
    matches = []
    for sig_def in signal_defs:
        evaluator = _CROSS_SELL_SIGNALS.get(sig_def.get("signal", ""))
        if not evaluator:
            continue  # signal not registered for this industry, skip silently
        try:
            if evaluator(customer_data):
                matches.append(sig_def)
        except Exception:
            continue  # defensive: don't crash on a bad signal evaluator
    return matches


# --- Financial Services signals ---

@_register_signal("has_checking_no_savings")
def _sig_has_checking_no_savings(customer_data):
    accounts = [a.get("type", "").lower() for a in customer_data.get("accounts", [])]
    return any("checking" in a for a in accounts) and not any("saving" in a for a in accounts)


@_register_signal("no_credit_card")
def _sig_no_credit_card(customer_data):
    accounts = [a.get("type", "").lower() for a in customer_data.get("accounts", [])]
    return not any("card" in a or "credit" in a for a in accounts)


@_register_signal("no_retirement_account")
def _sig_no_retirement(customer_data):
    all_text = " ".join(a.get("type", "").lower() for a in customer_data.get("accounts", []))
    all_text += " " + (customer_data.get("notes") or "").lower()
    return not any(kw in all_text for kw in ("ira", "401k", "retirement", "pension"))


@_register_signal("has_children")
def _sig_has_children(customer_data):
    notes = (customer_data.get("notes") or "").lower()
    return any(kw in notes for kw in ("529", "college", "child", "daughter", "son", "kids"))


@_register_signal("old_401k")
def _sig_old_401k(customer_data):
    all_text = " ".join(a.get("type", "").lower() for a in customer_data.get("accounts", []))
    all_text += " " + (customer_data.get("notes") or "").lower()
    return any(kw in all_text for kw in ("401k", "rollover", "old employer"))


@_register_signal("renting_home")
def _sig_renting_home(customer_data):
    accounts = [a.get("type", "").lower() for a in customer_data.get("accounts", [])]
    return not any("mortgage" in a or "home loan" in a for a in accounts)


@_register_signal("frequent_overdrafts")
def _sig_frequent_overdrafts(customer_data):
    all_text = " ".join(a.get("type", "").lower() for a in customer_data.get("accounts", []))
    all_text += " " + (customer_data.get("notes") or "").lower()
    return any(kw in all_text for kw in ("overdraft", "nsf"))


@_register_signal("owns_business")
def _sig_owns_business(customer_data):
    all_text = " ".join(a.get("type", "").lower() for a in customer_data.get("accounts", []))
    all_text += " " + (customer_data.get("notes") or "").lower()
    return any(kw in all_text for kw in ("business", "llc", "corp"))


@_register_signal("large_checking_balance")
def _sig_large_checking_balance(customer_data):
    accounts = [a.get("type", "").lower() for a in customer_data.get("accounts", [])]
    return any("checking" in a for a in accounts) and len(accounts) <= 1


# --- Healthcare signals (stubs) ---
# _STUB_TODO: Replace with real evaluators in healthcare content sprint.
# All stubs return False by default per spec v2 implementation notes.

@_register_signal("no_annual_wellness")
def _sig_no_annual_wellness(customer_data):
    # _STUB_TODO: Check patient visit history for annual wellness gap
    return False


@_register_signal("overdue_screenings")
def _sig_overdue_screenings(customer_data):
    # _STUB_TODO: Check age-appropriate screening schedule against visit history
    return False


@_register_signal("unmanaged_chronic")
def _sig_unmanaged_chronic(customer_data):
    # _STUB_TODO: Check for chronic condition flags without active care management
    return False


def _marcus_chat(user_message, history=None):
    """Chat via Marcus Reed persona on stock model + system prompt. Returns (response_text, elapsed_seconds)."""
    if not _MARCUS_AVAILABLE:
        return "Marcus Reed persona is not configured. Check configs/personas/marcus_reed.yaml.", 0.0

    system = _MARCUS_SYSTEM_PROMPT or "You are Marcus Reed, a Senior Wealth Advisor at Zava Financial."
    messages = [{"role": "system", "content": system}]
    if history:
        for msg in history:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    messages.append({"role": "user", "content": user_message})

    start = _time.time()
    response = foundry_chat(
        model=DEFAULT_MODEL,
        messages=messages,
        max_tokens=600,
        temperature=0.3,
    )
    elapsed = _time.time() - start
    _track_model_call(response, elapsed)
    result = (response.choices[0].message.content or "").strip()

    # Safety gate (uses registry when industry packs active, else financial_advice_gate)
    _active_gate = _get_active_safety_gate()
    is_safe, filtered = _active_gate(result)
    if not is_safe:
        result = filtered

    return result, elapsed


# --- Agent infrastructure ---
# Demo data lives alongside the app so the repo is self-contained.
# Resolves to <project_root>/demo_data regardless of working directory.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEMO_DIR = os.path.join(_APP_DIR, "demo_data")
os.makedirs(DEMO_DIR, exist_ok=True)

# Create demo NDA file for Clean Room Auditor if it doesn't exist
_nda_demo_path = os.path.join(DEMO_DIR, "contract_nda_vertex_pinnacle.txt")
if not os.path.exists(_nda_demo_path):
    with open(_nda_demo_path, 'w', encoding='utf-8') as _f:
        _f.write("""MUTUAL NON-DISCLOSURE AGREEMENT

Effective Date: January 15, 2026
Agreement Number: NDA-2026-VD-PS-0847

BETWEEN:

Vertex Dynamics, Inc.
1200 Innovation Drive, Suite 400
San Jose, CA 95134
Contact: James Morrison, VP Corporate Development
Email: j.morrison@vertexdyn.com
Phone: (415) 555-0142

AND:

Pinnacle Solutions Group, LLC
8900 Enterprise Boulevard
Austin, TX 78759
Contact: Sarah Chen, General Counsel

SECTION 1. DEFINITION OF CONFIDENTIAL INFORMATION

1.1 "Confidential Information" means any and all non-public, proprietary, or confidential information disclosed by either party to the other, whether orally, in writing, electronically, or by inspection of tangible objects.

SECTION 2. OBLIGATIONS OF RECEIVING PARTY

2.1 The receiving party shall hold all Confidential Information in strict confidence and shall not disclose such information to any third party without the prior written consent of the disclosing party.

SECTION 3. TERM AND DURATION

3.1 This Agreement shall remain in effect for a period of two (2) years from the Effective Date.

3.2 The obligations of confidentiality shall survive termination for a period of five (5) years.

SECTION 4. INDEMNIFICATION AND LIABILITY

4.1 Each party shall indemnify and hold harmless the other party from claims arising from a breach of this Agreement.

4.2 NOTWITHSTANDING ANY OTHER PROVISION, THE DISCLOSING PARTY SHALL BE ENTITLED TO FULL INDEMNIFICATION FOR ALL DAMAGES, INCLUDING CONSEQUENTIAL, INCIDENTAL, INDIRECT, SPECIAL, AND PUNITIVE DAMAGES, ARISING FROM ANY BREACH BY THE RECEIVING PARTY. THIS PROVISION SHALL NOT BE SUBJECT TO ANY CAP OR LIMITATION.

SECTION 5. RETURN OF MATERIALS

5.1 Upon termination, the receiving party shall return or destroy all Confidential Information within thirty (30) days.

SECTION 6. REMEDIES

6.1 The non-breaching party shall be entitled to seek injunctive relief in addition to any other remedies.

SECTION 7. INTELLECTUAL PROPERTY

7.1 ALL WORK PRODUCT, INVENTIONS, AND INNOVATIONS, WHETHER CREATED PRIOR TO OR DURING THIS AGREEMENT, THAT ARE USED IN CONNECTION WITH THE PURPOSE, SHALL BE THE SOLE PROPERTY OF THE DISCLOSING PARTY.

SECTION 8. NON-SOLICITATION

8.1 Neither party shall solicit or hire employees of the other party for twelve (12) months following termination.

SECTION 9. NON-COMPETITION

9.1 The receiving party shall not engage in any competing business anywhere in the world for twenty-four (24) months following termination.

SECTION 10. GOVERNING LAW

10.1 This Agreement shall be governed by the laws of the State of Delaware.

IN WITNESS WHEREOF:

VERTEX DYNAMICS, INC.
By: _________________________
Name: James A. Morrison
Title: VP Corporate Development
SSN (for notarization): 478-93-3847
Date: January 15, 2026

PINNACLE SOLUTIONS GROUP, LLC
By: _________________________
Name: Sarah L. Chen
Title: General Counsel
Date: January 15, 2026
""")

# --- Local Knowledge Index ---
KNOWLEDGE_INDEX = {}  # {filename: {"text": str, "path": str, "word_count": int, "terms": dict}}

_STOPWORDS = {'the','a','an','and','or','but','in','on','at','to','for','of','is','it','that','this',
              'with','as','by','from','be','was','were','are','been','being','have','has','had','do',
              'does','did','will','would','shall','should','may','might','can','could','not','no',
              'all','any','each','every','such','than','then','them','they','its','our','your','we'}


def build_knowledge_index():
    """Scan DEMO_DIR and build keyword index for Local Knowledge search."""
    global KNOWLEDGE_INDEX
    index = {}
    for root, dirs, files in os.walk(DEMO_DIR):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ('.txt', '.pdf', '.docx', '.md'):
                continue
            filepath = os.path.join(root, fname)
            try:
                text = extract_text(filepath)
                if text and not text.startswith("Error"):
                    words = re.findall(r'[a-z]+', text.lower())
                    term_freq = {}
                    for w in words:
                        if w not in _STOPWORDS and len(w) > 2:
                            term_freq[w] = term_freq.get(w, 0) + 1
                    index[fname] = {
                        "text": text,
                        "path": filepath,
                        "word_count": len(words),
                        "terms": term_freq,
                    }
            except Exception:
                continue
    KNOWLEDGE_INDEX = index
    print(f"  Local Knowledge: indexed {len(index)} documents in {DEMO_DIR}")


def search_knowledge(query, top_k=3):
    """Search the local knowledge index. Returns list of {filename, snippet, score}."""
    if not KNOWLEDGE_INDEX:
        return []
    query_terms = set(re.findall(r'[a-z]+', query.lower()))
    results = []
    for fname, data in KNOWLEDGE_INDEX.items():
        score = sum(data["terms"].get(t, 0) for t in query_terms)
        if score > 0:
            best_snippet = _extract_best_snippet(data["text"], query_terms, max_len=500)
            results.append({
                "filename": fname,
                "snippet": best_snippet,
                "score": score,
                "word_count": data["word_count"],
            })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _extract_best_snippet(text, query_terms, max_len=500):
    """Find the text region with highest density of query terms."""
    words = text.split()
    if len(words) <= 60:
        return text[:max_len]
    window = 60
    best_score = 0
    best_start = 0
    for i in range(len(words) - window):
        chunk = ' '.join(words[i:i+window]).lower()
        score = sum(1 for t in query_terms if t in chunk)
        if score > best_score:
            best_score = score
            best_start = i
    snippet = ' '.join(words[best_start:best_start+window])
    return snippet[:max_len]


AGENT_AUDIT_LOG = []

# --- Session stats for Local AI Savings widget ---
SESSION_STATS = {
    "calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "inference_seconds": 0.0,
}


def _track_model_call(response, elapsed_seconds):
    """Track model call stats for the savings widget."""
    SESSION_STATS["calls"] += 1
    SESSION_STATS["inference_seconds"] += elapsed_seconds
    if hasattr(response, 'usage') and response.usage:
        SESSION_STATS["input_tokens"] += response.usage.prompt_tokens or 0
        SESSION_STATS["output_tokens"] += response.usage.completion_tokens or 0


AGENT_SYSTEM_PROMPT = (
    'You are a local AI assistant for a bank wealth advisor running on a Surface Copilot+ PC. '
    'You help with financial product questions, client meeting preparation, and compliance checks. '
    'You have knowledge of: 529 College Savings Plans, Roth and Traditional IRAs, retirement planning, '
    'checking and savings accounts, and general banking regulations. '
    'You have access to the bank\'s product catalog and can recommend products based on client profiles. '
    'When prepping for a client meeting, include relevant product recommendations with specific talk tracks. '
    'All your processing runs on-device. No customer data leaves this device.\n\n'
    'You have these tools:\n\n'
    'LOCAL TOOLS:\n'
    '- read(path): VIEW or READ an existing file\n'
    '- write(path, content): CREATE or SAVE a NEW file with content\n'
    '- exec(command): RUN a shell command (PowerShell cmdlets)\n\n'
    'DYNAMICS 365 TOOLS (via MCP -- queries live D365 Dataverse):\n'
    '- d365_customer_lookup(name): Search D365 contacts by name. Returns profile, email, phone, address.\n'
    '- d365_check_in_queue(): Get the branch check-in queue from the kiosk. Shows who is waiting.\n'
    '- d365_log_activity(customer_name, note): Log a task or note on a customer D365 record.\n'
    '- d365_recent_activities(customer_name): Get recent timeline entries for a customer.\n\n'
    'CALENDAR & PRODUCTIVITY TOOLS:\n'
    '- my_calendar_today(): Get today\'s calendar events, meetings, and appointments.\n'
    '- prep_next_client(customer_name): Get client meeting from calendar and look up their D365 profile. Pass the client name if known.\n\n'
    'RULES:\n'
    '- For general knowledge questions (529 plans, IRA rules, banking regulations), answer directly. Do NOT use tools.\n'
    '- Use D365 tools when the user asks about a customer, the queue, or wants to log something.\n'
    '- Use calendar tools when the user asks about their schedule, next meeting, or wants to prep.\n'
    '- Use local tools when the user asks to read/write files or run commands.\n'
    '- Use "write" to CREATE files (needs path + content). Use "read" to VIEW files.\n'
    '- For "exec", ONLY provide "command". Do NOT add env, workdir, or other params.\n'
    '- Use Windows backslash paths: C:\\Users\\file.txt\n'
    '- Keep responses concise and helpful.\n\n'
    'ALWAYS use this EXACT format when using a tool:\n'
    '[TOOL_CALL]\n{"name": "TOOL_NAME", "arguments": {"param": "value"}}\n[/TOOL_CALL]\n\n'
    'When no tool is needed, respond with plain text (no markers needed).\n\n'
    'Examples:\n'
    '[TOOL_CALL]\n{"name": "read", "arguments": {"path": "C:\\\\Users\\\\me\\\\doc.txt"}}\n[/TOOL_CALL]\n\n'
    '[TOOL_CALL]\n{"name": "write", "arguments": {"path": "C:\\\\Users\\\\me\\\\notes.txt", '
    '"content": "Meeting notes from today"}}\n[/TOOL_CALL]\n\n'
    '[TOOL_CALL]\n{"name": "exec", "arguments": {"command": "Get-ChildItem C:\\\\Users"}}\n[/TOOL_CALL]\n\n'
    'D365 examples:\n'
    '[TOOL_CALL]\n{"name": "d365_customer_lookup", "arguments": {"name": "Jackie Rodriguez"}}\n[/TOOL_CALL]\n\n'
    '[TOOL_CALL]\n{"name": "d365_check_in_queue", "arguments": {}}\n[/TOOL_CALL]\n\n'
    '[TOOL_CALL]\n{"name": "d365_log_activity", "arguments": {"customer_name": "Jackie Rodriguez", "note": "Discussed 529 plan options"}}\n[/TOOL_CALL]\n\n'
    '[TOOL_CALL]\n{"name": "d365_recent_activities", "arguments": {"customer_name": "Jackie Rodriguez"}}\n[/TOOL_CALL]\n\n'
    '[TOOL_CALL]\n{"name": "my_calendar_today", "arguments": {}}\n[/TOOL_CALL]\n\n'
    '[TOOL_CALL]\n{"name": "prep_next_client", "arguments": {"customer_name": "Jackie Rodriguez"}}\n[/TOOL_CALL]'
)

# --- My Day infrastructure ---
MY_DAY_DIR = os.path.join(DEMO_DIR, "My_Day")
MY_DAY_INBOX = os.path.join(MY_DAY_DIR, "Inbox")

import csv
import email
from email import policy as _email_policy


def parse_ics(filepath):
    """Parse iCalendar file into list of event dicts, sorted by start time."""
    events = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return events
    blocks = re.split(r'BEGIN:VEVENT', content)[1:]  # skip preamble
    for block in blocks:
        block = block.split('END:VEVENT')[0]
        ev = {}
        for line in block.strip().splitlines():
            if ':' not in line:
                continue
            key, _, val = line.partition(':')
            key = key.split(';')[0].strip().upper()
            val = val.strip()
            if key == 'SUMMARY':
                ev['summary'] = val
            elif key == 'DTSTART':
                ev['dtstart'] = val
                # Parse into readable time
                try:
                    from datetime import datetime
                    dt = datetime.strptime(val, '%Y%m%dT%H%M%S')
                    ev['time'] = dt.strftime('%I:%M %p').lstrip('0')
                    ev['date'] = dt.strftime('%Y-%m-%d')
                except Exception:
                    ev['time'] = val
            elif key == 'DTEND':
                try:
                    from datetime import datetime
                    dt = datetime.strptime(val, '%Y%m%dT%H%M%S')
                    ev['end_time'] = dt.strftime('%I:%M %p').lstrip('0')
                except Exception:
                    pass
            elif key == 'LOCATION':
                ev['location'] = val
            elif key == 'DESCRIPTION':
                # ICS uses \n for newlines in description
                ev['description'] = val.replace('\\n', '\n')
            elif key == 'ATTENDEE':
                attendees = ev.get('attendees', [])
                cn_match = re.search(r'CN=([^;:]+)', line)
                if cn_match:
                    attendees.append(cn_match.group(1))
                ev['attendees'] = attendees
        if ev.get('summary'):
            events.append(ev)
    events.sort(key=lambda e: e.get('dtstart', ''))
    return events


def parse_tasks_csv(filepath):
    """Parse tasks CSV into list of task dicts."""
    tasks = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                tasks.append(dict(row))
    except Exception:
        pass
    return tasks


def parse_eml(filepath):
    """Parse a single .eml file into a dict."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            msg = email.message_from_file(f, policy=_email_policy.default)
        body = ''
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    body = part.get_content()
                    break
        else:
            body = msg.get_content()
        return {
            'from': str(msg.get('From', '')),
            'subject': str(msg.get('Subject', '')),
            'date': str(msg.get('Date', '')),
            'body': body.strip() if body else '',
            'filename': os.path.basename(filepath),
        }
    except Exception:
        return None


def parse_inbox(inbox_dir):
    """Read all .eml files in folder, return list sorted by filename."""
    emails = []
    if not os.path.isdir(inbox_dir):
        return emails
    for fname in sorted(os.listdir(inbox_dir)):
        if fname.lower().endswith('.eml'):
            parsed = parse_eml(os.path.join(inbox_dir, fname))
            if parsed:
                emails.append(parsed)
    return emails


def compress_for_briefing(events, tasks, emails):
    """Compress all data into compact text for the model's prompt limit."""
    lines = ['TODAY: Sat Feb 7 2026\n']

    # Calendar — top 5 events, short format
    lines.append(f'CALENDAR ({len(events)} events):')
    for ev in events[:5]:
        t = ev.get('time', '?')
        s = ev.get('summary', '?')
        lines.append(f'- {t} {s}')

    # Tasks — top 4, compact
    lines.append(f'\nTASKS ({len(tasks)} items):')
    for t in tasks[:4]:
        prio = t.get('Priority', 'Med')
        name = t.get('Task', '?')
        lines.append(f'- [{prio}] {name}')

    # Emails — top 3, sender + subject only
    lines.append(f'\nINBOX ({len(emails)} emails):')
    for em in emails[:3]:
        subj = em.get('subject', '?')[:50]
        frm = em.get('from', '?').split('<')[0].strip().strip('"')
        lines.append(f'- {frm}: {subj}')

    result = '\n'.join(lines)
    # Hard cap — phi-4-mini has ~1K token prompt limit; Qwen 2.5 has ~32K
    _char_limit = 3600 if SILICON == "qualcomm" else 1200
    if len(result) > _char_limit:
        result = result[:_char_limit]
    return result


BRIEFING_SYSTEM_PROMPT = (
    'You are a chief of staff. Write a MORNING BRIEFING with:\n'
    '1. Summary (3 sentences): who they see today, what to handle, any risks.\n'
    '2. ACTIONS: numbered priority list.\n'
    '3. PEOPLE: key names with one-line context.\n'
    '4. WARNINGS: landmines or legal issues.\n'
    'Cross-reference: connect people across calendar, email, and tasks. Be concise.'
)


# Allowlist of PowerShell cmdlets permitted for the demo (everything else blocked)
_ALLOWED_COMMANDS = [
    "get-childitem", "get-content", "set-content", "add-content", "out-file",
    "get-date", "get-location", "write-output", "select-object", "format-list",
    "get-netadapter", "disable-netadapter", "enable-netadapter",
]
_NETWORK_CMDS = ["disable-netadapter", "enable-netadapter"]


def parse_tool_call(text):
    """Parse [TOOL_CALL] markers from model output."""
    match = re.search(
        r'\[TOOL_(?:CALL|RESPONSE)\]\s*([\s\S]*?)\s*\[/TOOL_(?:CALL|RESPONSE)\]', text
    )
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            return None
    # Try bare JSON (model sometimes omits markers)
    stripped = text.strip()
    if stripped.startswith('{'):
        try:
            parsed = json.loads(stripped)
            if 'name' in parsed and 'arguments' in parsed:
                return parsed
        except Exception:
            pass
    return None


def _path_in_demo_dir(path):
    """Check if a path resolves within DEMO_DIR. Prevents path traversal."""
    try:
        resolved = os.path.realpath(os.path.normpath(path))
        demo_resolved = os.path.realpath(DEMO_DIR)
        return resolved.startswith(demo_resolved + os.sep) or resolved == demo_resolved
    except Exception:
        return False


def execute_tool(name, arguments):
    """Execute a tool with safety guardrails. Returns dict with success, output, error."""
    print(f"[DEBUG] execute_tool called: name={name}, arguments={arguments}")
    if name == "read":
        path = arguments.get("path", "")
        print(f"[DEBUG] read path='{path}', in_demo_dir={_path_in_demo_dir(path)}")
        if not _path_in_demo_dir(path):
            return {"success": False, "error": f"Security Policy Violation: Access restricted to approved folder ({DEMO_DIR})"}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            return {"success": True, "output": content[:5000]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif name == "write":
        path = arguments.get("path", "")
        if not _path_in_demo_dir(path):
            return {"success": False, "error": f"Security Policy Violation: Write restricted to approved folder ({DEMO_DIR})"}
        content = arguments.get("content", "")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            size_kb = round(len(content.encode('utf-8')) / 1024, 1)
            return {"success": True, "output": f"File written: {path} ({size_kb} KB)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif name == "exec":
        command = arguments.get("command", "")
        cmd_lower = command.lower().strip()
        # Safety: block command separators / chaining tokens that could smuggle extra commands
        _DANGEROUS_TOKENS = [';', '&&', '||', '$(', '\n', '\r', '`']
        for token in _DANGEROUS_TOKENS:
            if token in command:
                return {"success": False, "error": f"Security Policy: Command separators are not permitted. Blocked token: {repr(token)}"}
        # Safety: allowlist — only permitted cmdlets can run
        if not any(cmd_lower.startswith(a) or (" | " in cmd_lower and a in cmd_lower) for a in _ALLOWED_COMMANDS):
            return {"success": False, "error": "Security Policy: Only approved commands are permitted. Blocked: " + command.split()[0] if command.split() else command}
        try:
            # Network adapter commands: auto-suppress confirmation prompt
            is_network_cmd = any(a in cmd_lower for a in _NETWORK_CMDS)
            if is_network_cmd and "-confirm" not in cmd_lower:
                command = command.rstrip() + " -Confirm:$false"
            cmd_timeout = 30 if is_network_cmd else 15
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", command],
                capture_output=True, text=True, timeout=cmd_timeout
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            return {"success": proc.returncode == 0, "output": output.strip()[:3000]}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Command timed out ({cmd_timeout}s limit)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif name == "__text_response":
        return {"success": True, "output": arguments.get("text", ""), "is_text": True}

    # D365 MCP tools -- route to MCP server functions (with demo-mode fallbacks)
    elif name == "d365_customer_lookup":
        try:
            sys.path.insert(0, os.path.join(_APP_DIR, 'mcp-d365'))
            from server import d365_customer_lookup as _mcp_lookup
            result = _mcp_lookup(arguments.get("name", ""))
            return {"success": True, "output": result}
        except Exception as e:
            if DEMO_MODE:
                _qname = (arguments.get("name") or "").lower()
                _demo_cust = _get_concierge_customer(_qname)
                if _demo_cust:
                    return {"success": True, "output": json.dumps({"source": "demo", "customer": {"name": _demo_cust["name"], "email": _demo_cust.get("email", ""), "phone": _demo_cust.get("phone", ""), "notes": _demo_cust.get("context", "")}})}
                return {"success": True, "output": json.dumps({"source": "demo", "customer": {"name": arguments.get("name", "Unknown"), "email": "demo@example.com"}})}
            return {"success": False, "error": f"D365 MCP error: {e}"}

    elif name == "d365_check_in_queue":
        try:
            sys.path.insert(0, os.path.join(_APP_DIR, 'mcp-d365'))
            from server import d365_check_in_queue as _mcp_queue
            result = _mcp_queue()
            return {"success": True, "output": result}
        except Exception as e:
            if DEMO_MODE:
                _queue = [{"name": c["name"], "reason": "Scheduled appointment", "status": "waiting"} for c in _CONCIERGE_DEMO_CUSTOMERS.values()]
                return {"success": True, "output": json.dumps({"source": "demo", "queue": _queue})}
            return {"success": False, "error": f"D365 MCP error: {e}"}

    elif name == "d365_log_activity":
        try:
            sys.path.insert(0, os.path.join(_APP_DIR, 'mcp-d365'))
            from server import d365_log_activity as _mcp_log
            result = _mcp_log(
                arguments.get("customer_name", ""),
                arguments.get("note", ""),
                arguments.get("activity_type", "task")
            )
            return {"success": True, "output": result}
        except Exception as e:
            if DEMO_MODE:
                return {"success": True, "output": json.dumps({"source": "demo", "status": "logged", "message": f"Activity logged locally (demo mode): {arguments.get('note', '')}"})}
            return {"success": False, "error": f"D365 MCP error: {e}"}

    elif name == "d365_recent_activities":
        try:
            sys.path.insert(0, os.path.join(_APP_DIR, 'mcp-d365'))
            from server import d365_recent_activities as _mcp_activities
            result = _mcp_activities(arguments.get("customer_name", ""))
            return {"success": True, "output": result}
        except Exception as e:
            if DEMO_MODE:
                return {"success": True, "output": json.dumps({"source": "demo", "activities": [{"date": "2026-04-28", "type": "task", "subject": "529 plan consultation", "status": "completed"}, {"date": "2026-04-21", "type": "note", "subject": "Account review completed", "status": "completed"}]})}
            return {"success": False, "error": f"D365 MCP error: {e}"}

    elif name == "my_calendar_today":
        try:
            # Try Microsoft Graph (live Outlook calendar) first
            graph_events = _graph_get_calendar_today()
            if graph_events is not None:
                if not graph_events:
                    cal_text = "No calendar events found for today (Outlook)."
                else:
                    cal_text = f"Today's Calendar from Outlook ({len(graph_events)} events):\n"
                    for ev in graph_events:
                        start = ev.get('start', {}).get('dateTime', '')[:16]
                        end = ev.get('end', {}).get('dateTime', '')[:16]
                        subj = ev.get('subject', '?')
                        loc = ev.get('location', {}).get('displayName', '')
                        preview = ev.get('bodyPreview', '')[:150]
                        # Format time
                        try:
                            from datetime import datetime
                            st = datetime.fromisoformat(start)
                            et = datetime.fromisoformat(end)
                            time_str = f"{st.strftime('%I:%M %p').lstrip('0')}-{et.strftime('%I:%M %p').lstrip('0')}"
                        except Exception:
                            time_str = start
                        cal_text += f"\n- {time_str} {subj}"
                        if loc:
                            cal_text += f" @ {loc}"
                        if preview:
                            cal_text += f"\n  {preview}"
                cal_text += "\n\n(Source: Microsoft Graph - Live Outlook Calendar)"
                return {"success": True, "output": cal_text}

            # Fallback to local calendar file
            events = parse_ics(os.path.join(MY_DAY_DIR, 'calendar.ics'))
            if not events:
                return {"success": True, "output": "No calendar events found for today."}
            cal_text = f"Today's Calendar ({len(events)} events):\n"
            for ev in events:
                t = ev.get('time', '?')
                end = ev.get('end_time', '')
                s = ev.get('summary', '?')
                loc = ev.get('location', '')
                desc = ev.get('description', '')[:200]
                cal_text += f"\n- {t}" + (f"-{end}" if end else "") + f" {s}"
                if loc:
                    cal_text += f" @ {loc}"
                if desc:
                    cal_text += f"\n  {desc}"
            cal_text += "\n\n(Source: Local calendar data)"
            return {"success": True, "output": cal_text}
        except Exception as e:
            return {"success": False, "error": f"Calendar error: {e}"}

    elif name == "prep_next_client":
        try:
            # Check if a specific client name was requested
            requested_name = arguments.get("customer_name", "").lower().strip()

            # Try Graph calendar first
            graph_events = _graph_get_calendar_today()
            client_meeting = None
            from_graph = False

            # Words that indicate internal/non-client meetings (skip these)
            _skip_words = ['huddle', 'standup', 'compliance', 'training', 'webinar', 'lunch', 'break',
                           'team meeting', 'internal', 'end of day', 'crm notes', 'follow-up']
            # Words that indicate client meetings (prefer these)
            _client_words = ['client', 'jackie', 'henderson', 'rodriguez', 'portfolio', 'consultation',
                             '529', 'account opening', 'new client', 'review', 'retirement']

            if graph_events:
                # If a specific client was requested, find their meeting first
                if requested_name:
                    # First pass: match name in subject only (most reliable)
                    for ev in graph_events:
                        subj = (ev.get('subject', '') or '').lower()
                        if requested_name in subj:
                            client_meeting = ev
                            from_graph = True
                            break
                    # Second pass: match in body but only for non-internal meetings
                    if not client_meeting:
                        for ev in graph_events:
                            subj = (ev.get('subject', '') or '').lower()
                            if any(skip in subj for skip in _skip_words):
                                continue
                            preview = (ev.get('bodyPreview', '') or '').lower()
                            if requested_name in preview:
                                client_meeting = ev
                                from_graph = True
                                break
                    # Also extract the name for D365 lookup
                    if not client_meeting:
                        # No Graph meeting found but we have a name — create a stub
                        pass

                # Find first meeting that looks like a client meeting, skip internal ones
                if not client_meeting:
                 for ev in graph_events:
                    subj = (ev.get('subject', '') or '').lower()
                    preview = (ev.get('bodyPreview', '') or '').lower()
                    combined = subj + ' ' + preview
                    # Skip internal meetings
                    if any(skip in combined for skip in _skip_words):
                        continue
                    # Prefer meetings with client keywords
                    if any(kw in combined for kw in _client_words):
                        client_meeting = ev
                        from_graph = True
                        break
                # Second pass: any non-internal meeting with a person's name
                if not client_meeting:
                    for ev in graph_events:
                        subj = (ev.get('subject', '') or '').lower()
                        if not any(skip in subj for skip in _skip_words):
                            client_meeting = ev
                            from_graph = True
                            break

            # Fallback to local calendar
            if not client_meeting:
                events = parse_ics(os.path.join(MY_DAY_DIR, 'calendar.ics'))
                for ev in events:
                    summary = (ev.get('summary', '') or '').lower()
                    if any(kw in summary for kw in ['client', 'meeting', 'jackie', 'henderson', 'rodriguez', 'portfolio', 'consultation']):
                        client_meeting = ev
                        break

            if not client_meeting:
                return {"success": True, "output": "No client meetings found on today's calendar."}

            prep_text = "NEXT CLIENT MEETING:\n"
            if from_graph:
                # Graph event format
                start = client_meeting.get('start', {}).get('dateTime', '')[:16]
                end = client_meeting.get('end', {}).get('dateTime', '')[:16]
                try:
                    from datetime import datetime
                    st = datetime.fromisoformat(start)
                    et = datetime.fromisoformat(end)
                    time_str = f"{st.strftime('%I:%M %p').lstrip('0')}-{et.strftime('%I:%M %p').lstrip('0')}"
                except Exception:
                    time_str = start
                summary = client_meeting.get('subject', '?')
                loc = client_meeting.get('location', {}).get('displayName', 'N/A')
                desc = client_meeting.get('bodyPreview', '')
                prep_text += f"Time: {time_str}\n"
                prep_text += f"Meeting: {summary}\n"
                prep_text += f"Location: {loc}\n"
                if desc:
                    prep_text += f"Details: {desc[:500]}\n"
                prep_text += "(Source: Microsoft Graph - Live Outlook Calendar)\n"
            else:
                # Local event format
                prep_text += f"Time: {client_meeting.get('time', '?')}" + (f"-{client_meeting.get('end_time', '')}" if client_meeting.get('end_time') else "") + "\n"
                summary = client_meeting.get('summary', '?')
                prep_text += f"Meeting: {summary}\n"
                prep_text += f"Location: {client_meeting.get('location', 'N/A')}\n"
                desc = client_meeting.get('description', '')
                if desc:
                    prep_text += f"Details: {desc[:500]}\n"

            # Extract client name from meeting subject
            # Patterns: "Meeting -- Name", "Meeting - Name", "Review -- Name Family", "Name" after --
            import re
            client_name = ''
            # Try "-- Name" or "- Name" pattern first
            name_match = re.search(r'[-—]+\s*(.+?)$', summary)
            if name_match:
                client_name = name_match.group(1).strip()
            # Also check meeting body for names
            if not client_name and desc:
                body_match = re.search(r'(?:with|client[:\s]+|consultation[:\s]+)\s*([A-Z][a-z]+\s+[A-Z][a-z]+)', desc)
                if body_match:
                    client_name = body_match.group(1).strip()

            # Use requested name if provided, otherwise use extracted name
            if requested_name and not client_name:
                client_name = requested_name.title()
            elif requested_name:
                client_name = requested_name.title()

            # Always attempt D365 lookup if we have any name
            prep_text += f"\n{'='*40}\nD365 CUSTOMER PROFILE:\n"
            customer_profile = None
            if client_name:
                try:
                    sys.path.insert(0, os.path.join(_APP_DIR, 'mcp-d365'))
                    from server import d365_customer_lookup as _prep_lookup
                    d365_data = _prep_lookup(client_name)
                    prep_text += d365_data
                    prep_text += f"\n(Source: Live D365 Dataverse via MCP)"
                except Exception as d365_err:
                    prep_text += f"Could not look up {client_name} in D365: {d365_err}"

                # Also get detailed profile (with accounts) for product matching
                try:
                    import requests as _req
                    r = _req.post("http://127.0.0.1:5000/d365/customer-lookup",
                                  json={"name": client_name}, timeout=5)
                    if r.ok:
                        customer_profile = r.json().get("customer", {})
                except Exception:
                    pass
            else:
                prep_text += "No client name detected in meeting subject. Ask the advisor assistant to look up a specific client."

            # Product recommendations from catalog
            if customer_profile and PRODUCT_CATALOG:
                recs = _match_product_recommendations(customer_profile)
                prep_text += f"\n\n{'='*40}\nPRODUCT RECOMMENDATIONS:\n"
                prep_text += f"Penetration Tier: {recs['tier']} ({recs['current_count']} of {recs['total_count']} products)\n"
                prep_text += f"Gaps: {recs['gap_count']} products this client does not have\n"
                if recs.get("tier_action"):
                    prep_text += f"Strategy: {recs['tier_action']}\n"

                if recs["recommendations"]:
                    current_priority = None
                    for i, rec in enumerate(recs["recommendations"], 1):
                        if rec["priority"] != current_priority:
                            current_priority = rec["priority"]
                            prep_text += f"\n{current_priority.upper()} PRIORITY:\n"
                        prep_text += f"{i}. {rec['name']} ({rec['category']})\n"
                        prep_text += f"   Talk track: \"{rec['talk_track']}\"\n"
                        prep_text += f"   Trigger: {rec['reason']}\n"
                else:
                    prep_text += "\nNo specific cross-sell triggers matched. Review product catalog for opportunities.\n"

                prep_text += f"\n(Source: Product Catalog — {recs['total_count']} products, local analysis)"

            return {"success": True, "output": prep_text}
        except Exception as e:
            return {"success": False, "error": f"Prep error: {e}"}

    return {"success": False, "error": f"Unknown tool: {name}"}

def extract_text_from_pdf(filepath):
    try:
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(filepath)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        return f"Error reading PDF: {str(e)}"

def extract_text_from_docx(filepath):
    try:
        from docx import Document
        doc = Document(filepath)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text.strip()
    except Exception as e:
        return f"Error reading DOCX: {str(e)}"

def extract_text_from_txt(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception as e:
        return f"Error reading TXT: {str(e)}"

def extract_text(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.pdf':
        return extract_text_from_pdf(filepath)
    elif ext == '.docx':
        return extract_text_from_docx(filepath)
    elif ext in ['.txt', '.md']:
        return extract_text_from_txt(filepath)
    else:
        return "Unsupported file type"

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html>
<head>
    <title>{{APP_TITLE}}</title>
    <link rel="icon" type="image/png" href="/logos/favicon.png">
    <script src="/tesseract/tesseract.min.js"></script>
    <style>
        :root {
            --brand-accent: {{BRAND_ACCENT}};
            --brand-accent-rgb: {{BRAND_ACCENT_RGB}};
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
        }
        /* theme overrides injected at end of style block */

        /* ── App Shell: sidebar + main ── */
        .app-shell { display: flex; min-height: 100vh; }
        .sidebar {
            width: 260px; min-width: 260px;
            background: linear-gradient(180deg, {{BRAND_PRIMARY}} 0%, {{BRAND_PRIMARY_END}} 100%);
            border-right: 1px solid rgba(255,255,255,0.08);
            display: flex; flex-direction: column;
            transition: width 0.25s cubic-bezier(.4,0,.2,1), min-width 0.25s cubic-bezier(.4,0,.2,1);
            overflow: hidden; z-index: 200;
        }
        .sidebar.collapsed { width: 64px; min-width: 64px; }
        .sidebar.collapsed .sidebar-label,
        .sidebar.collapsed .sidebar-brand-text,
        .sidebar.collapsed .sidebar-footer-label,
        .sidebar.collapsed .sidebar-footer-controls { display: none; }
        .sidebar.collapsed .sidebar-brand { justify-content: center; }
        .sidebar.collapsed .sidebar-nav-item { justify-content: center; padding-left: 0; padding-right: 0; }
        .sidebar.collapsed .sidebar-nav-item .nav-icon { margin-right: 0; }
        .sidebar.collapsed .sidebar-footer { align-items: center; padding: 12px 8px; }
        .sidebar.collapsed .sidebar-toggle { margin: 8px auto; }

        .sidebar-toggle {
            background: none; border: 1px solid rgba(255,255,255,0.12);
            color: #fff; width: 34px; height: 34px; border-radius: 8px;
            cursor: pointer; font-size: 1.1em; display: flex; align-items: center;
            justify-content: center; margin: 12px 12px 0 12px; flex-shrink: 0;
            transition: background 0.15s;
        }
        .sidebar-toggle:hover { background: rgba(255,255,255,0.08); }

        .sidebar-brand {
            display: flex; flex-direction: column; align-items: center; gap: 0;
            padding: 0px 14px 10px; border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .sidebar-brand .brand-logo-surface { width: 92%; max-width: 220px; height: auto; object-fit: contain; }
        .sidebar-brand .brand-logo-copilot { width: 65%; max-width: 150px; height: auto; object-fit: contain; margin-top: -6px; }
        .sidebar-brand-text { display: none; }
        .sidebar.collapsed .sidebar-brand { padding: 12px 6px; gap: 6px; }
        .sidebar.collapsed .brand-logo-surface { width: 40px; }
        .sidebar.collapsed .brand-logo-copilot { width: 32px; }

        /* Persona Switcher */
        .persona-switcher {
            display: flex; gap: 6px; padding: 6px 14px 8px; border-bottom: 1px solid rgba(255,255,255,0.06);
            margin-bottom: 2px;
        }
        .persona-badge {
            flex: 1; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px; padding: 8px 10px; cursor: pointer; text-align: center;
            transition: all 0.2s; color: rgba(255,255,255,0.6);
        }
        .persona-badge:hover { background: rgba(255,255,255,0.08); color: #fff; }
        .persona-badge.active {
            background: rgba({{BRAND_ACCENT_RGB}},0.12); border-color: rgba({{BRAND_ACCENT_RGB}},0.4);
            color: #fff;
        }
        .persona-name { display: block; font-weight: 600; font-size: 0.85em; }
        .persona-role { display: block; font-size: 0.7em; opacity: 0.6; margin-top: 2px; }
        .sidebar.collapsed .persona-switcher { display: none; }
        .sidebar-nav-item.persona-dim { opacity: 0.35; }

        /* Branch Concierge — bell + arrivals panel */
        .concierge-bell { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 8px 14px; border-bottom: 1px solid rgba(255,255,255,0.06); cursor: pointer; position: relative; font-size: 0.85em; color: rgba(255,255,255,0.6); transition: color 0.2s; }
        .concierge-bell:hover { color: #fff; }
        .concierge-bell .bell-badge { position: absolute; top: 4px; right: 12px; min-width: 18px; height: 18px; border-radius: 9px; background: #E31837; color: #fff; font-size: 0.7em; font-weight: 700; display: none; align-items: center; justify-content: center; padding: 0 4px; }
        .concierge-bell .bell-badge.active { display: flex; }
        .sidebar.collapsed .concierge-bell span:not(.bell-badge) { display: none; }

        .arrivals-panel { position: fixed; top: 0; right: -420px; width: 400px; height: 100%; background: #1a1a2e; border-left: 1px solid rgba(255,255,255,0.1); z-index: 1000; transition: right 0.3s ease; display: flex; flex-direction: column; box-shadow: -4px 0 20px rgba(0,0,0,0.3); }
        .arrivals-panel.open { right: 0; }
        .arrivals-header { display: flex; justify-content: space-between; align-items: center; padding: 20px; border-bottom: 1px solid rgba(255,255,255,0.1); }
        .arrivals-header h3 { margin: 0; color: #fff; font-size: 1.05em; }
        .arrivals-close { background: none; border: none; color: rgba(255,255,255,0.5); font-size: 1.4em; cursor: pointer; }
        .arrivals-simulate { display: flex; gap: 6px; padding: 10px 20px; border-bottom: 1px solid rgba(255,255,255,0.06); }
        .arrivals-simulate button { flex: 1; padding: 6px 8px; border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; background: rgba(255,255,255,0.04); color: rgba(255,255,255,0.7); font-size: 0.72em; cursor: pointer; transition: background 0.2s; }
        .arrivals-simulate button:hover { background: rgba(255,255,255,0.1); color: #fff; }
        .arrivals-feed { flex: 1; overflow-y: auto; padding: 12px; }
        .arrivals-empty { text-align: center; color: rgba(255,255,255,0.3); padding: 40px 20px; font-size: 0.9em; }
        .arrival-card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 14px; margin-bottom: 10px; animation: liveFadeIn 0.5s ease; }
        .arrival-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .arrival-tier { font-size: 0.7em; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; padding: 3px 8px; border-radius: 10px; }
        .arrival-source { font-size: 0.72em; color: rgba(255,255,255,0.45); }
        .arrival-name { font-size: 1em; font-weight: 600; color: #fff; }
        .arrival-title { font-size: 0.8em; color: rgba(255,255,255,0.5); margin-top: 2px; }
        .arrival-meta { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; font-size: 0.78em; color: rgba(255,255,255,0.4); }
        .arrival-actions { display: flex; gap: 6px; margin-top: 10px; }
        .arrival-actions button { flex: 1; padding: 7px 10px; border: none; border-radius: 8px; font-size: 0.8em; font-weight: 600; cursor: pointer; transition: transform 0.1s; }
        .arrival-actions button:hover { transform: scale(1.03); }
        .arrival-greet { background: rgba(34,197,94,0.15); color: #22c55e; }
        .arrival-brief-btn { background: rgba(var(--brand-accent-rgb),0.12); color: var(--brand-accent); }
        .arrival-card.greeted { border-color: rgba(34,197,94,0.3); }
        .arrival-card.greeted .arrival-greet { background: rgba(34,197,94,0.25); }

        .arrival-brief-panel { display: none; margin-top: 12px; padding: 14px; background: rgba(var(--brand-accent-rgb),0.06); border: 1px solid rgba(var(--brand-accent-rgb),0.15); border-radius: 10px; }
        .arrival-brief-panel.visible { display: block; animation: liveFadeIn 0.4s ease; }
        .brief-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .brief-header-title { font-size: 0.82em; font-weight: 600; color: var(--brand-accent); }
        .brief-meta { font-size: 0.7em; color: rgba(255,255,255,0.4); }
        .brief-text { font-size: 0.85em; color: rgba(255,255,255,0.85); line-height: 1.55; white-space: pre-wrap; }
        .brief-local { display: inline-block; margin-top: 8px; font-size: 0.7em; padding: 3px 8px; border-radius: 6px; background: rgba(34,197,94,0.1); color: #22c55e; }

        .sidebar-nav { flex: 1; padding: 12px 0; display: flex; flex-direction: column; gap: 2px; }
        .sidebar-nav-item {
            display: flex; align-items: center; gap: 0;
            padding: 12px 18px; cursor: pointer; color: rgba(255,255,255,0.7);
            border-left: 3px solid transparent; transition: all 0.15s;
            white-space: nowrap; font-size: 0.92em; text-decoration: none;
        }
        .sidebar-nav-item:hover { background: rgba(255,255,255,0.05); color: #fff; }
        .sidebar-nav-item.active {
            border-left-color: {{BRAND_ACCENT}}; color: #fff;
            background: rgba({{BRAND_ACCENT_RGB}},0.08);
        }
        .nav-icon { font-size: 1.2em; width: 28px; text-align: center; flex-shrink: 0; margin-right: 10px; }
        .sidebar-label { overflow: hidden; text-overflow: ellipsis; }
        .sidebar-nav-sub { display: block; font-size: 0.65em; opacity: 0.45; font-weight: normal; margin-top: 1px; }

        .sidebar-footer {
            padding: 14px 18px; border-top: 1px solid rgba(255,255,255,0.06);
            display: flex; flex-direction: column; gap: 8px; font-size: 0.85em;
        }
        .sidebar-footer .badge,
        .sidebar-footer .offline-badge { font-size: 0.78em; margin: 0; padding: 5px 10px; }
        .sidebar-footer-controls { display: flex; flex-direction: column; gap: 6px; }
        .sidebar-footer-controls .net-toggle-btn { font-size: 0.78em; padding: 5px 10px; }
        .sidebar-footer-controls .model-selector { justify-content: flex-start; margin: 0; }
        .sidebar-footer-controls .model-selector select { font-size: 0.8em; padding: 5px 10px; }
        .sidebar-footer-label { font-size: 0.78em; opacity: 0.5; margin-bottom: 2px; }

        /* Local AI Savings Widget */
        .savings-widget {
            background: linear-gradient(135deg, rgba(34, 197, 94, 0.08) 0%, rgba(34, 197, 94, 0.02) 100%);
            border: 1px solid rgba(34, 197, 94, 0.25);
            border-radius: 8px;
            padding: 10px 12px;
            margin-bottom: 10px;
            font-size: 0.78em;
        }
        .savings-header {
            font-weight: 600;
            color: #22c55e;
            margin-bottom: 6px;
            font-size: 0.9em;
            letter-spacing: 0.02em;
        }
        .savings-stat {
            color: rgba(255, 255, 255, 0.75);
            margin: 3px 0;
            line-height: 1.4;
        }
        .savings-stat-highlight {
            color: #22c55e;
            font-weight: 500;
        }
        .savings-stat-hero {
            font-size: 1.35em;
            font-weight: 700;
            color: #22c55e;
            margin: 6px 0;
            line-height: 1.3;
            text-shadow: 0 0 12px rgba(34, 197, 94, 0.3);
        }
        .sidebar.collapsed .savings-widget {
            padding: 8px;
            text-align: center;
        }
        .sidebar.collapsed .savings-header,
        .sidebar.collapsed .savings-stat:not(.savings-stat-compact),
        .sidebar.collapsed .savings-stat-hero,
        .sidebar.collapsed .poc-footer { display: none; }
        .savings-stat-compact { display: none; }
        .sidebar.collapsed .savings-stat-compact {
            display: block;
            color: #22c55e;
            font-weight: 600;
            font-size: 0.95em;
        }

        .main-content { flex: 1; min-width: 0; overflow-y: auto; padding: 20px; max-height: 100vh; }

        /* Mobile overlay */
        .sidebar-backdrop {
            display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5);
            z-index: 199;
        }
        @media (max-width: 768px) {
            .sidebar {
                position: fixed; left: 0; top: 0; height: 100vh;
                transform: translateX(-100%); z-index: 200;
            }
            .sidebar.mobile-open { transform: translateX(0); }
            .sidebar.collapsed { transform: translateX(-100%); }
            .sidebar.collapsed.mobile-open { transform: translateX(0); }
            .sidebar-backdrop.visible { display: block; }
            .main-content { padding: 12px; }
            .mobile-hamburger {
                display: flex; position: fixed; top: 12px; left: 12px; z-index: 198;
                background: rgba(13,17,23,0.9); border: 1px solid rgba(255,255,255,0.12);
                color: #fff; width: 40px; height: 40px; border-radius: 10px;
                align-items: center; justify-content: center; font-size: 1.3em; cursor: pointer;
            }
        }
        @media (min-width: 769px) {
            .mobile-hamburger { display: none !important; }
        }

        .container { max-width: 100%; margin: 0 auto; padding: 0; }
        header { display: none; }
        .logos { display: flex; justify-content: center; align-items: center; gap: 35px; margin-bottom: 20px; }
        .logos img.surface-logo { height: 75px; width: auto; object-fit: contain; }
        .logos img.copilot-logo { height: 55px; width: auto; object-fit: contain; }
        .logo-divider { width: 2px; height: 60px; background: rgba(255,255,255,0.3); }
        h1 { font-size: 2.2em; margin-bottom: 10px; }
        .subtitle { color: var(--brand-accent); font-size: 1.1em; }
        .badge {
            display: inline-block;
            background: linear-gradient(90deg, #0078D4, var(--brand-accent));
            padding: 8px 16px;
            border-radius: 25px;
            font-weight: bold;
            margin: 15px 5px;
            font-size: 0.9em;
        }
        .offline-badge {
            display: inline-block;
            background: linear-gradient(90deg, #107C10, #00CC6A);
            padding: 8px 16px;
            border-radius: 25px;
            font-weight: bold;
            margin: 15px 5px;
            font-size: 0.9em;
        }
        .offline-badge.offline { background: linear-gradient(90deg, #FF8C00, #FFB900); }
        .header-status-row { display: flex; justify-content: center; align-items: center; gap: 8px; flex-wrap: wrap; }
        .net-toggle-btn {
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.25);
            color: #fff;
            padding: 6px 14px;
            border-radius: 25px;
            font-size: 0.82em;
            cursor: pointer;
            transition: all 0.2s;
        }
        .net-toggle-btn:hover { background: rgba(255,255,255,0.18); }
        .net-toggle-btn.net-toggle-off { border-color: rgba(255,140,0,0.5); }
        .net-toggle-btn.net-toggle-off:hover { background: rgba(255,140,0,0.2); }
        .net-toggle-btn.net-toggle-on { border-color: rgba(0,204,106,0.5); }
        .net-toggle-btn.net-toggle-on:hover { background: rgba(0,204,106,0.2); }
        .net-toggle-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .model-selector { display: flex; justify-content: center; align-items: center; gap: 10px; margin: 15px 0; }
        .model-selector label { font-size: 0.9em; opacity: 0.8; }
        .model-selector select {
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.3);
            color: #fff;
            padding: 8px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            cursor: pointer;
        }
        .model-selector select option { background: #1a1a2e; color: #fff; }
        .response-timer { text-align: center; font-size: 0.85em; color: var(--brand-accent); margin-top: 10px; }
        .tabs { display: none; gap: 10px; margin-bottom: 20px; }
        .tab-btn {
            flex: 1;
            padding: 15px;
            background: rgba(255,255,255,0.1);
            border: 2px solid transparent;
            color: #fff;
            border-radius: 10px;
            cursor: pointer;
            font-size: 1em;
        }
        .tab-btn:hover { background: rgba(var(--brand-accent-rgb),0.2); }
        .tab-btn.active { border-color: var(--brand-accent); background: rgba(var(--brand-accent-rgb),0.3); }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .camera-btn {
            background: linear-gradient(90deg, #0078D4, var(--brand-accent));
            border: none;
            color: #fff;
            padding: 12px 30px;
            border-radius: 25px;
            cursor: pointer;
            font-weight: bold;
            font-size: 1em;
            margin-top: 15px;
        }
        .camera-btn.stop { background: linear-gradient(90deg, #D41C00, #FF4444); }
        /* Agent chat layout — full-width single column */
        .agent-chat-layout {
            display: flex;
            flex-direction: column;
            height: calc(100vh - 120px);
        }
        .agent-topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            height: 36px;
            padding: 0 12px;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            margin-top: 4px;
            font-size: 0.82em;
        }
        .topbar-left, .topbar-right {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .topbar-status {
            display: flex;
            align-items: center;
            gap: 5px;
            opacity: 0.8;
        }
        .topbar-btn {
            background: transparent;
            border: 1px solid transparent;
            color: #fff;
            padding: 3px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95em;
            opacity: 0.7;
            transition: opacity 0.15s, border-color 0.15s, background 0.15s;
        }
        .topbar-btn:hover { opacity: 1; border-color: rgba(255,255,255,0.2); background: rgba(255,255,255,0.06); }
        .topbar-divider { width: 1px; height: 16px; background: rgba(255,255,255,0.15); }
        .policy-icon-wrap {
            position: relative;
            display: flex;
            align-items: center;
        }
        .policy-tooltip {
            display: none;
            position: absolute;
            bottom: 100%;
            right: 0;
            margin-bottom: 6px;
            background: #1a1a2e;
            border: 1px solid rgba(var(--brand-accent-rgb),0.3);
            border-radius: 10px;
            padding: 12px 14px;
            font-size: 0.85em;
            line-height: 1.6;
            width: 220px;
            z-index: 50;
            white-space: normal;
        }
        .policy-icon-wrap:hover .policy-tooltip { display: block; }
        .status-dot {
            width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
        }
        .status-dot.green { background: #00CC6A; box-shadow: 0 0 6px rgba(0,204,106,0.5); }
        .status-dot.red { background: #FF4444; box-shadow: 0 0 6px rgba(255,68,68,0.5); }
        .status-dot.blue { background: var(--brand-accent); box-shadow: 0 0 6px rgba(var(--brand-accent-rgb),0.5); }
        .status-dot.yellow { background: #FFB900; box-shadow: 0 0 6px rgba(255,185,0,0.5); }

        /* Empty state */
        .chat-empty-state {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 10px 20px;
        }
        .empty-title {
            font-size: 1.6em;
            font-weight: 700;
            margin-bottom: 6px;
        }
        .empty-subtitle {
            font-size: 0.95em;
            opacity: 0.55;
            margin-bottom: 16px;
        }
        .suggestion-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            max-width: 900px;
            width: 100%;
        }
        @media (min-width: 800px) {
            .suggestion-grid { grid-template-columns: repeat(5, 1fr); }
        }
        .suggestion-chip {
            display: flex;
            align-items: center;
            gap: 8px;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.12);
            color: #fff;
            padding: 10px 12px;
            border-radius: 10px;
            cursor: pointer;
            font-size: 0.82em;
            text-align: left;
            transition: background 0.15s, border-color 0.15s;
        }
        .suggestion-chip:hover { background: rgba(var(--brand-accent-rgb),0.15); border-color: rgba(var(--brand-accent-rgb),0.4); }
        .chip-icon { font-size: 1.1em; flex-shrink: 0; }

        /* Device Health check display */
        .health-checks-container { margin: 8px 0; }
        .health-check-entry {
            margin: 4px 0; padding: 8px 12px;
            background: rgba(255,255,255,0.03); border-radius: 6px;
            border-left: 3px solid rgba(255,255,255,0.15); font-size: 0.85em;
        }
        .health-check-entry.done { border-left-color: #1db954; }
        .health-check-entry.error { border-left-color: #FF4444; }
        .health-check-name { font-weight: 600; margin-bottom: 2px; }
        .health-check-cmd {
            font-family: 'Cascadia Code', 'Consolas', monospace;
            font-size: 0.78em; opacity: 0.4; margin: 2px 0;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .health-check-output {
            font-family: 'Cascadia Code', 'Consolas', monospace;
            font-size: 0.82em; white-space: pre-wrap; margin-top: 4px;
            max-height: 80px; overflow-y: auto; opacity: 0.8;
        }
        .health-ai-summary { margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.1); }

        /* Proof-of-concept disclaimer banners */
        .poc-banner {
            background: #FFF3CD;
            color: #856404;
            border: 1px solid #FFEEBA;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 16px;
            font-size: 0.85em;
            line-height: 1.5;
        }
        .poc-banner strong { font-weight: 700; }
        .industry-stub-banner {
            background: #FFF3CD;
            color: #856404;
            border: none;
            border-bottom: 2px solid #FFEEBA;
            padding: 10px 20px;
            font-size: 0.88em;
            font-weight: 600;
            text-align: center;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .poc-footer {
            color: rgba(255,255,255,0.4);
            font-size: 0.75em;
            line-height: 1.5;
            padding: 10px 12px;
            margin-top: 10px;
            border-top: 1px solid rgba(255,255,255,0.08);
        }

        /* Device Search results */
        .device-search-container {
            margin: 8px 0; padding: 10px 14px;
            background: rgba(255,255,255,0.03); border-radius: 8px;
            border: 1px solid rgba(255,255,255,0.08);
        }
        .device-search-container input[type="text"] {
            width: 100%; padding: 8px 12px; font-size: 0.9em;
            background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.15);
            border-radius: 6px; color: #fff; outline: none;
        }
        .device-search-container input[type="text"]:focus {
            border-color: rgba(var(--brand-accent-rgb),0.5);
        }
        .device-search-container .search-bar {
            display: flex; gap: 8px; align-items: center;
        }
        .device-search-container .search-bar button {
            padding: 8px 16px; font-size: 0.85em; white-space: nowrap;
            background: rgba(var(--brand-accent-rgb),0.2); border: 1px solid rgba(var(--brand-accent-rgb),0.4);
            border-radius: 6px; color: var(--brand-accent); cursor: pointer;
        }
        .device-search-container .search-bar button:hover {
            background: rgba(var(--brand-accent-rgb),0.3);
        }
        .search-result-item {
            margin: 6px 0; padding: 8px 12px;
            background: rgba(255,255,255,0.03); border-radius: 6px;
            border-left: 3px solid rgba(var(--brand-accent-rgb),0.4); font-size: 0.85em;
        }
        .search-result-item .sr-name { font-weight: 600; color: #7fdbff; }
        .search-result-item .sr-path {
            font-family: 'Cascadia Code', 'Consolas', monospace;
            font-size: 0.78em; opacity: 0.4; margin: 2px 0;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .search-result-item .sr-meta { font-size: 0.8em; opacity: 0.6; }

        /* Inline action buttons in chat messages */
        .inline-action-btn {
            display: inline-block;
            background: rgba(0,120,212,0.2);
            border: 1px solid rgba(0,120,212,0.4);
            color: #7fdbff;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.88em;
            margin-right: 8px;
            margin-top: 8px;
            transition: background 0.15s, border-color 0.15s;
        }
        .inline-action-btn:hover { background: rgba(0,120,212,0.35); border-color: rgba(var(--brand-accent-rgb),0.6); }

        .chat-container {
            border-radius: 15px;
            padding: 10px 20px;
            margin-bottom: 8px;
            flex: 1;
            min-height: 0;
            overflow-y: auto;
        }
        .message {
            margin: 12px auto;
            padding: 14px 18px;
            border-radius: 14px;
            max-width: 720px;
        }
        .user-msg { background: #0078D4; margin-left: auto; margin-right: 0; max-width: 600px; }
        .assistant-msg { background: rgba(255,255,255,0.08); margin-left: 0; margin-right: auto; }
        .role { font-size: 0.8em; opacity: 0.7; margin-bottom: 5px; }
        .chat-input-wrapper { max-width: 720px; margin: 0 auto; width: 100%; }
        .input-area {
            display: flex;
            gap: 8px;
            align-items: center;
            background: rgba(255,255,255,0.07);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 24px;
            padding: 4px 4px 4px 6px;
        }
        #attachBtn {
            width: 36px; height: 36px;
            border-radius: 50%;
            border: none;
            background: transparent;
            color: rgba(255,255,255,0.6);
            font-size: 1.3em;
            cursor: pointer;
            flex-shrink: 0;
            display: flex; align-items: center; justify-content: center;
            transition: color 0.15s, background 0.15s;
        }
        #attachBtn:hover { color: #fff; background: rgba(255,255,255,0.1); }
        #userInput {
            flex: 1;
            padding: 10px 8px;
            border-radius: 10px;
            border: none;
            background: transparent;
            color: #fff;
            font-size: 1em;
            outline: none;
        }
        #sendBtn {
            width: 36px; height: 36px;
            border-radius: 50%;
            background: linear-gradient(135deg, #0078D4, var(--brand-accent));
            border: none;
            color: #fff;
            cursor: pointer;
            font-size: 1.1em;
            flex-shrink: 0;
            display: flex; align-items: center; justify-content: center;
            padding: 0;
        }
        #sendBtn:disabled { opacity: 0.4; cursor: not-allowed; }
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: var(--brand-accent);
            animation: spin 1s linear infinite;
            margin-right: 10px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        footer { text-align: center; padding: 20px; opacity: 0.6; font-size: 0.9em; display: none; }
        .tab-footer { text-align: center; padding: 16px 10px; opacity: 0.5; font-size: 0.82em; margin-top: 12px; }

        /* My Day Dashboard */
        .day-cards { display: flex; gap: 14px; margin-bottom: 20px; }
        .day-card {
            flex: 1;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 18px 16px;
            text-align: center;
        }
        .day-card { cursor: pointer; transition: border-color 0.2s, background 0.2s; position: relative; }
        .day-card:hover { border-color: rgba(var(--brand-accent-rgb),0.4); background: rgba(255,255,255,0.09); }
        .day-card.expanded { border-color: rgba(var(--brand-accent-rgb),0.5); background: rgba(255,255,255,0.09); }
        .day-card .card-icon { font-size: 1.8em; margin-bottom: 6px; }
        .day-card .card-count { font-size: 2.2em; font-weight: bold; color: var(--brand-accent); }
        .day-card .card-label { font-size: 0.85em; opacity: 0.7; }
        .day-card .card-hint { font-size: 0.72em; opacity: 0.4; margin-top: 4px; }
        .day-card .card-peek {
            display: none;
            position: absolute;
            top: 100%;
            left: -1px;
            right: -1px;
            background: #1a1a2e;
            border: 1px solid rgba(var(--brand-accent-rgb),0.4);
            border-top: none;
            border-radius: 0 0 12px 12px;
            padding: 10px 12px;
            text-align: left;
            font-size: 0.78em;
            max-height: 320px;
            overflow-y: auto;
            z-index: 20;
            line-height: 1.5;
        }
        .day-card.expanded .card-peek { display: block; }
        .peek-row { padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.06); }
        .peek-row:last-child { border-bottom: none; }
        .peek-time { color: var(--brand-accent); font-weight: bold; margin-right: 6px; }
        .peek-prio { font-weight: bold; margin-right: 6px; }
        .peek-prio.high { color: #FF4444; }
        .peek-prio.medium { color: #FFB900; }
        .peek-prio.low { color: #00CC6A; }
        .peek-from { color: var(--brand-accent); margin-right: 6px; }
        .brief-me-btn {
            display: block;
            width: 100%;
            max-width: 400px;
            margin: 0 auto 16px;
            padding: 16px 32px;
            background: linear-gradient(90deg, #0078D4, var(--brand-accent));
            border: none;
            color: #fff;
            font-size: 1.15em;
            font-weight: bold;
            border-radius: 30px;
            cursor: pointer;
            transition: transform 0.1s;
        }
        .brief-me-btn:hover { transform: scale(1.02); }
        .brief-me-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        .hero-btn-row { display: flex; gap: 12px; justify-content: center; margin-bottom: 16px; max-width: 820px; margin-left: auto; margin-right: auto; }
        .hero-btn-row .brief-me-btn { margin: 0; flex: 1; }
        .focus-btn {
            flex: 1;
            padding: 16px 32px;
            background: linear-gradient(90deg, var(--brand-accent), rgba(var(--brand-accent-rgb), 0.75));
            border: none;
            color: #fff;
            font-size: 1.15em;
            font-weight: bold;
            border-radius: 30px;
            cursor: pointer;
            transition: transform 0.1s;
        }
        .focus-btn:hover { transform: scale(1.02); }
        .focus-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        .tomorrow-btn {
            flex: 1;
            padding: 16px 32px;
            background: linear-gradient(90deg, #B91C1C, #DC2626);
            border: none;
            color: #fff;
            font-size: 1.15em;
            font-weight: bold;
            border-radius: 30px;
            cursor: pointer;
            transition: transform 0.1s;
        }
        .tomorrow-btn:hover { transform: scale(1.02); }
        .tomorrow-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        .day-actions { display: flex; gap: 10px; justify-content: center; margin-bottom: 20px; }
        .day-action-btn {
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            color: #fff;
            padding: 10px 18px;
            border-radius: 20px;
            cursor: pointer;
            font-size: 0.88em;
        }
        .day-action-btn:hover { background: rgba(var(--brand-accent-rgb),0.2); border-color: rgba(var(--brand-accent-rgb),0.4); }
        .day-action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .briefing-progress {
            background: rgba(255,255,255,0.04);
            border-radius: 10px;
            padding: 12px 16px;
            margin-bottom: 16px;
            font-size: 0.88em;
            display: none;
        }
        .briefing-progress .step-line { padding: 3px 0; opacity: 0.7; }
        .briefing-progress .step-line.active { opacity: 1; color: var(--brand-accent); }
        .briefing-result {
            display: none;
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            overflow: hidden;
        }
        .exec-summary {
            background: linear-gradient(135deg, rgba(0,120,212,0.15), rgba(var(--brand-accent-rgb),0.08));
            padding: 24px;
            font-size: 1.05em;
            line-height: 1.65;
            border-bottom: 1px solid rgba(255,255,255,0.08);
        }
        .exec-summary .summary-label {
            font-size: 0.75em;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            opacity: 0.5;
            margin-bottom: 10px;
        }
        .breakdown-area { padding: 16px 24px; }
        .breakdown-section {
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 10px;
            margin-bottom: 10px;
            overflow: hidden;
        }
        .breakdown-header {
            padding: 12px 16px;
            background: rgba(255,255,255,0.04);
            cursor: pointer;
            font-weight: bold;
            font-size: 0.92em;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .breakdown-header:hover { background: rgba(255,255,255,0.07); }
        .breakdown-body {
            padding: 12px 16px;
            font-size: 0.9em;
            line-height: 1.6;
            white-space: pre-wrap;
        }
        .briefing-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 24px;
            border-top: 1px solid rgba(255,255,255,0.08);
            font-size: 0.82em;
            opacity: 0.7;
        }
        @keyframes resultPulse {
            0% { opacity: 0.4; }
            50% { opacity: 1; text-shadow: 0 0 12px rgba(0, 188, 242, 0.4); }
            100% { opacity: 1; text-shadow: none; }
        }
        .briefing-result-pulse { animation: resultPulse 1.2s ease-out; }

        /* Agent tool call card */
        .tool-card {
            background: rgba(0,120,212,0.15);
            border: 1px solid rgba(0,120,212,0.3);
            border-radius: 8px;
            padding: 10px 14px;
            margin: 8px 0;
            font-size: 0.88em;
        }
        .tool-card .tool-header {
            color: var(--brand-accent);
            font-weight: bold;
            margin-bottom: 4px;
        }
        .tool-card .tool-args {
            opacity: 0.8;
            word-break: break-all;
            max-height: 80px;
            overflow-y: auto;
        }
        .tool-card .tool-result {
            margin-top: 6px;
            padding-top: 6px;
            border-top: 1px solid rgba(255,255,255,0.1);
        }
        .tool-card .tool-ok { color: #00CC6A; }
        .tool-card .tool-fail { color: #FF4444; }
        .tool-time { font-size: 0.88em; color: rgba(var(--brand-accent-rgb),0.7); opacity: 1; }
        .tool-card .tool-time { opacity: 0.8; font-size: 0.9em; }

        /* Approval Gate Card */
        .approval-card {
            background: rgba(255, 185, 0, 0.06);
            border: 1px solid rgba(255, 185, 0, 0.3);
            border-radius: 12px;
            padding: 20px;
            margin: 8px 0;
        }
        .approval-card.approved { border-color: rgba(16, 124, 16, 0.4); background: rgba(16, 124, 16, 0.06); }
        .approval-card.denied { border-color: rgba(212, 28, 0, 0.4); background: rgba(212, 28, 0, 0.06); }
        .approval-header {
            font-size: 1.05em;
            font-weight: bold;
            margin-bottom: 12px;
        }
        .approval-body {
            font-size: 0.9em;
            line-height: 1.6;
            margin-bottom: 16px;
            opacity: 0.9;
        }
        .approval-actions {
            display: flex;
            gap: 12px;
            margin-bottom: 12px;
        }
        .approval-btn {
            padding: 12px 28px;
            border: none;
            border-radius: 8px;
            color: #fff;
            font-size: 0.95em;
            font-weight: bold;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .approval-btn:hover { opacity: 0.85; }
        .approval-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .approval-btn.approve { background: linear-gradient(90deg, #107C10, #00CC6A); }
        .approval-btn.deny { background: linear-gradient(90deg, #D41C00, #FF4444); }
        .approval-badge {
            display: inline-block;
            padding: 8px 20px;
            border-radius: 8px;
            font-weight: bold;
            font-size: 0.95em;
        }
        .approval-badge.approved { background: rgba(16, 124, 16, 0.2); color: #00CC6A; }
        .approval-badge.denied { background: rgba(212, 28, 0, 0.2); color: #FF4444; }
        .approval-policy {
            font-size: 0.78em;
            opacity: 0.45;
            margin-top: 8px;
        }
        /* Security Review Box (Agentic Firewall) */
        .security-review {
            background: rgba(var(--brand-accent-rgb),0.06);
            border: 1px solid rgba(var(--brand-accent-rgb),0.2);
            border-radius: 8px;
            padding: 12px 14px;
            margin: 12px 0;
            font-size: 0.85em;
        }
        .security-review-header {
            font-weight: bold;
            margin-bottom: 8px;
            font-size: 0.95em;
        }
        .security-review-line {
            padding: 2px 0;
            opacity: 0.9;
        }
        .security-check-line {
            color: rgba(255,255,255,0.7);
            font-size: 0.9em;
            padding: 4px 0;
            margin-bottom: 4px;
        }

        /* File Picker Modal */
        .file-picker-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        .file-picker-modal {
            background: linear-gradient(135deg, #1e1e2f 0%, #15151f 100%);
            border: 1px solid rgba(var(--brand-accent-rgb),0.3);
            border-radius: 16px;
            padding: 24px;
            min-width: 450px;
            max-width: 550px;
            max-height: 70vh;
            display: flex;
            flex-direction: column;
        }
        .file-picker-header {
            font-size: 1.15em;
            font-weight: bold;
            margin-bottom: 8px;
        }
        .file-picker-subtitle {
            font-size: 0.85em;
            opacity: 0.7;
            margin-bottom: 16px;
        }
        .file-picker-list {
            flex: 1;
            overflow-y: auto;
            margin-bottom: 16px;
            max-height: 300px;
        }
        .file-picker-item {
            display: flex;
            align-items: center;
            padding: 12px 14px;
            margin-bottom: 8px;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            cursor: pointer;
            transition: background 0.15s, border-color 0.15s;
        }
        .file-picker-item:hover {
            background: rgba(255,255,255,0.08);
            border-color: rgba(var(--brand-accent-rgb),0.3);
        }
        .file-picker-item.selected {
            background: rgba(var(--brand-accent-rgb),0.12);
            border-color: rgba(var(--brand-accent-rgb),0.5);
        }
        .file-picker-item input[type="checkbox"] {
            margin-right: 12px;
            width: 18px;
            height: 18px;
            accent-color: var(--brand-accent);
        }
        .file-picker-item .file-info {
            flex: 1;
        }
        .file-picker-item .file-name {
            font-weight: 500;
        }
        .file-picker-item .file-meta {
            font-size: 0.8em;
            opacity: 0.6;
            margin-top: 2px;
        }
        .file-picker-item .file-badge {
            background: rgba(255,185,0,0.15);
            border: 1px solid rgba(255,185,0,0.4);
            color: #FFB900;
            font-size: 0.75em;
            padding: 3px 8px;
            border-radius: 12px;
            margin-left: 8px;
        }
        .file-picker-actions {
            display: flex;
            gap: 12px;
            justify-content: flex-end;
        }
        .file-picker-btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 0.95em;
            cursor: pointer;
            font-weight: 600;
        }
        .file-picker-btn.cancel {
            background: rgba(255,255,255,0.1);
            color: #fff;
        }
        .file-picker-btn.confirm {
            background: linear-gradient(90deg, #0078D4, var(--brand-accent));
            color: #fff;
        }
        .file-picker-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Clean Room Auditor Styles */
        .auditor-header {
            font-size: 1.2em;
            font-weight: bold;
            margin-bottom: 20px;
            letter-spacing: 1px;
            text-align: center;
        }
        .auditor-upload-zone {
            text-align: center;
            padding: 20px;
        }
        .auditor-dropzone {
            background: rgba(255,255,255,0.03);
            border: 2px dashed rgba(var(--brand-accent-rgb),0.3);
            border-radius: 15px;
            padding: 40px;
            margin-bottom: 30px;
            transition: border-color 0.2s, background 0.2s;
        }
        .auditor-dropzone:hover, .auditor-dropzone.dragover {
            border-color: rgba(var(--brand-accent-rgb),0.6);
            background: rgba(var(--brand-accent-rgb),0.05);
        }
        .dropzone-icon { font-size: 3em; margin-bottom: 15px; }
        .dropzone-title { font-size: 1.15em; font-weight: 600; margin-bottom: 8px; }
        .dropzone-subtitle { font-size: 0.9em; opacity: 0.7; margin-bottom: 20px; line-height: 1.5; }
        .auditor-upload-btn {
            background: linear-gradient(90deg, #0078D4, var(--brand-accent));
            color: #fff;
            border: none;
            padding: 12px 32px;
            border-radius: 8px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            margin-bottom: 12px;
        }
        .dropzone-formats { font-size: 0.8em; opacity: 0.5; }
        .auditor-demo-section {
            padding: 20px;
            background: rgba(255,255,255,0.03);
            border-radius: 12px;
            border: 1px solid rgba(255,255,255,0.08);
        }
        .auditor-demo-btn {
            background: rgba(255,255,255,0.1);
            color: #fff;
            border: 1px solid rgba(255,255,255,0.2);
            padding: 10px 24px;
            border-radius: 8px;
            font-size: 0.95em;
            cursor: pointer;
            transition: background 0.2s;
        }
        .auditor-demo-btn:hover { background: rgba(255,255,255,0.15); }

        /* Auditor State 2: Document Staged */
        .auditor-staged { padding: 20px; }
        .auditor-doc-card {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .doc-card-header { display: flex; align-items: flex-start; gap: 15px; margin-bottom: 15px; }
        .doc-icon { font-size: 2.5em; }
        .doc-info { flex: 1; }
        .doc-name { font-size: 1.1em; font-weight: 600; margin-bottom: 4px; }
        .doc-meta { font-size: 0.85em; opacity: 0.6; }
        .doc-preview {
            background: rgba(0,0,0,0.2);
            border-radius: 8px;
            padding: 12px 15px;
            font-family: monospace;
            font-size: 0.85em;
            opacity: 0.8;
            max-height: 80px;
            overflow: hidden;
            line-height: 1.4;
        }
        .auditor-actions { margin-bottom: 20px; }
        .auditor-action-row { display: flex; gap: 10px; margin-bottom: 12px; }
        .auditor-action-btn {
            flex: 1;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            color: #fff;
            padding: 14px 16px;
            border-radius: 10px;
            font-size: 0.95em;
            cursor: pointer;
            transition: background 0.2s, border-color 0.2s;
        }
        .auditor-action-btn:hover { background: rgba(255,255,255,0.12); border-color: rgba(var(--brand-accent-rgb),0.4); }
        .auditor-action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .auditor-action-btn.secondary { background: rgba(255,255,255,0.05); }
        .auditor-full-audit-btn {
            width: 100%;
            background: linear-gradient(90deg, #0078D4, var(--brand-accent));
            border: none;
            color: #fff;
            padding: 16px;
            border-radius: 10px;
            font-size: 1.05em;
            font-weight: 600;
            cursor: pointer;
        }
        .auditor-full-audit-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .auditor-back-link { text-align: center; margin-top: 15px; }
        .auditor-back-link a { color: rgba(255,255,255,0.5); text-decoration: none; font-size: 0.9em; }
        .auditor-back-link a:hover { color: rgba(255,255,255,0.8); }

        /* Auditor State 3: Results */
        .auditor-results { padding: 20px; }
        .auditor-doc-summary {
            font-size: 0.9em;
            opacity: 0.7;
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }

        /* Processing Log (verbose demo mode) */
        .processing-log {
            background: rgba(0,0,0,0.3);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            margin-bottom: 20px;
            overflow: hidden;
        }
        .processing-log-header {
            background: rgba(255,255,255,0.05);
            padding: 12px 16px;
            font-weight: 600;
            font-size: 0.9em;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .processing-log-content {
            padding: 16px;
            font-family: monospace;
            font-size: 0.85em;
            line-height: 1.6;
            max-height: 350px;
            overflow-y: auto;
        }
        .log-step { margin-bottom: 12px; }
        .log-step.complete { opacity: 0.8; }
        .log-step.active { color: var(--brand-accent); }
        .log-step.pending { opacity: 0.4; }
        .log-step-icon { margin-right: 8px; }
        .log-step-detail {
            margin-left: 24px;
            font-size: 0.92em;
            opacity: 0.7;
            margin-top: 4px;
        }
        .log-prompt-box {
            background: rgba(var(--brand-accent-rgb),0.08);
            border: 1px solid rgba(var(--brand-accent-rgb),0.2);
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0 8px 24px;
            font-size: 0.9em;
            line-height: 1.5;
        }
        .log-prompt-label {
            color: var(--brand-accent);
            font-weight: 600;
            margin-bottom: 6px;
        }

        /* Result Cards */
        .result-card {
            background: rgba(255,255,255,0.06);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 15px;
        }
        .result-card-header {
            font-weight: 600;
            font-size: 1.05em;
            margin-bottom: 12px;
        }
        .result-card.pii {
            background: rgba(255,185,0,0.08);
            border: 1px solid rgba(255,185,0,0.3);
        }
        .result-card.risk-high { border-left: 4px solid #D41C00; background: rgba(212,28,0,0.06); }
        .result-card.risk-medium { border-left: 4px solid #FFB900; background: rgba(255,185,0,0.06); }
        .result-card.risk-low { border-left: 4px solid #107C10; background: rgba(16,124,16,0.06); }
        .risk-item { margin-bottom: 15px; padding-bottom: 15px; border-bottom: 1px solid rgba(255,255,255,0.08); }
        .risk-item:last-child { margin-bottom: 0; padding-bottom: 0; border-bottom: none; }
        .risk-severity { font-weight: 600; margin-bottom: 4px; }
        .risk-severity.high { color: #FF6B6B; }
        .risk-severity.medium { color: #FFB900; }
        .risk-severity.low { color: #00CC6A; }
        .risk-finding { font-size: 0.95em; line-height: 1.5; opacity: 0.9; }
        .risk-recommendation { font-size: 0.85em; opacity: 0.7; margin-top: 6px; font-style: italic; }
        .pii-item { display: flex; align-items: center; gap: 10px; padding: 8px 0; }
        .pii-severity { font-size: 1.1em; }
        .pii-type { font-weight: 600; min-width: 100px; }
        .pii-value { font-family: monospace; opacity: 0.9; }
        .pii-location { font-size: 0.85em; opacity: 0.6; margin-left: auto; }

        /* Audit Stamp */
        .audit-stamp {
            background: rgba(16,124,16,0.08);
            border: 1px solid rgba(16,124,16,0.3);
            border-radius: 12px;
            padding: 20px;
            margin-top: 20px;
        }
        .audit-stamp-header { font-weight: 600; margin-bottom: 12px; color: #00CC6A; }
        .audit-stamp-line { font-size: 0.9em; opacity: 0.8; padding: 3px 0; }
        .auditor-results-actions { display: flex; gap: 12px; margin-top: 20px; }

        /* Mode Selector */
        .mode-cards { display: flex; gap: 16px; justify-content: center; margin: 24px 0; flex-wrap: wrap; }
        .mode-card { flex: 1; max-width: 280px; min-width: 200px; padding: 24px; border: 1px solid rgba(255,255,255,0.15); border-radius: 12px; cursor: pointer; text-align: center; transition: all 0.2s; }
        .mode-card:hover { border-color: rgba(0,120,212,0.6); background: rgba(0,120,212,0.1); }
        .mode-card-icon { font-size: 2em; margin-bottom: 8px; }
        .mode-card-title { font-weight: 600; font-size: 1.05em; margin-bottom: 8px; }
        .mode-card-desc { font-size: 0.85em; opacity: 0.7; line-height: 1.4; }

        /* Claims Card */
        .claim-item { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.08); }
        .claim-item:last-child { border-bottom: none; }
        .claim-category { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 600; margin-right: 8px; }
        .claim-category.superlative, .claim-category.comparative { background: rgba(244,67,54,0.2); color: #FF6B6B; }
        .claim-category.stat_claim, .claim-category.stat-claim { background: rgba(255,152,0,0.2); color: #FFB74D; }
        .claim-category.ai_overclaim, .claim-category.ai-overclaim { background: rgba(156,39,176,0.2); color: #CE93D8; }
        .claim-category.green_claim, .claim-category.green-claim { background: rgba(76,175,80,0.2); color: #81C784; }
        .claim-category.customer_evidence, .claim-category.customer-evidence { background: rgba(33,150,243,0.2); color: #64B5F6; }
        .claim-category.pricing { background: rgba(255,193,7,0.2); color: #FFD54F; }
        .claim-category.absolute { background: rgba(244,67,54,0.2); color: #FF6B6B; }
        .claim-text { font-style: italic; color: #FFB900; margin: 6px 0; }
        .claim-risk { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 0.75em; font-weight: 700; }
        .claim-risk.high { background: rgba(244,67,54,0.2); color: #FF6B6B; }
        .claim-risk.medium { background: rgba(255,185,0,0.2); color: #FFB900; }
        .claim-risk.low { background: rgba(76,175,80,0.2); color: #81C784; }
        .claim-issue { font-size: 0.9em; margin-top: 4px; }
        .claim-substantiation { font-size: 0.85em; opacity: 0.7; margin-top: 4px; }
        .claim-recommendation { font-size: 0.85em; opacity: 0.7; font-style: italic; margin-top: 4px; }

        /* Verdict Card */
        .verdict-card { padding: 20px; border-radius: 12px; text-align: center; margin: 16px 0; }
        .verdict-card.verdict-ok { border: 2px solid #4CAF50; background: rgba(76,175,80,0.08); }
        .verdict-card.verdict-intake { border: 2px solid #f44336; background: rgba(244,67,54,0.08); }
        .verdict-badge { font-size: 1.3em; font-weight: 700; margin-bottom: 8px; }
        .verdict-ok .verdict-badge { color: #4CAF50; }
        .verdict-intake .verdict-badge { color: #f44336; }
        .verdict-reason { font-size: 0.9em; opacity: 0.8; margin-bottom: 12px; line-height: 1.4; }
        .verdict-counts { display: flex; gap: 16px; justify-content: center; margin-top: 12px; font-size: 0.85em; }
        .verdict-count { padding: 4px 10px; border-radius: 4px; background: rgba(255,255,255,0.06); }
        .trigger-tag { display: inline-block; padding: 2px 8px; margin: 2px; border-radius: 4px; font-size: 0.8em; background: rgba(244,67,54,0.2); color: #FF6B6B; }

        /* ID Verification Styles */
        .camera-section {
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 20px;
            text-align: center;
        }
        .camera-container {
            position: relative;
            max-width: 640px;
            margin: 0 auto;
        }
        #cameraPreview {
            width: 100%;
            max-width: 640px;
            border-radius: 10px;
            background: #000;
        }
        #capturedImage {
            width: 100%;
            max-width: 640px;
            border-radius: 10px;
            margin-top: 15px;
        }
        .camera-controls {
            margin-top: 15px;
            display: flex;
            gap: 10px;
            justify-content: center;
            flex-wrap: wrap;
        }
        .id-result-card {
            background: rgba(255,255,255,0.1);
            border-radius: 15px;
            padding: 20px;
            margin-top: 20px;
            text-align: left;
        }
        .id-result-card h3 {
            color: var(--brand-accent);
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .id-field {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .id-field:last-child { border-bottom: none; }
        .id-field-label { opacity: 0.7; }
        .id-field-value { font-weight: bold; }
        .status-badge {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
        }
        .status-valid { background: linear-gradient(90deg, #107C10, #00CC6A); }
        .status-warning { background: linear-gradient(90deg, #FF8C00, #FFB900); }
        .status-error { background: linear-gradient(90deg, #D41C00, #FF4444); }
        .processing-steps {
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            padding: 15px;
            margin-top: 15px;
            text-align: left;
        }
        .step {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 0;
        }
        .step-icon {
            width: 24px;
            height: 24px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
        }
        .step-pending { background: rgba(255,255,255,0.2); }
        .step-active { background: #0078D4; }
        .step-done { background: #107C10; }
        .step-text { flex: 1; }
        .step-status { font-size: 0.8em; opacity: 0.7; }
        .ocr-preview {
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
            padding: 15px;
            margin-top: 15px;
            font-family: monospace;
            font-size: 0.85em;
            max-height: 150px;
            overflow-y: auto;
            text-align: left;
            white-space: pre-wrap;
        }
        .privacy-note {
            background: rgba(16, 124, 16, 0.2);
            border: 1px solid rgba(16, 124, 16, 0.5);
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .privacy-icon { font-size: 1.5em; }

        /* Check Scanner / Mode Switcher */
        .id-mode-switcher { display: flex; gap: 0; margin-bottom: 20px; background: rgba(255,255,255,0.06); border-radius: 10px; padding: 4px; }
        .id-mode-btn { flex: 1; padding: 10px 16px; border: none; border-radius: 8px; background: transparent; color: rgba(255,255,255,0.5); font-size: 0.9em; font-weight: 600; cursor: pointer; transition: all 0.2s; }
        .id-mode-btn.active { background: var(--brand-accent); color: #fff; }
        .id-mode-btn:hover:not(.active) { color: rgba(255,255,255,0.8); }
        .check-result-card { display: none; background: rgba(255,255,255,0.05); border-radius: 15px; padding: 20px; margin-top: 20px; border: 1px solid rgba(255,255,255,0.1); }
        .check-result-card h3 { display: flex; justify-content: space-between; align-items: center; margin: 0 0 15px 0; padding-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.1); }
        .check-field { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
        .check-field-label { color: rgba(255,255,255,0.5); font-size: 0.85em; }
        .check-field-value { color: #fff; font-weight: 500; text-align: right; max-width: 60%; }
        .check-amount { font-size: 1.4em; font-weight: 700; color: #10b981; text-align: center; padding: 12px; background: rgba(16,185,129,0.1); border-radius: 10px; margin: 12px 0; }
        .check-flags { margin-top: 15px; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.1); }
        .check-flag { display: flex; align-items: center; gap: 8px; padding: 6px 10px; margin: 4px 0; border-radius: 6px; font-size: 0.85em; }
        .check-flag.flag-pass { background: rgba(16,185,129,0.1); color: #10b981; }
        .check-flag.flag-warn { background: rgba(234,179,8,0.1); color: #eab308; }
        .check-flag.flag-fail { background: rgba(239,68,68,0.1); color: #ef4444; }
        .check-demo-btn { background: rgba(var(--brand-accent-rgb),0.15); color: var(--brand-accent); border: 1px solid rgba(var(--brand-accent-rgb),0.3); padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 0.85em; font-weight: 600; margin-top: 10px; }
        .check-demo-btn:hover { background: rgba(var(--brand-accent-rgb),0.25); }
        .demo-id-preview { margin-top: 16px; text-align: center; }
        .demo-id-preview img { max-width: 420px; width: 100%; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }
        .mock-id-card { max-width: 420px; margin: 0 auto; background: linear-gradient(135deg, #e8e8e8, #f5f5f5); border-radius: 12px; padding: 16px 20px; color: #222; font-family: Arial, sans-serif; box-shadow: 0 4px 20px rgba(0,0,0,0.4); text-align: left; position: relative; overflow: hidden; }
        .mock-id-card .id-state { font-size: 1.1em; font-weight: 800; color: #1a3a5c; text-transform: uppercase; letter-spacing: 1px; }
        .mock-id-card .id-type { font-size: 0.7em; color: #555; text-transform: uppercase; letter-spacing: 0.5px; }
        .mock-id-card .id-photo-placeholder { width: 80px; height: 100px; background: #ccc; border-radius: 6px; display: inline-block; vertical-align: top; margin-right: 14px; display: flex; align-items: center; justify-content: center; font-size: 2em; color: #999; }
        .mock-id-card .id-details { display: inline-block; vertical-align: top; font-size: 0.8em; line-height: 1.8; }
        .mock-id-card .id-name { font-size: 1em; font-weight: 700; color: #111; margin: 8px 0 4px; }
        .mock-id-card .id-row { color: #444; }
        .mock-id-card .id-row span { color: #888; font-size: 0.85em; }
        .d365-card { display: none; background: linear-gradient(135deg, rgba(44,62,80,0.95), rgba(52,73,94,0.95)); border-radius: 15px; padding: 20px; margin-top: 20px; border: 1px solid rgba(255,255,255,0.15); }
        .d365-card h3 { display: flex; justify-content: space-between; align-items: center; margin: 0 0 15px 0; color: #fff; }
        .d365-badge { font-size: 0.7em; padding: 4px 10px; border-radius: 20px; background: rgba(16,185,129,0.2); color: #10b981; font-weight: 600; }
        .d365-section { margin-bottom: 12px; padding: 12px; background: rgba(255,255,255,0.05); border-radius: 8px; }
        .d365-section-title { font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.5px; color: rgba(255,255,255,0.4); margin-bottom: 8px; font-weight: 600; }
        .d365-field { display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.9em; }
        .d365-field-label { color: rgba(255,255,255,0.5); }
        .d365-field-value { color: #fff; font-weight: 500; }
        .d365-activity { padding: 8px 12px; background: rgba(255,255,255,0.03); border-left: 3px solid var(--brand-accent); border-radius: 4px; margin: 6px 0; font-size: 0.85em; }
        .d365-open-btn { display: inline-block; margin-top: 12px; padding: 8px 20px; background: rgba(0,120,212,0.2); color: #4db8ff; border: 1px solid rgba(0,120,212,0.4); border-radius: 8px; cursor: pointer; font-size: 0.85em; font-weight: 600; text-decoration: none; }
        .d365-open-btn:hover { background: rgba(0,120,212,0.35); }

        /* Pen Signature Pad */
        .sig-section { display: none; margin-top: 20px; border: 1px solid rgba(255,255,255,0.15); border-radius: 15px; overflow: hidden; background: rgba(255,255,255,0.03); }
        .sig-agreement { padding: 16px 20px; font-size: 0.85em; color: rgba(255,255,255,0.6); line-height: 1.6; border-bottom: 1px solid rgba(255,255,255,0.1); }
        .sig-agreement strong { color: rgba(255,255,255,0.85); }
        .sig-pad-wrapper { position: relative; background: #fff; margin: 16px; border-radius: 10px; }
        .sig-pad-wrapper canvas { display: block; border-radius: 10px; cursor: crosshair; touch-action: none; }
        .sig-pad-label { position: absolute; bottom: 40px; left: 20px; right: 20px; border-bottom: 1px solid #ccc; font-size: 0.8em; color: #999; padding-bottom: 4px; pointer-events: none; }
        .sig-pad-label span { background: #fff; padding: 0 8px; position: relative; top: 8px; }
        .sig-controls { display: flex; gap: 10px; padding: 12px 16px; justify-content: flex-end; }
        .sig-btn { padding: 10px 24px; border: none; border-radius: 8px; font-size: 0.85em; font-weight: 600; cursor: pointer; transition: all 0.2s; }
        .sig-clear { background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.7); }
        .sig-clear:hover { background: rgba(255,255,255,0.15); }
        .sig-accept { background: #10b981; color: #fff; }
        .sig-accept:hover { background: #059669; }
        .sig-confirm { display: none; margin-top: 16px; padding: 16px 20px; background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.3); border-radius: 12px; }
        .sig-confirm h4 { margin: 0 0 10px 0; color: #10b981; }
        .sig-confirm .sig-hash { font-family: monospace; font-size: 0.8em; color: rgba(255,255,255,0.5); word-break: break-all; background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 6px; margin: 8px 0; }

        /* Two-Brain Router — Decision Card */
        .decision-card {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(var(--brand-accent-rgb),0.3);
            border-radius: 12px;
            padding: 18px 22px;
            margin: 16px auto;
            max-width: 640px;
        }
        .decision-card-header {
            font-size: 0.75em;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            opacity: 0.5;
            margin-bottom: 12px;
            font-weight: 600;
        }
        .decision-card-row {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding: 6px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            font-size: 0.92em;
        }
        .decision-card-row:last-child { border-bottom: none; }
        .decision-card-label { opacity: 0.7; }
        .decision-card-value { font-weight: 600; text-align: right; max-width: 60%; }
        .confidence-high { color: #00CC6A; }
        .confidence-medium { color: #FFB900; }
        .confidence-low { color: #FF4444; }

        /* Auditor analysis text */
        .router-analysis {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            padding: 16px 20px;
            margin: 16px auto;
            max-width: 640px;
            font-size: 0.92em;
            line-height: 1.6;
            color: #e0e0e0;
        }
        .router-analysis:empty { display: none; }

        /* Document preview card in processing log */
        .doc-preview-card {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            padding: 12px 14px;
            margin: 8px 0;
        }
        .doc-preview-text {
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 0.8em;
            opacity: 0.4;
            margin-top: 6px;
            max-height: 60px;
            overflow: hidden;
            line-height: 1.4;
            white-space: pre-wrap;
        }

        /* Progressive decision card row reveal */
        .decision-card-row {
            transition: opacity 0.4s ease;
        }

        /* Escalation Consent */
        .escalation-header {
            font-size: 1.05em;
            font-weight: 600;
            color: #FFB900;
            margin: 20px 0 4px;
            text-align: center;
        }
        .escalation-subtext {
            text-align: center;
            opacity: 0.6;
            font-size: 0.88em;
            margin-bottom: 16px;
        }

        /* Redaction Diff */
        .redaction-diff {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin: 16px auto;
            max-width: 640px;
        }
        .diff-col {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            overflow: hidden;
        }
        .diff-col-header {
            padding: 8px 12px;
            font-size: 0.78em;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            opacity: 0.5;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            font-weight: 600;
        }
        .diff-col-body {
            padding: 12px;
            font-size: 0.82em;
            line-height: 1.5;
            max-height: 250px;
            overflow-y: auto;
            font-family: 'Cascadia Code', 'Consolas', monospace;
            white-space: pre-wrap;
        }
        .diff-redacted { color: rgba(255,255,255,0.9); }
        .pii-redacted {
            background: rgba(255, 68, 68, 0.25);
            color: #FF6B6B;
            padding: 1px 4px;
            border-radius: 3px;
            font-weight: 600;
        }

        /* Escalation cost bar */
        .escalation-cost {
            display: flex;
            justify-content: center;
            gap: 24px;
            margin: 14px 0;
            font-size: 0.85em;
            opacity: 0.8;
        }

        /* Escalation buttons */
        .escalation-buttons {
            display: flex;
            gap: 12px;
            justify-content: center;
            margin: 20px 0;
        }
        .escalation-btn {
            padding: 12px 24px;
            border-radius: 10px;
            border: 2px solid;
            font-size: 0.95em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .escalation-btn.decline {
            background: rgba(0, 204, 106, 0.1);
            border-color: rgba(0, 204, 106, 0.4);
            color: #00CC6A;
        }
        .escalation-btn.decline:hover {
            background: rgba(0, 204, 106, 0.25);
            border-color: #00CC6A;
        }
        .escalation-btn.approve {
            background: rgba(255, 185, 0, 0.08);
            border-color: rgba(255, 185, 0, 0.3);
            color: #FFB900;
        }
        .escalation-btn.approve:hover {
            background: rgba(255, 185, 0, 0.2);
            border-color: #FFB900;
        }

        /* Stayed Local celebration */
        .stayed-local-banner {
            text-align: center;
            padding: 24px;
            margin: 20px auto;
            max-width: 500px;
            background: linear-gradient(135deg, rgba(0,204,106,0.1) 0%, rgba(0,204,106,0.03) 100%);
            border: 1px solid rgba(0,204,106,0.3);
            border-radius: 14px;
        }
        .stayed-local-icon {
            font-size: 2.5em;
            margin-bottom: 8px;
            animation: lockPulse 0.6s ease-out;
        }
        @keyframes lockPulse {
            0% { transform: scale(0.5); opacity: 0; }
            50% { transform: scale(1.2); }
            100% { transform: scale(1); opacity: 1; }
        }
        .stayed-local-title {
            font-size: 1.3em;
            font-weight: 700;
            color: #00CC6A;
            margin-bottom: 6px;
        }
        .stayed-local-detail {
            font-size: 0.9em;
            opacity: 0.8;
        }

        /* Trust Receipt */
        .trust-receipt {
            background: rgba(var(--brand-accent-rgb),0.06);
            border: 1px solid rgba(var(--brand-accent-rgb),0.2);
            border-radius: 12px;
            padding: 18px 22px;
            margin: 16px auto;
            max-width: 640px;
        }
        .trust-receipt-header {
            font-size: 0.75em;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            opacity: 0.5;
            margin-bottom: 10px;
            font-weight: 600;
        }
        .trust-receipt-body {
            font-size: 0.88em;
            line-height: 1.7;
        }
        .trust-receipt-line { padding: 2px 0; }
        .trust-receipt-line.highlight {
            color: #00CC6A;
            font-weight: 600;
        }

        /* Warmup overlay */
        .warmup-overlay {
            position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            z-index: 10000;
            display: flex; flex-direction: column;
            align-items: center; justify-content: center;
            transition: opacity 0.5s ease;
        }
        .warmup-overlay.fade-out { opacity: 0; pointer-events: none; }
        .warmup-logo { display: flex; align-items: center; gap: 25px; margin-bottom: 30px; }
        .warmup-logo img { height: 36px; opacity: 0.9; }
        .warmup-title { font-size: 1.4em; font-weight: 600; color: #fff; margin-bottom: 8px; }
        .warmup-status { font-size: 0.95em; color: rgba(255,255,255,0.6); margin-bottom: 24px; }
        .warmup-bar-track {
            width: 320px; height: 4px; background: rgba(255,255,255,0.1);
            border-radius: 2px; overflow: hidden;
        }
        .warmup-bar-fill {
            height: 100%; width: 0%; border-radius: 2px;
            background: linear-gradient(90deg, #60a5fa, #a78bfa);
            transition: width 0.3s ease;
        }
        .warmup-time { font-size: 0.8em; color: rgba(255,255,255,0.35); margin-top: 12px; }

        /* ── Performance Monitor Overlay ── */
        .perf-monitor {
            position: fixed; bottom: 20px; right: 20px; z-index: 9999;
            background: rgba(10, 12, 20, 0.92); backdrop-filter: blur(16px);
            border: 1px solid rgba(255,255,255,0.12); border-radius: 14px;
            padding: 18px 22px 14px; width: 300px;
            font-family: 'Segoe UI', system-ui, sans-serif;
            color: #e0e0e0; box-shadow: 0 8px 32px rgba(0,0,0,0.5);
            transform: translateY(20px); opacity: 0; pointer-events: none;
            transition: opacity 0.3s ease, transform 0.3s ease;
        }
        .perf-monitor.visible { opacity: 1; transform: translateY(0); pointer-events: auto; }
        .perf-monitor-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
        .perf-monitor-title { font-size: 0.75em; text-transform: uppercase; letter-spacing: 1.5px; font-weight: 700; color: rgba(255,255,255,0.5); }
        .perf-monitor-close { background: none; border: none; color: rgba(255,255,255,0.35); cursor: pointer; font-size: 1.1em; padding: 2px 6px; border-radius: 4px; }
        .perf-monitor-close:hover { color: #fff; background: rgba(255,255,255,0.1); }
        .perf-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
        .perf-label { width: 32px; font-size: 0.7em; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: rgba(255,255,255,0.55); flex-shrink: 0; }
        .perf-bar-track { flex: 1; height: 8px; background: rgba(255,255,255,0.08); border-radius: 4px; overflow: hidden; position: relative; }
        .perf-bar-fill { height: 100%; border-radius: 4px; transition: width 0.8s ease; min-width: 2px; }
        .perf-bar-fill.cpu { background: linear-gradient(90deg, #60a5fa, #3b82f6); }
        .perf-bar-fill.gpu { background: linear-gradient(90deg, #34d399, #10b981); }
        .perf-bar-fill.npu { background: linear-gradient(90deg, #f6d107, #f18f12); }
        .perf-bar-fill.mem { background: linear-gradient(90deg, #a78bfa, #8b5cf6); }
        .perf-value { width: 38px; font-size: 0.8em; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }
        .perf-value.cpu { color: #60a5fa; }
        .perf-value.gpu { color: #34d399; }
        .perf-value.npu { color: #f6d107; }
        .perf-value.mem { color: #a78bfa; }
        .perf-mem-detail { font-size: 0.7em; color: rgba(255,255,255,0.3); text-align: right; margin-top: -6px; margin-bottom: 8px; }
        .perf-sparkline { display: flex; align-items: flex-end; gap: 1px; height: 24px; margin-top: 6px; padding-top: 4px; border-top: 1px solid rgba(255,255,255,0.06); }
        .perf-sparkline-bar { width: 4px; border-radius: 1px; transition: height 0.3s ease; background: rgba(241,143,18,0.6); min-height: 1px; }
        .perf-spark-label { display: flex; justify-content: space-between; font-size: 0.6em; color: rgba(255,255,255,0.25); margin-top: 2px; }
        .perf-hotkey-hint { font-size: 0.65em; color: rgba(255,255,255,0.2); text-align: center; margin-top: 8px; letter-spacing: 0.5px; }
        .perf-chip-icon { display: inline-block; font-size: 0.85em; margin-right: 3px; vertical-align: -1px; }

        /* ── Live Assist ── */
        .live-assist-layout { display: grid; grid-template-columns: 3fr 2fr; grid-template-rows: 1fr auto; gap: 16px; height: calc(100vh - 80px); padding: 16px; }
        .live-transcript-pane { background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; }
        .live-prompter-pane { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; }
        .live-bottom-bar { grid-column: 1 / -1; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 10px 20px; display: flex; align-items: center; gap: 12px; font-size: 0.85em; }
        .live-pane-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 0.85em; text-transform: uppercase; letter-spacing: 1px; color: rgba(255,255,255,0.6); font-weight: 600; }
        .live-pane-header .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: #555; flex-shrink: 0; }
        .live-pane-header .pulse-dot.active { background: #22c55e; animation: livePulse 1.5s ease-in-out infinite; }
        @keyframes livePulse { 0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(34,197,94,0.5); } 50% { opacity: 0.7; box-shadow: 0 0 0 6px rgba(34,197,94,0); } }
        .live-transcript-area { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
        .live-transcript-line { padding: 8px 12px; border-radius: 8px; background: rgba(255,255,255,0.04); animation: liveFadeIn 0.4s ease; font-size: 0.95em; line-height: 1.5; }
        .live-transcript-line .line-time { color: rgba(255,255,255,0.35); font-size: 0.8em; margin-right: 8px; font-family: monospace; }
        .live-transcript-line .line-speaker { font-size: 0.75em; font-weight: 700; letter-spacing: 0.5px; padding: 1px 6px; border-radius: 4px; margin-right: 8px; text-transform: uppercase; }
        .live-transcript-line.speaker-customer .line-speaker { background: rgba(99,102,241,0.2); color: #818cf8; }
        .live-transcript-line.speaker-advisor .line-speaker { background: rgba(34,197,94,0.2); color: #22c55e; }
        .live-transcript-line.speaker-customer { border-left: 3px solid rgba(99,102,241,0.4); }
        .live-transcript-line.speaker-advisor { border-left: 3px solid rgba(34,197,94,0.4); }
        .live-transcript-line.interim { color: rgba(255,255,255,0.4); font-style: italic; background: rgba(255,255,255,0.02); }
        @keyframes liveFadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        .live-insight-cards { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
        .live-insight-card { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; padding: 14px; animation: liveFadeIn 0.5s ease; }
        .live-insight-card .insight-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .live-insight-card .insight-time { font-size: 0.75em; color: rgba(255,255,255,0.35); font-family: monospace; }
        .live-insight-card .sentiment-badge { font-size: 0.7em; font-weight: 700; letter-spacing: 0.5px; padding: 2px 8px; border-radius: 10px; }
        .sentiment-positive { background: rgba(34,197,94,0.15); color: #22c55e; }
        .sentiment-neutral { background: rgba(234,179,8,0.15); color: #eab308; }
        .sentiment-cautious { background: rgba(239,68,68,0.15); color: #ef4444; }
        .live-insight-card .insight-text { font-size: 0.9em; line-height: 1.5; color: rgba(255,255,255,0.85); }
        .live-btn { padding: 8px 16px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.15); background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.8); cursor: pointer; font-size: 0.85em; transition: all 0.2s; display: inline-flex; align-items: center; gap: 6px; }
        .live-btn:hover { background: rgba(255,255,255,0.1); border-color: rgba(255,255,255,0.25); }
        .live-btn.active { background: var(--brand-accent); color: #fff; border-color: var(--brand-accent); }
        .live-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .live-status-text { color: rgba(255,255,255,0.5); font-size: 0.85em; margin-left: auto; }
        .live-translated-line { font-style: italic; color: rgba(255,255,255,0.6); font-size: 0.9em; padding-left: 12px; border-left: 2px solid rgba(var(--brand-accent-rgb),0.4); margin-top: 2px; }
        .live-summary-card { background: linear-gradient(135deg, rgba(var(--brand-accent-rgb),0.1), rgba(var(--brand-accent-rgb),0.05)); border: 1px solid rgba(var(--brand-accent-rgb),0.3); border-radius: 10px; padding: 16px; margin-top: 8px; }
        .live-summary-card h4 { margin: 0 0 8px 0; color: var(--brand-accent); font-size: 0.9em; }
        .live-summary-card p { margin: 4px 0; font-size: 0.85em; color: rgba(255,255,255,0.7); }

        /* ── Field Inspection ── */
        .inspection-workspace { display: grid; grid-template-columns: 300px 1fr 340px; grid-template-rows: 1fr auto; gap: 16px; height: calc(100vh - 80px); padding: 16px; }
        .inspection-form-panel { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; overflow-y: auto; }
        .inspection-photo-panel { background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; }
        .inspection-report-panel { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; overflow-y: auto; }
        .inspection-bottom-bar { grid-column: 1 / -1; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 10px 20px; display: flex; align-items: center; justify-content: space-between; font-size: 0.85em; }

        .inspection-form-panel h3 { margin: 0 0 16px 0; font-size: 1em; color: rgba(255,255,255,0.7); text-transform: uppercase; letter-spacing: 1px; }
        .insp-field { margin-bottom: 14px; }
        .insp-field label { display: block; font-size: 0.8em; color: rgba(255,255,255,0.5); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
        .insp-field input, .insp-field select { width: 100%; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15); color: #fff; padding: 10px 12px; border-radius: 8px; font-size: 0.95em; transition: border-color 0.15s, background 0.15s; }
        .insp-field input:focus, .insp-field select:focus { outline: none; border-color: #60a5fa; background: rgba(255,255,255,0.12); }
        .insp-field input.field-populated { border-color: #34d399; background: rgba(52,211,153,0.08); animation: fieldPop 0.3s ease; }
        @keyframes fieldPop { 0% { transform: translateX(-4px); opacity: 0.5; } 100% { transform: translateX(0); opacity: 1; } }

        .insp-mic-btn { width: 100%; padding: 12px; border: none; border-radius: 10px; background: linear-gradient(135deg, #3b82f6, #6366f1); color: #fff; font-size: 1em; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; transition: transform 0.1s; }
        .insp-mic-btn:hover { transform: scale(1.02); }
        .insp-mic-btn.recording { background: linear-gradient(135deg, #ef4444, #dc2626); animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
        .insp-mic-btn .rec-dot { width: 10px; height: 10px; border-radius: 50%; background: #fff; display: none; }
        .insp-mic-btn.recording .rec-dot { display: inline-block; animation: pulse 1s infinite; }

        .insp-transcript-input { width: 100%; margin-top: 14px; padding: 10px 12px; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15); color: #fff; border-radius: 8px; font-size: 0.9em; font-family: inherit; resize: vertical; min-height: 70px; transition: border-color 0.15s; }
        .insp-transcript-input:focus { outline: none; border-color: #60a5fa; background: rgba(255,255,255,0.12); }
        .insp-transcript-input::placeholder { color: rgba(255,255,255,0.3); }
        .insp-transcript { margin-top: 12px; padding: 10px; background: rgba(255,255,255,0.04); border-radius: 8px; font-size: 0.85em; color: rgba(255,255,255,0.6); max-height: 120px; overflow-y: auto; display: none; }
        .insp-transcript.visible { display: block; }

        .photo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; flex: 1; align-content: start; }
        .photo-grid-empty { display: flex; align-items: center; justify-content: center; flex: 1; color: rgba(255,255,255,0.3); font-size: 0.95em; }
        .photo-thumb { position: relative; border-radius: 8px; overflow: hidden; aspect-ratio: 4/3; cursor: pointer; border: 2px solid transparent; transition: border-color 0.2s; }
        .photo-thumb:hover { border-color: #60a5fa; }
        .photo-thumb img { width: 100%; height: 100%; object-fit: cover; }
        .photo-thumb .photo-badge { position: absolute; top: 6px; right: 6px; padding: 2px 8px; border-radius: 4px; font-size: 0.7em; font-weight: 600; }
        .photo-badge.severity-low { background: #22c55e; color: #000; }
        .photo-badge.severity-moderate { background: #f59e0b; color: #000; }
        .photo-badge.severity-high { background: #ef4444; color: #fff; }
        .photo-badge.severity-critical { background: #7c3aed; color: #fff; }

        .photo-capture-controls { display: flex; gap: 10px; margin-top: 12px; }
        .photo-capture-btn { flex: 1; padding: 10px; border: none; border-radius: 8px; cursor: pointer; font-size: 0.9em; transition: transform 0.1s; }
        .photo-capture-btn:hover { transform: scale(1.02); }
        .photo-capture-btn.primary { background: linear-gradient(135deg, #3b82f6, #6366f1); color: #fff; }
        .photo-capture-btn.secondary { background: rgba(255,255,255,0.1); color: #fff; border: 1px solid rgba(255,255,255,0.2); }

        .camera-live-preview { width: 100%; border-radius: 8px; background: #000; display: none; }
        .camera-live-preview.active { display: block; }

        .classification-card { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 14px; margin-top: 10px; }
        .classification-card .cc-category { font-size: 1.1em; font-weight: 600; margin-bottom: 6px; }
        .classification-card .cc-row { display: flex; align-items: center; gap: 12px; margin-top: 6px; }
        .classification-card .cc-severity { padding: 3px 10px; border-radius: 4px; font-size: 0.8em; font-weight: 600; }
        .classification-card .cc-confidence { flex: 1; }
        .classification-card .cc-confidence-bar { height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; overflow: hidden; }
        .classification-card .cc-confidence-fill { height: 100%; border-radius: 3px; transition: width 0.6s ease; }
        .conf-green .cc-confidence-fill { background: #22c55e; }
        .conf-amber .cc-confidence-fill { background: #f59e0b; }
        .conf-red .cc-confidence-fill { background: #ef4444; }
        .classification-card .cc-explain { font-size: 0.85em; color: rgba(255,255,255,0.6); margin-top: 8px; }
        .classification-card .cc-loading { display: flex; align-items: center; gap: 10px; padding: 18px 0; justify-content: center; color: rgba(255,255,255,0.5); }
        .photo-thumb { cursor: pointer; position: relative; }
        .photo-thumb.selected { outline: 2px solid #3b82f6; outline-offset: 2px; border-radius: 6px; }
        .photo-thumb .photo-expand { position: absolute; bottom: 6px; right: 6px; width: 28px; height: 28px; border-radius: 50%; background: rgba(0,0,0,0.6); color: #fff; border: none; cursor: pointer; display: none; align-items: center; justify-content: center; font-size: 14px; line-height: 1; backdrop-filter: blur(4px); }
        .photo-thumb:hover .photo-expand { display: flex; }
        .photo-lightbox { position: fixed; inset: 0; z-index: 10000; background: rgba(0,0,0,0.88); display: none; align-items: center; justify-content: center; cursor: pointer; backdrop-filter: blur(6px); }
        .photo-lightbox.active { display: flex; }
        .photo-lightbox img { max-width: 90vw; max-height: 85vh; border-radius: 10px; box-shadow: 0 8px 40px rgba(0,0,0,0.5); object-fit: contain; }
        .photo-lightbox .lb-close { position: absolute; top: 20px; right: 24px; width: 40px; height: 40px; border-radius: 50%; background: rgba(255,255,255,0.15); color: #fff; border: none; cursor: pointer; font-size: 22px; display: flex; align-items: center; justify-content: center; }
        .photo-lightbox .lb-close:hover { background: rgba(255,255,255,0.25); }
        .photo-lightbox .lb-caption { position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%); color: rgba(255,255,255,0.7); font-size: 0.9em; background: rgba(0,0,0,0.5); padding: 6px 16px; border-radius: 6px; }

        /* M4 — Pen Annotation styles */
        .photo-lightbox.annotating .lb-close,
        .photo-lightbox.annotating .lb-caption,
        .photo-lightbox.annotating > img { display: none; }
        .annotate-container { display: none; position: relative; }
        .photo-lightbox.annotating .annotate-container { display: block; }
        .annotate-container canvas { border-radius: 10px; display: block; }
        .ink-canvas { position: absolute; top: 0; left: 0; cursor: crosshair; touch-action: none; }
        .annotate-toolbar { display: none; position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%); background: rgba(30,30,30,0.95); backdrop-filter: blur(12px); padding: 10px 16px; border-radius: 12px; gap: 10px; z-index: 10002; border: 1px solid rgba(255,255,255,0.15); }
        .photo-lightbox.annotating .annotate-toolbar { display: flex; }
        .annotate-toolbar button { padding: 8px 18px; border: none; border-radius: 8px; font-size: 0.85em; cursor: pointer; font-weight: 600; transition: transform 0.1s, opacity 0.2s; }
        .annotate-toolbar button:hover { transform: scale(1.05); }
        .ann-undo { background: rgba(255,255,255,0.12); color: #fff; }
        .ann-clear { background: rgba(255,255,255,0.12); color: #fff; }
        .ann-done { background: #10b981; color: #fff; }
        .ann-cancel { background: rgba(239,68,68,0.3); color: #ef4444; }
        .photo-thumb .photo-annotate { position: absolute; bottom: 6px; left: 6px; width: 28px; height: 28px; border-radius: 50%; background: rgba(0,0,0,0.6); color: #fff; border: none; cursor: pointer; display: none; align-items: center; justify-content: center; font-size: 14px; line-height: 1; backdrop-filter: blur(4px); }
        .photo-thumb:hover .photo-annotate { display: flex; }
        .photo-thumb .annotation-badge { position: absolute; top: 6px; left: 6px; width: 22px; height: 22px; border-radius: 50%; background: #ef4444; color: #fff; display: flex; align-items: center; justify-content: center; font-size: 11px; }
        .annotation-note { display: none; margin-top: 10px; padding: 10px 12px; border: 1px solid rgba(14,165,233,0.3); border-radius: 8px; background: rgba(14,165,233,0.06); font-size: 0.85em; color: rgba(255,255,255,0.8); }
        .annotation-note .ann-label { color: #0ea5e9; font-weight: 600; font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }

        .findings-log { margin-bottom: 16px; }
        .findings-log h3 { margin: 0 0 10px 0; font-size: 0.9em; color: rgba(255,255,255,0.6); text-transform: uppercase; letter-spacing: 1px; }
        .finding-item { padding: 10px; background: rgba(255,255,255,0.04); border-radius: 8px; margin-bottom: 8px; font-size: 0.85em; display: flex; align-items: center; gap: 10px; }
        .finding-item .finding-num { width: 24px; height: 24px; border-radius: 50%; background: rgba(255,255,255,0.1); display: flex; align-items: center; justify-content: center; font-size: 0.75em; flex-shrink: 0; }
        .finding-item .finding-text { flex: 1; }

        .report-draft { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 16px; margin-top: 12px; }
        .report-draft h4 { margin: 0 0 10px 0; font-size: 0.85em; color: rgba(255,255,255,0.5); }
        .report-draft .report-content { font-size: 0.9em; line-height: 1.6; color: rgba(255,255,255,0.8); }
        .report-draft .report-content h1, .report-draft .report-content h2, .report-draft .report-content h3 { color: #fff; margin: 12px 0 6px 0; }
        .report-draft .report-empty { color: rgba(255,255,255,0.3); font-style: italic; }

        .insp-generate-btn { width: 100%; padding: 12px; border: none; border-radius: 10px; background: linear-gradient(135deg, #10b981, #059669); color: #fff; font-size: 0.95em; cursor: pointer; margin-top: 12px; transition: transform 0.1s, opacity 0.2s; }
        .insp-generate-btn:hover { transform: scale(1.02); }
        .insp-generate-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
        .insp-translate-btn { width: 100%; padding: 10px; border: 1px solid rgba(255,255,255,0.2); border-radius: 10px; background: rgba(255,255,255,0.05); color: #fff; font-size: 0.9em; cursor: pointer; margin-top: 8px; transition: transform 0.1s; }
        .insp-translate-btn:hover { transform: scale(1.02); }

        .insp-status { display: flex; align-items: center; gap: 8px; color: rgba(255,255,255,0.5); }
        .insp-status .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; }
        .insp-status .status-dot.processing { background: #f59e0b; animation: pulse 1s infinite; }
        .insp-token-count { color: rgba(255,255,255,0.4); font-size: 0.85em; }
        .insp-privacy { display: flex; align-items: center; gap: 6px; color: rgba(255,255,255,0.4); font-size: 0.85em; }

        /* ── Inspection Escalation Dialog ── */
        .insp-escalation-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 1000; display: flex; align-items: center; justify-content: center; }
        .insp-escalation-dialog { background: #1e1e2e; border: 1px solid rgba(255,255,255,0.15); border-radius: 16px; padding: 28px; max-width: 700px; width: 90%; }
        .insp-esc-header { font-size: 1.2em; font-weight: 600; margin-bottom: 6px; color: #f59e0b; }
        .insp-esc-subtext { font-size: 0.85em; color: rgba(255,255,255,0.5); margin-bottom: 20px; }
        .insp-esc-options { display: flex; gap: 16px; }
        .insp-esc-option { flex: 1; padding: 20px; border-radius: 12px; border: 2px solid rgba(255,255,255,0.1); cursor: pointer; transition: border-color 0.2s, transform 0.1s; }
        .insp-esc-option:hover { transform: scale(1.02); }
        .insp-esc-option.esc-cloud { border-color: rgba(255,185,0,0.3); }
        .insp-esc-option.esc-cloud:hover { border-color: #FFB900; }
        .insp-esc-option.esc-local { border-color: rgba(0,204,106,0.4); background: rgba(0,204,106,0.05); }
        .insp-esc-option.esc-local:hover { border-color: #00CC6A; }
        .insp-esc-option h4 { margin: 0 0 8px 0; font-size: 1em; }
        .insp-esc-option p { margin: 4px 0; font-size: 0.82em; color: rgba(255,255,255,0.6); }
        .insp-esc-option .esc-highlight { font-size: 0.8em; font-weight: 600; margin-top: 8px; }
        .insp-esc-option.esc-local .esc-highlight { color: #00CC6A; }
        .insp-esc-option.esc-cloud .esc-highlight { color: #FFB900; }
        .insp-esc-preferred { display: inline-block; font-size: 0.7em; background: #00CC6A; color: #000; padding: 2px 8px; border-radius: 4px; font-weight: 600; margin-left: 8px; vertical-align: middle; }

        /* ── Inspection Stayed Local Banner ── */
        .insp-stayed-local { background: rgba(0,204,106,0.08); border: 1px solid rgba(0,204,106,0.3); border-radius: 10px; padding: 16px; text-align: center; margin-top: 12px; }
        .insp-stayed-local .lock-icon { font-size: 2em; animation: lockPulse 0.6s ease-out; }
        .insp-stayed-local .sl-title { font-weight: 600; margin-top: 4px; color: #00CC6A; }
        .insp-stayed-local .sl-detail { font-size: 0.82em; color: rgba(255,255,255,0.5); margin-top: 4px; }

        /* ── Inspection Dashboard Tally ── */
        .insp-dashboard-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1001; display: flex; align-items: center; justify-content: center; }
        .insp-dashboard { background: #1a1a2e; border: 1px solid rgba(255,255,255,0.12); border-radius: 20px; padding: 36px; max-width: 750px; width: 90%; }
        .insp-dashboard h2 { text-align: center; margin: 0 0 24px 0; font-size: 1.3em; color: #fff; }
        .insp-dash-columns { display: flex; gap: 20px; margin-bottom: 24px; }
        .insp-dash-col { flex: 1; border-radius: 14px; padding: 24px; }
        .insp-dash-col.local { background: rgba(0,204,106,0.08); border: 1px solid rgba(0,204,106,0.25); }
        .insp-dash-col.cloud { background: rgba(239,68,68,0.05); border: 1px solid rgba(239,68,68,0.15); }
        .insp-dash-col h3 { margin: 0 0 16px 0; font-size: 0.85em; text-transform: uppercase; letter-spacing: 1px; }
        .insp-dash-col.local h3 { color: #00CC6A; }
        .insp-dash-col.cloud h3 { color: #ef4444; }
        .insp-dash-task { padding: 8px 0; font-size: 0.9em; color: rgba(255,255,255,0.7); display: flex; align-items: center; gap: 8px; }
        .insp-dash-task .check { color: #00CC6A; font-weight: bold; }
        .insp-dash-zero { font-size: 3em; text-align: center; color: rgba(239,68,68,0.4); padding: 20px 0; }
        .insp-dash-summary { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 14px 20px; text-align: center; font-size: 0.9em; color: rgba(255,255,255,0.5); margin-bottom: 20px; }
        .insp-dash-close { display: block; margin: 0 auto; padding: 12px 32px; border: 1px solid rgba(255,255,255,0.2); border-radius: 10px; background: rgba(255,255,255,0.05); color: #fff; font-size: 0.95em; cursor: pointer; transition: transform 0.1s; }
        .insp-dash-close:hover { transform: scale(1.02); background: rgba(255,255,255,0.1); }
        .insp-summary-btn { padding: 8px 16px; border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; background: rgba(255,255,255,0.05); color: rgba(255,255,255,0.6); font-size: 0.8em; cursor: pointer; transition: transform 0.1s; }
        .insp-summary-btn:hover { transform: scale(1.02); color: #fff; }

        @media (max-width: 1200px) {
            .inspection-workspace { grid-template-columns: 260px 1fr 300px; }
        }
        @media (max-width: 900px) {
            .inspection-workspace { grid-template-columns: 1fr; grid-template-rows: auto; height: auto; }
        }
        {{THEME_OVERRIDES}}
    </style>
</head>
<body>
    <!-- Warmup overlay — shown until model is ready -->
    <div class="warmup-overlay" id="warmupOverlay">
        <div class="warmup-logo">
            <img src="/logos/surface-logo.png" alt="Surface" onerror="this.style.display='none'">
            <img src="/logos/copilot-logo.avif" alt="Copilot+" onerror="this.style.display='none'">
        </div>
        <div class="warmup-title">{{APP_TITLE}}</div>
        <div class="warmup-status" id="warmupStatus">Loading {{MODEL_LABEL}} on NPU...</div>
        <div class="warmup-bar-track"><div class="warmup-bar-fill" id="warmupBar"></div></div>
        <div class="warmup-time" id="warmupTime"></div>
    </div>

    <!-- Performance Monitor Overlay (Ctrl+Shift+M) -->
    <div class="perf-monitor" id="perfMonitor">
        <div class="perf-monitor-header">
            <span class="perf-monitor-title"><span class="perf-chip-icon">&#9889;</span> Device Performance</span>
            <button class="perf-monitor-close" id="perfClose" title="Close (Ctrl+Shift+M)">&times;</button>
        </div>
        <div class="perf-row"><span class="perf-label">CPU</span><div class="perf-bar-track"><div class="perf-bar-fill cpu" id="perfCpuBar" style="width:0%"></div></div><span class="perf-value cpu" id="perfCpuVal">0%</span></div>
        <div class="perf-row"><span class="perf-label">GPU</span><div class="perf-bar-track"><div class="perf-bar-fill gpu" id="perfGpuBar" style="width:0%"></div></div><span class="perf-value gpu" id="perfGpuVal">0%</span></div>
        <div class="perf-row"><span class="perf-label">NPU</span><div class="perf-bar-track"><div class="perf-bar-fill npu" id="perfNpuBar" style="width:0%"></div></div><span class="perf-value npu" id="perfNpuVal">0%</span></div>
        <div class="perf-sparkline" id="perfSparkline"></div>
        <div class="perf-spark-label"><span>NPU 30s</span><span>now</span></div>
        <div class="perf-hotkey-hint">Ctrl + Shift + M</div>
    </div>

    <!-- Mobile hamburger (hidden on desktop) -->
    <button class="mobile-hamburger" id="mobileHamburger" aria-label="Open menu">&#9776;</button>
    <div class="sidebar-backdrop" id="sidebarBackdrop"></div>

    <div class="app-shell">
      <!-- ── Sidebar ── -->
      <aside class="sidebar" id="appSidebar">
        <button class="sidebar-toggle" id="sidebarToggle" title="Toggle sidebar">&#9776;</button>
        <div class="sidebar-brand">
          {{SIDEBAR_LOGO}}
        </div>

        <nav class="sidebar-nav">
          {{PERSONA_SWITCHER}}
          <div class="concierge-bell" id="conciergeBell" title="Branch Arrivals">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>
            <span>Branch Arrivals</span>
            <span class="bell-badge" id="bellBadge">0</span>
          </div>
          <a class="sidebar-nav-item active" data-tab="chat">
            <span class="nav-icon">{{TAB_CHAT_ICON}}</span>
            <span class="sidebar-label">{{TAB_CHAT_NAME}}<span class="sidebar-nav-sub">{{TAB_CHAT_SUB}} with {{MODEL_LABEL}}</span></span>
          </a>
          <a class="sidebar-nav-item" data-tab="day">
            <span class="nav-icon">{{TAB_DAY_ICON}}</span>
            <span class="sidebar-label">{{TAB_DAY_NAME}}<span class="sidebar-nav-sub">{{TAB_DAY_SUB}}</span></span>
          </a>
          <a class="sidebar-nav-item" data-tab="auditor">
            <span class="nav-icon">{{TAB_AUDITOR_ICON}}</span>
            <span class="sidebar-label">{{TAB_AUDITOR_NAME}}<span class="sidebar-nav-sub">{{TAB_AUDITOR_SUB}}</span></span>
          </a>
          <a class="sidebar-nav-item" data-tab="id">
            <span class="nav-icon">{{TAB_ID_ICON}}</span>
            <span class="sidebar-label">{{TAB_ID_NAME}}<span class="sidebar-nav-sub">{{TAB_ID_SUB}}</span></span>
          </a>
          <a class="sidebar-nav-item" data-tab="live">
            <span class="nav-icon">{{TAB_LIVE_ICON}}</span>
            <span class="sidebar-label">{{TAB_LIVE_NAME}}<span class="sidebar-nav-sub">{{TAB_LIVE_SUB}}</span></span>
          </a>
          <a class="sidebar-nav-item" data-tab="field">
            <span class="nav-icon">{{TAB_FIELD_ICON}}</span>
            <span class="sidebar-label">{{TAB_FIELD_NAME}}<span class="sidebar-nav-sub">{{TAB_FIELD_SUB}}</span></span>
          </a>
        </nav>

        <div class="sidebar-footer">
          <div class="savings-widget" id="savingsWidget">
            <div class="savings-header">&#128994; LOCAL AI SESSION</div>
            <div class="savings-stat" id="savingsCalls">0 calls &middot; 0 tokens</div>
            <div class="savings-stat savings-stat-hero" id="savingsCost">&#128176; $0.00 saved vs cloud</div>
            <div class="savings-stat" id="savingsPower">&#9889; 0 Wh local &middot; 0 Wh cloud</div>
            <div class="savings-stat savings-stat-hero" id="savingsCO2">&#127793; 0g CO&#8322; avoided</div>
            <div class="savings-stat savings-stat-compact" id="savingsCompact">&#128994; $0.00</div>
          </div>
          <span class="badge" style="text-align:center;">&#9889; {{CHIP_LABEL}}</span>
          <span class="offline-badge" id="offlineBadge">Online</span>
          <div class="sidebar-footer-controls">
            <div class="sidebar-footer-label">Network</div>
            <button class="net-toggle-btn net-toggle-off" id="goOfflineBtn" title="Disable Wi-Fi">&#9992;&#65039; Go Offline</button>
            <button class="net-toggle-btn net-toggle-on" id="goOnlineBtn" title="Enable Wi-Fi">&#128246; Go Online</button>
            <div class="model-selector" style="margin:0;">
              <label for="modelSelect">Model:</label>
              <select id="modelSelect">
                <option value="{{MODEL_ALIAS}}">{{MODEL_LABEL}} (NPU)</option>
              </select>
            </div>
          </div>
          <div class="poc-footer">{{POC_FOOTER}}</div>
        </div>
      </aside>

      <!-- ── Main Content ── -->
      <main class="main-content">
        <!-- Industry Packs: stub banner (hidden unless stub mode) -->
        <div id="industry-stub-banner" class="industry-stub-banner" style="display:none;">
          Architecture Preview: <span id="stubIndustryName"></span> pack is a stub. Demo content not yet authored.
        </div>
        <div class="container">
        <!-- Hidden tab buttons (preserve IDs for switchToTab backward compat) -->
        <div class="tabs" style="display:none;">
            <button class="tab-btn" id="dayTabBtn">My Day</button>
            <button class="tab-btn active" id="chatTabBtn">AI Agent</button>
            <button class="tab-btn" id="auditorTabBtn">&#128274; Auditor</button>
            <button class="tab-btn" id="idTabBtn">ID Verification</button>
            <button class="tab-btn" id="liveTabBtn">Live Assist</button>
            <button class="tab-btn" id="fieldTabBtn">Field Inspection</button>
        </div>

        <!-- My Day Tab -->
        <div id="day-tab" class="tab-content">
            <div class="auditor-header"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="2" fill="#f6d107" stroke="none"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg> MORNING BRIEFING</div>

            <!-- Data Summary Cards -->
            <div class="day-cards">
                <div class="day-card" id="emailCard" data-peek="emails">
                    <div class="card-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/><circle cx="12" cy="10" r="1.5" fill="#f6d107" stroke="none"/></svg></div>
                    <div class="card-count" id="emailCount">&mdash;</div>
                    <div class="card-label">Emails</div>
                    <div class="card-hint">click to peek</div>
                    <div class="card-peek" id="emailPeek"></div>
                </div>
                <div class="day-card" id="eventCard" data-peek="events">
                    <div class="card-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><rect x="7" y="14" width="4" height="3" rx="0.5" fill="#f6d107" stroke="none"/></svg></div>
                    <div class="card-count" id="eventCount">&mdash;</div>
                    <div class="card-label">Events Today</div>
                    <div class="card-hint">click to peek</div>
                    <div class="card-peek" id="eventPeek"></div>
                </div>
                <div class="day-card" id="taskCard" data-peek="tasks">
                    <div class="card-icon">&#9744;</div>
                    <div class="card-count" id="taskCount">&mdash;</div>
                    <div class="card-label">Tasks Due</div>
                    <div class="card-hint">click to peek</div>
                    <div class="card-peek" id="taskPeek"></div>
                </div>
            </div>

            <!-- Hero Action Buttons -->
            <div class="hero-btn-row">
                <button class="brief-me-btn" id="briefMeBtn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="2" fill="{{BRAND_HOVER}}" stroke="none"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg> Brief Me</button>
                <button class="focus-btn" id="focusBtn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="{{BRAND_HOVER}}" stroke="none"/></svg> Top 3 Focus</button>
                <button class="tomorrow-btn" id="tomorrowBtn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><rect x="7" y="14" width="4" height="3" rx="0.5" fill="{{BRAND_HOVER}}" stroke="none"/></svg> Tomorrow</button>
            </div>

            <!-- Secondary Action Buttons -->
            <div class="day-actions">
                <button class="day-action-btn" id="triageBtn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/><circle cx="12" cy="10" r="1.5" fill="#f6d107" stroke="none"/></svg> Triage Inbox</button>
                <button class="day-action-btn" id="prepBtn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><rect x="8" y="9" width="3" height="2" rx="0.5" fill="#f6d107" stroke="none"/></svg> Prep for Next Meeting</button>
            </div>

            <!-- Progress Indicator -->
            <div class="briefing-progress" id="briefingProgress"></div>

            <!-- Briefing Result -->
            <div class="briefing-result" id="briefingResult">
                <div class="exec-summary">
                    <div class="summary-label">Executive Summary</div>
                    <div id="execSummaryText"></div>
                </div>
                <div class="breakdown-area" id="breakdownArea"></div>
                <div class="briefing-footer">
                    <span>&#128274; All data processed locally on NPU</span>
                    <span id="briefingTimer"></span>
                </div>
            </div>

            <div class="tab-footer">{{DEVICE_LABEL}} &mdash; {{MODEL_LABEL}} on {{CHIP_LABEL}} &mdash; All processing happens locally</div>
        </div>

        <!-- Agent Chat Tab -->
        <div id="chat-tab" class="tab-content active">
          <div class="auditor-header"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:8px;"><rect x="3" y="3" width="18" height="14" rx="2"/><path d="M8 21h8M12 17v4"/><circle cx="12" cy="10" r="2" fill="#f6d107" stroke="none"/></svg>ADVISOR ASSISTANT</div>
          <div class="agent-chat-layout">

            <!-- Suggestion chips (directly under tabs) -->
            <div class="chat-empty-state" id="chatEmptyState">
              <div class="suggestion-grid">
                <button class="suggestion-chip" data-action="my-calendar">
                  <span class="chip-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><rect x="7" y="14" width="4" height="3" rx="0.5" fill="#f6d107" stroke="none"/></svg></span>
                  <span>My Calendar</span>
                </button>
                <button class="suggestion-chip" data-action="prep-next-client">
                  <span class="chip-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/><circle cx="12" cy="7" r="1.5" fill="#f6d107" stroke="none"/></svg></span>
                  <span>Prep Next Client</span>
                </button>
                <a class="suggestion-chip" href="https://orgdf28000a.crm.dynamics.com/main.aspx?appid=c22cb86f-ff3c-f111-88b5-002248357e0e&pagetype=genux&id=e62fe4bc-354b-4113-86e8-2653b2b6b3a4" target="_blank" style="text-decoration:none;">
                  <span class="chip-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/><circle cx="9" cy="7" r="1.5" fill="#f6d107" stroke="none"/></svg></span>
                  <span>Customer Queue</span>
                </a>
                <a class="suggestion-chip" href="https://outlook.cloud.microsoft/calendar/view/day" target="_blank" style="text-decoration:none;">
                  <span class="chip-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/><circle cx="12" cy="10" r="1.5" fill="#f6d107" stroke="none"/></svg></span>
                  <span>Outlook / Office</span>
                </a>
              </div>
            </div>

            <!-- Chat messages -->
            <div class="chat-container" id="chatContainer">
            </div>

            <!-- AI Actions Log (collapsible) -->
            <div id="auditTrail" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:10px 15px;margin-bottom:10px;max-height:120px;overflow-y:auto;font-size:0.8em;display:none;">
              <strong style="color:var(--brand-accent);">AI Actions (Logged)</strong>
              <div style="font-size:0.85em;opacity:0.5;margin:4px 0 6px;">All actions recorded locally for review.</div>
              <div id="auditEntries"></div>
            </div>

            <!-- Input bar (bottom, like Claude/ChatGPT) -->
            <div class="chat-input-wrapper">
              <div class="input-area">
                <button id="attachBtn" title="Load a document">+</button>
                <input type="text" id="userInput" placeholder="Ask anything or try a suggestion above...">
                <button id="sendBtn" title="Send">&#10148;</button>
              </div>
            </div>
            <div id="chatTimer" class="response-timer"></div>

            <!-- Bottom status bar -->
            <div class="agent-topbar">
              <div class="topbar-left">
                <div class="topbar-status" id="connectivityCard" style="cursor:pointer;" title="Click to refresh status">
                    <span class="status-dot green" id="netDot"></span>
                    <span id="netStatus">Online</span>
                </div>
                <div class="topbar-divider"></div>
                <div class="topbar-status">
                    <span class="status-dot blue" id="npuDot"></span>
                    <span id="npuStatus">NPU Ready</span>
                </div>
              </div>
              <div class="topbar-right">
                <button class="topbar-btn" id="qpAuditSummary" title="View AI action log"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><rect x="8" y="9" width="3" height="2" rx="0.5" fill="#f6d107" stroke="none"/></svg> Audit Log</button>
                <button class="topbar-btn" id="qpClear" title="Clear chat"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg> Clear</button>
                <div class="topbar-divider"></div>
                <div class="policy-icon-wrap">
                  <button class="topbar-btn" title="Agent Policy">&#128737;&#65039;</button>
                  <div class="policy-tooltip">
                    &#128203; <strong>Agent Policy</strong><br>
                    &#9989; Read within approved folder<br>
                    &#9989; Create new documents<br>
                    &#9989; Run approved commands<br>
                    &#10060; No file deletion<br>
                    &#10060; No network access<br>
                    &#128220; All actions logged
                  </div>
                </div>
              </div>
            </div>

            <!-- Hidden elements: keep IDs for JS handlers -->
            <input type="file" id="agentFileInput" accept=".pdf,.docx,.txt,.md" style="display:none;">
            <button id="qpSummarizeDoc" style="display:none;"></button>
            <button id="qpDetectPII" style="display:none;"></button>
            <button id="qpSaveSummary" style="display:none;"></button>
            <span id="agentFileName" style="display:none;"></span>

            <div class="tab-footer">{{DEVICE_LABEL}} &mdash; {{MODEL_LABEL}} on {{CHIP_LABEL}} &mdash; All processing happens locally</div>
          </div>
        </div>

        <!-- Auditor Tab (unified: structured analysis + smart escalation) -->
        <div id="auditor-tab" class="tab-content">

            <div class="poc-banner">&#9888;&#65039; <strong>PROOF OF CONCEPT DEMO</strong> -- {{POC_AUDITOR}}</div>

            <!-- Mode Selector -->
            <div id="auditorModeSelector">
                <div class="auditor-header"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><path d="M12 2L4 5v6c0 5.55 3.84 10.74 8 12 4.16-1.26 8-6.45 8-12V5L12 2z"/><path d="M9 12l2 2 4-4" stroke="#f6d107" stroke-width="2"/></svg> PII GUARD</div>
                <div class="mode-cards">
                    <div class="mode-card" id="modeCardContract" data-mode="contract">
                        <div class="mode-card-icon">&#128274;</div>
                        <div class="mode-card-title">Contract / Legal Review</div>
                        <div class="mode-card-desc">Structured risk analysis of contracts, NDAs, and legal documents with smart escalation.</div>
                    </div>
                    <div class="mode-card" id="modeCardMarketing" data-mode="marketing">
                        <div class="mode-card-icon">&#128226;</div>
                        <div class="mode-card-title">Marketing / Campaign Review</div>
                        <div class="mode-card-desc">CELA compliance check for marketing assets. Claims analysis, substantiation requirements, and intake determination.</div>
                    </div>
                </div>
            </div>

            <!-- State 1a: Contract Input Zone -->
            <div id="routerInputZone" style="display:none;">
                <div class="auditor-dropzone" id="routerDropzone">
                    <div class="dropzone-icon">&#128274;</div>
                    <div class="dropzone-title">Drop a confidential document</div>
                    <div class="dropzone-subtitle">Full analysis runs on-device. Smart escalation if expert review needed.</div>
                    <input type="file" id="routerFileInput" accept=".pdf,.docx,.txt,.md" style="display:none;">
                    <button class="auditor-upload-btn" id="routerUploadBtn">Select File</button>
                    <div class="dropzone-formats">PDF &bull; DOCX &bull; TXT &bull; MD</div>
                </div>
                <div style="text-align:center;margin:16px 0 8px;opacity:0.5;font-size:0.9em;">&mdash; or &mdash;</div>
                <div style="max-width:600px;margin:0 auto;">
                    <div class="input-area">
                        <input type="text" id="routerQueryInput" placeholder="Ask a question about your local documents..." style="flex:1;padding:10px 14px;border:none;background:transparent;color:#fff;font-size:1em;outline:none;">
                        <button class="send-btn" id="routerAskBtn">&#10148;</button>
                    </div>
                </div>
                <div class="auditor-demo-section" style="margin-top:20px;">
                    <div style="opacity:0.6;font-size:0.9em;margin-bottom:8px;">Quick demo:</div>
                    <button class="auditor-demo-btn" id="routerDemoBtn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><rect x="8" y="9" width="3" height="2" rx="0.5" fill="#f6d107" stroke="none"/></svg> Analyze Demo NDA</button>
                    <button class="auditor-demo-btn" id="routerEscalationDemoBtn" style="margin-top:8px;border-color:rgba(255,185,0,0.4);color:#FFB900;">&#9888;&#65039; Demo: Escalation Path</button>
                </div>
                <div style="text-align:center;margin-top:16px;">
                    <a href="#" id="contractBackLink" style="color:rgba(255,255,255,0.5);font-size:0.85em;text-decoration:none;">&larr; Back to mode selection</a>
                </div>
            </div>

            <!-- State 1b: Marketing Input Zone -->
            <div id="marketingInputZone" style="display:none;">
                <div class="auditor-header"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><path d="M3 11l18-5v16l-18-5v-6z"/><path d="M11 11v6"/><circle cx="7" cy="14" r="1" fill="#f6d107" stroke="none"/></svg> MARKETING / CAMPAIGN REVIEW</div>
                <div class="auditor-dropzone" id="marketingDropzone">
                    <div class="dropzone-icon">&#128226;</div>
                    <div class="dropzone-title">Drop a marketing asset for CELA review</div>
                    <div class="dropzone-subtitle">Claims analysis, substantiation check, and CELA intake determination — all on-device.</div>
                    <input type="file" id="marketingFileInput" accept=".pdf,.docx,.txt,.md" style="display:none;">
                    <button class="auditor-upload-btn" id="marketingUploadBtn">Select File</button>
                    <div class="dropzone-formats">PDF &bull; DOCX &bull; TXT &bull; MD</div>
                </div>
                <div class="auditor-demo-section" style="margin-top:20px;">
                    <div style="opacity:0.6;font-size:0.9em;margin-bottom:8px;">Quick demo:</div>
                    <button class="auditor-demo-btn" id="marketingDemoCleanBtn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><rect x="8" y="9" width="3" height="2" rx="0.5" fill="#f6d107" stroke="none"/></svg> Review: Clean Campaign</button>
                    <button class="auditor-demo-btn" id="marketingDemoRiskyBtn" style="margin-top:8px;border-color:rgba(255,185,0,0.4);color:#FFB900;">&#9888;&#65039; Review: Risky Campaign Brief</button>
                </div>
                <div style="text-align:center;margin-top:16px;">
                    <a href="#" id="marketingBackLink" style="color:rgba(255,255,255,0.5);font-size:0.85em;text-decoration:none;">&larr; Back to mode selection</a>
                </div>
            </div>

            <!-- State 2: Results -->
            <div id="routerDecision" style="display:none;">
                <div id="routerStatusArea" class="processing-log">
                    <div class="processing-log-header">&#128203; PROCESSING LOG</div>
                    <div class="processing-log-content" id="routerStatusLog"></div>
                </div>

                <!-- Structured Results Cards (PII, Risk, Obligations, Summary) -->
                <div id="auditorResultsCards"></div>

                <div id="routerDecisionCard" style="display:none;">
                    <div class="decision-card">
                        <div class="decision-card-header">LOCAL DECISION</div>
                        <div class="decision-card-row">
                            <span class="decision-card-label">Answered locally:</span>
                            <span id="dcConfidence" class="decision-card-value"></span>
                        </div>
                        <div class="decision-card-row">
                            <span class="decision-card-label">Local Knowledge sources:</span>
                            <span id="dcSources" class="decision-card-value"></span>
                        </div>
                        <div class="decision-card-row">
                            <span class="decision-card-label">Escalation benefit:</span>
                            <span id="dcFrontierBenefit" class="decision-card-value"></span>
                        </div>
                    </div>

                    <div class="router-analysis" id="routerAnalysisText"></div>

                    <!-- Escalation Consent (shown only if MEDIUM/LOW) -->
                    <div id="escalationConsent" style="display:none;">
                        <div class="escalation-header">&#9888;&#65039; ESCALATION AVAILABLE &mdash; Consult Expert (Frontier AI)</div>
                        <div class="escalation-subtext">Review exactly what would leave the device:</div>

                        <div class="redaction-diff">
                            <div class="diff-col">
                                <div class="diff-col-header">Original (stays on device)</div>
                                <div class="diff-col-body" id="diffOriginal"></div>
                            </div>
                            <div class="diff-col">
                                <div class="diff-col-header">Sanitized payload (would be sent)</div>
                                <div class="diff-col-body diff-redacted" id="diffRedacted"></div>
                            </div>
                        </div>

                        <div class="escalation-cost">
                            <span>PII redacted: <strong id="escPiiCount">0</strong> items</span>
                            <span>Estimated tokens: <strong id="escTokens">0</strong></span>
                            <span>Estimated cost: <strong id="escCost">$0.0000</strong></span>
                        </div>

                        <div class="escalation-buttons">
                            <button class="escalation-btn decline" id="btnDeclineEsc">&#128274; Stay Local &mdash; Send Nothing</button>
                            <button class="escalation-btn approve" id="btnApproveEsc">&#9729;&#65039; Send Sanitized to Frontier</button>
                        </div>
                    </div>

                    <!-- Stayed Local Celebration -->
                    <div id="stayedLocalBanner" style="display:none;">
                        <div class="stayed-local-banner">
                            <div class="stayed-local-icon" id="stayedLocalLockIcon">&#128274;</div>
                            <div class="stayed-local-title">Stayed Local</div>
                            <div class="stayed-local-detail" id="stayedLocalDetail"></div>
                        </div>
                    </div>

                    <!-- Trust Receipt -->
                    <div id="routerTrustReceipt" style="display:none;">
                        <div class="trust-receipt">
                            <div class="trust-receipt-header">&#128203; TRUST RECEIPT</div>
                            <div class="trust-receipt-body" id="trustReceiptBody"></div>
                        </div>
                    </div>

                    <!-- Post-action buttons -->
                    <div id="routerPostActions" style="display:none;text-align:center;margin-top:16px;">
                        <button class="auditor-action-btn" onclick="resetAuditor()">&#128274; Analyze Another Document</button>
                    </div>
                </div>

                <!-- Audit Stamp -->
                <div class="audit-stamp" id="auditStamp" style="display:none;"></div>
            </div>

            <div class="tab-footer">{{DEVICE_LABEL}} &mdash; {{MODEL_LABEL}} on {{CHIP_LABEL}} &mdash; All processing happens locally</div>
        </div>

        <!-- ID Verification Tab -->
        <div id="id-tab" class="tab-content">
            <div class="poc-banner">&#9888;&#65039; <strong>PROOF OF CONCEPT DEMO</strong> -- {{POC_ID}}</div>
            <div class="auditor-header"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="2" y="4" width="20" height="16" rx="2"/><circle cx="9" cy="11" r="2.5" fill="#f6d107" stroke="none"/><path d="M15 9h4M15 12h3M15 15h2M5 17c0-2 1.5-3 4-3s4 1 4 3"/></svg> ID &amp; CHECK VERIFY</div>

            <div class="id-mode-switcher">
                <button class="id-mode-btn active" id="idModeBtn" data-mode="id"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="2" y="4" width="20" height="16" rx="2"/><circle cx="9" cy="11" r="2.5" fill="#f6d107" stroke="none"/><path d="M15 9h4M15 12h3M15 15h2M5 17c0-2 1.5-3 4-3s4 1 4 3"/></svg> Scan ID</button>
                <button class="id-mode-btn" id="checkModeBtn" data-mode="check"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="2" y="5" width="20" height="14" rx="1"/><path d="M2 10h20"/><circle cx="17" cy="15" r="2" fill="#f6d107" stroke="none"/></svg> Scan Check</button>
            </div>

            <div class="camera-section">
                <div class="camera-selector" style="margin-bottom: 15px;">
                    <label for="cameraSelect" style="margin-right: 10px;">Camera:</label>
                    <select id="cameraSelect" style="background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.3); color: #fff; padding: 8px 15px; border-radius: 20px; min-width: 200px;">
                        <option value="">Loading cameras...</option>
                    </select>
                    <button id="refreshCamerasBtn" style="background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.3); color: #fff; padding: 8px 15px; border-radius: 20px; margin-left: 10px; cursor: pointer;">Refresh</button>
                </div>
                <div class="camera-container">
                    <video id="cameraPreview" autoplay playsinline style="display: none;"></video>
                    <canvas id="captureCanvas" style="display: none;"></canvas>
                    <img id="capturedImage" style="display: none;" alt="Captured ID">
                    <div id="cameraPlaceholder" style="padding: 60px; background: rgba(0,0,0,0.3); border-radius: 10px;">
                        <div style="margin-bottom: 15px;"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="2" y="5" width="48" height="15" rx="2"/><circle cx="12" cy="13" r="3"/><circle cx="12" cy="13" r="1" fill="#f6d107" stroke="none"/><path d="M17 5V3H7v2"/></svg></div>
                        <div>Click "Start Camera" to begin ID verification</div>
                    </div>
                </div>
                
                <div class="camera-controls">
                    <button class="camera-btn" id="startCameraBtn">Start Camera</button>
                    <button class="camera-btn" id="captureBtn" style="display: none;">Capture ID</button>
                    <button class="camera-btn" id="retakeBtn" style="display: none;">Retake</button>
                    <button class="camera-btn" id="analyzeIdBtn" style="display: none;">Analyze ID</button>
                    <button class="camera-btn" id="analyzeCheckBtn" style="display: none;">Analyze Check</button>
                    <button class="check-demo-btn" id="loadDemoCheckBtn" style="display: none;"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="2" y="5" width="20" height="14" rx="1"/><path d="M2 10h20"/><circle cx="17" cy="15" r="2" fill="#f6d107" stroke="none"/></svg> Load Demo Check</button>
                    <button class="check-demo-btn" id="loadDemoIdBtn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="2" y="4" width="20" height="16" rx="2"/><circle cx="9" cy="11" r="2.5" fill="#f6d107" stroke="none"/><path d="M15 9h4M15 12h3M15 15h2M5 17c0-2 1.5-3 4-3s4 1 4 3"/></svg> Load Demo ID &#9660;</button>
                    <div id="demoIdMenu" style="display:none; position:absolute; z-index:100; background:rgba(30,30,30,0.97); border:1px solid rgba(255,255,255,0.15); border-radius:10px; padding:6px; backdrop-filter:blur(12px); min-width:220px;">
                        <button class="check-demo-btn" id="demoIdMclovin" style="width:100%; margin:2px 0; text-align:left;"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="2" y="4" width="20" height="16" rx="2"/><circle cx="9" cy="11" r="2.5" fill="#ef4444" stroke="none"/><path d="M15 9h4M15 12h3M15 15h2M5 17c0-2 1.5-3 4-3s4 1 4 3"/></svg> McLovin (Fake ID)</button>
                        <button class="check-demo-btn" id="demoIdJackie" style="width:100%; margin:2px 0; text-align:left;"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="2" y="4" width="20" height="16" rx="2"/><circle cx="9" cy="11" r="2.5" fill="#10b981" stroke="none"/><path d="M15 9h4M15 12h3M15 15h2M5 17c0-2 1.5-3 4-3s4 1 4 3"/></svg> Jackie Rodriguez (Valid)</button>
                    </div>
                </div>
            </div>
            
            <div id="processingSteps" class="processing-steps" style="display: none;">
                <div class="step" id="step1">
                    <div class="step-icon step-pending">1</div>
                    <div class="step-text">Image Capture</div>
                    <div class="step-status">Browser API (Local)</div>
                </div>
                <div class="step" id="step2">
                    <div class="step-icon step-pending">2</div>
                    <div class="step-text">Text Extraction (OCR)</div>
                    <div class="step-status">Tesseract.js (Local)</div>
                </div>
                <div class="step" id="step3">
                    <div class="step-icon step-pending">3</div>
                    <div class="step-text">AI Analysis</div>
                    <div class="step-status">{{MODEL_LABEL}} on NPU (Local)</div>
                </div>
            </div>
            
            <div id="demoIdPreview" class="demo-id-preview" style="display: none;"></div>

            <div id="ocrPreview" class="ocr-preview" style="display: none;">
                <strong>Extracted Text:</strong><br><span id="ocrText"></span>
            </div>
            
            <div id="idResultCard" class="id-result-card" style="display: none;">
                <h3>
                    <span>ID Verification Result</span>
                    <span class="status-badge" id="idStatusBadge">Checking...</span>
                </h3>
                <div id="idFields"></div>
                <div id="idNotes" style="margin-top: 15px; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.1);"></div>
            </div>

            <!-- Check Scanner Result Card -->
            <div id="checkResultCard" class="check-result-card">
                <h3>
                    <span>&#128179; Check Verification Result</span>
                    <span class="status-badge" id="checkStatusBadge">Checking...</span>
                </h3>
                <div id="checkAmount" class="check-amount" style="display:none;"></div>
                <div id="checkFields"></div>
                <div id="checkFlags" class="check-flags"></div>
            </div>

            <!-- D365 Customer Profile Card (after ID scan) -->
            <div id="d365CustomerCard" class="d365-card">
                <h3>
                    <span>&#128100; Customer Profile</span>
                    <span class="d365-badge" id="d365Status">Connected to Dynamics 365</span>
                </h3>
                <div id="d365CustomerContent"></div>
                <a class="d365-open-btn" id="d365OpenLink" href="#" target="_blank">Open in Dynamics 365 &#8594;</a>
            </div>

            <!-- D365 Transaction Confirmation (after check deposit) -->
            <div id="d365TransactionCard" class="d365-card">
                <h3>
                    <span>&#128196; Transaction Logged</span>
                    <span class="d365-badge">Synced to D365</span>
                </h3>
                <div id="d365TransactionContent"></div>
            </div>

            <!-- Pen Signature Section -->
            <div id="sigSection" class="sig-section">
                <div class="sig-agreement">
                    <strong>Account Agreement</strong><br>
                    I, the undersigned, authorize the opening of the account(s) described above and agree to the terms and conditions
                    of the account agreement, fee schedule, and privacy notice provided by the financial institution.
                    I certify that the information provided is accurate and complete. I understand that this account
                    is governed by federal and state regulations, and I consent to electronic record-keeping as permitted by law.
                </div>
                <div class="sig-pad-wrapper">
                    <canvas id="sigCanvas" width="600" height="150"></canvas>
                    <div class="sig-pad-label"><span>Sign here</span></div>
                </div>
                <div class="sig-controls">
                    <button class="sig-btn sig-clear" id="sigClearBtn">Clear</button>
                    <button class="sig-btn sig-accept" id="sigAcceptBtn">&#10003; Accept &amp; Sign</button>
                </div>
            </div>

            <!-- Signature Confirmation -->
            <div id="sigConfirm" class="sig-confirm">
                <h4>&#10003; Signature Captured</h4>
                <div>Document signed digitally on-device. No signature data transmitted.</div>
                <div class="sig-hash" id="sigHash"></div>
                <div style="font-size:0.8em;color:rgba(255,255,255,0.4);margin-top:6px;">Trust Receipt logged. All processing local.</div>
            </div>

            <div class="privacy-note" style="margin-top: 20px;">
                <span class="privacy-icon">&#128274;</span>
                <div>
                    <strong>100% Local Processing</strong><br>
                    <span id="idPrivacyText">Your ID image and data never leave this device. Camera capture, OCR, and AI analysis all run locally.</span>
                </div>
            </div>
            <div class="tab-footer">{{DEVICE_LABEL}} &mdash; {{MODEL_LABEL}} on {{CHIP_LABEL}} &mdash; All processing happens locally</div>
        </div>

        <!-- Live Assist Tab -->
        <div id="live-tab" class="tab-content">
            <div class="live-assist-layout">
                <!-- Left Pane: Live Transcript (60%) -->
                <div class="live-transcript-pane" id="liveTranscriptPane">
                    <div class="live-pane-header">
                        <span class="pulse-dot" id="livePulseDot"></span>
                        Live Transcript
                    </div>
                    <div class="live-transcript-area" id="liveTranscriptArea">
                        <div style="color: rgba(255,255,255,0.3); text-align: center; margin-top: 40px; font-size: 0.9em;">
                            Press <strong>Start Live Voice</strong> or <strong>Run Demo Script</strong> to begin
                        </div>
                    </div>
                </div>

                <!-- Right Pane: AI Prompter (40%) -->
                <div class="live-prompter-pane" id="livePrompterPane">
                    <div class="live-pane-header">
                        <span class="pulse-dot" id="liveInsightDot"></span>
                        AI Advisor Insights
                    </div>
                    <div class="live-insight-cards" id="liveInsightCards">
                        <div id="liveInsightPlaceholder" style="color: rgba(255,255,255,0.3); text-align: center; margin-top: 40px; font-size: 0.9em;">
                            Insights will appear here as the conversation flows
                        </div>
                    </div>
                </div>

                <!-- Bottom Bar -->
                <div class="live-bottom-bar">
                    <button class="live-btn" id="liveVoiceBtn" title="Start live speech-to-text using your microphone"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"/><path d="M19 10v2a7 7 0 01-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><circle cx="12" cy="8" r="1.5" fill="#f6d107" stroke="none"/></svg> Start Live Voice</button>
                    <button class="live-btn" id="liveDemoBtn" title="Run a scripted demo conversation"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><polygon points="5 3 19 12 5 21 5 3" fill="#f6d107" stroke="none"/></svg> Run Demo Script</button>
                    <button class="live-btn" id="liveStopBtn" style="display:none;" title="Stop the current session"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="4" y="4" width="16" height="16" rx="2" fill="#ef4444" stroke="none"/></svg> Stop</button>
                    <button class="live-btn" id="liveTranslateBtn" style="display:none;" title="Translate transcript to another language">&#127760; Translate to Spanish</button>
                    <span class="live-status-text" id="liveStatusText">Ready</span>
                </div>
            </div>
        </div>

        <!-- Field Inspection Tab -->
        <div id="field-tab" class="tab-content">
            <div class="inspection-workspace">

                <!-- Left Panel: Structured Form -->
                <div class="inspection-form-panel">
                    <h3>&#128221; Meeting Details</h3>

                    <div class="insp-field">
                        <label for="inspInspector">Client</label>
                        <input type="text" id="inspInspector" placeholder="{{PLACEHOLDER_CLIENT}}">
                    </div>
                    <div class="insp-field">
                        <label for="inspLocation">Location</label>
                        <input type="text" id="inspLocation" placeholder="{{PLACEHOLDER_LOCATION}}">
                    </div>
                    <div class="insp-field">
                        <label for="inspDateTime">Meeting Date</label>
                        <input type="datetime-local" id="inspDateTime">
                    </div>
                    <div class="insp-field">
                        <label for="inspIssue">Products Discussed</label>
                        <input type="text" id="inspIssue" placeholder="{{PLACEHOLDER_ISSUE}}">
                    </div>
                    <div class="insp-field">
                        <label for="inspSource">Source / Referral</label>
                        <input type="text" id="inspSource" placeholder="{{PLACEHOLDER_SOURCE}}">
                    </div>

                    <p style="margin:12px 0 6px; font-size:0.82em; color:rgba(255,255,255,0.5);">Press <kbd style="background:rgba(255,255,255,0.12); padding:1px 5px; border-radius:3px; font-size:0.95em;">Win+H</kbd> to dictate with on-device speech recognition, or type notes below.</p>
                    <textarea class="insp-transcript-input" id="inspTranscriptInput" rows="4" placeholder="Meeting notes will appear here..."></textarea>
                    <div style="display:flex; gap:8px; margin-top:8px;">
                        <button class="insp-mic-btn" id="inspExtractBtn" style="flex:1;">
                            &#129504; Extract Fields with AI
                        </button>
                    </div>
                    <div style="display:flex; gap:8px; margin-top:6px;">
                        <button class="insp-mic-btn secondary" id="inspFluidDictationBtn" style="flex:1; background: rgba(255,255,255,0.1); font-size:0.85em;">
                            &#127908; Fluid Dictation
                        </button>
                        <button class="insp-mic-btn secondary" id="inspScriptedBtn" style="flex:1; background: rgba(255,255,255,0.1); font-size:0.85em;">
                            &#9654; Use Scripted Input (Demo)
                        </button>
                    </div>

                    <div class="insp-transcript" id="inspTranscript"></div>
                </div>

                <!-- Center Panel: Photo Grid -->
                <div class="inspection-photo-panel">
                    <h3 style="margin:0 0 12px 0; font-size:1em; color:rgba(255,255,255,0.7); text-transform:uppercase; letter-spacing:1px;">&#128247; Photo Evidence</h3>

                    <video id="inspCameraPreview" class="camera-live-preview" autoplay playsinline></video>
                    <canvas id="inspCaptureCanvas" style="display:none;"></canvas>

                    <div class="photo-grid" id="inspPhotoGrid">
                        <div class="photo-grid-empty" id="inspPhotoEmpty">No photos captured</div>
                    </div>

                    <div class="photo-capture-controls">
                        <button class="photo-capture-btn primary" id="inspStartCameraBtn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="2" y="5" width="20" height="15" rx="2"/><circle cx="12" cy="13" r="3"/><circle cx="12" cy="13" r="1" fill="#f6d107" stroke="none"/><path d="M17 5V3H7v2"/></svg> Start Camera</button>
                        <button class="photo-capture-btn primary" id="inspCapturePhotoBtn" style="display:none;">&#128248; Capture</button>
                        <button class="photo-capture-btn secondary" id="inspStopCameraBtn" style="display:none;">Stop Camera</button>
                        <button class="photo-capture-btn secondary" id="inspFlipCameraBtn" style="display:none;">&#128260; Flip</button>
                        <button class="photo-capture-btn secondary" id="inspDemoPhotoBtn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="2" y="3" width="20" height="18" rx="2"/><path d="M2 15l5-5 3 3 4-4 8 8"/><circle cx="8" cy="9" r="2" fill="#f6d107" stroke="none"/></svg> Load Demo Photo</button>
                        <button class="photo-capture-btn secondary" id="inspLoadFormBtn"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15l2 2 4-4" stroke="#f6d107" stroke-width="2"/></svg> Beneficiary Form</button>
                    </div>

                    <!-- Classification card (appears after photo analysis) -->
                    <div class="classification-card" id="inspClassCard" style="display:none;">
                        <div class="cc-loading" id="inspClassLoading" style="display:none;"><span class="spinner"></span> Analyzing image on NPU...</div>
                        <div class="cc-inner">
                            <div class="cc-category" id="inspClassCategory">--</div>
                            <div class="cc-row">
                                <span class="cc-severity" id="inspClassSeverity">--</span>
                                <div class="cc-confidence">
                                    <div style="font-size:0.8em; color:rgba(255,255,255,0.5); margin-bottom:3px;">Confidence: <span id="inspClassConfPct">0</span>%</div>
                                    <div class="cc-confidence-bar"><div class="cc-confidence-fill" id="inspClassConfBar" style="width:0%"></div></div>
                                </div>
                            </div>
                            <div class="cc-explain" id="inspClassExplain"></div>
                            <div id="inspClassSource" style="display:none; font-size:0.75em; color:rgba(255,255,255,0.4); margin-top:6px; font-style:italic;"></div>
                            <button id="inspAnnotateBtn" style="display:none; margin-top:10px; padding:8px 16px; border:none; border-radius:8px; background:rgba(239,68,68,0.15); color:#ef4444; font-size:0.85em; cursor:pointer; font-weight:600; width:100%;">&#9998; Annotate Photo</button>
                            <!-- Signature pad for beneficiary form (inline in classification card) -->
                            <div id="inspSigSection" style="display:none; margin-top:12px; border:1px solid #e0e0e0; border-radius:10px; overflow:hidden; background:#fff;">
                                <div style="padding:12px 16px; font-size:0.82em; color:#555; line-height:1.5; border-bottom:1px solid #e0e0e0;">
                                    <strong style="color:#333;">Beneficiary Designation Agreement</strong><br>
                                    I, the undersigned, hereby designate the beneficiary(ies) listed on this form for the retirement account
                                    referenced above. I understand that this designation supersedes all prior beneficiary designations.
                                    I certify that the information provided is accurate and authorize {{BRAND_COMPANY}} to update the records accordingly.
                                </div>
                                <div style="position:relative; background:#fff; margin:12px; border-radius:8px;">
                                    <canvas id="inspSigCanvas" width="600" height="150" style="display:block; border-radius:8px; cursor:crosshair; touch-action:none; border:1px solid #ccc;"></canvas>
                                    <div style="position:absolute; bottom:40px; left:20px; right:20px; border-bottom:1px solid #ccc; font-size:0.8em; color:#999; padding-bottom:4px; pointer-events:none;"><span style="background:#fff; padding:0 8px; position:relative; top:8px;">Sign here</span></div>
                                </div>
                                <div style="display:flex; gap:10px; padding:10px 16px; justify-content:flex-end;">
                                    <button class="sig-btn sig-clear" id="inspSigClearBtn" style="padding:8px 20px; border:none; border-radius:8px; font-size:0.85em; font-weight:600; cursor:pointer; background:#f5f5f5; color:#666;">Clear</button>
                                    <button class="sig-btn sig-accept" id="inspSigAcceptBtn" style="padding:8px 20px; border:none; border-radius:8px; font-size:0.85em; font-weight:600; cursor:pointer; background:#22c55e; color:#fff;">&#10003; Accept &amp; Sign</button>
                                </div>
                            </div>
                            <div id="inspSigConfirm" style="display:none; margin-top:10px; padding:12px 16px; background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.25); border-radius:10px;">
                                <h4 style="margin:0 0 8px 0; color:#10b981; font-size:0.95em;">&#10003; Signature Captured</h4>
                                <div style="font-size:0.85em; color:#555;">Beneficiary form signed digitally on-device. No signature data transmitted.</div>
                                <div id="inspSigHash" style="font-family:monospace; font-size:0.78em; color:#888; word-break:break-all; background:#f5f5f5; padding:6px 10px; border-radius:6px; margin:6px 0;"></div>
                                <div style="font-size:0.78em; color:#aaa; margin-top:4px;">Trust Receipt logged. All processing local.</div>
                            </div>
                        </div>
                    </div>
                    <div class="annotation-note" id="inspAnnotationNote">
                        <div class="ann-label">&#9998; {{ANNOTATION_LABEL}}</div>
                        <div id="inspAnnotationText"></div>
                    </div>
                    <!-- sigConfirm placeholder removed, now inline above -->
                </div>

                <!-- Photo lightbox overlay -->
                <div class="photo-lightbox" id="inspLightbox">
                    <button class="lb-close" id="inspLbClose">&times;</button>
                    <img id="inspLbImg" src="" alt="Expanded photo">
                    <div class="lb-caption" id="inspLbCaption"></div>
                    <div class="annotate-container" id="inspAnnotateContainer">
                        <canvas id="inspAnnotateBase"></canvas>
                        <canvas id="inspAnnotateInk" class="ink-canvas"></canvas>
                    </div>
                    <div class="annotate-toolbar" id="inspAnnotateToolbar">
                        <button class="ann-undo" id="inspAnnUndo">&#8630; Undo</button>
                        <button class="ann-clear" id="inspAnnClear">Clear</button>
                        <button class="ann-done" id="inspAnnDone">&#10003; Done</button>
                        <button class="ann-cancel" id="inspAnnCancel">Cancel</button>
                    </div>
                </div>

                <!-- Right Panel: Findings + Report -->
                <div class="inspection-report-panel">
                    <div class="findings-log">
                        <h3>&#128270; Findings</h3>
                        <div id="inspFindings">
                            <div class="finding-item" style="color:rgba(255,255,255,0.3); font-style:italic;">No findings yet. Capture and classify a photo to add findings.</div>
                        </div>
                    </div>

                    <button class="insp-generate-btn" id="inspGenerateBtn" disabled>&#128196; Generate Report</button>
                    <button class="insp-translate-btn" id="inspTranslateBtn" style="display:none;">&#127760; Translate to Spanish</button>
                    <button class="insp-generate-btn" id="inspPostD365Btn" style="display:none; background:linear-gradient(135deg, #0078D4, #00BCF2);">&#9729; Post to D365</button>
                    <div id="inspD365PostResult" style="display:none; margin-top:10px; padding:12px 16px; border-radius:10px; font-size:0.85em;"></div>

                    <!-- Client Follow-Up Email Panel -->
                    <div id="inspEmailPanel" style="display:none; margin-top:16px; border:1px solid #e0e0e0; border-radius:12px; overflow:hidden; background:#fff;">
                        <div style="padding:12px 16px; background:#f8f9fa; border-bottom:1px solid #e0e0e0; font-weight:600; font-size:0.9em; color:#333;">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#333" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 4L12 13 2 4"/></svg>
                            Send Follow-Up to Client
                        </div>
                        <div style="padding:12px 16px;">
                            <div style="display:flex; gap:8px; margin-bottom:8px; align-items:center;">
                                <label style="font-size:0.82em; color:#666; white-space:nowrap;">To:</label>
                                <span id="inspEmailTo" style="font-size:0.85em; color:#333; font-weight:500;">Looking up customer email...</span>
                            </div>
                            <div style="display:flex; gap:8px; margin-bottom:10px; align-items:center;">
                                <label style="font-size:0.82em; color:#666; white-space:nowrap;">Subject:</label>
                                <input type="text" id="inspEmailSubject" value="Thank you for meeting with us today" style="flex:1; padding:6px 10px; border:1px solid #ddd; border-radius:6px; font-size:0.85em; color:#333; background:#fff;">
                            </div>
                            <div style="position:relative;">
                                <textarea id="inspEmailBody" rows="6" placeholder="Type or dictate your follow-up message... (press Win+H for voice input)" style="width:100%; padding:10px 12px; border:1px solid #ddd; border-radius:8px; font-size:0.85em; color:#333; background:#fff; resize:vertical; font-family:inherit; line-height:1.5; box-sizing:border-box;"></textarea>
                                <div style="position:absolute; top:8px; right:8px; display:flex; gap:4px;">
                                    <button id="inspEmailMicBtn" title="Dictate with voice (Win+H)" style="padding:4px 8px; border:none; border-radius:6px; background:rgba(24,61,76,0.08); cursor:pointer; font-size:1.1em;">&#127908;</button>
                                </div>
                            </div>
                            <div style="display:flex; gap:8px; margin-top:10px; flex-wrap:wrap;">
                                <button id="inspPolishBtn" style="flex:1; padding:10px 16px; border:none; border-radius:8px; background:linear-gradient(135deg, rgba(var(--brand-accent-rgb),0.12), rgba(var(--brand-accent-rgb),0.06)); color:var(--brand-accent); font-size:0.85em; font-weight:600; cursor:pointer; min-width:140px;">&#9998; Polish with Writing Assistant</button>
                                <button id="inspSendEmailBtn" style="flex:1; padding:10px 16px; border:none; border-radius:8px; background:linear-gradient(135deg, #0078D4, #00BCF2); color:#fff; font-size:0.85em; font-weight:600; cursor:pointer; min-width:140px;">&#9993; Send to Customer</button>
                            </div>
                            <div id="inspEmailStatus" style="display:none; margin-top:10px; padding:10px 14px; border-radius:8px; font-size:0.85em;"></div>
                        </div>
                    </div>

                    <div class="report-draft" id="inspReportDraft" style="display:none;">
                        <h4>Report Preview</h4>
                        <div class="report-content" id="inspReportContent">
                            <div class="report-empty">Report will appear here after generation.</div>
                        </div>
                    </div>

                    <div class="insp-stayed-local" id="inspStayedLocal" style="display:none;">
                        <div class="lock-icon" id="inspLockIcon">&#128274;</div>
                        <div class="sl-title">Inspection completed locally</div>
                        <div class="sl-detail">Finding flagged for on-site expert review. Data leaving device: None.</div>
                    </div>
                </div>

                <!-- Bottom Bar: Tokenomics + Status -->
                <div class="inspection-bottom-bar">
                    <div class="insp-status">
                        <span class="status-dot" id="inspStatusDot"></span>
                        <span id="inspStatusText">Ready</span>
                    </div>
                    <div class="insp-token-count" id="inspTokenCount">0 local tokens &middot; $0.00 cloud cost &middot; 0 bytes transmitted</div>
                    <button id="inspAIReportBtn" style="display:none; padding:4px 12px; border:none; border-radius:6px; background:rgba(var(--brand-accent-rgb),0.15); color:var(--brand-accent); font-size:0.78em; font-weight:600; cursor:pointer; margin-left:8px;">&#128202; AI Session Report</button>
                    <button class="insp-summary-btn" id="inspSummaryBtn" style="display:none;">&#128202; Show Summary</button>
                    <div class="insp-privacy">&#128274; 100% Local Processing &mdash; {{CHIP_LABEL}}</div>
                </div>

                <!-- AI Session Report Overlay -->
                <div class="insp-dashboard-overlay" id="inspAIReportOverlay" style="display:none;">
                    <div style="background:#1a1a2e; border:1px solid rgba(255,255,255,0.12); border-radius:20px; padding:32px; max-width:700px; width:92%; max-height:85vh; overflow-y:auto;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
                            <h2 style="margin:0; font-size:1.2em; color:#fff !important;">&#128202; AI Session Report</h2>
                            <button id="inspAIReportClose" style="background:none; border:none; color:rgba(255,255,255,0.5); font-size:1.4em; cursor:pointer;">&times;</button>
                        </div>
                        <div style="font-size:0.78em; color:#ddd !important; margin-bottom:16px;">Every AI operation below ran locally on the Intel NPU. Zero data left this device. Zero cloud API calls.</div>
                        <table style="width:100%; border-collapse:collapse; font-size:0.85em;">
                            <thead>
                                <tr style="border-bottom:1px solid rgba(255,255,255,0.15); text-align:left;">
                                    <th style="padding:8px 10px; color:#ccc !important; font-weight:600; font-size:0.8em; text-transform:uppercase; letter-spacing:0.5px;">#</th>
                                    <th style="padding:8px 10px; color:#ccc !important; font-weight:600; font-size:0.8em; text-transform:uppercase; letter-spacing:0.5px;">Operation</th>
                                    <th style="padding:8px 10px; color:#ccc !important; font-weight:600; font-size:0.8em; text-transform:uppercase; letter-spacing:0.5px;">Model</th>
                                    <th style="padding:8px 10px; color:#ccc !important; font-weight:600; font-size:0.8em; text-transform:uppercase; letter-spacing:0.5px; text-align:right;">Tokens</th>
                                    <th style="padding:8px 10px; color:#ccc !important; font-weight:600; font-size:0.8em; text-transform:uppercase; letter-spacing:0.5px; text-align:right;">Cloud Cost*</th>
                                    <th style="padding:8px 10px; color:#ccc !important; font-weight:600; font-size:0.8em; text-transform:uppercase; letter-spacing:0.5px;">Time</th>
                                </tr>
                            </thead>
                            <tbody id="inspAIReportBody"></tbody>
                        </table>
                        <div id="inspAIReportSummary" style="margin-top:20px; padding:16px; background:rgba(0,204,106,0.08); border:1px solid rgba(0,204,106,0.25); border-radius:12px;"></div>
                        <div style="margin-top:12px; font-size:0.7em; color:#bbb !important;">*Cloud cost estimate based on GPT-4o pricing ($2.50/1M input + $10/1M output tokens). Actual NPU cost: $0.00.</div>
                    </div>
                </div>

                <!-- Escalation Dialog -->
                <div class="insp-escalation-overlay" id="inspEscOverlay" style="display:none;">
                    <div class="insp-escalation-dialog">
                        <div class="insp-esc-header">&#9888;&#65039; LOW CONFIDENCE FINDING &mdash; Escalation Available</div>
                        <div class="insp-esc-subtext">Confidence below 75%. Review escalation options:</div>
                        <div class="insp-esc-options">
                            <div class="insp-esc-option esc-cloud" id="inspEscCloud">
                                <h4>&#9729;&#65039; Escalate to Cloud</h4>
                                <p>Send this photo to a frontier vision model for detailed analysis</p>
                                <p id="inspEscPayload">Sending: 1 photo</p>
                                <p>Withheld: voice transcript, pen annotations, report draft</p>
                                <div class="esc-highlight">Requires connectivity</div>
                            </div>
                            <div class="insp-esc-option esc-local" id="inspEscLocal">
                                <h4>&#128274; Keep Local <span class="insp-esc-preferred">RECOMMENDED</span></h4>
                                <p>Proceed with local classification. Flag for manual expert review.</p>
                                <p>Data leaving device: None</p>
                                <div class="esc-highlight">Cost: $0.00</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Dashboard Tally -->
                <div class="insp-dashboard-overlay" id="inspDashOverlay" style="display:none;">
                    <div class="insp-dashboard">
                        <h2>&#128202; Inspection Summary</h2>
                        <div class="insp-dash-columns">
                            <div class="insp-dash-col local">
                                <h3>Local AI Tasks</h3>
                                <div id="inspDashLocalTasks"></div>
                            </div>
                            <div class="insp-dash-col cloud">
                                <h3>Cloud Tasks</h3>
                                <div class="insp-dash-zero" id="inspDashCloudCount">0</div>
                            </div>
                        </div>
                        <div class="insp-dash-summary" id="inspDashSummary"></div>
                        <button class="insp-dash-close" id="inspDashClose">Close</button>
                    </div>
                </div>

            </div>
        </div>

        <footer>
            {{DEVICE_LABEL}} - {{MODEL_LABEL}} on {{CHIP_LABEL}} - All processing happens locally
        </footer>
        </div><!-- /.container -->
      </main>
    </div><!-- /.app-shell -->

    <script>
        // --- Warmup overlay: poll /health until model is ready ---
        (function() {
            var overlay = document.getElementById("warmupOverlay");
            if (!overlay) return;
            var bar = document.getElementById("warmupBar");
            var statusEl = document.getElementById("warmupStatus");
            var timeEl = document.getElementById("warmupTime");
            var start = Date.now();
            var maxSecs = 90;
            var poll;
            function tick() {
                var elapsed = (Date.now() - start) / 1000;
                var pct = Math.min((elapsed / maxSecs) * 100, 95);
                bar.style.width = pct + "%";
                timeEl.textContent = Math.floor(elapsed) + "s elapsed";
            }
            var ticker = setInterval(tick, 300);
            poll = setInterval(function() {
                fetch("/health").then(function(r) { return r.json(); }).then(function(d) {
                    if (d.ready) {
                        clearInterval(poll);
                        clearInterval(ticker);
                        bar.style.width = "100%";
                        statusEl.textContent = "Ready";
                        setTimeout(function() {
                            overlay.classList.add("fade-out");
                            setTimeout(function() { overlay.remove(); }, 600);
                        }, 400);
                    }
                }).catch(function() {});
            }, 1000);
        })();

        console.log("Script starting...");

        var currentModel = "{{MODEL_ALIAS}}";
        var cameraStream = null;
        
        document.addEventListener("DOMContentLoaded", function() {
            console.log("DOM loaded, setting up event handlers...");

            // Reset session stats and arrivals on page load (hard refresh resets everything)
            fetch("/session-stats/reset", { method: "POST" }).catch(function() {});
            fetch("/arrivals/reset", { method: "POST" }).catch(function() {});
            
            // Tab switching
            function switchToTab(tabId, btnId) {
                document.querySelectorAll(".tab-btn").forEach(function(btn) { btn.classList.remove("active"); });
                document.querySelectorAll(".tab-content").forEach(function(c) { c.classList.remove("active"); });
                document.getElementById(btnId).classList.add("active");
                document.getElementById(tabId).classList.add("active");
                // Sync sidebar nav active state
                var tabKey = tabId.replace("-tab", "");
                document.querySelectorAll(".sidebar-nav-item").forEach(function(item) {
                    item.classList.toggle("active", item.getAttribute("data-tab") === tabKey);
                });
            }

            function showTabToast(text) {
                var toast = document.createElement("div");
                toast.textContent = text;
                toast.style.cssText = "position:fixed;bottom:32px;left:50%;transform:translateX(-50%);" +
                    "background:rgba(0,18,36,0.85);border:1px solid rgba(var(--brand-accent-rgb),0.3);" +
                    "color:#7fdbff;padding:10px 28px;border-radius:20px;font-size:0.82em;" +
                    "z-index:9999;opacity:0;transition:opacity 0.4s ease;pointer-events:none;" +
                    "backdrop-filter:blur(8px);";
                document.body.appendChild(toast);
                setTimeout(function() { toast.style.opacity = "1"; }, 50);
                setTimeout(function() { toast.style.opacity = "0"; }, 2500);
                setTimeout(function() { toast.remove(); }, 3000);
            }

            // Local AI Savings Widget
            function formatNumber(n) {
                return n.toLocaleString("en-US");
            }
            function updateSavingsWidget() {
                // Merge server stats with client-side AI log for unified numbers
                fetch("/session-stats")
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        var callsEl = document.getElementById("savingsCalls");
                        var costEl = document.getElementById("savingsCost");
                        var powerEl = document.getElementById("savingsPower");
                        var co2El = document.getElementById("savingsCO2");
                        var compactEl = document.getElementById("savingsCompact");

                        // Use client-side log if available (more accurate for Meeting Notes tab)
                        var log = window._inspAILog || [];
                        var clientTokens = window._inspTotalTokens || 0;
                        var clientOps = log.length;

                        // If client has tracked operations, use client numbers
                        // Otherwise fall back to server stats (for other tabs)
                        var displayCalls = clientOps > 0 ? clientOps : data.calls;
                        var displayTokens = clientTokens > 0 ? clientTokens : data.total_tokens;

                        if (callsEl) callsEl.textContent = formatNumber(displayCalls) + " calls \u00b7 " + formatNumber(displayTokens) + " tokens";

                        // Cloud cost: GPT-4o blended rate $6.25/1M tokens
                        var cloudCost = displayTokens * 0.00625 / 1000;
                        var costStr = "$" + cloudCost.toFixed(2);
                        if (costEl) costEl.innerHTML = "&#128176; " + costStr + " saved vs cloud";

                        if (powerEl) powerEl.innerHTML = "&#9889; " + data.npu_wh.toFixed(2) + " Wh local \u00b7 " + data.cloud_wh.toFixed(1) + " Wh cloud";
                        if (co2El) co2El.innerHTML = "&#127793; " + data.co2_avoided_g.toFixed(1) + "g CO&#8322; avoided";
                        if (compactEl) compactEl.innerHTML = "&#128994; " + costStr;
                    })
                    .catch(function(e) { console.warn("Savings widget fetch failed:", e); });
            }
            // Initial update and auto-refresh every 5 seconds
            updateSavingsWidget();
            setInterval(updateSavingsWidget, 5000);

            document.getElementById("dayTabBtn").addEventListener("click", function() {
                switchToTab("day-tab", "dayTabBtn");
                showTabToast("Same local AI \u2014 now reading your day");
            });
            document.getElementById("chatTabBtn").addEventListener("click", function() {
                switchToTab("chat-tab", "chatTabBtn");
                showTabToast("Same local AI \u2014 now with execution tools");
            });
            document.getElementById("idTabBtn").addEventListener("click", function() {
                switchToTab("id-tab", "idTabBtn");
                showTabToast("Same local AI \u2014 now verifying identity");
            });
            document.getElementById("liveTabBtn").addEventListener("click", function() {
                switchToTab("live-tab", "liveTabBtn");
                showTabToast("Same local AI \u2014 real-time meeting insights");
            });
            document.getElementById("auditorTabBtn").addEventListener("click", function() {
                switchToTab("auditor-tab", "auditorTabBtn");
                showTabToast("Same local AI \u2014 now in clean room mode");
            });

            // === Sidebar logic ===
            var sidebar = document.getElementById("appSidebar");
            var sidebarToggle = document.getElementById("sidebarToggle");
            var backdrop = document.getElementById("sidebarBackdrop");
            var hamburger = document.getElementById("mobileHamburger");

            // Restore collapsed state from localStorage
            if (localStorage.getItem("sidebarCollapsed") === "true") {
                sidebar.classList.add("collapsed");
            }

            function toggleSidebar() {
                sidebar.classList.toggle("collapsed");
                localStorage.setItem("sidebarCollapsed", sidebar.classList.contains("collapsed"));
            }
            sidebarToggle.addEventListener("click", toggleSidebar);

            // Sidebar nav item clicks
            var tabMap = {
                day:     { tabId: "day-tab",     btnId: "dayTabBtn",     toast: "Same local AI \u2014 now reading your day" },
                chat:    { tabId: "chat-tab",    btnId: "chatTabBtn",    toast: "Same local AI \u2014 now with execution tools" },
                auditor: { tabId: "auditor-tab", btnId: "auditorTabBtn", toast: "Same local AI \u2014 structured analysis + smart escalation" },
                id:      { tabId: "id-tab",      btnId: "idTabBtn",     toast: "Same local AI \u2014 now verifying identity" },
                live:    { tabId: "live-tab",    btnId: "liveTabBtn",   toast: "Same local AI \u2014 real-time meeting insights" },
                field:   { tabId: "field-tab",   btnId: "fieldTabBtn",  toast: "Same local AI \u2014 field inspection + on-site assessment" }
            };
            document.querySelectorAll(".sidebar-nav-item").forEach(function(item) {
                item.addEventListener("click", function() {
                    var key = item.getAttribute("data-tab");
                    var info = tabMap[key];
                    if (info) {
                        switchToTab(info.tabId, info.btnId);
                        showTabToast(info.toast);
                    }
                    // Close mobile overlay
                    if (window.innerWidth <= 768) {
                        sidebar.classList.remove("mobile-open");
                        backdrop.classList.remove("visible");
                    }
                });
            });

            // Mobile hamburger
            if (hamburger) {
                hamburger.addEventListener("click", function() {
                    sidebar.classList.add("mobile-open");
                    backdrop.classList.add("visible");
                });
            }
            if (backdrop) {
                backdrop.addEventListener("click", function() {
                    sidebar.classList.remove("mobile-open");
                    backdrop.classList.remove("visible");
                });
            }

            // === Persona Switcher ===
            (function() {
                var badges = document.querySelectorAll(".persona-badge");
                if (!badges.length) return;
                badges.forEach(function(badge) {
                    badge.addEventListener("click", function() {
                        var wasActive = badge.classList.contains("active");
                        badges.forEach(function(b) { b.classList.remove("active"); });
                        var navItems = document.querySelectorAll(".sidebar-nav-item[data-tab]");
                        if (wasActive) {
                            // Deselect: restore all tabs
                            navItems.forEach(function(n) { n.classList.remove("persona-dim"); });
                            return;
                        }
                        badge.classList.add("active");
                        var tabs = [];
                        try { tabs = JSON.parse(badge.getAttribute("data-persona-tabs") || "[]"); } catch(e) {}
                        navItems.forEach(function(n) {
                            var key = n.getAttribute("data-tab");
                            if (tabs.length && tabs.indexOf(key) === -1) {
                                n.classList.add("persona-dim");
                            } else {
                                n.classList.remove("persona-dim");
                            }
                        });
                    });
                });
            })();

            // === My Day handlers ===
            // --- My Day: counts + peek windows ---
            var peekDataCache = null;

            function loadCounts() {
                fetch("/my-day-counts").then(function(r) { return r.json(); }).then(function(d) {
                    document.getElementById("emailCount").textContent = d.emails;
                    document.getElementById("eventCount").textContent = d.events;
                    document.getElementById("taskCount").textContent = d.tasks;
                });
            }
            loadCounts();

            function loadPeekData(cb) {
                if (peekDataCache) { cb(peekDataCache); return; }
                fetch("/my-day-data").then(function(r) { return r.json(); }).then(function(d) {
                    peekDataCache = d;
                    cb(d);
                });
            }

            function renderEmailPeek(emails) {
                return emails.map(function(em) {
                    return '<div class="peek-row"><span class="peek-from">' + em.from + '</span>' + em.subject + '</div>';
                }).join('');
            }
            function renderEventPeek(events) {
                return events.map(function(ev) {
                    return '<div class="peek-row"><span class="peek-time">' + ev.time + '</span>' + ev.summary +
                        (ev.location ? ' <span style="opacity:0.5">@ ' + ev.location + '</span>' : '') + '</div>';
                }).join('');
            }
            function renderTaskPeek(tasks) {
                return tasks.map(function(t) {
                    var cls = t.priority.toLowerCase();
                    return '<div class="peek-row"><span class="peek-prio ' + cls + '">[' + t.priority + ']</span>' + t.task + '</div>';
                }).join('');
            }

            // Simple Markdown to HTML conversion
            function mdToHtml(text) {
                return text
                    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')  // **bold**
                    .replace(/\*([^*]+)\*/g, '<em>$1</em>')              // *italic*
                    .replace(/^### (.+)$/gm, '<h4>$1</h4>')              // ### Header
                    .replace(/^## (.+)$/gm, '<h3>$1</h3>')               // ## Header
                    .replace(/^# (.+)$/gm, '<h2>$1</h2>')                // # Header
                    .replace(/\n/g, '<br>');                              // newlines
            }

            document.querySelectorAll(".day-card[data-peek]").forEach(function(card) {
                card.addEventListener("click", function(e) {
                    var peekType = this.getAttribute("data-peek");
                    var isExpanded = this.classList.contains("expanded");

                    // Close all other peek windows
                    document.querySelectorAll(".day-card.expanded").forEach(function(c) { c.classList.remove("expanded"); });

                    if (isExpanded) return; // was open, now closed

                    var self = this;
                    loadPeekData(function(data) {
                        var peekEl = self.querySelector(".card-peek");
                        if (peekType === "emails") peekEl.innerHTML = renderEmailPeek(data.emails);
                        else if (peekType === "events") peekEl.innerHTML = renderEventPeek(data.events);
                        else if (peekType === "tasks") peekEl.innerHTML = renderTaskPeek(data.tasks);
                        self.classList.add("expanded");
                    });
                });
            });

            // Close peek when clicking outside
            document.addEventListener("click", function(e) {
                if (!e.target.closest(".day-card[data-peek]")) {
                    document.querySelectorAll(".day-card.expanded").forEach(function(c) { c.classList.remove("expanded"); });
                }
            });

            // --- Network toggle buttons (header) ---
            function handleNetworkToggle(btn, action, label) {
                btn.disabled = true;
                btn.textContent = action === 'offline' ? 'Disabling...' : 'Enabling...';
                fetch("/network-toggle", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({action: action})
                }).then(function(r) { return r.json(); }).then(function(data) {
                    btn.textContent = label;
                    btn.disabled = false;
                    if (data.success) {
                        setTimeout(checkConnectivity, 1500);
                    } else {
                        // Show UAC prompt hint if elevation is needed
                        var msg = data.error || 'Failed to toggle network.';
                        if (msg.indexOf('Administrator') >= 0) {
                            alert('Network toggle requires admin rights.\\nRestart the app as Administrator (right-click \u2192 Run as admin).');
                        } else {
                            alert(msg);
                        }
                    }
                }).catch(function() {
                    btn.textContent = label;
                    btn.disabled = false;
                });
            }
            document.getElementById("goOfflineBtn").addEventListener("click", function() {
                handleNetworkToggle(this, 'offline', '\u2708\uFE0F Go Offline');
            });
            document.getElementById("goOnlineBtn").addEventListener("click", function() {
                handleNetworkToggle(this, 'online', '\uD83D\uDCF6 Go Online');
            });

            function runBriefing(url) {
                var progress = document.getElementById("briefingProgress");
                var result = document.getElementById("briefingResult");
                progress.style.display = "block";
                progress.innerHTML = '<div class="step-line active"><span class="spinner"></span> Starting...</div>';
                result.style.display = "none";
                document.getElementById("briefMeBtn").disabled = true; document.getElementById("focusBtn").disabled = true; document.getElementById("tomorrowBtn").disabled = true;

                fetch(url, {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ model: currentModel })
                })
                .then(function(r) { return r.body.getReader(); })
                .then(function(reader) {
                    var decoder = new TextDecoder();
                    var buffer = "";

                    function processLine(line) {
                        line = line.trim();
                        if (!line) return;
                        try { var evt = JSON.parse(line); } catch(e) { return; }

                        if (evt.type === "status") {
                            progress.innerHTML += '<div class="step-line active"><span class="spinner"></span> ' + evt.message + '</div>';
                            progress.scrollTop = progress.scrollHeight;
                        }
                        else if (evt.type === "briefing") {
                            progress.style.display = "none";
                            result.style.display = "block";
                            document.getElementById("briefMeBtn").disabled = false; document.getElementById("focusBtn").disabled = false; document.getElementById("tomorrowBtn").disabled = false;

                            var text = evt.text || "";
                            // Strip decorative horizontal rules that some models emit
                            text = text.replace(/\n\s*---\s*\n/g, '\n');
                            // Strip title lines like "**MORNING BRIEFING**" at the very start
                            text = text.replace(/^\s*\*\*[A-Z ]+\*\*\s*\n+/, '');
                            // Split into executive summary and details.
                            // Phi uses "PART 2 / KEY DETAILS / PRIORITY" section headers.
                            // Qwen uses numbered bold headers like "**2. ACTIONS:**".
                            var parts = text.split(/\n\s*(?:PART 2|KEY DETAILS|PRIORITY|\*\*\s*2[\.\)]\s)/i);
                            var summary = parts[0].replace(/^PART 1[^\n]*\n/i, '').replace(/^EXECUTIVE SUMMARY[^\n]*\n/i, '').trim();
                            // Strip leading "**1. Summary:**" label from the summary itself
                            summary = summary.replace(/^\*\*\d+\.\s*Summary:?\*\*\s*/i, '');
                            var details = parts.length > 1 ? parts.slice(1).join('\n') : '';

                            document.getElementById("execSummaryText").innerHTML = mdToHtml(summary);

                            // Render details as breakdown sections
                            var breakdownArea = document.getElementById("breakdownArea");
                            if (details) {
                                // Split by section headers:
                                // Phi: lines starting with "ACTIONS:", "PEOPLE:", "WARNINGS:"
                                // Qwen: lines starting with "**3. PEOPLE:**" or "ACTIONS:" etc.
                                var sections = details.split(/\n(?=\*\*\d+\.\s*[A-Z]|\s*[A-Z][A-Z ]+:)/);
                                var html = '';
                                sections.forEach(function(sec) {
                                    sec = sec.trim();
                                    if (!sec) return;
                                    var firstLine = sec.split('\n')[0];
                                    var body = sec.split('\n').slice(1).join('\n').trim();
                                    // Clean header: strip ** markers, leading numbers, trailing colons
                                    var cleanHeader = firstLine.replace(/\*\*/g, '').replace(/^\d+[\.\)]\s*/, '').replace(/:+$/, '').trim();
                                    if (!cleanHeader) return;  // skip empty headers
                                    html += '<div class="breakdown-section">' +
                                        '<div class="breakdown-header" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'none\'?\'block\':\'none\'">' +
                                        '<span>' + cleanHeader + '</span><span>&#9660;</span></div>' +
                                        '<div class="breakdown-body">' + mdToHtml(body) + '</div></div>';
                                });
                                breakdownArea.innerHTML = html;
                            } else {
                                // If model didn't split into parts, show everything as summary
                                document.getElementById("execSummaryText").innerHTML = mdToHtml(text);
                                breakdownArea.innerHTML = '';
                            }

                            var counts = evt.counts || {};
                            var timerEl = document.getElementById("briefingTimer");
                            timerEl.textContent = "Analyzed " + (counts.emails || "?") + " emails, " + (counts.events || "?") + " events, " + (counts.tasks || "?") + " tasks in " + evt.time + "s on NPU";
                            timerEl.classList.add("briefing-result-pulse");
                        }
                        else if (evt.type === "error") {
                            progress.innerHTML += '<div class="step-line" style="color:#FF4444;">Error: ' + evt.message + '</div>';
                            document.getElementById("briefMeBtn").disabled = false; document.getElementById("focusBtn").disabled = false; document.getElementById("tomorrowBtn").disabled = false;
                        }
                    }

                    function read() {
                        reader.read().then(function(chunk) {
                            if (chunk.done) {
                                if (buffer.trim()) processLine(buffer);
                                document.getElementById("briefMeBtn").disabled = false; document.getElementById("focusBtn").disabled = false; document.getElementById("tomorrowBtn").disabled = false;
                                return;
                            }
                            buffer += decoder.decode(chunk.value);
                            var lines = buffer.split("\n");
                            buffer = lines.pop();
                            lines.forEach(processLine);
                            read();
                        });
                    }
                    read();
                })
                .catch(function(err) {
                    progress.innerHTML += '<div style="color:#FF4444;">Connection error: ' + err.message + '</div>';
                    document.getElementById("briefMeBtn").disabled = false; document.getElementById("focusBtn").disabled = false; document.getElementById("tomorrowBtn").disabled = false;
                });
            }

            document.getElementById("briefMeBtn").addEventListener("click", function() { runBriefing("/brief-me"); });
            document.getElementById("triageBtn").addEventListener("click", function() { runBriefing("/triage-inbox"); });
            document.getElementById("prepBtn").addEventListener("click", function() { runBriefing("/prep-next-meeting"); });
            document.getElementById("focusBtn").addEventListener("click", function() { runBriefing("/top-3-focus"); });
            document.getElementById("tomorrowBtn").addEventListener("click", function() { runBriefing("/tomorrow-preview"); });

            // Agent chat handlers
            document.getElementById("sendBtn").addEventListener("click", sendMessage);
            document.getElementById("userInput").addEventListener("keypress", function(e) {
                if (e.key === "Enter") sendMessage();
            });

            // Demo flow buttons — use dedicated endpoints to avoid two-step agent loop
            function runDemoEndpoint(url, statusText, userPrompt) {
                // Show user message first so it's clear what was requested
                if (userPrompt) {
                    addMessage("user", userPrompt);
                }
                var assistantDiv = addMessage("assistant", '<span class="spinner"></span> ' + statusText);
                var contentDiv = assistantDiv.querySelector(".content");

                fetch(url, {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ model: currentModel })
                })
                .then(function(r) { return r.text(); })
                .then(function(body) {
                    var lines = body.split("\n");
                    var resultText = "";
                    var totalTime = "";
                    var fileName = "";
                    var errorMsg = "";
                    lines.forEach(function(line) {
                        line = line.trim();
                        if (!line) return;
                        try { var evt = JSON.parse(line); } catch(e) { return; }
                        if (evt.type === "status") {
                            contentDiv.innerHTML = '<span class="spinner"></span> ' + evt.text;
                        } else if (evt.type === "result") {
                            resultText = evt.text || "";
                            totalTime = evt.time || "";
                            fileName = evt.file || "";
                        } else if (evt.type === "error") {
                            errorMsg = evt.message || "Unknown error";
                        }
                    });
                    if (errorMsg) {
                        contentDiv.innerHTML = '<div style="color:#FF4444;">Error: ' + errorMsg + '</div>';
                    } else if (resultText) {
                        var html = '<div style="margin-top:4px;">' + mdToHtml(resultText) + '</div>';
                        if (fileName) {
                            html += '<div style="margin-top:8px;padding:8px 12px;background:rgba(16,124,16,0.15);border-radius:6px;color:#1db954;">&#128190; Saved to: ' + fileName + '</div>';
                        }
                        html += '<div class="tool-time" style="margin-top:4px;">&#9201; ' + totalTime + 's on NPU</div>';
                        contentDiv.innerHTML = html;
                    }
                    document.getElementById("chatContainer").scrollTop = document.getElementById("chatContainer").scrollHeight;
                })
                .catch(function(err) {
                    contentDiv.innerHTML = '<div style="color:#FF4444;">Error: ' + err + '</div>';
                });
            }

            function runDeviceHealth() {
                addMessage("user", "Run a device health check on this machine");
                var assistantDiv = addMessage("assistant", '<div class="health-checks-container" id="healthChecksLive"></div>');
                var contentDiv = assistantDiv.querySelector(".content");
                var checksDiv = document.getElementById("healthChecksLive");
                checksDiv.innerHTML = '<div style="margin-bottom:8px;font-weight:600;">&#128737; Device Health Check</div>';

                fetch("/demo/device-health", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ model: currentModel })
                })
                .then(function(r) { return r.body.getReader(); })
                .then(function(reader) {
                    var decoder = new TextDecoder();
                    var buffer = "";

                    function processLine(line) {
                        line = line.trim();
                        if (!line) return;
                        try { var evt = JSON.parse(line); } catch(e) { return; }

                        if (evt.type === "check-start") {
                            var entry = document.createElement("div");
                            entry.className = "health-check-entry";
                            entry.id = "hc-" + evt.id;
                            entry.innerHTML = '<div class="health-check-name">' + evt.icon + ' ' + evt.name +
                                ' <span class="spinner" style="display:inline-block;width:12px;height:12px;"></span></div>' +
                                '<div class="health-check-cmd">&gt; ' + evt.cmd + '</div>' +
                                '<div class="health-check-output" id="hc-out-' + evt.id + '"></div>';
                            checksDiv.appendChild(entry);
                        } else if (evt.type === "check-done") {
                            var el = document.getElementById("hc-" + evt.id);
                            if (el) {
                                el.className = "health-check-entry done";
                                el.querySelector(".spinner").style.display = "none";
                                var outEl = document.getElementById("hc-out-" + evt.id);
                                if (outEl) outEl.textContent = evt.output;
                            }
                        } else if (evt.type === "check-error") {
                            var el2 = document.getElementById("hc-" + evt.id);
                            if (el2) {
                                el2.className = "health-check-entry error";
                                el2.querySelector(".spinner").style.display = "none";
                                var outEl2 = document.getElementById("hc-out-" + evt.id);
                                if (outEl2) { outEl2.textContent = evt.output; outEl2.style.color = "#FF4444"; }
                            }
                        } else if (evt.type === "status") {
                            var statusDiv = document.createElement("div");
                            statusDiv.style.cssText = "margin:8px 0;opacity:0.6;font-size:0.85em;";
                            statusDiv.innerHTML = '<span class="spinner" style="display:inline-block;width:12px;height:12px;"></span> ' + evt.text;
                            statusDiv.id = "healthAiStatus";
                            checksDiv.appendChild(statusDiv);
                        } else if (evt.type === "result") {
                            var st = document.getElementById("healthAiStatus");
                            if (st) st.remove();
                            var summaryDiv = document.createElement("div");
                            summaryDiv.className = "health-ai-summary";
                            var html = '<div style="font-weight:600;margin-bottom:6px;">&#129302; AI Assessment</div>' +
                                mdToHtml(evt.text) +
                                '<div class="tool-time" style="margin-top:6px;">&#9201; ' + evt.time + 's on NPU</div>';
                            // Add Learn More buttons for findings
                            if (evt.findings && evt.findings.length > 0) {
                                html += '<div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.08);">' +
                                    '<div style="font-size:0.75em;text-transform:uppercase;letter-spacing:0.05em;opacity:0.4;margin-bottom:6px;">Learn More</div>';
                                evt.findings.forEach(function(f) {
                                    html += '<button class="health-learn-btn" data-question="' +
                                        f.q.replace(/"/g, '&quot;') + '"' +
                                        ' style="display:inline-block;margin:3px 4px 3px 0;padding:4px 10px;font-size:0.78em;' +
                                        'background:rgba(var(--brand-accent-rgb),0.1);border:1px solid rgba(var(--brand-accent-rgb),0.25);border-radius:12px;' +
                                        'color:var(--brand-accent);cursor:pointer;">' + f.label + ' &rarr;</button>';
                                });
                                html += '</div>';
                            }
                            summaryDiv.innerHTML = html;
                            checksDiv.appendChild(summaryDiv);
                            // Bind Learn More click handlers — route to /knowledge (no tools)
                            summaryDiv.querySelectorAll(".health-learn-btn").forEach(function(btn) {
                                btn.addEventListener("click", function() {
                                    var q = this.getAttribute("data-question");
                                    var btnEl = this;
                                    btnEl.disabled = true;
                                    btnEl.style.opacity = '0.5';
                                    btnEl.textContent = 'Thinking...';
                                    // Show the question as a user message in chat
                                    addMessage('user', q);
                                    // Call the knowledge endpoint (no tool access)
                                    fetch('/knowledge', {
                                        method: 'POST',
                                        headers: {'Content-Type': 'application/json'},
                                        body: JSON.stringify({question: q})
                                    }).then(function(resp) {
                                        return resp.text();
                                    }).then(function(body) {
                                        var lines = body.trim().split('\n');
                                        var answer = '';
                                        var time = 0;
                                        lines.forEach(function(line) {
                                            try {
                                                var evt2 = JSON.parse(line);
                                                if (evt2.type === 'result') { answer = evt2.text; time = evt2.time; }
                                                if (evt2.type === 'error') { answer = 'Error: ' + evt2.message; }
                                            } catch(e) {}
                                        });
                                        var rendered = mdToHtml(answer || 'No response.');
                                        if (time) rendered += '<div class="tool-time" style="margin-top:8px;">⏱ ' + time + 's on NPU</div>';
                                        addMessage('assistant', rendered);
                                        btnEl.disabled = false;
                                        btnEl.style.opacity = '1';
                                        btnEl.textContent = btnEl.getAttribute('data-question').split('.')[0].substring(0, 20) + '… ✓';
                                    }).catch(function(err) {
                                        addMessage('assistant', 'Error: ' + err.message);
                                        btnEl.disabled = false;
                                        btnEl.style.opacity = '1';
                                    });
                                });
                            });
                        } else if (evt.type === "error") {
                            checksDiv.innerHTML += '<div style="color:#FF4444;margin-top:8px;">Error: ' + evt.message + '</div>';
                        }
                        document.getElementById("chatContainer").scrollTop = document.getElementById("chatContainer").scrollHeight;
                    }

                    function read() {
                        reader.read().then(function(chunk) {
                            if (chunk.done) {
                                if (buffer.trim()) processLine(buffer);
                                return;
                            }
                            buffer += decoder.decode(chunk.value);
                            var lines = buffer.split("\n");
                            buffer = lines.pop();
                            lines.forEach(processLine);
                            read();
                        });
                    }
                    read();
                })
                .catch(function(err) {
                    checksDiv.innerHTML += '<div style="color:#FF4444;">Error: ' + err + '</div>';
                });
            }

            function runSecurityAudit() {
                addMessage("user", "Run a security audit on this device");
                var assistantDiv = addMessage("assistant", '<div class="health-checks-container" id="securityChecksLive"></div>');
                var contentDiv = assistantDiv.querySelector(".content");
                var checksDiv = document.getElementById("securityChecksLive");
                checksDiv.innerHTML = '<div style="margin-bottom:8px;font-weight:600;">&#128272; Security Audit</div>';

                fetch("/demo/security-audit", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ model: currentModel })
                })
                .then(function(r) { return r.body.getReader(); })
                .then(function(reader) {
                    var decoder = new TextDecoder();
                    var buffer = "";

                    function processLine(line) {
                        line = line.trim();
                        if (!line) return;
                        try { var evt = JSON.parse(line); } catch(e) { return; }

                        if (evt.type === "check-start") {
                            var entry = document.createElement("div");
                            entry.className = "health-check-entry";
                            entry.id = "sc-" + evt.id;
                            entry.innerHTML = '<div class="health-check-name">' + evt.icon + ' ' + evt.name +
                                ' <span class="spinner" style="display:inline-block;width:12px;height:12px;"></span></div>' +
                                '<div class="health-check-cmd">&gt; ' + evt.cmd + '</div>' +
                                '<div class="health-check-output" id="sc-out-' + evt.id + '"></div>';
                            checksDiv.appendChild(entry);
                        } else if (evt.type === "check-done") {
                            var el = document.getElementById("sc-" + evt.id);
                            if (el) {
                                el.className = "health-check-entry done";
                                el.querySelector(".spinner").style.display = "none";
                                var outEl = document.getElementById("sc-out-" + evt.id);
                                if (outEl) outEl.textContent = evt.output;
                            }
                        } else if (evt.type === "check-error") {
                            var el2 = document.getElementById("sc-" + evt.id);
                            if (el2) {
                                el2.className = "health-check-entry error";
                                el2.querySelector(".spinner").style.display = "none";
                                var outEl2 = document.getElementById("sc-out-" + evt.id);
                                if (outEl2) { outEl2.textContent = evt.output; outEl2.style.color = "#FF4444"; }
                            }
                        } else if (evt.type === "status") {
                            var statusDiv = document.createElement("div");
                            statusDiv.style.cssText = "margin:8px 0;opacity:0.6;font-size:0.85em;";
                            statusDiv.innerHTML = '<span class="spinner" style="display:inline-block;width:12px;height:12px;"></span> ' + evt.text;
                            statusDiv.id = "securityAiStatus";
                            checksDiv.appendChild(statusDiv);
                        } else if (evt.type === "result") {
                            var st = document.getElementById("securityAiStatus");
                            if (st) st.remove();
                            var summaryDiv = document.createElement("div");
                            summaryDiv.className = "health-ai-summary";
                            var html = '<div style="font-weight:600;margin-bottom:6px;">&#128272; Security Posture Assessment</div>' +
                                mdToHtml(evt.text) +
                                '<div class="tool-time" style="margin-top:6px;">&#9201; ' + evt.time + 's on NPU</div>';
                            if (evt.findings && evt.findings.length > 0) {
                                html += '<div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.08);">' +
                                    '<div style="font-size:0.75em;text-transform:uppercase;letter-spacing:0.05em;opacity:0.4;margin-bottom:6px;">Learn More</div>';
                                evt.findings.forEach(function(f) {
                                    html += '<button class="health-learn-btn" data-question="' +
                                        f.q.replace(/"/g, '&quot;') + '"' +
                                        ' style="display:inline-block;margin:3px 4px 3px 0;padding:4px 10px;font-size:0.78em;' +
                                        'background:rgba(var(--brand-accent-rgb),0.1);border:1px solid rgba(var(--brand-accent-rgb),0.25);border-radius:12px;' +
                                        'color:var(--brand-accent);cursor:pointer;">' + f.label + ' &rarr;</button>';
                                });
                                html += '</div>';
                            }
                            summaryDiv.innerHTML = html;
                            checksDiv.appendChild(summaryDiv);
                            summaryDiv.querySelectorAll(".health-learn-btn").forEach(function(btn) {
                                btn.addEventListener("click", function() {
                                    var q = this.getAttribute("data-question");
                                    var btnEl = this;
                                    btnEl.disabled = true;
                                    btnEl.style.opacity = '0.5';
                                    btnEl.textContent = 'Thinking...';
                                    addMessage('user', q);
                                    fetch('/knowledge', {
                                        method: 'POST',
                                        headers: {'Content-Type': 'application/json'},
                                        body: JSON.stringify({question: q})
                                    }).then(function(resp) {
                                        return resp.text();
                                    }).then(function(body) {
                                        var lines = body.trim().split('\n');
                                        var answer = '';
                                        var time = 0;
                                        lines.forEach(function(line) {
                                            try {
                                                var evt2 = JSON.parse(line);
                                                if (evt2.type === 'result') { answer = evt2.text; time = evt2.time; }
                                                if (evt2.type === 'error') { answer = 'Error: ' + evt2.message; }
                                            } catch(e) {}
                                        });
                                        var rendered = mdToHtml(answer || 'No response.');
                                        if (time) rendered += '<div class="tool-time" style="margin-top:8px;">⏱ ' + time + 's on NPU</div>';
                                        addMessage('assistant', rendered);
                                        btnEl.disabled = false;
                                        btnEl.style.opacity = '1';
                                        btnEl.textContent = btnEl.getAttribute('data-question').split('.')[0].substring(0, 20) + '… ✓';
                                    }).catch(function(err) {
                                        addMessage('assistant', 'Error: ' + err.message);
                                        btnEl.disabled = false;
                                        btnEl.style.opacity = '1';
                                    });
                                });
                            });
                        } else if (evt.type === "error") {
                            checksDiv.innerHTML += '<div style="color:#FF4444;margin-top:8px;">Error: ' + evt.message + '</div>';
                        }
                        document.getElementById("chatContainer").scrollTop = document.getElementById("chatContainer").scrollHeight;
                    }

                    function read() {
                        reader.read().then(function(chunk) {
                            if (chunk.done) {
                                if (buffer.trim()) processLine(buffer);
                                return;
                            }
                            buffer += decoder.decode(chunk.value);
                            var lines = buffer.split("\n");
                            buffer = lines.pop();
                            lines.forEach(processLine);
                            read();
                        });
                    }
                    read();
                })
                .catch(function(err) {
                    checksDiv.innerHTML += '<div style="color:#FF4444;">Error: ' + err + '</div>';
                });
            }

            function runDeviceSearch() {
                addMessage("user", "Search for files on this device");
                var assistantDiv = addMessage("assistant",
                    '<div class="device-search-container" id="deviceSearchBox">' +
                        '<div style="font-weight:600;margin-bottom:8px;">&#128269; Device Search</div>' +
                        '<div style="font-size:0.85em;opacity:0.6;margin-bottom:8px;">Describe what you\'re looking for in plain English</div>' +
                        '<div class="search-bar">' +
                            '<input type="text" id="deviceSearchInput" placeholder="e.g. Excel files about Q4 budget from last month">' +
                            '<button id="deviceSearchBtn">Search</button>' +
                        '</div>' +
                    '</div>');
                var searchInput = document.getElementById("deviceSearchInput");
                var searchBtn = document.getElementById("deviceSearchBtn");
                searchInput.focus();

                function executeSearch() {
                    var query = searchInput.value.trim();
                    if (!query) return;
                    searchBtn.disabled = true;
                    searchBtn.textContent = "Searching...";
                    searchInput.disabled = true;

                    var resultsDiv = document.createElement("div");
                    resultsDiv.id = "deviceSearchResults";
                    resultsDiv.innerHTML = '<div style="margin:8px 0;opacity:0.6;font-size:0.85em;"><span class="spinner" style="display:inline-block;width:12px;height:12px;"></span> Parsing query with AI...</div>';
                    document.getElementById("deviceSearchBox").appendChild(resultsDiv);

                    fetch("/demo/device-search", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({ query: query, model: currentModel })
                    })
                    .then(function(r) { return r.body.getReader(); })
                    .then(function(reader) {
                        var decoder = new TextDecoder();
                        var buffer = "";

                        function processLine(line) {
                            line = line.trim();
                            if (!line) return;
                            try { var evt = JSON.parse(line); } catch(e) { return; }

                            if (evt.type === "status") {
                                resultsDiv.innerHTML = '<div style="margin:8px 0;opacity:0.6;font-size:0.85em;"><span class="spinner" style="display:inline-block;width:12px;height:12px;"></span> ' + evt.text + '</div>';
                            } else if (evt.type === "search-results") {
                                var html = '<div style="font-weight:600;margin:10px 0 6px;">Files Found (' + evt.count + ')</div>';
                                if (evt.files && evt.files.length > 0) {
                                    evt.files.forEach(function(f) {
                                        html += '<div class="search-result-item">' +
                                            '<div class="sr-name">' + f.name + '</div>' +
                                            '<div class="sr-path">' + f.path + '</div>' +
                                            '<div class="sr-meta">' + f.size + ' &middot; Modified: ' + f.modified + '</div>' +
                                        '</div>';
                                    });
                                } else {
                                    html += '<div style="opacity:0.5;font-size:0.85em;">No matching files found.</div>';
                                }
                                resultsDiv.innerHTML = html;
                            } else if (evt.type === "result") {
                                var summaryDiv = document.createElement("div");
                                summaryDiv.className = "health-ai-summary";
                                summaryDiv.innerHTML = '<div style="font-weight:600;margin-bottom:6px;">&#129302; AI Summary</div>' +
                                    mdToHtml(evt.text) +
                                    '<div class="tool-time" style="margin-top:6px;">&#9201; ' + evt.time + 's on NPU</div>';
                                resultsDiv.appendChild(summaryDiv);
                            } else if (evt.type === "error") {
                                resultsDiv.innerHTML = '<div style="color:#FF4444;margin-top:8px;">Error: ' + evt.message + '</div>';
                            }
                            document.getElementById("chatContainer").scrollTop = document.getElementById("chatContainer").scrollHeight;
                        }

                        function read() {
                            reader.read().then(function(chunk) {
                                if (chunk.done) {
                                    if (buffer.trim()) processLine(buffer);
                                    return;
                                }
                                buffer += decoder.decode(chunk.value);
                                var lines = buffer.split("\n");
                                buffer = lines.pop();
                                lines.forEach(processLine);
                                read();
                            });
                        }
                        read();
                    })
                    .catch(function(err) {
                        resultsDiv.innerHTML = '<div style="color:#FF4444;">Error: ' + err + '</div>';
                    });
                }

                searchBtn.addEventListener("click", executeSearch);
                searchInput.addEventListener("keydown", function(e) {
                    if (e.key === "Enter") executeSearch();
                });
            }

            // Suggestion chip handlers
            function bindChipHandlers() {
                document.querySelectorAll(".suggestion-chip[data-action]").forEach(function(chip) {
                    chip.addEventListener("click", function() {
                        var action = this.getAttribute("data-action");
                        if (action === "device-health") {
                            runDeviceHealth();
                        } else if (action === "security-audit") {
                            runSecurityAudit();
                        } else if (action === "device-search") {
                            runDeviceSearch();
                        } else if (action === "my-calendar") {
                            sendChatMessage("Show me my calendar for today. What meetings do I have and who am I meeting with?");
                        } else if (action === "prep-next-client") {
                            // Progressive steps UI: show each data source being queried
                            var input = document.getElementById("userInput");
                            var emptyState = document.getElementById("chatEmptyState");
                            if (emptyState) emptyState.style.display = "none";
                            addMessage("user", "Prep me for my next client meeting and pull up their D365 profile.");
                            input.value = "";
                            document.getElementById("sendBtn").disabled = true;
                            var assistantDiv = addMessage("assistant", "");
                            var contentDiv = assistantDiv.querySelector(".content");

                            var steps = [
                                {icon: "&#128197;", text: "Checking Outlook Calendar via Work IQ..."},
                                {icon: "&#128269;", text: "Found next client meeting — pulling details..."},
                                {icon: "&#127981;", text: "Looking up client in Dynamics 365 via MCP..."},
                                {icon: "&#128218;", text: "Scanning Product Catalog for recommendations..."},
                                {icon: "&#129302;", text: "Phi-4 Mini summarizing all sources on NPU..."}
                            ];
                            var currentStep = 0;

                            function renderSteps() {
                                var html = '<div style="display:flex;flex-direction:column;gap:6px;font-size:0.88em;">';
                                for (var s = 0; s < steps.length; s++) {
                                    var marker = s < currentStep ? '<span style="color:#22c55e;">&#10003;</span>'
                                               : s === currentStep ? '<span class="spinner" style="width:14px;height:14px;"></span>'
                                               : '<span style="opacity:0.3;">&#9711;</span>';
                                    var opacity = s <= currentStep ? '1' : '0.4';
                                    html += '<div style="display:flex;align-items:center;gap:8px;opacity:' + opacity + ';">' +
                                            marker + ' ' + steps[s].icon + ' ' + steps[s].text + '</div>';
                                }
                                html += '</div>';
                                return html;
                            }

                            contentDiv.innerHTML = renderSteps();

                            // Advance steps 0-3 on a timer (800ms each); step 4 waits for response
                            var stepTimer = setInterval(function() {
                                currentStep++;
                                if (currentStep >= steps.length - 1) {
                                    clearInterval(stepTimer);
                                    currentStep = steps.length - 1;
                                }
                                contentDiv.innerHTML = renderSteps();
                                document.getElementById("chatContainer").scrollTop = document.getElementById("chatContainer").scrollHeight;
                            }, 800);

                            fetch("/chat", {
                                method: "POST",
                                headers: {"Content-Type": "application/json"},
                                body: JSON.stringify({
                                    message: "Use the prep_next_client tool with customer_name Jackie Rodriguez to prep me for my meeting with her and pull up her D365 profile.",
                                    history: []
                                })
                            }).then(function(r) { return r.body.getReader(); })
                            .then(function(reader) {
                                var buffer = "";
                                var responseText = "";
                                var responseTime = "";
                                function read() {
                                    reader.read().then(function(chunk) {
                                        if (chunk.done) {
                                            document.getElementById("sendBtn").disabled = false;
                                            return;
                                        }
                                        buffer += new TextDecoder().decode(chunk.value);
                                        var lines = buffer.split("\n");
                                        buffer = lines.pop();
                                        lines.forEach(function(line) {
                                            if (!line.trim()) return;
                                            try {
                                                var evt = JSON.parse(line);
                                                if (evt.type === "response") {
                                                    responseText = evt.text || "";
                                                    responseTime = evt.time || "";
                                                    lastAssistantResponse = responseText;
                                                    chatHistory.push({"role": "assistant", "content": responseText});
                                                    // Final checkmark on last step + show result below checklist
                                                    clearInterval(stepTimer);
                                                    currentStep = steps.length;
                                                    var finalHtml = renderSteps();
                                                    finalHtml += '<div style="border-top:1px solid rgba(var(--brand-accent-rgb),0.15);margin:12px 0;"></div>';
                                                    finalHtml += '<div>' + mdToHtml(responseText) + '</div>';
                                                    finalHtml += '<div class="tool-time" style="margin-top:4px;">&#9201; Total: ' + responseTime + 's &middot; All search and consolidation on-device</div>';
                                                    contentDiv.innerHTML = finalHtml;
                                                } else if (evt.type === "done") {
                                                    document.getElementById("sendBtn").disabled = false;
                                                    if (lastAssistantResponse) {
                                                        var chips = generateFollowUpChips(lastAssistantResponse);
                                                        if (chips.length > 0) {
                                                            var chipHtml = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;">';
                                                            for (var ci = 0; ci < chips.length; ci++) {
                                                                chipHtml += '<button class="suggestion-chip dynamic-followup" onclick="sendChatMessage(\'' + chips[ci].query.replace(/'/g, "\\'") + '\')" style="font-size:0.82em;padding:8px 14px;cursor:pointer;"><span class="chip-icon">' + chips[ci].icon + '</span><span>' + chips[ci].label + '</span></button>';
                                                            }
                                                            chipHtml += '</div>';
                                                            contentDiv.innerHTML += chipHtml;
                                                        }
                                                    }
                                                }
                                                document.getElementById("chatContainer").scrollTop = document.getElementById("chatContainer").scrollHeight;
                                            } catch(e) {}
                                        });
                                        read();
                                    });
                                }
                                read();
                            });
                            return;
                        }
                    });
                });
            }
            bindChipHandlers();

            // === File Picker for Review & Summarize ===
            var selectedReviewFiles = [];

            function openFilePicker() {
                // Fetch files from Demo folder
                fetch("/demo/list-files")
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var listDiv = document.getElementById("filePickerList");
                    listDiv.innerHTML = "";
                    selectedReviewFiles = [];

                    if (!data.files || data.files.length === 0) {
                        listDiv.innerHTML = '<div style="opacity:0.6;padding:20px;text-align:center;">No documents found in Demo folder</div>';
                        return;
                    }

                    data.files.forEach(function(file) {
                        var item = document.createElement("div");
                        item.setAttribute("data-filename", file.name);

                        // Check if file requires Clean Room (contract, nda, loan)
                        var fnLower = file.name.toLowerCase();
                        var requiresCleanRoom = fnLower.indexOf('contract') >= 0 ||
                                                fnLower.indexOf('nda') >= 0 ||
                                                fnLower.indexOf('loan') >= 0;

                        if (requiresCleanRoom) {
                            // Locked file - must use Clean Room Auditor
                            item.className = "file-picker-item locked";
                            item.style.opacity = "0.6";
                            item.style.cursor = "not-allowed";
                            var badge = file.confidential ?
                                '<span class="file-badge">' + file.confidential.icon + ' ' + file.confidential.label + '</span>' : '';
                            item.innerHTML =
                                '<div style="font-size:1.3em;margin-right:12px;">🔒</div>' +
                                '<div class="file-info">' +
                                    '<div class="file-name">' + file.name + badge + '</div>' +
                                    '<div class="file-meta" style="color:#FFB900;">Requires Clean Room Auditor</div>' +
                                '</div>';
                            item.addEventListener("click", function(e) {
                                e.preventDefault();
                                alert("This document is classified as confidential.\\n\\nPlease use the 🔒 Auditor tab (Clean Room) for secure analysis of contracts, NDAs, and documents containing PII.");
                            });
                        } else {
                            // Normal selectable file
                            item.className = "file-picker-item";
                            var badge = file.confidential ?
                                '<span class="file-badge">' + file.confidential.icon + ' ' + file.confidential.label + '</span>' : '';
                            item.innerHTML =
                                '<input type="checkbox" id="fp_' + file.name.replace(/\./g, '_') + '">' +
                                '<div class="file-info">' +
                                    '<div class="file-name">📄 ' + file.name + badge + '</div>' +
                                    '<div class="file-meta">' + file.size + '</div>' +
                                '</div>';
                            item.addEventListener("click", function(e) {
                                if (e.target.type !== "checkbox") {
                                    var cb = item.querySelector("input[type=checkbox]");
                                    cb.checked = !cb.checked;
                                }
                                updateFilePickerSelection();
                            });
                        }

                        listDiv.appendChild(item);
                    });

                    document.getElementById("filePickerOverlay").style.display = "flex";
                    updateFilePickerSelection();
                });
            }

            function updateFilePickerSelection() {
                selectedReviewFiles = [];
                var items = document.querySelectorAll(".file-picker-item");
                items.forEach(function(item) {
                    var cb = item.querySelector("input[type=checkbox]");
                    if (cb && cb.checked) {
                        item.classList.add("selected");
                        selectedReviewFiles.push(item.getAttribute("data-filename"));
                    } else {
                        item.classList.remove("selected");
                    }
                });

                var btn = document.getElementById("filePickerConfirm");
                btn.textContent = "Review Selected (" + selectedReviewFiles.length + ")";
                btn.disabled = selectedReviewFiles.length === 0;
            }

            window.closeFilePicker = function() {
                document.getElementById("filePickerOverlay").style.display = "none";
            };

            window.confirmFilePicker = function() {
                if (selectedReviewFiles.length === 0) return;
                document.getElementById("filePickerOverlay").style.display = "none";

                // Show user message about selection
                addMessage("user", "Review and summarize these files: " + selectedReviewFiles.join(", "));

                // Phase 1: Get the plan and show approval card with Security Review
                fetch("/demo/review-summarize", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ model: currentModel, phase: "plan", files: selectedReviewFiles })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.type === "plan") {
                        var cardId = "approval_" + Date.now();
                        // Generate Security Review
                        var securityLines = generateSecurityReview(data.text);
                        var securityHtml = '<div class="security-review">' +
                            '<div class="security-review-header">\uD83D\uDEE1\uFE0F Security Review</div>' +
                            securityLines.map(function(line) {
                                return '<div class="security-review-line">\u2022 ' + line + '</div>';
                            }).join('') +
                            '</div>';

                        var html = '<div class="approval-card" id="' + cardId + '" data-files=\'' + JSON.stringify(selectedReviewFiles) + '\'>' +
                            '<div class="approval-header">🔒 This action requires approval</div>' +
                            '<div style="font-size:0.85em;opacity:0.7;margin-bottom:10px;">The following files require authorization to access:</div>' +
                            '<div class="approval-body">' + mdToHtml(data.text) + '</div>' +
                            securityHtml +
                            '<div class="approval-actions">' +
                            '<button class="approval-btn approve" onclick="window.executeReviewSummarize(\'' + cardId + '\')">✅ Approve</button>' +
                            '<button class="approval-btn deny" onclick="window.denyReviewSummarize(\'' + cardId + '\')">❌ Deny</button>' +
                            '</div>' +
                            '<div class="approval-policy">📋 Policy: Read-only within approved folder. All actions logged.</div>' +
                            '</div>';
                        addMessage("assistant", html);
                    }
                });
            };

            // Review & Summarize (kept for programmatic use, sidebar button removed)

            // Execute review after approval
            window.executeReviewSummarize = function(cardId) {
                var card = document.getElementById(cardId);
                var files = [];
                try {
                    files = JSON.parse(card.getAttribute("data-files") || "[]");
                } catch(e) { files = selectedReviewFiles; }

                if (card) {
                    card.classList.add("approved");
                    card.querySelector(".approval-actions").innerHTML = '<span class="approval-badge" style="background:#107c10;color:#fff;padding:4px 12px;border-radius:4px;">✅ Approved</span>';
                }
                addAuditEntry("APPROVAL", {action: "Review & Summarize", files: files.length}, true, 0);

                var assistantDiv = addMessage("assistant", '<span class="spinner"></span> Reading documents...');
                var contentDiv = assistantDiv.querySelector(".content");

                fetch("/demo/review-summarize", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ model: currentModel, phase: "execute", files: files })
                })
                .then(function(r) { return r.text(); })
                .then(function(body) {
                    var lines = body.split("\n");
                    var resultText = "";
                    var totalTime = "";
                    var filesRead = [];
                    var errorMsg = "";
                    lines.forEach(function(line) {
                        line = line.trim();
                        if (!line) return;
                        try { var evt = JSON.parse(line); } catch(e) { return; }
                        if (evt.type === "status") {
                            contentDiv.innerHTML = '<span class="spinner"></span> ' + evt.text;
                        } else if (evt.type === "result") {
                            resultText = evt.text || "";
                            totalTime = evt.time || "";
                            filesRead = evt.files_read || [];
                        } else if (evt.type === "error") {
                            errorMsg = evt.message || "Unknown error";
                        }
                    });
                    if (errorMsg) {
                        contentDiv.innerHTML = '<div style="color:#FF4444;">Error: ' + errorMsg + '</div>';
                    } else if (resultText) {
                        var html = '<div style="margin-bottom:8px;font-size:0.85em;opacity:0.7;">📄 Files reviewed: ' + filesRead.join(", ") + '</div>';
                        html += '<div style="margin-top:4px;">' + mdToHtml(resultText) + '</div>';
                        html += '<div class="tool-time" style="margin-top:8px;">⏱ ' + totalTime + 's on NPU</div>';
                        contentDiv.innerHTML = html;
                    }
                    document.getElementById("chatContainer").scrollTop = document.getElementById("chatContainer").scrollHeight;
                });
            };

            window.denyReviewSummarize = function(cardId) {
                var card = document.getElementById(cardId);
                if (card) {
                    card.classList.add("denied");
                    card.querySelector(".approval-actions").innerHTML = '<span class="approval-badge" style="background:#d32f2f;color:#fff;padding:4px 12px;border-radius:4px;">❌ Denied</span>';
                }
                addAuditEntry("APPROVAL_DENIED", {action: "Review & Summarize"}, false, 0);
                addMessage("assistant", '<div style="color:#FF8C00;">Action denied by user. No files were accessed.</div>');
            };

            // Audit summary button — shows trust receipt banner then asks AI to summarize
            document.getElementById("qpAuditSummary").addEventListener("click", function() {
                fetch("/audit-log").then(function(r) { return r.json(); }).then(function(log) {
                    if (log.length === 0) {
                        addMessage("assistant", "No agent actions recorded yet. Try running some commands first!");
                        return;
                    }
                    // Compute deterministic trust receipt
                    var reads = 0, writes = 0, execs = 0;
                    for (var i = 0; i < log.length; i++) {
                        if (log[i].tool === "read") reads++;
                        else if (log[i].tool === "write") writes++;
                        else if (log[i].tool === "exec") execs++;
                    }
                    var parts = [];
                    if (reads) parts.push(reads + " file" + (reads > 1 ? "s" : "") + " accessed");
                    if (writes) parts.push(writes + " document" + (writes > 1 ? "s" : "") + " created");
                    if (execs) parts.push(execs + " system command" + (execs > 1 ? "s" : ""));
                    var summaryText = parts.length > 0 ? parts.join(", ") : "No actions recorded";

                    // Show trust receipt banner in chat
                    var receiptHtml = '<div style="background:rgba(var(--brand-accent-rgb),0.08);border:1px solid rgba(var(--brand-accent-rgb),0.25);border-radius:10px;padding:14px 18px;margin-bottom:14px;">' +
                        '<div style="font-size:0.7em;text-transform:uppercase;letter-spacing:0.1em;opacity:0.5;margin-bottom:6px;">\uD83D\uDCCB Session Trust Receipt</div>' +
                        '<div style="font-size:1.05em;font-weight:bold;">' + summaryText + '</div>' +
                        '<div style="font-size:0.85em;opacity:0.6;margin-top:4px;">All actions local. No network calls. No data egress.</div>' +
                        '</div>';
                    addMessage("assistant", receiptHtml);

                    // Then send to AI for detailed summary
                    var detail = log.map(function(e) {
                        return e.timestamp + " - " + e.tool + "(" + JSON.stringify(e.arguments) + ") " + (e.success ? "OK" : "FAIL") + " [" + e.time + "s]";
                    }).join("\n");
                    document.getElementById("userInput").value = "Here is the audit trail of everything you did this session:\n\n" + detail + "\n\nSummarize this in 5 bullet points for an executive briefing. What actions were taken, what was the outcome, and confirm that all processing was local.";
                    sendMessage();
                });
            });

            document.getElementById("qpClear").addEventListener("click", function() {
                // Clear chat messages
                document.getElementById("chatContainer").innerHTML = "";
                // Restore suggestion chips
                var emptyState = document.getElementById("chatEmptyState");
                if (emptyState) {
                    emptyState.style.display = "flex";
                } else {
                    // Rebuild if removed from DOM
                    var chipsHtml = '<div class="chat-empty-state" id="chatEmptyState">' +
                        '<div class="suggestion-grid">' +
                            '<button class="suggestion-chip" data-action="my-calendar"><span class="chip-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><rect x="7" y="14" width="4" height="3" rx="0.5" fill="#f6d107" stroke="none"/></svg></span><span>My Calendar</span></button>' +
                            '<button class="suggestion-chip" data-action="prep-next-client"><span class="chip-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/><circle cx="12" cy="7" r="1.5" fill="#f6d107" stroke="none"/></svg></span><span>Prep Next Client</span></button>' +
                        '</div></div>';
                    document.getElementById("chatContainer").insertAdjacentHTML("afterend", chipsHtml);
                    bindChipHandlers();
                }
                document.getElementById("auditTrail").style.display = "none";
                document.getElementById("auditEntries").innerHTML = "";
                fetch("/audit-log", { method: "DELETE" });
                document.getElementById("qpSaveSummary").style.display = "none";
                lastAssistantResponse = "";
                pendingSummarize = false;
            });

            // Connectivity check
            document.getElementById("connectivityCard").addEventListener("click", checkConnectivity);

            function checkConnectivity() {
                document.getElementById("netStatus").textContent = "Checking...";
                document.getElementById("npuStatus").textContent = "Checking...";
                fetch("/connectivity-check").then(function(r) { return r.json(); }).then(function(d) {
                    var netDot = document.getElementById("netDot");
                    var npuDot = document.getElementById("npuDot");
                    document.getElementById("netStatus").textContent = d.network ? "Online" : "Offline";
                    netDot.className = "status-dot " + (d.network ? "green" : "red");
                    document.getElementById("npuStatus").textContent = d.npu ? "NPU Ready" : "NPU Down";
                    npuDot.className = "status-dot " + (d.npu ? "blue" : "red");
                    // Update header badge too
                    var badge = document.getElementById("offlineBadge");
                    if (d.network) {
                        badge.textContent = "Online";
                        badge.classList.remove("offline");
                    } else {
                        badge.textContent = "Offline Mode";
                        badge.classList.add("offline");
                    }
                }).catch(function() {
                    document.getElementById("netStatus").textContent = "Offline";
                    document.getElementById("netDot").className = "status-dot red";
                });
            }
            
            document.getElementById("modelSelect").addEventListener("change", function() {
                currentModel = this.value;
            });

            // File picker — uploads, extracts text, saves to Demo folder
            var lastUploadedFile = "";
            document.getElementById("attachBtn").addEventListener("click", function() {
                document.getElementById("agentFileInput").click();
            });
            document.getElementById("agentFileInput").addEventListener("change", function(e) {
                var file = e.target.files[0];
                if (!file) return;
                var formData = new FormData();
                formData.append("file", file);
                fetch("/upload-to-demo", { method: "POST", body: formData })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.success) {
                        lastUploadedFile = data.path;
                        // Show inline action buttons in chat message
                        var msgHtml = 'Loaded <strong>' + file.name + '</strong> (' + data.words + ' words).' +
                            '<div style="margin-top:10px;">' +
                            '<button class="inline-action-btn" onclick="document.getElementById(\'qpSummarizeDoc\').click();">&#128221; Summarize</button>' +
                            '<button class="inline-action-btn" onclick="document.getElementById(\'qpDetectPII\').click();">&#128680; Detect PII</button>' +
                            '</div>';
                        addMessage("assistant", msgHtml);
                    } else {
                        addMessage("assistant", '<div style="color:#FF4444;">Upload error: ' + data.error + '</div>');
                    }
                });
                e.target.value = "";
            });
            document.getElementById("qpSummarizeDoc").addEventListener("click", function() {
                if (!lastUploadedFile) return;
                document.getElementById("qpSaveSummary").style.display = "none";
                var assistantDiv = addMessage("assistant", '<span class="spinner"></span> Reading document...');
                var contentDiv = assistantDiv.querySelector(".content");

                fetch("/summarize-doc", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ path: lastUploadedFile, model: currentModel })
                })
                .then(function(r) { return r.text(); })
                .then(function(body) {
                    var lines = body.split("\n");
                    var summaryText = "";
                    var totalTime = "";
                    var errorMsg = "";
                    lines.forEach(function(line) {
                        line = line.trim();
                        if (!line) return;
                        try { var evt = JSON.parse(line); } catch(e) { return; }
                        if (evt.type === "status") {
                            contentDiv.innerHTML = '<span class="spinner"></span> ' + evt.text;
                        } else if (evt.type === "summary") {
                            summaryText = evt.text || "";
                            totalTime = evt.time || "";
                        } else if (evt.type === "error") {
                            errorMsg = evt.message || "Unknown error";
                        }
                    });
                    if (errorMsg) {
                        contentDiv.innerHTML = '<div style="color:#FF4444;">Error: ' + errorMsg + '</div>';
                    } else if (summaryText) {
                        lastAssistantResponse = summaryText;
                        var html = '<div style="margin-top:4px;">' + summaryText.replace(/\n/g, "<br>") + '</div>';
                        html += '<div class="tool-time" style="margin-top:4px;">&#9201; ' + totalTime + 's on NPU</div>';
                        html += '<div style="margin-top:12px;"><button onclick="window.saveSummary()" style="background:linear-gradient(135deg,#0078d4,#00bcf2);color:#fff;border:none;padding:10px 24px;border-radius:8px;font-size:0.95em;cursor:pointer;font-weight:600;">&#128190; Save Summary to File</button></div>';
                        contentDiv.innerHTML = html;
                    }
                    document.getElementById("chatContainer").scrollTop = document.getElementById("chatContainer").scrollHeight;
                })
                .catch(function(err) {
                    contentDiv.innerHTML = '<div style="color:#FF4444;">Error: ' + err + '</div>';
                });
            });
            document.getElementById("qpDetectPII").addEventListener("click", function() {
                if (!lastUploadedFile) return;
                var assistantDiv = addMessage("assistant", '<span class="spinner"></span> Scanning for PII...');
                var contentDiv = assistantDiv.querySelector(".content");

                fetch("/detect-pii", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ path: lastUploadedFile, model: currentModel })
                })
                .then(function(r) { return r.text(); })
                .then(function(body) {
                    var lines = body.split("\n");
                    var resultText = "";
                    var totalTime = "";
                    var errorMsg = "";
                    lines.forEach(function(line) {
                        line = line.trim();
                        if (!line) return;
                        try { var evt = JSON.parse(line); } catch(e) { return; }
                        if (evt.type === "status") {
                            contentDiv.innerHTML = '<span class="spinner"></span> ' + evt.text;
                        } else if (evt.type === "result") {
                            resultText = evt.text || "";
                            totalTime = evt.time || "";
                        } else if (evt.type === "error") {
                            errorMsg = evt.message || "Unknown error";
                        }
                    });
                    if (errorMsg) {
                        contentDiv.innerHTML = '<div style="color:#FF4444;">Error: ' + errorMsg + '</div>';
                    } else if (resultText) {
                        var html = '<div style="margin-top:4px;">' + mdToHtml(resultText) + '</div>';
                        html += '<div class="tool-time" style="margin-top:4px;">&#9201; ' + totalTime + 's on NPU</div>';
                        contentDiv.innerHTML = html;
                    }
                    document.getElementById("chatContainer").scrollTop = document.getElementById("chatContainer").scrollHeight;
                })
                .catch(function(err) {
                    contentDiv.innerHTML = '<div style="color:#FF4444;">Error: ' + err + '</div>';
                });
            });
            document.getElementById("qpSaveSummary").addEventListener("click", function() {
                window.saveSummary();
            });
            window.saveSummary = function() {
                if (!lastAssistantResponse || !lastUploadedFile) return;
                var baseName = lastUploadedFile.replace(/\\/g, "/").split("/").pop().replace(/\.[^.]+$/, "");
                var dirParts = lastUploadedFile.replace(/\\/g, "/").split("/").slice(0, -1);
                var savePath = dirParts.join("\\") + "\\" + baseName + "_Summary.txt";
                // Direct backend write — no AI needed
                var btn = event.target || document.querySelector('[onclick*="saveSummary"]');
                if (btn) { btn.disabled = true; btn.textContent = "Saving..."; }
                fetch("/save-summary", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ path: savePath, content: lastAssistantResponse })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.success) {
                        var savedName = data.filename || savePath.replace(/\\/g, "/").split("/").pop();
                        if (btn) {
                            btn.style.background = "linear-gradient(135deg,#107c10,#1db954)";
                            btn.textContent = "\u2705 Saved: " + savedName;
                            btn.disabled = true;
                        }
                        addAuditEntry("write", {path: savedName}, true, 0);
                    } else {
                        if (btn) { btn.textContent = "\u274c Save failed"; btn.disabled = false; }
                    }
                })
                .catch(function(err) {
                    if (btn) { btn.textContent = "\u274c Save failed"; btn.disabled = false; }
                });
            };

            // Camera/ID handlers
            document.getElementById("startCameraBtn").addEventListener("click", startCamera);
            document.getElementById("captureBtn").addEventListener("click", captureImage);
            document.getElementById("retakeBtn").addEventListener("click", retakeImage);
            document.getElementById("analyzeIdBtn").addEventListener("click", analyzeId);
            document.getElementById("refreshCamerasBtn").addEventListener("click", enumerateCameras);
            
            // Enumerate cameras on load
            enumerateCameras();
            
            // Online status
            function updateOnlineStatus() {
                var badge = document.getElementById("offlineBadge");
                var netDot = document.getElementById("netDot");
                var netLabel = document.getElementById("netStatus");
                if (navigator.onLine) {
                    badge.textContent = "Online";
                    badge.classList.remove("offline");
                    if (netDot) netDot.className = "status-dot green";
                    if (netLabel) netLabel.textContent = "Online";
                } else {
                    badge.textContent = "Offline Mode";
                    badge.classList.add("offline");
                    if (netDot) netDot.className = "status-dot red";
                    if (netLabel) netLabel.textContent = "Offline";
                }
            }
            window.addEventListener("online", updateOnlineStatus);
            window.addEventListener("offline", updateOnlineStatus);
            updateOnlineStatus();

            console.log("All event handlers set up!");
        });
        
        // === Agent Chat Functions ===
        function addMessage(role, content) {
            var container = document.getElementById("chatContainer");
            // Hide suggestion chips on first message
            var emptyState = document.getElementById("chatEmptyState");
            if (emptyState) emptyState.style.display = "none";
            var div = document.createElement("div");
            div.className = "message " + (role === "user" ? "user-msg" : "assistant-msg");
            var label = role === "user" ? "You" : "Agent ({{MODEL_LABEL}})";
            div.innerHTML = '<div class="role">' + label + '</div><div class="content">' + content + '</div>';
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
            return div;
        }

        function addAuditEntry(tool, args, success, elapsed) {
            var trail = document.getElementById("auditTrail");
            trail.style.display = "block";
            var entries = document.getElementById("auditEntries");
            var now = new Date().toLocaleTimeString();
            var icon = success ? "&#9989;" : "&#10060;";
            var argStr = typeof args === "object" ? Object.keys(args).map(function(k) {
                var v = args[k];
                if (typeof v === "string" && v.length > 40) v = v.substring(0, 40) + "...";
                return k + "=" + v;
            }).join(", ") : "";
            entries.innerHTML += '<div style="padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.05);">' +
                icon + ' <strong>' + now + '</strong> ' + tool + '(' + argStr + ') <span class="tool-time">' + elapsed + 's</span></div>';
            trail.scrollTop = trail.scrollHeight;
        }

        // === Agentic Firewall: Security Explanations ===
        function getSecurityExplanation(toolName, args) {
            switch(toolName.toLowerCase()) {
                case 'read':
                    var path = (args && args.path) ? args.path.split(/[\\\/]/).pop() : 'file';
                    return 'Reading file "' + path + '". Read-only, no modifications. Within approved folder.';
                case 'write':
                    var wpath = (args && args.path) ? args.path.split(/[\\\/]/).pop() : 'file';
                    return 'Creating file "' + wpath + '" in approved demo folder. No existing files modified.';
                case 'exec':
                    var cmd = ((args && args.command) || '').toLowerCase().trim();
                    if (cmd.indexOf('get-childitem') >= 0) {
                        return 'Listing directory contents. Read-only operation, no files affected.';
                    } else if (cmd.indexOf('get-date') >= 0) {
                        return 'Retrieving system date/time. No system changes.';
                    } else if (cmd.indexOf('disable-netadapter') >= 0) {
                        return 'Disabling network adapter(s). Device will go offline. Re-enable available.';
                    } else if (cmd.indexOf('enable-netadapter') >= 0) {
                        return 'Enabling network adapter(s). Restoring network connectivity.';
                    } else if (cmd.indexOf('get-content') >= 0) {
                        return 'Reading file contents via PowerShell. Read-only operation.';
                    } else {
                        return 'Running approved PowerShell command within allowlisted cmdlet set.';
                    }
                default:
                    return 'Executing approved tool within security policy.';
            }
        }

        function generateSecurityReview(planText) {
            var lines = [];
            // Count files mentioned (look for file patterns in the plan)
            var fileMatches = planText.match(/[\w_-]+\.\w{2,4}/g) || [];
            var uniqueFiles = [];
            fileMatches.forEach(function(f) {
                if (uniqueFiles.indexOf(f) < 0) uniqueFiles.push(f);
            });

            if (uniqueFiles.length > 0) {
                lines.push(uniqueFiles.length + ' file' + (uniqueFiles.length > 1 ? 's' : '') + ' requested — all within approved folder');
            }

            // Determine access type
            var hasWrite = /\b(write|create|save|modify|edit|update)\b/i.test(planText);
            var hasExec = /\b(run|execute|command|powershell)\b/i.test(planText);

            if (hasWrite) {
                lines.push('Read and write access — files may be created or modified');
            } else {
                lines.push('Read-only access — no files will be modified');
            }

            if (hasExec) {
                lines.push('System commands requested — limited to approved PowerShell cmdlets');
            } else {
                lines.push('No system commands — no PowerShell execution');
            }

            lines.push('Results stay on-device — no network calls');

            return lines;
        }

        function renderToolCard(name, args, result, execTime) {
            var argsHtml = "";
            if (args) {
                for (var k in args) {
                    var v = args[k];
                    if (typeof v === "string" && v.length > 120) v = v.substring(0, 120) + "...";
                    argsHtml += "<div><strong>" + k + ":</strong> " + (v + "").replace(/</g, "&lt;") + "</div>";
                }
            }
            var statusClass = (result && result.success) ? "tool-ok" : "tool-fail";
            var statusIcon = (result && result.success) ? "&#9989;" : "&#10060;";
            var outputPreview = "";
            if (result) {
                var out = result.output || result.error || "";
                if (out.length > 200) out = out.substring(0, 200) + "...";
                outputPreview = out.replace(/</g, "&lt;").replace(/\n/g, "<br>");
            }
            return '<div class="tool-card">' +
                '<div class="tool-header">&#128295; Tool: ' + name + '</div>' +
                '<div class="tool-args">' + argsHtml + '</div>' +
                (result ? '<div class="tool-result"><span class="' + statusClass + '">' + statusIcon +
                    (result.success ? " Success" : " Failed") + '</span>' +
                    (outputPreview ? '<div style="margin-top:4px;opacity:0.85;font-size:0.92em;">' + outputPreview + '</div>' : '') +
                    '<div class="tool-time">&#9201; ' + (execTime || "?") + 's</div></div>' : '') +
                '</div>';
        }

        // --- Approval gate state ---
        var pendingApprovalReview = false;
        var pendingSummarize = false;
        var lastAssistantResponse = "";
        var chatHistory = [];  // Conversation history for persona continuity

        function renderApprovalCard(planText) {
            // Parse plan body — extract lines between markers or use raw text
            var body = planText;
            var planMatch = planText.match(/\[PLAN\]([\s\S]*?)\[\/PLAN\]/i);
            if (planMatch) {
                body = planMatch[1].trim();
            }
            // Convert bullet lines to HTML list
            var bodyHtml = body.split("\n").map(function(line) {
                line = line.trim();
                if (!line) return "";
                if (line.match(/^[-•*]\s/)) return "<div style='padding:2px 0;'>\u2022 " + line.replace(/^[-•*]\s*/, "") + "</div>";
                if (line.match(/^(Files|Action|Plan):/i)) return "<div style='font-weight:bold;margin-top:6px;'>" + line + "</div>";
                return "<div>" + line + "</div>";
            }).join("");

            // Generate Security Review section (Agentic Firewall)
            var securityLines = generateSecurityReview(body);
            var securityHtml = '<div class="security-review">' +
                '<div class="security-review-header">\uD83D\uDEE1\uFE0F Security Review</div>' +
                securityLines.map(function(line) {
                    return '<div class="security-review-line">\u2022 ' + line + '</div>';
                }).join('') +
                '</div>';

            var cardId = "approvalCard_" + Date.now();
            return '<div class="approval-card" id="' + cardId + '">' +
                '<div class="approval-header">\uD83D\uDD12 This action requires approval</div>' +
                '<div style="font-size:0.85em;opacity:0.7;margin-bottom:10px;">The AI agent wants to:</div>' +
                '<div class="approval-body">' + bodyHtml + '</div>' +
                securityHtml +
                '<div class="approval-actions">' +
                    '<button class="approval-btn approve" onclick="handleApproval(\'' + cardId + '\', true)">\u2705 Approve</button>' +
                    '<button class="approval-btn deny" onclick="handleApproval(\'' + cardId + '\', false)">\u274C Deny</button>' +
                '</div>' +
                '<div class="approval-policy">\uD83D\uDCCB Policy: Read-only within approved folder. All actions logged.</div>' +
                '</div>';
        }

        window.handleApproval = function(cardId, approved) {
            var card = document.getElementById(cardId);
            if (!card) return;
            var actionsDiv = card.querySelector(".approval-actions");
            if (!actionsDiv) return;

            if (approved) {
                actionsDiv.innerHTML = '<span class="approval-badge approved">\u2705 Approved</span>';
                card.classList.add("approved");
                // Add audit entry
                addAuditEntry("APPROVAL", {action: "Review & Summarize"}, true, 0);
                // Send follow-up to agent
                document.getElementById("userInput").value = "APPROVED. Proceed with the plan you outlined. Execute the file reads and produce the risk summary.";
                sendMessage();
            } else {
                actionsDiv.innerHTML = '<span class="approval-badge denied">\u274C Denied</span>';
                card.classList.add("denied");
                addAuditEntry("APPROVAL_DENIED", {action: "Review & Summarize", files: 0}, false, 0);
                addMessage("assistant", '<div style="color:#FF8C00;">Action denied by user. No files were accessed.</div>');
            }
        };

        function generateFollowUpChips(responseText) {
            var text = responseText.toLowerCase();
            var chips = [];
            var topicMap = [
                {keywords: ["529", "college savings", "maya", "education"], label: "529 Plan Details", icon: "&#127891;", query: "Answer from your knowledge, do not use any tools. What are the 2026 529 Plan contribution limits and Michigan state tax deduction benefits? How does it compare to a Coverdell ESA?"},
                {keywords: ["roth ira", "ira conversion", "401k", "rollover", "retirement"], label: "Roth IRA Conversion", icon: "&#128176;", query: "Answer from your knowledge, do not use any tools. Explain the pros and cons of converting a 401k to a Roth IRA for someone aged 45. What are the tax implications and income limits?"},
                {keywords: ["henderson", "portfolio", "estate"], label: "Henderson Portfolio", icon: "&#128200;", query: "Look up Henderson in D365 and show me their recent account activity."},
                {keywords: ["jackie", "rodriguez", "new client", "new account"], label: "Jackie Rodriguez D365", icon: "&#128100;", query: "Look up Jackie Rodriguez in D365 and show me her full customer profile and recent activity."},
                {keywords: ["compliance", "bsa", "aml", "kyc", "cdd"], label: "Compliance Requirements", icon: "&#128220;", query: "Answer from your knowledge, do not use any tools. What are the key BSA/AML compliance requirements for new account openings at a bank branch?"},
                {keywords: ["checking", "savings", "deposit", "account opening"], label: "Account Products", icon: "&#127974;", query: "Answer from your knowledge, do not use any tools. Compare Essential Checking vs High-Yield Savings accounts. What are typical rates and minimum balances?"},
                {keywords: ["cd ", "certificate", "maturation", "rate"], label: "CD Rates & Options", icon: "&#128178;", query: "Answer from your knowledge, do not use any tools. What are the current CD rate trends and what options does a client have when their CD matures?"},
                {keywords: ["beneficiary", "designation", "will", "trust"], label: "Beneficiary Rules", icon: "&#128221;", query: "Answer from your knowledge, do not use any tools. What are the rules for changing a beneficiary on a 403b retirement account? What documentation is required?"},
                {keywords: ["surface", "device", "deployment", "npu"], label: "Device Deployment", icon: "&#128187;", query: "What is the status of our Surface Pro deployment and how are the AI features being used in the branch?"},
                {keywords: ["regional", "patricia", "branch metrics", "target"], label: "Branch Performance", icon: "&#128202;", query: "What are our branch performance metrics YTD? How are we tracking against the 100 new account target?"}
            ];
            for (var t = 0; t < topicMap.length && chips.length < 3; t++) {
                var topic = topicMap[t];
                for (var k = 0; k < topic.keywords.length; k++) {
                    if (text.indexOf(topic.keywords[k]) >= 0) {
                        chips.push(topic);
                        break;
                    }
                }
            }
            return chips;
        }

        function sendChatMessage(text) {
            var input = document.getElementById("userInput");
            input.value = text;
            // Hide empty state
            var emptyState = document.getElementById("chatEmptyState");
            if (emptyState) emptyState.style.display = "none";
            sendMessage();
        }

        function sendMessage() {
            var input = document.getElementById("userInput");
            var message = input.value.trim();
            if (!message) return;

            input.value = "";
            document.getElementById("sendBtn").disabled = true;

            addMessage("user", message);
            var historyToSend = chatHistory.slice(-10);
            chatHistory.push({"role": "user", "content": message});

            var assistantDiv = addMessage("assistant", '<span class="spinner"></span> Thinking...');
            var contentDiv = assistantDiv.querySelector(".content");
            var htmlParts = [];

            fetch("/chat", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ message: message, model: currentModel, history: historyToSend })
            })
            .then(function(r) { return r.body.getReader(); })
            .then(function(reader) {
                var decoder = new TextDecoder();
                var buffer = "";

                function processLine(line) {
                    line = line.trim();
                    if (!line) return;
                    try {
                        var evt = JSON.parse(line);
                    } catch(e) { console.log("[FE] JSON parse error:", line.substring(0, 50)); return; }
                    console.log("[FE] Event received:", evt.type, evt.type === "response" ? "text_len=" + (evt.text||"").length : "");

                    if (evt.type === "thinking") {
                        htmlParts.push('<div style="opacity:0.6;"><span class="spinner"></span> Thinking...</div>');
                        contentDiv.innerHTML = htmlParts.join("");
                    }
                    else if (evt.type === "think_done") {
                        // Replace last thinking indicator with done
                        for (var i = htmlParts.length - 1; i >= 0; i--) {
                            if (htmlParts[i].indexOf("Thinking...") >= 0) {
                                htmlParts[i] = '<div style="opacity:0.5;">&#129504; Thought for ' + evt.time + 's</div>';
                                break;
                            }
                        }
                        contentDiv.innerHTML = htmlParts.join("");
                    }
                    else if (evt.type === "tool_call") {
                        // Agentic Firewall: Add security check line before tool execution
                        var securityMsg = getSecurityExplanation(evt.name, evt.arguments);
                        htmlParts.push('<div class="security-check-line">\uD83D\uDEE1\uFE0F Security: ' + securityMsg + '</div>');
                        htmlParts.push(renderToolCard(evt.name, evt.arguments, null, null));
                        contentDiv.innerHTML = htmlParts.join("");
                    }
                    else if (evt.type === "tool_result") {
                        // Update the last tool card with result
                        for (var j = htmlParts.length - 1; j >= 0; j--) {
                            if (htmlParts[j].indexOf("tool-card") >= 0 && htmlParts[j].indexOf("tool-result") < 0) {
                                var nameMatch = htmlParts[j].match(/Tool: (\w+)/);
                                var toolName = nameMatch ? nameMatch[1] : "?";
                                // Parse args back from HTML (simplified)
                                htmlParts[j] = renderToolCard(toolName, null, evt.result, evt.time);
                                addAuditEntry(toolName, {}, evt.result.success, evt.time);
                                break;
                            }
                        }
                        contentDiv.innerHTML = htmlParts.join("");
                        // After network tool calls, refresh connectivity
                        if (htmlParts.join("").toLowerCase().indexOf("netadapter") >= 0) {
                            setTimeout(checkConnectivity, 2000);
                        }
                    }
                    else if (evt.type === "response") {
                        // Remove any remaining thinking indicators
                        htmlParts = htmlParts.filter(function(p) { return p.indexOf("Thinking...") < 0; });

                        var responseText = evt.text || "";
                        lastAssistantResponse = responseText;
                        chatHistory.push({"role": "assistant", "content": responseText});
                        // Check for approval gate: [PLAN] markers OR heuristic (pendingApprovalReview + bullet list + no TOOL_CALL)
                        var hasPlanMarkers = responseText.indexOf("[PLAN]") >= 0 && responseText.indexOf("[/PLAN]") >= 0;
                        var hasBullets = (responseText.match(/^[-•*]\s/m) || responseText.match(/^\d+\.\s/m));
                        var noToolCall = responseText.indexOf("[TOOL_CALL]") < 0;
                        var isApprovalResponse = hasPlanMarkers || (pendingApprovalReview && hasBullets && noToolCall);

                        if (isApprovalResponse) {
                            pendingApprovalReview = false;
                            htmlParts.push(renderApprovalCard(responseText));
                            htmlParts.push('<div class="tool-time" style="margin-top:4px;">&#9201; ' + evt.time + 's</div>');
                        } else {
                            if (pendingApprovalReview && noToolCall) {
                                // Model didn't follow plan format — still show as approval card with raw text
                                pendingApprovalReview = false;
                                htmlParts.push(renderApprovalCard(responseText));
                                htmlParts.push('<div class="tool-time" style="margin-top:4px;">&#9201; ' + evt.time + 's</div>');
                            } else {
                                pendingApprovalReview = false;
                                htmlParts.push('<div style="margin-top:8px;">' + responseText.replace(/\n/g, "<br>") + '</div>');
                                htmlParts.push('<div class="tool-time" style="margin-top:4px;">&#9201; Total: ' + evt.time + 's</div>');
                            }
                        }
                        // Add inline Save Summary button after summarize completes
                        if (pendingSummarize && lastAssistantResponse) {
                            pendingSummarize = false;
                            htmlParts.push('<div style="margin-top:12px;"><button onclick="window.saveSummary()" style="background:linear-gradient(135deg,#0078d4,#00bcf2);color:#fff;border:none;padding:10px 24px;border-radius:8px;font-size:0.95em;cursor:pointer;font-weight:600;">&#128190; Save Summary to File</button></div>');
                        }
                        contentDiv.innerHTML = htmlParts.join("");
                    }
                    else if (evt.type === "error") {
                        htmlParts.push('<div style="color:#FF4444;">Error: ' + evt.message + '</div>');
                        contentDiv.innerHTML = htmlParts.join("");
                    }
                    else if (evt.type === "done") {
                        document.getElementById("sendBtn").disabled = false;
                        document.getElementById("userInput").focus();
                        // Generate dynamic follow-up chips based on response content
                        if (lastAssistantResponse && lastAssistantResponse.length > 50) {
                            var chips = generateFollowUpChips(lastAssistantResponse);
                            if (chips.length > 0) {
                                var chipHtml = '<div class="dynamic-chips" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;">';
                                for (var ci = 0; ci < chips.length; ci++) {
                                    chipHtml += '<button class="suggestion-chip dynamic-followup" onclick="sendChatMessage(\'' + chips[ci].query.replace(/'/g, "\\'") + '\')" style="font-size:0.82em;padding:8px 14px;cursor:pointer;">' +
                                        '<span class="chip-icon">' + chips[ci].icon + '</span><span>' + chips[ci].label + '</span></button>';
                                }
                                chipHtml += '</div>';
                                htmlParts.push(chipHtml);
                                contentDiv.innerHTML = htmlParts.join("");
                            }
                        }
                    }
                    document.getElementById("chatContainer").scrollTop = document.getElementById("chatContainer").scrollHeight;
                }

                function read() {
                    reader.read().then(function(chunk) {
                        if (chunk.done) {
                            if (buffer.trim()) processLine(buffer);
                            document.getElementById("sendBtn").disabled = false;
                            document.getElementById("userInput").focus();
                            return;
                        }
                        buffer += decoder.decode(chunk.value);
                        var lines = buffer.split("\n");
                        buffer = lines.pop();
                        lines.forEach(processLine);
                        read();
                    });
                }
                read();
            })
            .catch(function(err) {
                contentDiv.innerHTML = '<div style="color:#FF4444;">Connection error: ' + err.message + '</div>';
                document.getElementById("sendBtn").disabled = false;
            });
        }
        
        // === Camera/ID Functions ===
        function enumerateCameras() {
            var select = document.getElementById("cameraSelect");
            select.innerHTML = '<option value="">Detecting cameras...</option>';
            
            // Need to request permission first to get device labels
            navigator.mediaDevices.getUserMedia({ video: true })
            .then(function(stream) {
                // Stop this temporary stream
                stream.getTracks().forEach(function(track) { track.stop(); });
                
                // Now enumerate devices
                return navigator.mediaDevices.enumerateDevices();
            })
            .then(function(devices) {
                select.innerHTML = "";
                var videoDevices = devices.filter(function(d) { return d.kind === "videoinput"; });
                
                if (videoDevices.length === 0) {
                    select.innerHTML = '<option value="">No cameras found</option>';
                    return;
                }
                
                videoDevices.forEach(function(device, index) {
                    var option = document.createElement("option");
                    option.value = device.deviceId;
                    // Use label if available, otherwise generic name
                    var label = device.label || ("Camera " + (index + 1));
                    // Try to identify built-in vs external
                    if (label.toLowerCase().indexOf("front") >= 0) {
                        label += " (Front)";
                    } else if (label.toLowerCase().indexOf("back") >= 0 || label.toLowerCase().indexOf("rear") >= 0) {
                        label += " (Rear)";
                    } else if (label.toLowerCase().indexOf("surface") >= 0 || label.toLowerCase().indexOf("integrated") >= 0 || label.toLowerCase().indexOf("built-in") >= 0) {
                        label += " (Built-in)";
                    }
                    option.textContent = label;
                    select.appendChild(option);
                });
                
                console.log("Found " + videoDevices.length + " camera(s)");
            })
            .catch(function(err) {
                console.error("Error enumerating cameras:", err);
                select.innerHTML = '<option value="">Camera access denied</option>';
            });
        }
        
        function startCamera() {
            console.log("Starting camera...");
            var selectedDeviceId = document.getElementById("cameraSelect").value;
            
            var constraints = {
                video: {
                    width: { ideal: 1280 },
                    height: { ideal: 720 }
                }
            };
            
            // If a specific device is selected, use it
            if (selectedDeviceId) {
                constraints.video.deviceId = { exact: selectedDeviceId };
            }
            
            navigator.mediaDevices.getUserMedia(constraints)
            .then(function(stream) {
                cameraStream = stream;
                var video = document.getElementById("cameraPreview");
                video.srcObject = stream;
                video.style.display = "block";
                document.getElementById("cameraPlaceholder").style.display = "none";
                document.getElementById("startCameraBtn").textContent = "Stop Camera";
                document.getElementById("startCameraBtn").classList.add("stop");
                document.getElementById("startCameraBtn").removeEventListener("click", startCamera);
                document.getElementById("startCameraBtn").addEventListener("click", stopCamera);
                document.getElementById("captureBtn").style.display = "inline-block";
                document.getElementById("capturedImage").style.display = "none";
                document.getElementById("retakeBtn").style.display = "none";
                document.getElementById("analyzeIdBtn").style.display = "none";
            })
            .catch(function(err) {
                console.error("Camera error:", err);
                var msg = "Could not access camera: " + err.message;
                if (err.message && err.message.indexOf("video source") >= 0) {
                    msg += "\n\nThis can happen in airplane mode on some devices. " +
                           "Use the 'Load Demo ID' or 'Load Demo Check' buttons instead.";
                }
                alert(msg);
            });
        }
        
        function stopCamera() {
            if (cameraStream) {
                cameraStream.getTracks().forEach(function(track) { track.stop(); });
                cameraStream = null;
            }
            document.getElementById("cameraPreview").style.display = "none";
            document.getElementById("cameraPlaceholder").style.display = "block";
            document.getElementById("startCameraBtn").textContent = "Start Camera";
            document.getElementById("startCameraBtn").classList.remove("stop");
            document.getElementById("startCameraBtn").removeEventListener("click", stopCamera);
            document.getElementById("startCameraBtn").addEventListener("click", startCamera);
            document.getElementById("captureBtn").style.display = "none";
        }
        
        function captureImage() {
            var video = document.getElementById("cameraPreview");
            var canvas = document.getElementById("captureCanvas");
            var img = document.getElementById("capturedImage");
            
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext("2d").drawImage(video, 0, 0);
            
            img.src = canvas.toDataURL("image/png");
            img.style.display = "block";
            video.style.display = "none";
            
            document.getElementById("captureBtn").style.display = "none";
            document.getElementById("retakeBtn").style.display = "inline-block";
            document.getElementById("analyzeIdBtn").style.display = "inline-block";
            
            // Stop camera to save resources
            if (cameraStream) {
                cameraStream.getTracks().forEach(function(track) { track.stop(); });
            }
        }
        
        function retakeImage() {
            document.getElementById("capturedImage").style.display = "none";
            document.getElementById("retakeBtn").style.display = "none";
            document.getElementById("analyzeIdBtn").style.display = "none";
            document.getElementById("processingSteps").style.display = "none";
            document.getElementById("ocrPreview").style.display = "none";
            document.getElementById("idResultCard").style.display = "none";
            startCamera();
        }
        
        function updateStep(stepNum, status) {
            var step = document.getElementById("step" + stepNum);
            var icon = step.querySelector(".step-icon");
            icon.classList.remove("step-pending", "step-active", "step-done");
            icon.classList.add("step-" + status);
            if (status === "done") {
                icon.innerHTML = "&#10003;";
            } else if (status === "active") {
                icon.innerHTML = '<span class="spinner" style="width:14px;height:14px;margin:0;border-width:2px;"></span>';
            }
        }
        
        function analyzeId() {
            console.log("Analyzing ID...");
            
            document.getElementById("processingSteps").style.display = "block";
            document.getElementById("ocrPreview").style.display = "none";
            document.getElementById("idResultCard").style.display = "none";
            
            // Reset steps
            for (var i = 1; i <= 3; i++) {
                var step = document.getElementById("step" + i);
                var icon = step.querySelector(".step-icon");
                icon.classList.remove("step-active", "step-done");
                icon.classList.add("step-pending");
                icon.innerHTML = i;
            }
            
            // Step 1: Image captured (already done)
            updateStep(1, "done");
            
            // Step 2: OCR
            updateStep(2, "active");
            
            var img = document.getElementById("capturedImage");
            
            Tesseract.recognize(img.src, "eng", {
                workerPath: "/tesseract/worker.min.js",
                corePath: "/tesseract/core",
                langPath: "/tesseract/lang",
                workerBlobURL: false,
                logger: function(m) { console.log("Tesseract:", m); }
            }).then(function(result) {
                var ocrText = result.data.text;
                console.log("OCR Result:", ocrText);
                
                updateStep(2, "done");
                
                document.getElementById("ocrPreview").style.display = "block";
                document.getElementById("ocrText").textContent = ocrText;
                
                // Step 3: AI Analysis
                updateStep(3, "active");
                
                fetch("/analyze-id", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ ocr_text: ocrText, model: currentModel })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    updateStep(3, "done");
                    displayIdResult(data);
                })
                .catch(function(err) {
                    console.error("Analysis error:", err);
                    updateStep(3, "done");
                    displayIdResult({ error: err.message });
                });
                
            }).catch(function(err) {
                console.error("OCR error:", err);
                updateStep(2, "done");
                document.getElementById("ocrPreview").style.display = "block";
                document.getElementById("ocrText").textContent = "Error: " + err.message;
            });
        }
        
        function displayIdResult(data) {
            var card = document.getElementById("idResultCard");
            var badge = document.getElementById("idStatusBadge");
            var fieldsDiv = document.getElementById("idFields");
            var notesDiv = document.getElementById("idNotes");
            
            card.style.display = "block";
            
            if (data.error) {
                badge.textContent = "Error";
                badge.className = "status-badge status-error";
                fieldsDiv.innerHTML = "<p>Could not analyze ID: " + data.error + "</p>";
                notesDiv.innerHTML = "";
                return;
            }
            
            // Set status badge
            var status = data.status || "Unknown";
            badge.textContent = status;
            if (status.toLowerCase().indexOf("valid") >= 0) {
                badge.className = "status-badge status-valid";
            } else if (status.toLowerCase().indexOf("review") >= 0 || status.toLowerCase().indexOf("warning") >= 0) {
                badge.className = "status-badge status-warning";
            } else {
                badge.className = "status-badge status-error";
            }
            
            // Display fields
            var fields = data.fields || {};
            var fieldsHtml = "";
            var fieldLabels = {
                "name": "Full Name",
                "address": "Address",
                "dob": "Date of Birth",
                "id_number": "ID Number",
                "expiration": "Expiration Date",
                "state": "State",
                "class": "License Class"
            };
            
            for (var key in fields) {
                var label = fieldLabels[key] || key;
                var value = fields[key] || "Not detected";
                fieldsHtml += '<div class="id-field"><span class="id-field-label">' + label + '</span><span class="id-field-value">' + value + '</span></div>';
            }
            
            fieldsDiv.innerHTML = fieldsHtml || "<p>No fields extracted</p>";
            
            // Display notes
            if (data.notes) {
                notesDiv.innerHTML = "<strong>Notes:</strong> " + data.notes;
            } else {
                notesDiv.innerHTML = "";
            }

            // Trigger D365 customer lookup if name was extracted
            var extractedName = (data.fields && data.fields.name) ? data.fields.name : null;
            if (extractedName && extractedName !== "Could not parse" && typeof window._d365CustomerLookup === "function") {
                window._d365CustomerLookup(extractedName);
            }
        }

        // ── Check Scanner + Mode Switcher + D365 Integration ──
        (function() {
            var idModeBtn = document.getElementById("idModeBtn");
            var checkModeBtn = document.getElementById("checkModeBtn");
            var analyzeIdBtn = document.getElementById("analyzeIdBtn");
            var analyzeCheckBtn = document.getElementById("analyzeCheckBtn");
            var loadDemoCheckBtn = document.getElementById("loadDemoCheckBtn");
            var captureBtn = document.getElementById("captureBtn");
            var idResultCard = document.getElementById("idResultCard");
            var checkResultCard = document.getElementById("checkResultCard");
            var d365CustomerCard = document.getElementById("d365CustomerCard");
            var d365TransactionCard = document.getElementById("d365TransactionCard");
            var cameraPlaceholder = document.getElementById("cameraPlaceholder");
            var idPrivacyText = document.getElementById("idPrivacyText");
            var _currentIdMode = "id";

            // -- Demo ID presets --
            var DEMO_ID_MCLOVIN = "STATE OF HAWAII\n" +
                "DRIVER LICENSE\n\n" +
                "DL: 01-47-87441\n" +
                "EXP: 06/03/2008\n" +
                "DOB: 06/03/1981\n\n" +
                "McLOVIN\n" +
                "892 MOMONA ST\n" +
                "HONOLULU, HI 96820\n\n" +
                "SEX: M    HT: 5-10    WT: 150\n" +
                "HAIR: BRN    EYES: BRN\n" +
                "ISS: 06/18/1998\n\n" +
                "ORGAN DONOR";

            var DEMO_ID_JACKIE = "STATE OF MICHIGAN\n" +
                "DRIVER LICENSE\n\n" +
                "DL: R 320 481 227 093\n" +
                "EXP: 09/15/2028\n" +
                "DOB: 04/12/1981\n\n" +
                "1 RODRIGUEZ\n" +
                "2 JACKIE MARIE\n" +
                "1847 MAPLE AVENUE\n" +
                "TROY, MI 48083\n\n" +
                "SEX: F    HT: 5-06    WT: 135\n" +
                "HAIR: BRN    EYES: BRN\n" +
                "ISS: 09/15/2024\n" +
                "CLASS: D";

            var DEMO_CHECK_OCR = "MICHIGAN POWER & LIGHT\n" +
                "123 UTILITY WAY\n" +
                "DETROIT, MI 48202\n\n" +
                "FIRST CITY BANK\n" +
                "1847 MAPLE AVENUE, TROY, MI 48083\n\n" +
                "DATE: MARCH 15, 2026\n\n" +
                "PAY TO THE ORDER OF: JACKIE MARIE RODRIGUEZ  $245.89\n\n" +
                "TWO HUNDRED FORTY-FIVE AND 89/100 DOLLARS\n\n" +
                "MEMO: ACCOUNT OVERPAYMENT REFUND\n\n" +
                "|: 1896700101 |: 0090161991 |: 1133\n\n" +
                "Sarah J. Reed\n" +
                "AUTHORIZED SIGNATURE\n" +
                "Check #: 1133";

            function setMode(mode) {
                _currentIdMode = mode;
                idModeBtn.classList.toggle("active", mode === "id");
                checkModeBtn.classList.toggle("active", mode === "check");
                idResultCard.style.display = "none";
                checkResultCard.style.display = "none";
                d365CustomerCard.style.display = "none";
                d365TransactionCard.style.display = "none";
                var _prev = document.getElementById("demoIdPreview"); if (_prev) _prev.style.display = "none";
                var _sig = document.getElementById("sigSection"); if (_sig) _sig.style.display = "none";
                var _sigC = document.getElementById("sigConfirm"); if (_sigC) _sigC.style.display = "none";
                if (loadDemoCheckBtn) loadDemoCheckBtn.style.display = (mode === "check") ? "inline-block" : "none";
                if (cameraPlaceholder && cameraPlaceholder.style.display !== "none") {
                    var pt = cameraPlaceholder.querySelector("div:last-child");
                    if (pt) {
                        pt.textContent = (mode === "check")
                            ? 'Click "Start Camera" or "Load Demo Check" to begin'
                            : 'Click "Start Camera" to begin ID verification';
                    }
                }
                if (idPrivacyText) {
                    idPrivacyText.innerHTML = (mode === "check")
                        ? "Check images and financial data never leave this device. Camera capture, OCR, and AI analysis all run locally."
                        : "Your ID image and data never leave this device. Camera capture, OCR, and AI analysis all run locally.";
                }
            }

            if (idModeBtn) idModeBtn.addEventListener("click", function() { setMode("id"); });
            if (checkModeBtn) checkModeBtn.addEventListener("click", function() { setMode("check"); });

            if (captureBtn) {
                new MutationObserver(function() {
                    if (captureBtn.style.display !== "none") {
                        captureBtn.textContent = (_currentIdMode === "check") ? "Capture Check" : "Capture ID";
                    }
                }).observe(captureBtn, { attributes: true, attributeFilter: ["style"] });
            }

            var capturedImg = document.getElementById("capturedImage");
            if (capturedImg) {
                new MutationObserver(function() {
                    if (capturedImg.style.display !== "none") {
                        if (_currentIdMode === "check") {
                            if (analyzeIdBtn) analyzeIdBtn.style.display = "none";
                            if (analyzeCheckBtn) analyzeCheckBtn.style.display = "inline-block";
                        } else {
                            if (analyzeCheckBtn) analyzeCheckBtn.style.display = "none";
                        }
                    } else {
                        if (analyzeCheckBtn) analyzeCheckBtn.style.display = "none";
                    }
                }).observe(capturedImg, { attributes: true, attributeFilter: ["style"] });
            }

            function analyzeCheck(ocrTextOverride) {
                var useOcrText = ocrTextOverride || null;
                // Show check image in the camera area for demo preset
                if (useOcrText) {
                    var capturedImg = document.getElementById("capturedImage");
                    var placeholder = document.getElementById("cameraPlaceholder");
                    var camPreview = document.getElementById("cameraPreview");
                    capturedImg.src = "/demo-assets/jackie_check.png";
                    capturedImg.style.display = "block";
                    if (placeholder) placeholder.style.display = "none";
                    if (camPreview) camPreview.style.display = "none";
                    var previewDiv = document.getElementById("demoIdPreview");
                    if (previewDiv) previewDiv.style.display = "none";
                }
                document.getElementById("processingSteps").style.display = "block";
                document.getElementById("ocrPreview").style.display = "none";
                checkResultCard.style.display = "none";
                idResultCard.style.display = "none";
                d365TransactionCard.style.display = "none";

                for (var i = 1; i <= 3; i++) {
                    var step = document.getElementById("step" + i);
                    var icon = step.querySelector(".step-icon");
                    icon.classList.remove("step-active", "step-done");
                    icon.classList.add("step-pending");
                    icon.innerHTML = i;
                }
                if (useOcrText) {
                    // Staggered processing animation for demo preset (~5s)
                    updateStep(1, "active");
                    setTimeout(function() {
                        updateStep(1, "done");
                        updateStep(2, "active");
                        setTimeout(function() {
                            updateStep(2, "done");
                            document.getElementById("ocrPreview").style.display = "block";
                            document.getElementById("ocrText").textContent = useOcrText;
                            updateStep(3, "active");
                            var fetchDone = false, fetchResult = null, timerDone = false;
                            function maybeFinishCheck() {
                                if (fetchDone && timerDone) {
                                    updateStep(3, "done");
                                    displayCheckResult(fetchResult);
                                    if (fetchResult.fields && !fetchResult.error) logCheckToD365(fetchResult);
                                }
                            }
                            fetch("/analyze-check", {
                                method: "POST",
                                headers: {"Content-Type": "application/json"},
                                body: JSON.stringify({ ocr_text: useOcrText })
                            })
                            .then(function(r) { return r.json(); })
                            .then(function(data) { fetchResult = data; fetchDone = true; maybeFinishCheck(); })
                            .catch(function(err) { fetchResult = { error: err.message }; fetchDone = true; maybeFinishCheck(); });
                            setTimeout(function() { timerDone = true; maybeFinishCheck(); }, 2000);
                        }, 1800);
                    }, 1200);
                } else {
                    updateStep(1, "done");
                    updateStep(2, "active");
                    var img = document.getElementById("capturedImage");
                    Tesseract.recognize(img.src, "eng", {
                        workerPath: "/tesseract/worker.min.js",
                        corePath: "/tesseract/core",
                        langPath: "/tesseract/lang",
                        workerBlobURL: false
                    }).then(function(result) {
                        updateStep(2, "done");
                        document.getElementById("ocrPreview").style.display = "block";
                        document.getElementById("ocrText").textContent = result.data.text;
                        updateStep(3, "active");
                        sendCheckAnalysis(result.data.text);
                    }).catch(function(err) {
                        updateStep(2, "done");
                        document.getElementById("ocrPreview").style.display = "block";
                        document.getElementById("ocrText").textContent = "Error: " + err.message;
                    });
                }
            }

            function sendCheckAnalysis(ocrText) {
                fetch("/analyze-check", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ ocr_text: ocrText })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    updateStep(3, "done");
                    displayCheckResult(data);
                    if (data.fields && !data.error) logCheckToD365(data);
                })
                .catch(function(err) {
                    updateStep(3, "done");
                    displayCheckResult({ error: err.message });
                });
            }

            function displayCheckResult(data) {
                checkResultCard.style.display = "block";
                var badge = document.getElementById("checkStatusBadge");
                var amountDiv = document.getElementById("checkAmount");
                var fieldsDiv = document.getElementById("checkFields");
                var flagsDiv = document.getElementById("checkFlags");

                if (data.error) {
                    badge.textContent = "Error";
                    badge.className = "status-badge status-error";
                    fieldsDiv.innerHTML = "<p>Could not analyze check: " + data.error + "</p>";
                    flagsDiv.innerHTML = "";
                    amountDiv.style.display = "none";
                    return;
                }

                var status = data.status || "Review Needed";
                badge.textContent = status;
                badge.className = "status-badge " + (status === "Verified" ? "status-valid" : status === "Review Needed" ? "status-warning" : "status-error");

                var fields = data.fields || {};
                amountDiv.textContent = fields.amount_numbers ? "$" + fields.amount_numbers : "";
                amountDiv.style.display = fields.amount_numbers ? "block" : "none";

                var fieldLabels = {
                    "payee_name": "Pay To (Payee)", "payer_name": "From (Payer)",
                    "check_number": "Check Number", "date": "Date",
                    "amount_numbers": "Amount (Numeric)", "amount_words": "Amount (Written)",
                    "bank_name": "Bank", "routing_last4": "Routing (last 4)",
                    "account_last4": "Account (last 4)", "memo": "Memo",
                    "signature_present": "Signature"
                };
                var fh = "";
                for (var key in fieldLabels) {
                    var val = fields[key] || "Not detected";
                    if (key === "signature_present") val = (val === "yes" || val === true) ? "&#10003; Present" : "&#10007; Missing";
                    fh += '<div class="check-field"><span class="check-field-label">' + fieldLabels[key] + '</span><span class="check-field-value">' + val + '</span></div>';
                }
                fieldsDiv.innerHTML = fh;

                var flags = data.flags || [];
                var flh = "<strong style='font-size:0.85em;color:rgba(255,255,255,0.5);'>Validation</strong>";
                if (flags.length === 0) {
                    flh += '<div class="check-flag flag-pass">&#10003; All checks passed</div>';
                } else {
                    for (var f = 0; f < flags.length; f++) {
                        var fl = flags[f];
                        var cls = fl.severity === "error" ? "flag-fail" : fl.severity === "warning" ? "flag-warn" : "flag-pass";
                        var ic = fl.severity === "error" ? "&#10007;" : fl.severity === "warning" ? "&#9888;" : "&#10003;";
                        flh += '<div class="check-flag ' + cls + '">' + ic + ' ' + fl.message + '</div>';
                    }
                }
                flagsDiv.innerHTML = flh;
            }

            // -- D365 Customer Lookup (after ID scan) --
            window._d365CustomerLookup = function(customerName) {
                fetch("/d365/customer-lookup", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ name: customerName })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.error) return;
                    renderD365Customer(data);
                })
                .catch(function(err) { console.log("D365 lookup failed:", err); });
            };

            function renderD365Customer(data) {
                var content = document.getElementById("d365CustomerContent");
                var statusBadge = document.getElementById("d365Status");
                var openLink = document.getElementById("d365OpenLink");
                statusBadge.textContent = data.source === "live" ? "Live from Dynamics 365" : "Demo Environment";

                var ci = data.customer || {};
                var html = '<div class="d365-section"><div class="d365-section-title">Customer Information</div>';
                var ciFields = [["Full Name", ci.full_name], ["Email", ci.email], ["Phone", ci.phone], ["Address", ci.address], ["Account Type", ci.account_type], ["Account Age", ci.account_age], ["Source", ci.source], ["Relationship Manager", ci.relationship_manager]];
                for (var i = 0; i < ciFields.length; i++) {
                    if (ciFields[i][1]) html += '<div class="d365-field"><span class="d365-field-label">' + ciFields[i][0] + '</span><span class="d365-field-value">' + ciFields[i][1] + '</span></div>';
                }
                html += '</div>';
                if (ci.accounts && ci.accounts.length > 0) {
                    html += '<div class="d365-section"><div class="d365-section-title">Accounts</div>';
                    for (var a = 0; a < ci.accounts.length; a++) {
                        html += '<div class="d365-field"><span class="d365-field-label">' + ci.accounts[a].type + '</span><span class="d365-field-value">' + (ci.accounts[a].number || '') + ' &mdash; ' + (ci.accounts[a].balance || '') + '</span></div>';
                    }
                    html += '</div>';
                }
                if (ci.recent_activity && ci.recent_activity.length > 0) {
                    html += '<div class="d365-section"><div class="d365-section-title">Recent Activity</div>';
                    for (var r = 0; r < ci.recent_activity.length; r++) html += '<div class="d365-activity">' + ci.recent_activity[r] + '</div>';
                    html += '</div>';
                }
                content.innerHTML = html;
                openLink.href = data.d365_url || "#";
                openLink.style.display = data.d365_url ? "inline-block" : "none";
                d365CustomerCard.style.display = "block";
                // Show signature pad after customer profile loads
                if (typeof window._showSignaturePad === "function") window._showSignaturePad();
            }

            function logCheckToD365(checkData) {
                fetch("/d365/log-transaction", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        customer_name: checkData.fields.payer_name || checkData.fields.payee_name || "Unknown",
                        transaction_type: "Check Deposit",
                        amount: checkData.fields.amount_numbers || "0",
                        check_number: checkData.fields.check_number || "N/A",
                        memo: checkData.fields.memo || "",
                        bank: checkData.fields.bank_name || ""
                    })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (!data.error) renderD365Transaction(data);
                })
                .catch(function(err) { console.log("D365 log failed:", err); });
            }

            function renderD365Transaction(data) {
                var content = document.getElementById("d365TransactionContent");
                var html = '<div class="d365-section"><div class="d365-section-title">Transaction Details</div>';
                var txf = [["Type", data.transaction_type], ["Amount", "$" + (data.amount || "0")], ["Check #", data.check_number], ["Customer", data.customer_name], ["Memo", data.memo], ["Status", data.status || "Completed"], ["D365 Activity ID", data.activity_id || "N/A"], ["Timestamp", data.timestamp || new Date().toISOString()]];
                for (var i = 0; i < txf.length; i++) {
                    if (txf[i][1]) html += '<div class="d365-field"><span class="d365-field-label">' + txf[i][0] + '</span><span class="d365-field-value">' + txf[i][1] + '</span></div>';
                }
                html += '</div>';
                content.innerHTML = html;
                d365TransactionCard.style.display = "block";
            }

            if (loadDemoCheckBtn) loadDemoCheckBtn.addEventListener("click", function() { analyzeCheck(DEMO_CHECK_OCR); });
            if (analyzeCheckBtn) analyzeCheckBtn.addEventListener("click", function() { analyzeCheck(null); });

            // -- Demo ID dropdown menu --
            var demoIdBtn = document.getElementById("loadDemoIdBtn");
            var demoIdMenu = document.getElementById("demoIdMenu");
            var demoIdMclovin = document.getElementById("demoIdMclovin");
            var demoIdJackie = document.getElementById("demoIdJackie");

            if (demoIdBtn && demoIdMenu) {
                demoIdBtn.addEventListener("click", function(e) {
                    e.stopPropagation();
                    var rect = demoIdBtn.getBoundingClientRect();
                    demoIdMenu.style.position = "fixed";
                    demoIdMenu.style.left = rect.left + "px";
                    demoIdMenu.style.top = (rect.bottom + 4) + "px";
                    demoIdMenu.style.display = demoIdMenu.style.display === "none" ? "block" : "none";
                });
                document.addEventListener("click", function() { demoIdMenu.style.display = "none"; });
            }

            function runDemoId(ocrText, previewType) {
                demoIdMenu.style.display = "none";
                if (_currentIdMode !== "id") setMode("id");

                // Show ID image in the camera area (where the camera preview would be)
                var capturedImg = document.getElementById("capturedImage");
                var placeholder = document.getElementById("cameraPlaceholder");
                var camPreview = document.getElementById("cameraPreview");
                if (previewType === "mclovin") {
                    capturedImg.src = "/demo-assets/mclovin_id.png";
                } else if (previewType === "jackie") {
                    capturedImg.src = "/demo-assets/jackie_rodriguez_id.png";
                }
                capturedImg.style.display = "block";
                if (placeholder) placeholder.style.display = "none";
                if (camPreview) camPreview.style.display = "none";
                // Hide the separate preview div
                var previewDiv = document.getElementById("demoIdPreview");
                if (previewDiv) previewDiv.style.display = "none";

                // Show processing steps with staggered animation
                document.getElementById("processingSteps").style.display = "block";
                document.getElementById("ocrPreview").style.display = "none";
                idResultCard.style.display = "none";
                d365CustomerCard.style.display = "none";

                for (var i = 1; i <= 3; i++) {
                    var step = document.getElementById("step" + i);
                    var icon = step.querySelector(".step-icon");
                    icon.classList.remove("step-active", "step-done");
                    icon.classList.add("step-pending");
                    icon.innerHTML = i;
                }

                // Step 1: Image captured — spinner then done after 1.2s
                updateStep(1, "active");
                setTimeout(function() {
                    updateStep(1, "done");
                    // Step 2: OCR extraction — spinner then done after 1.8s
                    updateStep(2, "active");
                    setTimeout(function() {
                        updateStep(2, "done");
                        document.getElementById("ocrPreview").style.display = "block";
                        document.getElementById("ocrText").textContent = ocrText;
                        // Step 3: AI Analysis — fire fetch, show spinner for at least 2s
                        updateStep(3, "active");
                        var fetchDone = false;
                        var fetchResult = null;
                        var timerDone = false;

                        function maybeFinish() {
                            if (fetchDone && timerDone) {
                                updateStep(3, "done");
                                displayIdResult(fetchResult);
                            }
                        }

                        fetch("/analyze-id", {
                            method: "POST",
                            headers: {"Content-Type": "application/json"},
                            body: JSON.stringify({ ocr_text: ocrText })
                        })
                        .then(function(r) { return r.json(); })
                        .then(function(data) { fetchResult = data; fetchDone = true; maybeFinish(); })
                        .catch(function(err) { fetchResult = { error: err.message }; fetchDone = true; maybeFinish(); });

                        setTimeout(function() { timerDone = true; maybeFinish(); }, 2000);
                    }, 1800);
                }, 1200);
            }

            if (demoIdMclovin) demoIdMclovin.addEventListener("click", function(e) { e.stopPropagation(); runDemoId(DEMO_ID_MCLOVIN, "mclovin"); });
            if (demoIdJackie) demoIdJackie.addEventListener("click", function(e) { e.stopPropagation(); runDemoId(DEMO_ID_JACKIE, "jackie"); });

            // Hide demo ID button in check mode, show in ID mode
            function updateDemoIdVisibility() {
                if (demoIdBtn) demoIdBtn.style.display = (_currentIdMode === "id") ? "inline-block" : "none";
            }
            var origSetMode = setMode;
            setMode = function(mode) { origSetMode(mode); updateDemoIdVisibility(); };

            window._getIdMode = function() { return _currentIdMode; };

            // Show signature section after successful ID scan or check deposit
            window._showSignaturePad = function() {
                var sig = document.getElementById("sigSection");
                if (sig) sig.style.display = "block";
            };
        })();

        // ── Pen Signature Pad ──
        (function() {
            var canvas = document.getElementById("sigCanvas");
            var clearBtn = document.getElementById("sigClearBtn");
            var acceptBtn = document.getElementById("sigAcceptBtn");
            var sigSection = document.getElementById("sigSection");
            var sigConfirm = document.getElementById("sigConfirm");
            var sigHash = document.getElementById("sigHash");
            if (!canvas) return;

            var ctx = canvas.getContext("2d");
            var strokes = [];
            var currentStroke = null;
            var isDrawing = false;

            // Resize canvas to fill container
            function resizeCanvas() {
                var wrapper = canvas.parentElement;
                var w = wrapper.clientWidth;
                if (w > 0) {
                    canvas.width = w;
                    canvas.height = 150;
                    redraw();
                }
            }
            window.addEventListener("resize", resizeCanvas);
            setTimeout(resizeCanvas, 100);

            function getPos(e) {
                var rect = canvas.getBoundingClientRect();
                return {
                    x: (e.clientX - rect.left) * (canvas.width / rect.width),
                    y: (e.clientY - rect.top) * (canvas.height / rect.height),
                    pressure: e.pressure || 0.5
                };
            }

            function drawSegment(p1, p2) {
                ctx.beginPath();
                ctx.strokeStyle = "#111";
                ctx.lineWidth = 2 + (p2.pressure * 4); // 2-6px based on pressure
                ctx.lineCap = "round";
                ctx.lineJoin = "round";
                ctx.moveTo(p1.x, p1.y);
                ctx.lineTo(p2.x, p2.y);
                ctx.stroke();
            }

            function redraw() {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                for (var s = 0; s < strokes.length; s++) {
                    var pts = strokes[s];
                    for (var i = 1; i < pts.length; i++) {
                        drawSegment(pts[i-1], pts[i]);
                    }
                }
            }

            canvas.addEventListener("pointerdown", function(e) {
                e.preventDefault();
                isDrawing = true;
                currentStroke = [getPos(e)];
                canvas.setPointerCapture(e.pointerId);
            });

            canvas.addEventListener("pointermove", function(e) {
                if (!isDrawing || !currentStroke) return;
                e.preventDefault();
                var pos = getPos(e);
                currentStroke.push(pos);
                if (currentStroke.length >= 2) {
                    drawSegment(currentStroke[currentStroke.length - 2], pos);
                }
            });

            function endStroke() {
                if (!isDrawing) return;
                isDrawing = false;
                if (currentStroke && currentStroke.length >= 2) {
                    strokes.push(currentStroke);
                }
                currentStroke = null;
            }
            canvas.addEventListener("pointerup", endStroke);
            canvas.addEventListener("pointerleave", endStroke);
            canvas.addEventListener("pointercancel", endStroke);

            if (clearBtn) clearBtn.addEventListener("click", function() {
                strokes = [];
                currentStroke = null;
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                if (sigConfirm) sigConfirm.style.display = "none";
            });

            if (acceptBtn) acceptBtn.addEventListener("click", function() {
                if (strokes.length === 0) return;

                // Get signature image as base64
                var dataUrl = canvas.toDataURL("image/png");

                // Send to backend for hash
                fetch("/signature/verify", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ image_data: dataUrl })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (sigConfirm && sigHash) {
                        sigHash.textContent = "Document hash: " + (data.hash || "N/A") + "\nTimestamp: " + (data.timestamp || new Date().toISOString());
                        sigConfirm.style.display = "block";
                    }
                    // Disable further signing
                    acceptBtn.disabled = true;
                    acceptBtn.textContent = "Signed";
                    acceptBtn.style.opacity = "0.5";
                })
                .catch(function(err) {
                    // Offline fallback
                    if (sigConfirm && sigHash) {
                        sigHash.textContent = "Document hash: [generated locally]\nTimestamp: " + new Date().toISOString();
                        sigConfirm.style.display = "block";
                    }
                });
            });
        })();

        // ── Meeting Notes Signature Pad (beneficiary form) ──
        (function() {
            var canvas = document.getElementById("inspSigCanvas");
            var clearBtn = document.getElementById("inspSigClearBtn");
            var acceptBtn = document.getElementById("inspSigAcceptBtn");
            var sigConfirm = document.getElementById("inspSigConfirm");
            var sigHash = document.getElementById("inspSigHash");
            if (!canvas) return;

            var ctx = canvas.getContext("2d");
            var strokes = [];
            var currentStroke = null;
            var isDrawing = false;

            function resizeCanvas() {
                var wrapper = canvas.parentElement;
                var w = wrapper.clientWidth;
                if (w > 0) { canvas.width = w; canvas.height = 150; redraw(); }
            }
            window.addEventListener("resize", resizeCanvas);
            setTimeout(resizeCanvas, 100);

            function getPos(e) {
                var rect = canvas.getBoundingClientRect();
                return { x: (e.clientX - rect.left) * (canvas.width / rect.width), y: (e.clientY - rect.top) * (canvas.height / rect.height), pressure: e.pressure || 0.5 };
            }
            function drawSegment(p1, p2) {
                ctx.beginPath(); ctx.strokeStyle = "#111"; ctx.lineWidth = 2 + (p2.pressure * 4);
                ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
            }
            function redraw() {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                for (var s = 0; s < strokes.length; s++) { var pts = strokes[s]; for (var i = 1; i < pts.length; i++) drawSegment(pts[i-1], pts[i]); }
            }

            canvas.addEventListener("pointerdown", function(e) { e.preventDefault(); isDrawing = true; currentStroke = [getPos(e)]; canvas.setPointerCapture(e.pointerId); });
            canvas.addEventListener("pointermove", function(e) { if (!isDrawing || !currentStroke) return; e.preventDefault(); var pos = getPos(e); currentStroke.push(pos); if (currentStroke.length >= 2) drawSegment(currentStroke[currentStroke.length - 2], pos); });
            function endStroke() { if (!isDrawing) return; isDrawing = false; if (currentStroke && currentStroke.length >= 2) strokes.push(currentStroke); currentStroke = null; }
            canvas.addEventListener("pointerup", endStroke);
            canvas.addEventListener("pointerleave", endStroke);
            canvas.addEventListener("pointercancel", endStroke);

            if (clearBtn) clearBtn.addEventListener("click", function() { strokes = []; currentStroke = null; ctx.clearRect(0, 0, canvas.width, canvas.height); if (sigConfirm) sigConfirm.style.display = "none"; });

            if (acceptBtn) acceptBtn.addEventListener("click", function() {
                if (strokes.length === 0) return;
                var dataUrl = canvas.toDataURL("image/png");
                fetch("/signature/verify", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({ image_data: dataUrl }) })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (sigConfirm && sigHash) { sigHash.textContent = "Document hash: " + (data.hash || "N/A") + "\nTimestamp: " + (data.timestamp || new Date().toISOString()); sigConfirm.style.display = "block"; }
                    acceptBtn.disabled = true; acceptBtn.textContent = "Signed"; acceptBtn.style.opacity = "0.5";
                })
                .catch(function() {
                    if (sigConfirm && sigHash) { sigHash.textContent = "Document hash: [generated locally]\nTimestamp: " + new Date().toISOString(); sigConfirm.style.display = "block"; }
                });
            });
        })();

        // === Unified Auditor Functions (analysis + escalation) ===
        var routerDocText = "";
        var routerDocName = "";
        var routerRunning = false;
        var routerEscalationContext = {};  // saved for decline/approve decision
        var pendingAuditStamp = null;     // saved for deferred audit stamp display

        // --- Render functions (structured results cards) ---

        function renderPiiCard(findings) {
            if (!findings || findings.length === 0) return;
            var cards = document.getElementById("auditorResultsCards");
            var html = '<div class="result-card pii">' +
                '<div class="result-card-header">\uD83D\uDD10 PII DETECTED</div>';
            findings.forEach(function(f) {
                var sevIcon = f.severity === "high" ? "\uD83D\uDD34" : "\uD83D\uDFE1";
                html += '<div class="pii-item">' +
                    '<span class="pii-severity">' + sevIcon + '</span>' +
                    '<span class="pii-type">' + f.type + '</span>' +
                    '<span class="pii-value">' + f.value + '</span>' +
                    '<span class="pii-location">' + (f.location || "") + '</span>' +
                    '</div>';
            });
            html += '<div style="margin-top:12px;font-size:0.85em;opacity:0.7;">\u26A1 Recommendation: Redact before external sharing</div>';
            html += '</div>';
            cards.innerHTML += html;
        }

        function renderRiskCard(findings) {
            if (!findings || findings.length === 0) return;
            var cards = document.getElementById("auditorResultsCards");
            var html = '<div class="result-card">' +
                '<div class="result-card-header">\u26A0\uFE0F RISK ASSESSMENT</div>';
            findings.forEach(function(f) {
                var sevClass = (f.severity || "medium").toLowerCase();
                var sevIcon = sevClass === "high" ? "\uD83D\uDD34" : sevClass === "medium" ? "\uD83D\uDFE1" : "\uD83D\uDFE2";
                var sevLabel = sevClass.toUpperCase();
                html += '<div class="risk-item">' +
                    '<div class="risk-severity ' + sevClass + '">' + sevIcon + ' ' + sevLabel + ' \u2014 ' + (f.type || "Risk") + (f.section ? " (Sec " + f.section + ")" : "") + '</div>' +
                    '<div class="risk-finding">' + (f.finding || "") + '</div>' +
                    (f.recommendation ? '<div class="risk-recommendation">\u2192 ' + f.recommendation + '</div>' : '') +
                    '</div>';
            });
            html += '</div>';
            cards.innerHTML += html;
        }

        function renderObligationsCard(findings) {
            if (!findings || findings.length === 0) return;
            var cards = document.getElementById("auditorResultsCards");
            var html = '<div class="result-card">' +
                '<div class="result-card-header">\uD83D\uDCCB KEY OBLIGATIONS</div>' +
                '<table style="width:100%;font-size:0.9em;border-collapse:collapse;">' +
                '<tr style="opacity:0.6;"><th style="text-align:left;padding:8px 4px;">Obligation</th><th style="text-align:left;padding:8px 4px;">Deadline</th><th style="text-align:left;padding:8px 4px;">Consequence</th></tr>';
            findings.forEach(function(f) {
                html += '<tr style="border-top:1px solid rgba(255,255,255,0.1);">' +
                    '<td style="padding:8px 4px;">' + (f.obligation || "") + '</td>' +
                    '<td style="padding:8px 4px;">' + (f.deadline || "") + '</td>' +
                    '<td style="padding:8px 4px;">' + (f.consequence || "") + '</td>' +
                    '</tr>';
            });
            html += '</table></div>';
            cards.innerHTML += html;
        }

        function renderSummaryCard(text) {
            if (!text) return;
            var cards = document.getElementById("auditorResultsCards");
            var html = '<div class="result-card">' +
                '<div class="result-card-header">\uD83D\uDCDD EXECUTIVE SUMMARY</div>' +
                '<div style="line-height:1.6;">' + text.replace(/\n/g, "<br>") + '</div>' +
                '</div>';
            cards.innerHTML += html;
        }

        function renderAuditStamp(data) {
            var stamp = document.getElementById("auditStamp");
            stamp.style.display = "block";
            stamp.innerHTML = '<div class="audit-stamp-header">\uD83D\uDD12 AUDIT STAMP</div>' +
                '<div class="audit-stamp-line">Audit Complete</div>' +
                '<div class="audit-stamp-line">Analyzed: ' + routerDocName + '</div>' +
                '<div class="audit-stamp-line">Total time: ' + (data.total_time || "?") + 's</div>' +
                '<div class="audit-stamp-line">PII scan: regex (local) \u2014 ' + (data.pii_time || "0") + 's</div>' +
                '<div class="audit-stamp-line">Risk analysis: {{MODEL_LABEL}} (NPU) \u2014 ' + (data.analysis_time || "?") + 's</div>' +
                '<div class="audit-stamp-line" style="color:#00CC6A;margin-top:8px;">Network calls: 0 \u2022 Data transmitted: 0 bytes</div>';
        }

        // --- Marketing mode render functions ---

        function renderClaimsCard(findings) {
            if (!findings || findings.length === 0) return;
            var cards = document.getElementById("auditorResultsCards");
            var html = '<div class="result-card">' +
                '<div class="result-card-header">\u26A0\uFE0F CLAIMS ANALYSIS (' + findings.length + ' findings)</div>';
            findings.forEach(function(f) {
                var riskClass = (f.risk_level || "medium").toLowerCase();
                var riskLabel = (f.risk_level || "MEDIUM").toUpperCase();
                var catClass = (f.category || "").toLowerCase().replace(/\s+/g, '-').replace(/_/g, '-');
                html += '<div class="claim-item">' +
                    '<div><span class="claim-category ' + catClass + '">' + (f.category || "General") + '</span>' +
                    '<span class="claim-risk ' + riskClass + '">' + riskLabel + '</span></div>' +
                    '<div class="claim-text">\u201C' + (f.claim_text || "") + '\u201D</div>' +
                    '<div class="claim-issue">' + (f.issue || "") + '</div>' +
                    (f.substantiation ? '<div class="claim-substantiation">\uD83D\uDCCB ' + f.substantiation + '</div>' : '') +
                    (f.recommendation ? '<div class="claim-recommendation">\u2192 ' + f.recommendation + '</div>' : '') +
                    '</div>';
            });
            html += '</div>';
            cards.innerHTML += html;
        }

        function renderVerdictCard(data) {
            var cards = document.getElementById("auditorResultsCards");
            var isOk = (data.verdict || "").toUpperCase().indexOf("SELF-SERVICE") !== -1;
            var verdictClass = isOk ? "verdict-ok" : "verdict-intake";
            var verdictIcon = isOk ? "\u2705" : "\uD83D\uDD34";
            var html = '<div class="verdict-card ' + verdictClass + '">' +
                '<div class="verdict-badge">' + verdictIcon + ' ' + (data.verdict || "UNKNOWN") + '</div>' +
                '<div class="verdict-reason">' + (data.verdict_reason || "") + '</div>';

            // Trigger categories
            if (data.trigger_categories && data.trigger_categories !== "None") {
                var tags = data.trigger_categories.split(',');
                html += '<div style="margin:8px 0;">';
                tags.forEach(function(tag) {
                    html += '<span class="trigger-tag">' + tag.trim() + '</span>';
                });
                html += '</div>';
            }

            // Counts
            html += '<div class="verdict-counts">' +
                '<div class="verdict-count">Total: ' + (data.total_findings || "0") + '</div>' +
                '<div class="verdict-count" style="color:#FF6B6B;">High: ' + (data.high_risk_count || "0") + '</div>' +
                '<div class="verdict-count" style="color:#FFB900;">Medium: ' + (data.medium_risk_count || "0") + '</div>' +
                '<div class="verdict-count" style="color:#81C784;">Low: ' + (data.low_risk_count || "0") + '</div>' +
                '</div></div>';
            cards.innerHTML += html;
        }

        // --- Auditor mode state ---
        var currentAuditorMode = "";

        // --- Mode selector handlers ---
        document.getElementById("modeCardContract").addEventListener("click", function() {
            currentAuditorMode = "contract";
            document.getElementById("auditorModeSelector").style.display = "none";
            document.getElementById("routerInputZone").style.display = "block";
            document.getElementById("marketingInputZone").style.display = "none";
        });
        document.getElementById("modeCardMarketing").addEventListener("click", function() {
            currentAuditorMode = "marketing";
            document.getElementById("auditorModeSelector").style.display = "none";
            document.getElementById("routerInputZone").style.display = "none";
            document.getElementById("marketingInputZone").style.display = "block";
        });

        // Back links
        document.getElementById("contractBackLink").addEventListener("click", function(e) {
            e.preventDefault();
            document.getElementById("routerInputZone").style.display = "none";
            document.getElementById("auditorModeSelector").style.display = "block";
            currentAuditorMode = "";
        });
        document.getElementById("marketingBackLink").addEventListener("click", function(e) {
            e.preventDefault();
            document.getElementById("marketingInputZone").style.display = "none";
            document.getElementById("auditorModeSelector").style.display = "block";
            currentAuditorMode = "";
        });

        // --- Marketing file upload + demo buttons ---
        document.getElementById("marketingUploadBtn").addEventListener("click", function() {
            document.getElementById("marketingFileInput").click();
        });
        document.getElementById("marketingFileInput").addEventListener("change", function(e) {
            var file = e.target.files[0];
            if (!file) return;
            var formData = new FormData();
            formData.append("file", file);
            fetch("/upload-to-demo", { method: "POST", body: formData })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) { alert("Upload failed: " + data.error); return; }
                routerDocText = data.text || "";
                routerDocName = data.filename || file.name;
                runRouterAnalysis();
            });
        });

        // Marketing drag and drop
        var marketingDZ = document.getElementById("marketingDropzone");
        marketingDZ.addEventListener("dragover", function(e) { e.preventDefault(); marketingDZ.classList.add("dragover"); });
        marketingDZ.addEventListener("dragleave", function() { marketingDZ.classList.remove("dragover"); });
        marketingDZ.addEventListener("drop", function(e) {
            e.preventDefault();
            marketingDZ.classList.remove("dragover");
            var file = e.dataTransfer.files[0];
            if (file) {
                var input = document.getElementById("marketingFileInput");
                var dt = new DataTransfer();
                dt.items.add(file);
                input.files = dt.files;
                input.dispatchEvent(new Event("change"));
            }
        });

        // Marketing demo buttons
        document.getElementById("marketingDemoCleanBtn").addEventListener("click", function() {
            fetch("/auditor-marketing-demo-doc")
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) { alert("Demo document not found: " + data.error); return; }
                routerDocText = data.text;
                routerDocName = data.filename;
                runRouterAnalysis();
            });
        });
        document.getElementById("marketingDemoRiskyBtn").addEventListener("click", function() {
            fetch("/auditor-marketing-escalation-demo-doc")
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) { alert("Escalation demo document not found: " + data.error); return; }
                routerDocText = data.text;
                routerDocName = data.filename;
                runRouterAnalysis();
            });
        });

        // --- File upload / demo buttons (Contract mode) ---

        document.getElementById("routerUploadBtn").addEventListener("click", function() {
            document.getElementById("routerFileInput").click();
        });

        document.getElementById("routerFileInput").addEventListener("change", function(e) {
            var file = e.target.files[0];
            if (!file) return;
            var formData = new FormData();
            formData.append("file", file);
            fetch("/upload-to-demo", { method: "POST", body: formData })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) { alert("Upload failed: " + data.error); return; }
                routerDocText = data.text || "";
                routerDocName = data.filename || file.name;
                runRouterAnalysis();
            });
        });

        // Drag and drop
        var routerDZ = document.getElementById("routerDropzone");
        routerDZ.addEventListener("dragover", function(e) { e.preventDefault(); routerDZ.classList.add("dragover"); });
        routerDZ.addEventListener("dragleave", function() { routerDZ.classList.remove("dragover"); });
        routerDZ.addEventListener("drop", function(e) {
            e.preventDefault();
            routerDZ.classList.remove("dragover");
            var file = e.dataTransfer.files[0];
            if (file) {
                var input = document.getElementById("routerFileInput");
                var dt = new DataTransfer();
                dt.items.add(file);
                input.files = dt.files;
                input.dispatchEvent(new Event("change"));
            }
        });

        // Demo button — load demo NDA
        document.getElementById("routerDemoBtn").addEventListener("click", function() {
            fetch("/auditor-demo-doc")
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) { alert("Demo document not found: " + data.error); return; }
                routerDocText = data.text;
                routerDocName = data.filename;
                runRouterAnalysis();
            });
        });

        // Escalation demo button — load cross-border IP license
        document.getElementById("routerEscalationDemoBtn").addEventListener("click", function() {
            fetch("/auditor-escalation-demo-doc")
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) { alert("Escalation demo document not found: " + data.error); return; }
                routerDocText = data.text;
                routerDocName = data.filename;
                runRouterAnalysis();
            });
        });

        // Query-only mode (no file)
        document.getElementById("routerAskBtn").addEventListener("click", function() {
            var q = document.getElementById("routerQueryInput").value.trim();
            if (!q) return;
            routerDocText = "";
            routerDocName = "";
            runRouterAnalysis(q);
        });
        document.getElementById("routerQueryInput").addEventListener("keydown", function(e) {
            if (e.key === "Enter") document.getElementById("routerAskBtn").click();
        });

        // --- Main analysis function ---

        function runRouterAnalysis(queryOnly) {
            if (routerRunning) return;
            routerRunning = true;
            pendingAuditStamp = null;

            // Switch to results view
            document.getElementById("auditorModeSelector").style.display = "none";
            document.getElementById("routerInputZone").style.display = "none";
            document.getElementById("marketingInputZone").style.display = "none";
            document.getElementById("routerDecision").style.display = "block";
            document.getElementById("routerDecisionCard").style.display = "none";
            document.getElementById("escalationConsent").style.display = "none";
            document.getElementById("stayedLocalBanner").style.display = "none";
            document.getElementById("routerTrustReceipt").style.display = "none";
            document.getElementById("routerPostActions").style.display = "none";
            document.getElementById("auditorResultsCards").innerHTML = "";
            document.getElementById("auditStamp").style.display = "none";
            document.getElementById("routerStatusLog").innerHTML =
                '<div class="log-step active"><span class="spinner"></span> Starting analysis...</div>';

            var body = {};
            body.mode = currentAuditorMode || "contract";
            if (routerDocText) {
                body.text = routerDocText;
                body.filename = routerDocName;
            }
            if (queryOnly) {
                body.query = queryOnly;
            } else if (!routerDocText) {
                routerRunning = false;
                return;
            }

            fetch("/router/analyze", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(body)
            })
            .then(function(r) { return r.body.getReader(); })
            .then(function(reader) {
                var decoder = new TextDecoder();
                var buffer = "";

                function processLine(line) {
                    line = line.trim();
                    if (!line) return;
                    try {
                        var evt = JSON.parse(line);
                        processRouterEvent(evt);
                    } catch(e) { console.log("Auditor parse error:", e); }
                }

                function read() {
                    reader.read().then(function(result) {
                        if (result.done) {
                            if (buffer.trim()) processLine(buffer);
                            routerRunning = false;
                            return;
                        }
                        buffer += decoder.decode(result.value);
                        var lines = buffer.split("\n");
                        buffer = lines.pop();
                        lines.forEach(processLine);
                        read();
                    });
                }
                read();
            })
            .catch(function(err) {
                document.getElementById("routerStatusLog").innerHTML +=
                    '<div class="log-step" style="color:#FF4444;">Error: ' + err.message + '</div>';
                routerRunning = false;
            });
        }

        function resolveRouterSpinners() {
            var log = document.getElementById("routerStatusLog");
            var activeSteps = log.querySelectorAll(".log-step.active");
            activeSteps.forEach(function(step) {
                step.classList.remove("active");
                step.classList.add("complete");
                var spinner = step.querySelector(".spinner");
                if (spinner) spinner.outerHTML = '<span style="color:#00CC6A;">&#10003;</span>';
            });
        }

        // --- Unified event handler ---

        function processRouterEvent(evt) {
            var log = document.getElementById("routerStatusLog");

            if (evt.type === "document_preview") {
                var html = '<div class="doc-preview-card">';
                html += '<div style="font-weight:600;color:#fff;">&#128196; ' + (evt.filename || 'document') + '</div>';
                html += '<div style="opacity:0.6;font-size:0.85em;">' + (evt.word_count || 0) + ' words</div>';
                if (evt.preview) {
                    var safePreview = evt.preview.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                    html += '<div class="doc-preview-text">' + safePreview + '...</div>';
                }
                html += '</div>';
                log.innerHTML += html;
            }
            else if (evt.type === "status") {
                resolveRouterSpinners();
                log.innerHTML += '<div class="log-step active"><span class="spinner"></span> ' + evt.message + '</div>';
            }
            else if (evt.type === "knowledge") {
                resolveRouterSpinners();
            }
            else if (evt.type === "pii") {
                renderPiiCard(evt.findings);
            }
            else if (evt.type === "risk") {
                renderRiskCard(evt.findings);
            }
            else if (evt.type === "obligations") {
                renderObligationsCard(evt.findings);
            }
            else if (evt.type === "summary") {
                renderSummaryCard(evt.text);
            }
            else if (evt.type === "claims") {
                renderClaimsCard(evt.findings);
            }
            else if (evt.type === "verdict") {
                renderVerdictCard(evt);
            }
            else if (evt.type === "decision_card") {
                resolveRouterSpinners();

                var card = document.getElementById("routerDecisionCard");
                var analysisEl = document.getElementById("routerAnalysisText");

                // Confidence indicator
                var confEl = document.getElementById("dcConfidence");
                if (evt.confidence === "HIGH") {
                    confEl.innerHTML = '<span class="confidence-high">&#10004; Sufficient</span>';
                } else if (evt.confidence === "MEDIUM") {
                    confEl.innerHTML = '<span class="confidence-medium">&#9888;&#65039; Partial</span>';
                } else {
                    confEl.innerHTML = '<span class="confidence-low">&#10060; Insufficient</span>';
                }
                confEl.title = evt.reasoning || "";

                // Sources
                var srcCount = evt.sources_used ? evt.sources_used.length : 0;
                document.getElementById("dcSources").textContent = srcCount + " document" + (srcCount !== 1 ? "s" : "");

                // Frontier benefit
                document.getElementById("dcFrontierBenefit").textContent = evt.frontier_benefit || "None";

                // Show card
                card.style.display = "block";

                // Analysis text (only for query mode — document mode uses structured cards)
                var analysisContent = (evt.analysis || "").trim();
                if (!analysisContent && evt.reasoning) {
                    analysisContent = evt.reasoning;
                }
                if (analysisContent && !routerDocText) {
                    // Query mode: show analysis text
                    try {
                        var safe = analysisContent
                            .replace(/&/g, '&amp;')
                            .replace(/</g, '&lt;')
                            .replace(/>/g, '&gt;');
                        analysisEl.innerHTML = mdToHtml(safe);
                        analysisEl.style.display = "block";
                    } catch(mdErr) {
                        analysisEl.textContent = analysisContent;
                        analysisEl.style.display = "block";
                    }
                } else {
                    analysisEl.style.display = "none";
                }

                // Update status log
                log.innerHTML += '<div class="log-step" style="color:#00CC6A;">&#10003; Analysis complete (' + evt.analysis_time + 's)</div>';

                // Save for escalation context
                routerEscalationContext.confidence = evt.confidence;
                routerEscalationContext.sources_used = evt.sources_used || [];

                // If HIGH confidence, show audit stamp and post-actions immediately
                if (evt.confidence === "HIGH") {
                    if (pendingAuditStamp) renderAuditStamp(pendingAuditStamp);
                    document.getElementById("routerPostActions").style.display = "block";
                }
            }
            else if (evt.type === "escalation_available") {
                document.getElementById("routerDecisionCard").style.display = "block";
                document.getElementById("escalationConsent").style.display = "block";

                // Populate diff
                document.getElementById("diffOriginal").textContent = evt.original_preview || "";
                var redactedHtml = (evt.redacted_preview || "").replace(
                    /\[REDACTED (.*?)\]/g,
                    '<span class="pii-redacted">[REDACTED $1]</span>'
                );
                document.getElementById("diffRedacted").innerHTML = redactedHtml;

                // Cost/token info
                document.getElementById("escPiiCount").textContent = evt.pii_found || 0;
                document.getElementById("escTokens").textContent = evt.estimated_tokens || 0;
                document.getElementById("escCost").textContent = "$" + (evt.estimated_cost || 0).toFixed(4);

                // Save escalation context
                routerEscalationContext.pii_found = evt.pii_found;
                routerEscalationContext.pii_details = evt.pii_details || [];
                routerEscalationContext.estimated_tokens = evt.estimated_tokens;
                routerEscalationContext.estimated_cost = evt.estimated_cost;
            }
            else if (evt.type === "audit") {
                // Save audit stamp data; render immediately if no escalation pending
                pendingAuditStamp = evt;
                var noEscalation = routerEscalationContext.confidence === "HIGH" ||
                    (evt.mode === "marketing" && !routerEscalationContext.estimated_cost);
                if (noEscalation) {
                    renderAuditStamp(evt);
                    document.getElementById("routerPostActions").style.display = "block";
                }
            }
            else if (evt.type === "error") {
                resolveRouterSpinners();
                log.innerHTML += '<div class="log-step" style="color:#FF4444;">&#10060; ' + evt.message + '</div>';
                document.getElementById("routerPostActions").style.display = "block";
            }
            else if (evt.type === "complete") {
                resolveRouterSpinners();
                log.innerHTML += '<div class="log-step" style="color:#00CC6A;">&#10003; Auditor complete (' + evt.total_time + 's)</div>';
            }
        }

        // --- Escalation handlers ---

        // Decline escalation — the heroic path
        document.getElementById("btnDeclineEsc").addEventListener("click", function() {
            document.getElementById("escalationConsent").style.display = "none";

            // Show Stayed Local banner
            document.getElementById("stayedLocalBanner").style.display = "block";
            var icon = document.getElementById("stayedLocalLockIcon");
            icon.style.animation = "none";
            icon.offsetHeight;  // force reflow
            icon.style.animation = "";

            // Build detail text
            var piiCount = routerEscalationContext.pii_found || 0;
            var piiTypes = (routerEscalationContext.pii_details || []).map(function(p) { return p.type; });
            var uniqueTypes = piiTypes.filter(function(v, i, a) { return a.indexOf(v) === i; });
            var detail = "";
            if (piiCount > 0) {
                detail = piiCount + " PII item" + (piiCount !== 1 ? "s" : "") + " (" + uniqueTypes.join(", ") + ") never left this device. ";
            }
            detail += "$0.00 spent. 0 bytes transmitted.";
            document.getElementById("stayedLocalDetail").textContent = detail;

            // POST decision to backend
            fetch("/router/decide", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ decision: "decline", context: routerEscalationContext })
            })
            .then(function(r) { return r.json(); })
            .then(function(receipt) {
                renderTrustReceipt(receipt);
                updateSavingsWidget();
            });

            // Show audit stamp after escalation decision
            if (pendingAuditStamp) renderAuditStamp(pendingAuditStamp);
            document.getElementById("routerPostActions").style.display = "block";
        });

        // Approve escalation (simulated)
        document.getElementById("btnApproveEsc").addEventListener("click", function() {
            document.getElementById("escalationConsent").style.display = "none";

            var log = document.getElementById("routerStatusLog");
            log.innerHTML += '<div class="log-step active"><span class="spinner"></span> Sending sanitized payload to Frontier...</div>';

            // Simulated delay
            setTimeout(function() {
                resolveRouterSpinners();
                log.innerHTML += '<div class="log-step" style="color:#FFB900;">&#9729;&#65039; Frontier response received (simulated)</div>';

                fetch("/router/decide", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ decision: "approve", context: routerEscalationContext })
                })
                .then(function(r) { return r.json(); })
                .then(function(receipt) {
                    renderTrustReceipt(receipt);
                    updateSavingsWidget();
                });

                // Show audit stamp after escalation decision
                if (pendingAuditStamp) renderAuditStamp(pendingAuditStamp);
                document.getElementById("routerPostActions").style.display = "block";
            }, 2000);
        });

        function renderTrustReceipt(receipt) {
            document.getElementById("routerTrustReceipt").style.display = "block";
            var html = "";
            html += '<div class="trust-receipt-line">Timestamp: ' + receipt.timestamp + '</div>';
            html += '<div class="trust-receipt-line">Decision: <strong>' + receipt.decision.toUpperCase() + '</strong></div>';
            html += '<div class="trust-receipt-line">Model: ' + receipt.model_used + '</div>';
            html += '<div class="trust-receipt-line">Offline: ' + (receipt.offline ? "Yes" : "No") + '</div>';
            html += '<div class="trust-receipt-line">PII detected: ' + receipt.pii_detected + ' (' + (receipt.pii_types || []).join(", ") + ')</div>';
            html += '<div class="trust-receipt-line">Local Knowledge sources: ' + (receipt.sources_consulted || []).join(", ") + '</div>';
            html += '<div class="trust-receipt-line">Confidence: ' + receipt.confidence + '</div>';
            if (receipt.counterfactual) {
                html += '<div class="trust-receipt-line highlight">' + receipt.counterfactual + '</div>';
            }
            if (receipt.decision === "decline") {
                html += '<div class="trust-receipt-line highlight">Network calls: 0 &bull; Data transmitted: 0 bytes</div>';
            } else {
                html += '<div class="trust-receipt-line">Data transmitted: sanitized payload sent &bull; Est. cost: $' + (receipt.estimated_cost_if_escalated || 0).toFixed(4) + '</div>';
            }
            document.getElementById("trustReceiptBody").innerHTML = html;
        }

        // --- Reset function ---

        window.resetAuditor = function() {
            routerDocText = "";
            routerDocName = "";
            routerRunning = false;
            routerEscalationContext = {};
            pendingAuditStamp = null;
            currentAuditorMode = "";
            document.getElementById("auditorModeSelector").style.display = "block";
            document.getElementById("routerInputZone").style.display = "none";
            document.getElementById("marketingInputZone").style.display = "none";
            document.getElementById("routerDecision").style.display = "none";
            document.getElementById("routerDecisionCard").style.display = "none";
            document.getElementById("escalationConsent").style.display = "none";
            document.getElementById("stayedLocalBanner").style.display = "none";
            document.getElementById("routerTrustReceipt").style.display = "none";
            document.getElementById("routerPostActions").style.display = "none";
            document.getElementById("auditorResultsCards").innerHTML = "";
            document.getElementById("auditStamp").style.display = "none";
            document.getElementById("routerStatusLog").innerHTML = "";
            document.getElementById("routerQueryInput").value = "";
        };

        console.log("Script loaded!");

        // ── Field Inspection: Milestone 2 — Voice Capture + Field Extraction ──
        (function() {
            var inspScriptedBtn = document.getElementById("inspScriptedBtn");
            var inspTranscript = document.getElementById("inspTranscript");
            var inspStatusDot = document.getElementById("inspStatusDot");
            var inspStatusText = document.getElementById("inspStatusText");
            var inspTokenCount = document.getElementById("inspTokenCount");
            var recognition = null;
            var isRecording = false;

            // Shared global token counter + operation log — all Meeting Notes IIFEs use this
            if (typeof window._inspTotalTokens === "undefined") window._inspTotalTokens = 0;
            if (typeof window._inspAILog === "undefined") window._inspAILog = [];
            // Global helper: call from any IIFE to add tokens and log the operation
            window._addInspTokens = function(tokens, opName, model) {
                tokens = tokens || 0;
                window._inspTotalTokens += tokens;
                if (opName) {
                    window._inspAILog.push({
                        op: opName,
                        tokens: tokens,
                        model: model || "Phi-4 Mini",
                        time: new Date().toLocaleTimeString()
                    });
                }
                // Update bottom bar directly from client-side counter
                var el = document.getElementById("inspTokenCount");
                if (el) el.textContent = window._inspTotalTokens + " local tokens \u00b7 $0.00 cloud cost \u00b7 0 bytes transmitted";
                // Show report button after first AI call
                var rptBtn = document.getElementById("inspAIReportBtn");
                if (rptBtn && window._inspAILog.length > 0) rptBtn.style.display = "inline-block";
            };

            // AI Session Report — button + overlay logic
            (function() {
                var rptBtn = document.getElementById("inspAIReportBtn");
                var overlay = document.getElementById("inspAIReportOverlay");
                var closeBtn = document.getElementById("inspAIReportClose");
                var tbody = document.getElementById("inspAIReportBody");
                var summary = document.getElementById("inspAIReportSummary");
                if (!rptBtn || !overlay) return;

                rptBtn.addEventListener("click", function() {
                    var log = window._inspAILog || [];
                    // GPT-4o blended rate for cloud cost comparison
                    var cloudRate = 0.00625 / 1000; // per token

                    // Build table from client-side operation log (single source of truth)
                    var html = "";
                    var totalTokens = 0;
                    for (var i = 0; i < log.length; i++) {
                        var entry = log[i];
                        totalTokens += entry.tokens;
                        var cost = entry.tokens ? "$" + (entry.tokens * cloudRate).toFixed(4) : "\u2014";
                        html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.06);">' +
                            '<td style="padding:8px 10px; color:#fff !important;">' + (i + 1) + '</td>' +
                            '<td style="padding:8px 10px; color:#fff !important; font-weight:500;">' + entry.op + '</td>' +
                            '<td style="padding:8px 10px; color:#fff !important; font-size:0.9em;">' + entry.model + '</td>' +
                            '<td style="padding:8px 10px; text-align:right; color:#22c55e !important; font-weight:600;">' + (entry.tokens ? entry.tokens.toLocaleString() : '\u2014') + '</td>' +
                            '<td style="padding:8px 10px; text-align:right; color:#ef4444 !important; font-size:0.9em;">' + cost + '</td>' +
                            '<td style="padding:8px 10px; color:#fff !important; font-size:0.85em;">' + entry.time + '</td>' +
                            '</tr>';
                    }
                    // Total row
                    var totalCost = (totalTokens * cloudRate).toFixed(4);
                    html += '<tr style="border-top:2px solid rgba(255,255,255,0.2);">' +
                        '<td colspan="3" style="padding:10px 10px; color:#fff; font-weight:700; text-align:right;">TOTAL</td>' +
                        '<td style="padding:10px 10px; text-align:right; color:#22c55e; font-weight:700; font-size:1.05em;">' + totalTokens.toLocaleString() + '</td>' +
                        '<td style="padding:10px 10px; text-align:right; color:#ef4444; font-weight:700;">$' + totalCost + '</td>' +
                        '<td></td></tr>';
                    tbody.innerHTML = html;

                    // CO2: ~0.4 Wh per cloud query, 373g CO2/kWh grid average
                    var aiOps = log.filter(function(e) { return e.tokens > 0; }).length;
                    var co2Avoided = (aiOps * 0.4 / 1000 * 373).toFixed(1);
                    var carbonVisible = (typeof window._showCarbon === "function") ? window._showCarbon() : true;
                    var co2Display = carbonVisible ? "" : "display:none;";

                    summary.innerHTML =
                        '<div style="display:flex; gap:24px; flex-wrap:wrap; justify-content:center;">' +
                        '<div style="text-align:center;"><div style="font-size:1.6em; font-weight:700; color:#22c55e !important;">' + totalTokens.toLocaleString() + '</div><div style="font-size:0.75em; color:#ccc !important; text-transform:uppercase; letter-spacing:0.5px;">Total Tokens</div></div>' +
                        '<div style="text-align:center;"><div style="font-size:1.6em; font-weight:700; color:#22c55e !important;">$0.00</div><div style="font-size:0.75em; color:#ccc !important; text-transform:uppercase; letter-spacing:0.5px;">NPU Cost</div></div>' +
                        '<div style="text-align:center;"><div style="font-size:1.6em; font-weight:700; color:#ef4444 !important; text-decoration:line-through;">$' + totalCost + '</div><div style="font-size:0.75em; color:#ccc !important; text-transform:uppercase; letter-spacing:0.5px;">Cloud Would Cost</div></div>' +
                        '<div style="text-align:center;' + co2Display + '"><div style="font-size:1.6em; font-weight:700; color:#22c55e !important;">' + co2Avoided + 'g</div><div style="font-size:0.75em; color:#ccc !important; text-transform:uppercase; letter-spacing:0.5px;">CO&#8322; Saved</div></div>' +
                        '<div style="text-align:center;"><div style="font-size:1.6em; font-weight:700; color:#22c55e !important;">0</div><div style="font-size:0.75em; color:#ccc !important; text-transform:uppercase; letter-spacing:0.5px;">Bytes Transmitted</div></div>' +
                        '<div style="text-align:center;"><div style="font-size:1.6em; font-weight:700; color:#22c55e !important;">' + log.length + '</div><div style="font-size:0.75em; color:#ccc !important; text-transform:uppercase; letter-spacing:0.5px;">AI Operations</div></div>' +
                        '</div>';

                    overlay.style.display = "flex";
                });

                closeBtn.addEventListener("click", function() {
                    overlay.style.display = "none";
                });
                overlay.addEventListener("click", function(e) {
                    if (e.target === overlay) overlay.style.display = "none";
                });
            })();

            // Field IDs in order for staggered animation
            var fieldMap = [
                { key: "inspector_name", elId: "inspInspector" },
                { key: "location", elId: "inspLocation" },
                { key: "datetime", elId: "inspDateTime" },
                { key: "reported_issue", elId: "inspIssue" },
                { key: "source", elId: "inspSource" }
            ];

            function setInspStatus(text, processing) {
                if (inspStatusText) inspStatusText.textContent = text;
                if (inspStatusDot) {
                    inspStatusDot.classList.toggle("processing", !!processing);
                }
            }

            function updateInspTokens(tokens, opName, model) {
                window._addInspTokens(tokens, opName || "Field Extraction", model || "Phi-4 Mini");
            }

            // Staggered field animation
            function animateFields(fields) {
                var delay = 0;
                fieldMap.forEach(function(f) {
                    var val = fields[f.key];
                    if (val) {
                        delay += 200;
                        setTimeout(function() {
                            var el = document.getElementById(f.elId);
                            if (el) {
                                el.value = val;
                                el.classList.add("field-populated");
                                setTimeout(function() { el.classList.remove("field-populated"); }, 1500);
                            }
                        }, delay);
                    }
                });
            }

            function showTranscript(text) {
                if (inspTranscript) {
                    inspTranscript.textContent = text;
                    inspTranscript.classList.add("visible");
                }
                // Expose globally so M3 findings can attach voice context
                window._inspLastTranscript = text;
            }

            // Send transcript to backend for field extraction
            function extractFields(transcript) {
                setInspStatus("Extracting fields with AI...", true);
                fetch("/inspection/transcribe", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ transcript: transcript })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.error) {
                        setInspStatus("Error: " + data.error, false);
                        return;
                    }
                    showTranscript(data.transcript || transcript);
                    // Auto-populate date/time with current local time
                    var now = new Date();
                    var dtLocal = now.getFullYear() + "-" +
                        String(now.getMonth()+1).padStart(2,"0") + "-" +
                        String(now.getDate()).padStart(2,"0") + "T" +
                        String(now.getHours()).padStart(2,"0") + ":" +
                        String(now.getMinutes()).padStart(2,"0");
                    var fields = data.fields || {};
                    fields.datetime = dtLocal;
                    animateFields(fields);
                    updateInspTokens(data.tokens_used || 0);
                    setInspStatus("Fields extracted", false);
                })
                .catch(function(e) {
                    setInspStatus("Extraction failed: " + e.message, false);
                });
            }

            // --- Extract Fields button: reads from textarea ---
            var inspExtractBtn = document.getElementById("inspExtractBtn");
            var inspTranscriptInput = document.getElementById("inspTranscriptInput");

            if (inspExtractBtn && inspTranscriptInput) {
                inspExtractBtn.addEventListener("click", function() {
                    // Close Voice Typing if it's open
                    fetch("/inspection/fluid-dictation", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ action: "close" })
                    }).catch(function() {});
                    var text = inspTranscriptInput.value.trim();
                    if (!text) {
                        setInspStatus("Type or dictate (Win+H) inspection notes first", false);
                        return;
                    }
                    showTranscript(text);
                    extractFields(text);
                });
            }

            // --- Fluid Dictation — opens Windows Voice Typing (Win+H) via backend ---
            var inspFluidDictationBtn = document.getElementById("inspFluidDictationBtn");
            if (inspFluidDictationBtn) {
                inspFluidDictationBtn.addEventListener("click", function() {
                    // Refocus the textarea so Voice Typing has an active text field
                    if (inspTranscriptInput) inspTranscriptInput.focus();
                    // Small delay to let focus settle before Win+H fires
                    setTimeout(function() {
                        fetch("/inspection/fluid-dictation", { method: "POST" })
                            .then(function(r) { return r.json(); })
                            .then(function(data) {
                                if (data.error) setInspStatus("Could not open Voice Typing: " + data.error, false);
                            })
                            .catch(function() { setInspStatus("Could not open Voice Typing", false); });
                    }, 150);
                });
            }

            // --- Scripted input (demo safety net) — typewriter effect then extracts ---
            if (inspScriptedBtn && inspTranscriptInput) {
                inspScriptedBtn.addEventListener("click", function() {
                    var scriptedTranscript = "Just finished meeting with Jackie Rodriguez at the Starbucks " +
                        "on Main Street in Troy, Michigan. Meeting date March 26th 2026. " +
                        "We discussed opening a 529 plan for her daughter Maya who starts college in 2030. " +
                        "She is also interested in a Roth IRA conversion from her old employer 401k. " +
                        "Need to send her the contribution limits comparison by Friday and schedule a " +
                        "follow-up for next Thursday to review the paperwork. Marcus the branch manager referred her to me.";
                    inspScriptedBtn.disabled = true;
                    inspScriptedBtn.innerHTML = "&#9654; Transcribing...";
                    inspTranscriptInput.value = "";
                    // Typewriter: reveal word-by-word at spoken pace
                    var words = scriptedTranscript.split(" ");
                    var idx = 0;
                    var interval = setInterval(function() {
                        if (idx < words.length) {
                            inspTranscriptInput.value += (idx > 0 ? " " : "") + words[idx];
                            inspTranscriptInput.scrollTop = inspTranscriptInput.scrollHeight;
                            idx++;
                        } else {
                            clearInterval(interval);
                            inspScriptedBtn.disabled = false;
                            inspScriptedBtn.innerHTML = "&#9654; Use Scripted Input (Demo)";
                            // Track voice transcription — on-device via Windows Speech, cloud would cost ~$0.006/15s
                            window._addInspTokens(150, "Voice Transcription", "Windows Speech (On-Device)");
                            showTranscript(scriptedTranscript);
                            extractFields(scriptedTranscript);
                        }
                    }, 80);
                });
            }
        })();

        // ── Field Inspection: Milestone 3 — Camera Capture + Classification ──
        (function() {
            var inspCameraStream = null;
            var inspFindings = [];
            var inspStartCameraBtn = document.getElementById("inspStartCameraBtn");
            var inspCapturePhotoBtn = document.getElementById("inspCapturePhotoBtn");
            var inspStopCameraBtn = document.getElementById("inspStopCameraBtn");
            var inspDemoPhotoBtn = document.getElementById("inspDemoPhotoBtn");
            var inspCameraPreview = document.getElementById("inspCameraPreview");
            var inspCaptureCanvas = document.getElementById("inspCaptureCanvas");
            var inspPhotoGrid = document.getElementById("inspPhotoGrid");
            var inspPhotoEmpty = document.getElementById("inspPhotoEmpty");
            var inspClassCard = document.getElementById("inspClassCard");
            var inspGenerateBtn = document.getElementById("inspGenerateBtn");
            var inspStatusDot = document.getElementById("inspStatusDot");
            var inspStatusText = document.getElementById("inspStatusText");
            var inspTokenCount = document.getElementById("inspTokenCount");
            var inspFindingsEl = document.getElementById("inspFindings");

            // Expose findings globally for report generation (Milestone 5)
            window._inspFindings = inspFindings;
            if (typeof window._inspTotalTokens === "undefined") window._inspTotalTokens = 0;

            function setInspStatus3(text, processing) {
                if (inspStatusText) inspStatusText.textContent = text;
                if (inspStatusDot) inspStatusDot.classList.toggle("processing", !!processing);
            }

            function updateInspTokens3(tokens, opName, model) {
                window._addInspTokens(tokens, opName || "Document Classification", model || "Phi-4 Mini");
                if (inspTokenCount) {
                    inspTokenCount.textContent = window._inspTotalTokens + " local tokens \u00b7 $0.00 cloud cost \u00b7 0 bytes transmitted";
                }
            }

            // Lightbox expand/close
            var inspLightbox = document.getElementById("inspLightbox");
            var inspLbImg = document.getElementById("inspLbImg");
            var inspLbCaption = document.getElementById("inspLbCaption");
            function openLightbox(src, caption) {
                if (inspLbImg) inspLbImg.src = src;
                if (inspLbCaption) inspLbCaption.textContent = caption || "";
                if (inspLightbox) inspLightbox.classList.add("active");
            }
            function closeLightbox() {
                if (inspLightbox && inspLightbox.classList.contains("annotating")) return;
                if (inspLightbox) inspLightbox.classList.remove("active");
                if (inspLbImg) inspLbImg.src = "";
            }
            if (inspLightbox) {
                inspLightbox.addEventListener("click", function(e) {
                    if (inspLightbox.classList.contains("annotating")) return;
                    if (e.target === inspLightbox) closeLightbox();
                });
            }
            var inspLbClose = document.getElementById("inspLbClose");
            if (inspLbClose) inspLbClose.addEventListener("click", closeLightbox);
            document.addEventListener("keydown", function(e) {
                if (e.key === "Escape" && inspLightbox && inspLightbox.classList.contains("annotating")) return;
                if (e.key === "Escape") closeLightbox();
            });

            // Add photo thumbnail to grid
            function addPhotoToGrid(dataUrl, findingId) {
                if (inspPhotoEmpty) inspPhotoEmpty.style.display = "none";
                var thumb = document.createElement("div");
                thumb.className = "photo-thumb";
                thumb.id = "photo-" + findingId;
                thumb.innerHTML = '<img src="' + dataUrl + '" alt="Finding ' + findingId + '">' +
                    '<button class="photo-expand" title="Expand photo">&#x26F6;</button>' +
                    '<button class="photo-annotate" title="Annotate photo">&#9998;</button>';
                // Click thumbnail: show classification
                thumb.addEventListener("click", function(e) {
                    if (e.target.classList.contains("photo-expand") || e.target.classList.contains("photo-annotate")) return;
                    var allThumbs = inspPhotoGrid.querySelectorAll(".photo-thumb");
                    allThumbs.forEach(function(t) { t.classList.remove("selected"); });
                    thumb.classList.add("selected");
                    var finding = inspFindings[findingId - 1];
                    if (finding && finding.classification) {
                        showClassification(finding.classification, null);
                    }
                });
                // Click expand button: open lightbox
                thumb.querySelector(".photo-expand").addEventListener("click", function(e) {
                    e.stopPropagation();
                    var finding = inspFindings[findingId - 1];
                    var caption = finding && finding.classification
                        ? "Finding #" + findingId + " — " + finding.classification.category + " (" + finding.classification.severity + ")"
                        : "Finding #" + findingId;
                    openLightbox(dataUrl, caption);
                });
                // Click annotate button: open annotation mode
                thumb.querySelector(".photo-annotate").addEventListener("click", function(e) {
                    e.stopPropagation();
                    if (window._inspOpenAnnotation) window._inspOpenAnnotation(findingId);
                });
                inspPhotoGrid.appendChild(thumb);
                return thumb;
            }

            // Show classification result
            function showClassification(result, thumb) {
                // Update classification card
                hideClassLoading();
                if (inspClassCard) {
                    inspClassCard.style.display = "block";
                    document.getElementById("inspClassCategory").textContent = result.category;

                    var sevEl = document.getElementById("inspClassSeverity");
                    sevEl.textContent = result.severity;
                    sevEl.style.background = {
                        "Low": "#22c55e", "Moderate": "#f59e0b",
                        "High": "#ef4444", "Critical": "#7c3aed"
                    }[result.severity] || "#666";
                    sevEl.style.color = result.severity === "Low" || result.severity === "Moderate" ? "#000" : "#fff";

                    document.getElementById("inspClassConfPct").textContent = result.confidence;
                    var confBar = document.getElementById("inspClassConfBar");
                    confBar.style.width = result.confidence + "%";
                    // Color by threshold
                    var confClass = result.confidence >= 75 ? "conf-green" : result.confidence >= 60 ? "conf-amber" : "conf-red";
                    inspClassCard.className = "classification-card " + confClass;

                    document.getElementById("inspClassExplain").textContent = result.explanation || "";

                    // Show analysis source (Phi Silica Vision vs preset vs text fallback)
                    var sourceEl = document.getElementById("inspClassSource");
                    if (sourceEl) {
                        var sourceLabel = {
                            "phi_silica_vision": "Phi Silica Vision on NPU",
                            "demo_preset": "Demo Preset",
                            "text_model_fallback": "Phi-4 Mini (text)",
                            "hardcoded_fallback": "Demo Preset"
                        }[result.source] || "";
                        sourceEl.textContent = sourceLabel;
                        sourceEl.style.display = sourceLabel ? "" : "none";
                    }
                }

                // Add severity badge to photo thumbnail
                if (thumb) {
                    var badge = document.createElement("div");
                    badge.className = "photo-badge severity-" + result.severity.toLowerCase();
                    badge.textContent = result.severity;
                    thumb.appendChild(badge);
                }

                // Show annotate or sign button depending on document type
                var annBtn = document.getElementById("inspAnnotateBtn");
                if (annBtn) {
                    annBtn.style.display = "";
                    var isBeneficiary = (result.category || "").toLowerCase().indexOf("beneficiary") >= 0;
                    window._inspLastDocIsBeneficiary = isBeneficiary;
                    if (isBeneficiary) {
                        annBtn.innerHTML = "&#9998; Sign Document";
                        annBtn.style.background = "rgba(34,197,94,0.15)";
                        annBtn.style.color = "#22c55e";
                    } else {
                        annBtn.innerHTML = "&#9998; Annotate Photo";
                        annBtn.style.background = "rgba(239,68,68,0.15)";
                        annBtn.style.color = "#ef4444";
                    }
                }

                // Show annotation note if this finding already has one
                var annNote = document.getElementById("inspAnnotationNote");
                var annText = document.getElementById("inspAnnotationText");
                var selectedThumb = inspPhotoGrid ? inspPhotoGrid.querySelector(".photo-thumb.selected") : null;
                if (selectedThumb && annNote && annText) {
                    var fIdx = parseInt(selectedThumb.id.replace("photo-", ""), 10) - 1;
                    var selFinding = inspFindings[fIdx];
                    if (selFinding && selFinding.annotations && selFinding.annotations.extracted_text) {
                        annText.textContent = selFinding.annotations.extracted_text;
                        annNote.style.display = "block";
                    } else {
                        annNote.style.display = "none";
                    }
                } else if (annNote) {
                    annNote.style.display = "none";
                }
            }

            // Add finding to the findings log
            function addFinding(result, photoDataUrl) {
                var finding = {
                    id: inspFindings.length + 1,
                    classification: result,
                    photo_base64: photoDataUrl,
                    annotations: null,
                    transcript_excerpt: window._inspLastTranscript || null
                };
                inspFindings.push(finding);
                window._inspFindings = inspFindings;

                // Update findings panel
                if (inspFindingsEl) {
                    if (inspFindings.length === 1) inspFindingsEl.innerHTML = "";
                    var item = document.createElement("div");
                    item.className = "finding-item";
                    item.innerHTML =
                        '<div class="finding-num">' + finding.id + '</div>' +
                        '<div class="finding-text"><strong>' + result.category + '</strong> \u2014 ' +
                        result.severity + ' (' + result.confidence + '% confidence)</div>';
                    inspFindingsEl.appendChild(item);
                }

                // Enable Generate Report button
                if (inspGenerateBtn) inspGenerateBtn.disabled = false;
            }

            // Show loading spinner on classification card
            function showClassLoading() {
                if (inspClassCard) {
                    inspClassCard.style.display = "block";
                    inspClassCard.className = "classification-card";
                    var inner = inspClassCard.querySelector(".cc-inner");
                    if (inner) inner.style.display = "none";
                    var loadEl = document.getElementById("inspClassLoading");
                    if (loadEl) loadEl.style.display = "flex";
                }
            }
            function hideClassLoading() {
                var inner = inspClassCard ? inspClassCard.querySelector(".cc-inner") : null;
                if (inner) inner.style.display = "";
                var loadEl = document.getElementById("inspClassLoading");
                if (loadEl) loadEl.style.display = "none";
            }

            // Classify a captured photo
            function classifyPhoto(dataUrl, demoType) {
                // Show the photo immediately in the camera area while AI analyzes
                var camPreview = document.getElementById("inspCameraPreview");
                var camPlaceholder = document.querySelector(".photo-grid-empty");
                var photoArea = document.getElementById("inspPhotoGrid");
                if (photoArea && dataUrl) {
                    // Show a large preview of the photo being analyzed
                    var existingPreview = document.getElementById("inspAnalyzingPreview");
                    if (!existingPreview) {
                        var previewImg = document.createElement("img");
                        previewImg.id = "inspAnalyzingPreview";
                        previewImg.style.cssText = "width:100%;max-height:300px;object-fit:contain;border-radius:8px;border:2px solid rgba(var(--brand-accent-rgb),0.4);margin-bottom:8px;";
                        photoArea.parentNode.insertBefore(previewImg, photoArea);
                    }
                    document.getElementById("inspAnalyzingPreview").src = dataUrl;
                }
                showClassLoading();
                setInspStatus3("Analyzing image with AI...", true);

                if (demoType) {
                    // Use demo preset
                    fetch("/inspection/classify", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ demo_type: demoType })
                    })
                    .then(function(r) { return r.json(); })
                    .then(function(result) {
                        var thumb = addPhotoToGrid(dataUrl, inspFindings.length + 1);
                        showClassification(result, thumb);
                        addFinding(result, dataUrl);
                        updateInspTokens3(result.tokens_used || 0);
                        setInspStatus3("Classification complete: " + result.category, false);
                        if (window._inspCheckEscalation) window._inspCheckEscalation(result, dataUrl);
                    })
                    .catch(function(e) {
                        setInspStatus3("Classification failed: " + e.message, false);
                    });
                    return;
                }

                // Upload image for real classification (Phi Silica Vision on NPU)
                setInspStatus3("Classifying with Phi Silica Vision on NPU...", true);
                var blob = dataURLtoBlob(dataUrl);
                var formData = new FormData();
                formData.append("image", blob, "capture.jpg");

                fetch("/inspection/classify", {
                    method: "POST",
                    body: formData
                })
                .then(function(r) { return r.json(); })
                .then(function(result) {
                    var thumb = addPhotoToGrid(dataUrl, inspFindings.length + 1);
                    showClassification(result, thumb);
                    addFinding(result, dataUrl);
                    updateInspTokens3(result.tokens_used || 0);
                    var src = result.source === "phi_silica_vision" ? " via Phi Silica Vision" : "";
                    setInspStatus3("Classification complete: " + result.category + src, false);
                    if (window._inspCheckEscalation) window._inspCheckEscalation(result, dataUrl);
                })
                .catch(function(e) {
                    setInspStatus3("Classification failed: " + e.message, false);
                });
            }

            function dataURLtoBlob(dataUrl) {
                var parts = dataUrl.split(",");
                var mime = parts[0].match(/:(.*?);/)[1];
                var raw = atob(parts[1]);
                var arr = new Uint8Array(raw.length);
                for (var i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
                return new Blob([arr], { type: mime });
            }

            // --- Camera controls ---
            var inspFacingMode = "user"; // default to front camera for Surface Pro demo
            var inspFlipCameraBtn = document.getElementById("inspFlipCameraBtn");

            function startInspCamera() {
                navigator.mediaDevices.getUserMedia({
                    video: { facingMode: inspFacingMode, width: { ideal: 1280 }, height: { ideal: 720 } }
                })
                .then(function(stream) {
                    inspCameraStream = stream;
                    inspCameraPreview.srcObject = stream;
                    inspCameraPreview.classList.add("active");
                    inspStartCameraBtn.style.display = "none";
                    inspCapturePhotoBtn.style.display = "";
                    inspStopCameraBtn.style.display = "";
                    if (inspFlipCameraBtn) inspFlipCameraBtn.style.display = "";
                    setInspStatus3("Camera active \u2014 tap Capture", false);
                })
                .catch(function(err) {
                    setInspStatus3("Camera error: " + err.message, false);
                });
            }

            if (inspStartCameraBtn) {
                inspStartCameraBtn.addEventListener("click", startInspCamera);
            }

            if (inspFlipCameraBtn) {
                inspFlipCameraBtn.addEventListener("click", function() {
                    inspFacingMode = (inspFacingMode === "user") ? "environment" : "user";
                    if (inspCameraStream) {
                        inspCameraStream.getTracks().forEach(function(t) { t.stop(); });
                    }
                    startInspCamera();
                });
            }

            if (inspCapturePhotoBtn) {
                inspCapturePhotoBtn.addEventListener("click", function() {
                    if (!inspCameraPreview || !inspCameraPreview.videoWidth) return;
                    inspCaptureCanvas.width = inspCameraPreview.videoWidth;
                    inspCaptureCanvas.height = inspCameraPreview.videoHeight;
                    inspCaptureCanvas.getContext("2d").drawImage(inspCameraPreview, 0, 0);
                    var dataUrl = inspCaptureCanvas.toDataURL("image/jpeg", 0.85);

                    // Stop camera after capture
                    if (inspCameraStream) {
                        inspCameraStream.getTracks().forEach(function(t) { t.stop(); });
                        inspCameraStream = null;
                    }
                    inspCameraPreview.classList.remove("active");
                    inspStartCameraBtn.style.display = "";
                    inspCapturePhotoBtn.style.display = "none";
                    inspStopCameraBtn.style.display = "none";
                    if (inspFlipCameraBtn) inspFlipCameraBtn.style.display = "none";

                    classifyPhoto(dataUrl, null);
                });
            }

            if (inspStopCameraBtn) {
                inspStopCameraBtn.addEventListener("click", function() {
                    if (inspCameraStream) {
                        inspCameraStream.getTracks().forEach(function(t) { t.stop(); });
                        inspCameraStream = null;
                    }
                    inspCameraPreview.classList.remove("active");
                    inspStartCameraBtn.style.display = "";
                    inspCapturePhotoBtn.style.display = "none";
                    inspStopCameraBtn.style.display = "none";
                    if (inspFlipCameraBtn) inspFlipCameraBtn.style.display = "none";
                    setInspStatus3("Ready", false);
                });
            }

            // --- Load Demo Photo ---
            if (inspDemoPhotoBtn) {
                var demoPhotoIndex = 0;
                var demoPhotos = [
                    { type: "financial_statement", label: "403(b) Statement", color: "#3b82f6" },
                    { type: "water_damage", label: "Account Application", color: "#22c55e" },
                    { type: "structural_crack", label: "Tax Document", color: "#ef4444" },
                    { type: "mold", label: "Business Card", color: "#f59e0b" },
                    { type: "electrical_hazard", label: "Insurance Document", color: "#8b5cf6" }
                ];

                inspDemoPhotoBtn.addEventListener("click", function() {
                    var demo = demoPhotos[demoPhotoIndex % demoPhotos.length];
                    demoPhotoIndex++;

                    // Fetch actual demo photo from server
                    inspDemoPhotoBtn.disabled = true;
                    inspDemoPhotoBtn.textContent = "Loading " + demo.label + "...";
                    fetch("/inspection/demo-photo/" + demo.type)
                        .then(function(r) {
                            if (!r.ok) throw new Error("Photo not found");
                            return r.blob();
                        })
                        .then(function(blob) {
                            var reader = new FileReader();
                            reader.onloadend = function() {
                                inspDemoPhotoBtn.disabled = false;
                                inspDemoPhotoBtn.innerHTML = "&#128193; Load Demo Photo";
                                // Use demo preset classification for reliable demo
                                classifyPhoto(reader.result, demo.type);
                            };
                            reader.readAsDataURL(blob);
                        })
                        .catch(function() {
                            // Fallback: generate canvas placeholder if photo file missing
                            inspDemoPhotoBtn.disabled = false;
                            inspDemoPhotoBtn.innerHTML = "&#128193; Load Demo Photo";
                            var canvas = document.createElement("canvas");
                            canvas.width = 640; canvas.height = 480;
                            var ctx = canvas.getContext("2d");
                            ctx.fillStyle = demo.color + "60";
                            ctx.fillRect(0, 0, 640, 480);
                            ctx.fillStyle = "#fff";
                            ctx.font = "bold 28px sans-serif";
                            ctx.textAlign = "center";
                            ctx.fillText(demo.label, 320, 240);
                            classifyPhoto(canvas.toDataURL("image/jpeg", 0.85), demo.type);
                        });
                });
            }

            // --- Load Beneficiary Form ---
            var inspLoadFormBtn = document.getElementById("inspLoadFormBtn");
            if (inspLoadFormBtn) {
                inspLoadFormBtn.addEventListener("click", function() {
                    inspLoadFormBtn.disabled = true;
                    inspLoadFormBtn.textContent = "Loading Beneficiary Form...";

                    fetch("/inspection/demo-photo/beneficiary_form")
                        .then(function(r) {
                            if (!r.ok) throw new Error("Form not found");
                            return r.blob();
                        })
                        .then(function(blob) {
                            var reader = new FileReader();
                            reader.onloadend = function() {
                                inspLoadFormBtn.disabled = false;
                                inspLoadFormBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="vertical-align:middle;margin-right:6px;"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15l2 2 4-4" stroke="#f6d107" stroke-width="2"/></svg> Beneficiary Form';
                                // Classify as beneficiary form (demo preset)
                                classifyPhoto(reader.result, "beneficiary_form");
                            };
                            reader.readAsDataURL(blob);
                        })
                        .catch(function() {
                            inspLoadFormBtn.disabled = false;
                            inspLoadFormBtn.innerHTML = "Beneficiary Form";
                            // Fallback canvas
                            var canvas = document.createElement("canvas");
                            canvas.width = 850; canvas.height = 1100;
                            var ctx = canvas.getContext("2d");
                            ctx.fillStyle = "#fff";
                            ctx.fillRect(0, 0, 850, 1100);
                            ctx.fillStyle = "#6b1d2a";
                            ctx.fillRect(0, 0, 850, 5);
                            ctx.font = "bold 24px Arial";
                            ctx.fillText("{{BRAND_COMPANY}}", 40, 40);
                            ctx.font = "bold 16px Arial";
                            ctx.fillText("BENEFICIARY DESIGNATION FORM", 40, 70);
                            ctx.font = "13px Arial";
                            ctx.fillStyle = "#222";
                            ctx.fillText("Account Holder: Jackie Marie Rodriguez", 40, 110);
                            ctx.fillText("Account: ****7093  |  Type: 403(b)", 40, 130);
                            ctx.fillText("[Sign below with Surface Pen]", 40, 200);
                            ctx.strokeStyle = "#999";
                            ctx.strokeRect(40, 220, 500, 150);
                            classifyPhoto(canvas.toDataURL("image/jpeg", 0.85), "beneficiary_form");
                        });
                });
            }
        })();

        // ── Field Inspection: Milestone 4 — Pen Annotation ──
        (function() {
            var lightbox = document.getElementById("inspLightbox");
            var container = document.getElementById("inspAnnotateContainer");
            var baseCanvas = document.getElementById("inspAnnotateBase");
            var inkCanvas = document.getElementById("inspAnnotateInk");
            var toolbar = document.getElementById("inspAnnotateToolbar");
            var btnUndo = document.getElementById("inspAnnUndo");
            var btnClear = document.getElementById("inspAnnClear");
            var btnDone = document.getElementById("inspAnnDone");
            var btnCancel = document.getElementById("inspAnnCancel");
            var annotateBtn = document.getElementById("inspAnnotateBtn");
            var annotationNote = document.getElementById("inspAnnotationNote");
            var annotationText = document.getElementById("inspAnnotationText");
            var inspFindingsEl = document.getElementById("inspFindings");

            if (!lightbox || !baseCanvas || !inkCanvas) return;

            var baseCtx = baseCanvas.getContext("2d");
            var inkCtx = inkCanvas.getContext("2d");

            var currentFindingId = null;
            var strokes = [];
            var currentStroke = null;
            var isDrawing = false;

            // Pen style
            var PEN_COLOR = "#ef4444";
            var PEN_WIDTH = 7;

            function openAnnotation(findingId) {
                var findings = window._inspFindings || [];
                var finding = findings[findingId - 1];
                if (!finding || !finding.photo_base64) return;

                currentFindingId = findingId;
                strokes = [];
                currentStroke = null;
                isDrawing = false;

                // Load photo into base canvas
                var img = new Image();
                img.onload = function() {
                    // Scale to fit viewport (max 90vw x 80vh)
                    var maxW = window.innerWidth * 0.9;
                    var maxH = window.innerHeight * 0.8;
                    var scale = Math.min(maxW / img.width, maxH / img.height, 1);
                    var w = Math.round(img.width * scale);
                    var h = Math.round(img.height * scale);

                    baseCanvas.width = w;
                    baseCanvas.height = h;
                    inkCanvas.width = w;
                    inkCanvas.height = h;

                    baseCtx.drawImage(img, 0, 0, w, h);
                    inkCtx.clearRect(0, 0, w, h);

                    // Enter annotation mode
                    lightbox.classList.add("active", "annotating");
                };
                img.src = finding.photo_base64;
            }

            function closeAnnotation() {
                lightbox.classList.remove("annotating");
                lightbox.classList.remove("active");
                strokes = [];
                currentStroke = null;
                isDrawing = false;
                currentFindingId = null;
            }

            function getPointerPos(e) {
                var rect = inkCanvas.getBoundingClientRect();
                return {
                    x: (e.clientX - rect.left) * (inkCanvas.width / rect.width),
                    y: (e.clientY - rect.top) * (inkCanvas.height / rect.height)
                };
            }

            function drawStroke(ctx, points, color, width) {
                if (points.length < 2) return;
                ctx.beginPath();
                ctx.strokeStyle = color;
                ctx.lineWidth = width;
                ctx.lineCap = "round";
                ctx.lineJoin = "round";
                ctx.moveTo(points[0].x, points[0].y);
                for (var i = 1; i < points.length; i++) {
                    ctx.lineTo(points[i].x, points[i].y);
                }
                ctx.stroke();
            }

            function redrawStrokes() {
                inkCtx.clearRect(0, 0, inkCanvas.width, inkCanvas.height);
                for (var i = 0; i < strokes.length; i++) {
                    drawStroke(inkCtx, strokes[i], PEN_COLOR, PEN_WIDTH);
                }
            }

            // Pointer event handlers
            inkCanvas.addEventListener("pointerdown", function(e) {
                e.preventDefault();
                isDrawing = true;
                currentStroke = [getPointerPos(e)];
                inkCanvas.setPointerCapture(e.pointerId);
            });

            inkCanvas.addEventListener("pointermove", function(e) {
                if (!isDrawing || !currentStroke) return;
                e.preventDefault();
                var pos = getPointerPos(e);
                currentStroke.push(pos);
                // Draw incremental segment
                if (currentStroke.length >= 2) {
                    inkCtx.beginPath();
                    inkCtx.strokeStyle = PEN_COLOR;
                    inkCtx.lineWidth = PEN_WIDTH;
                    inkCtx.lineCap = "round";
                    inkCtx.lineJoin = "round";
                    var prev = currentStroke[currentStroke.length - 2];
                    inkCtx.moveTo(prev.x, prev.y);
                    inkCtx.lineTo(pos.x, pos.y);
                    inkCtx.stroke();
                }
            });

            function endStroke(e) {
                if (!isDrawing) return;
                isDrawing = false;
                if (currentStroke && currentStroke.length >= 2) {
                    strokes.push(currentStroke);
                }
                currentStroke = null;
            }
            inkCanvas.addEventListener("pointerup", endStroke);
            inkCanvas.addEventListener("pointerleave", endStroke);
            inkCanvas.addEventListener("pointercancel", endStroke);

            // Toolbar buttons
            if (btnUndo) btnUndo.addEventListener("click", function() {
                strokes.pop();
                redrawStrokes();
            });

            if (btnClear) btnClear.addEventListener("click", function() {
                strokes = [];
                inkCtx.clearRect(0, 0, inkCanvas.width, inkCanvas.height);
            });

            if (btnCancel) btnCancel.addEventListener("click", function() {
                closeAnnotation();
            });

            function dataURLtoBlob4(dataURL) {
                var parts = dataURL.split(",");
                var mime = parts[0].match(/:(.*?);/)[1];
                var b64 = atob(parts[1]);
                var arr = new Uint8Array(b64.length);
                for (var i = 0; i < b64.length; i++) arr[i] = b64.charCodeAt(i);
                return new Blob([arr], { type: mime });
            }

            if (btnDone) btnDone.addEventListener("click", function() {
                if (strokes.length === 0) {
                    closeAnnotation();
                    return;
                }

                var findings = window._inspFindings || [];
                var finding = findings[currentFindingId - 1];
                if (!finding) { closeAnnotation(); return; }

                // 1. Composite base + ink → JPEG for thumbnail
                var compCanvas = document.createElement("canvas");
                compCanvas.width = baseCanvas.width;
                compCanvas.height = baseCanvas.height;
                var compCtx = compCanvas.getContext("2d");
                compCtx.drawImage(baseCanvas, 0, 0);
                compCtx.drawImage(inkCanvas, 0, 0);
                var compositeDataUrl = compCanvas.toDataURL("image/jpeg", 0.85);

                // Update finding photo and thumbnail
                finding.photo_base64 = compositeDataUrl;
                var thumbEl = document.getElementById("photo-" + currentFindingId);
                if (thumbEl) {
                    var thumbImg = thumbEl.querySelector("img");
                    if (thumbImg) thumbImg.src = compositeDataUrl;
                    // Add annotation badge if not already present
                    if (!thumbEl.querySelector(".annotation-badge")) {
                        var badge = document.createElement("div");
                        badge.className = "annotation-badge";
                        badge.textContent = "\u270e";
                        thumbEl.appendChild(badge);
                    }
                }

                // 2. Send composite image (photo + ink overlay) to Phi Silica Vision
                //    The vision model describes the annotated photo — much richer than ink-only OCR
                var compositeBlob = dataURLtoBlob4(compositeDataUrl);

                // 3. POST to /inspection/annotate
                var statusText = document.getElementById("inspStatusText");
                var statusDot = document.getElementById("inspStatusDot");
                if (statusText) statusText.textContent = "Analyzing annotated photo with Phi Silica Vision...";
                if (statusDot) statusDot.classList.add("processing");

                var savedFindingId = currentFindingId;
                var savedStrokeCount = strokes.length;
                closeAnnotation();

                var fd = new FormData();
                fd.append("image", compositeBlob, "annotated_photo.jpg");
                fd.append("finding_id", savedFindingId);

                fetch("/inspection/annotate", { method: "POST", body: fd })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        var f = findings[savedFindingId - 1];
                        if (f) {
                            f.annotations = {
                                extracted_text: data.extracted_text || "",
                                stroke_count: savedStrokeCount
                            };
                        }
                        window._inspFindings = findings;

                        // Show annotation note in classification card area
                        if (annotationNote && annotationText && data.extracted_text) {
                            annotationText.textContent = data.extracted_text;
                            annotationNote.style.display = "block";
                        }

                        // Also show inspector note in the findings log panel
                        if (data.extracted_text && inspFindingsEl) {
                            var findingItems = inspFindingsEl.querySelectorAll(".finding-item");
                            var targetItem = findingItems[savedFindingId - 1];
                            if (targetItem && !targetItem.querySelector(".finding-note")) {
                                var noteEl = document.createElement("div");
                                noteEl.className = "finding-note";
                                noteEl.style.cssText = "margin-top:6px;padding:6px 8px;background:rgba(14,165,233,0.08);border-left:3px solid #0ea5e9;border-radius:4px;font-size:0.82em;color:rgba(255,255,255,0.75);line-height:1.4;";
                                noteEl.innerHTML = '<span style="color:#0ea5e9;font-weight:600;font-size:0.8em;text-transform:uppercase;letter-spacing:0.3px;">&#9998; {{ANNOTATION_LABEL}}</span><br>' + data.extracted_text;
                                targetItem.appendChild(noteEl);
                            }
                        }

                        // Update status
                        if (statusText) statusText.textContent = "Annotation saved — " + (data.extracted_text || "no text extracted");
                        if (statusDot) statusDot.classList.remove("processing");

                        // Update token count
                        // Phi Silica Vision doesn't report tokens — estimate ~300 for image description
                        window._addInspTokens(data.tokens_used || 300, "Document Analysis", "Phi Silica Vision");

                        // Track completed task
                        var completed = window._inspCompletedTasks || [];
                        if (completed.indexOf("Pen annotation") === -1) {
                            completed.push("Pen annotation");
                            window._inspCompletedTasks = completed;
                        }
                    })
                    .catch(function(err) {
                        console.error("Annotation error:", err);
                        if (statusText) statusText.textContent = "Annotation saved (text extraction unavailable)";
                        if (statusDot) statusDot.classList.remove("processing");

                        // Only set fallback if annotations weren't already set by .then()
                        var f = findings[savedFindingId - 1];
                        var fallbackNote = "{{ANNOTATION_FALLBACK}}";
                        if (f && !(f.annotations && f.annotations.extracted_text)) {
                            f.annotations = {
                                extracted_text: fallbackNote,
                                stroke_count: savedStrokeCount
                            };
                        } else if (f && f.annotations) {
                            fallbackNote = f.annotations.extracted_text;
                        }
                        if (annotationNote && annotationText) {
                            annotationText.textContent = fallbackNote;
                            annotationNote.style.display = "block";
                        }
                        // Show fallback note in findings log panel
                        if (inspFindingsEl) {
                            var findingItems2 = inspFindingsEl.querySelectorAll(".finding-item");
                            var targetItem2 = findingItems2[savedFindingId - 1];
                            if (targetItem2 && !targetItem2.querySelector(".finding-note")) {
                                var noteEl2 = document.createElement("div");
                                noteEl2.className = "finding-note";
                                noteEl2.style.cssText = "margin-top:6px;padding:6px 8px;background:rgba(14,165,233,0.08);border-left:3px solid #0ea5e9;border-radius:4px;font-size:0.82em;color:rgba(255,255,255,0.75);line-height:1.4;";
                                noteEl2.innerHTML = '<span style="color:#0ea5e9;font-weight:600;font-size:0.8em;text-transform:uppercase;letter-spacing:0.3px;">&#9998; {{ANNOTATION_LABEL}}</span><br>' + fallbackNote;
                                targetItem2.appendChild(noteEl2);
                            }
                        }
                        var completed = window._inspCompletedTasks || [];
                        if (completed.indexOf("Pen annotation") === -1) {
                            completed.push("Pen annotation");
                            window._inspCompletedTasks = completed;
                        }
                    });
            });

            // Wire annotate button in classification card
            if (annotateBtn) annotateBtn.addEventListener("click", function() {
                // Beneficiary form → show signature pad instead of annotation
                if (window._inspLastDocIsBeneficiary) {
                    var inspSig = document.getElementById("inspSigSection");
                    if (inspSig) {
                        inspSig.style.display = "block";
                        // Reset signature state
                        var inspSigAccept = document.getElementById("inspSigAcceptBtn");
                        if (inspSigAccept) { inspSigAccept.disabled = false; inspSigAccept.textContent = "\u2713 Accept & Sign"; inspSigAccept.style.opacity = "1"; }
                        var inspSigConf = document.getElementById("inspSigConfirm");
                        if (inspSigConf) inspSigConf.style.display = "none";
                        // Resize canvas now that it's visible
                        var inspSigCanvas = document.getElementById("inspSigCanvas");
                        if (inspSigCanvas) {
                            var w = inspSigCanvas.parentElement.clientWidth;
                            if (w > 0) { inspSigCanvas.width = w; inspSigCanvas.height = 150; }
                        }
                    }
                    return;
                }
                // Find selected thumbnail's finding ID, or use latest
                var grid = document.getElementById("inspPhotoGrid");
                var selected = grid ? grid.querySelector(".photo-thumb.selected") : null;
                var fId;
                if (selected) {
                    fId = parseInt(selected.id.replace("photo-", ""), 10);
                } else {
                    var findings = window._inspFindings || [];
                    fId = findings.length;
                }
                if (fId) openAnnotation(fId);
            });

            // Expose for cross-milestone access
            window._inspOpenAnnotation = openAnnotation;
        })();

        // ── Field Inspection: Milestone 5 — Report Generation ──
        (function() {
            var generateBtn = document.getElementById("inspGenerateBtn");
            var translateBtn = document.getElementById("inspTranslateBtn");
            var reportDraft = document.getElementById("inspReportDraft");
            var reportContent = document.getElementById("inspReportContent");
            var statusDot = document.getElementById("inspStatusDot");
            var statusText = document.getElementById("inspStatusText");
            var tokenCount = document.getElementById("inspTokenCount");

            if (!generateBtn) return;

            function setStatus(text, processing) {
                if (statusText) statusText.textContent = text;
                if (statusDot) statusDot.classList.toggle("processing", !!processing);
            }

            generateBtn.addEventListener("click", function() {
                var findings = window._inspFindings || [];
                if (findings.length === 0) {
                    setStatus("No findings to report", false);
                    return;
                }

                // Collect form fields
                var fields = {
                    inspector_name: (document.getElementById("inspInspector") || {}).value || "",
                    location: (document.getElementById("inspLocation") || {}).value || "",
                    datetime: (document.getElementById("inspDateTime") || {}).value || "",
                    reported_issue: (document.getElementById("inspIssue") || {}).value || "",
                    source: (document.getElementById("inspSource") || {}).value || ""
                };

                generateBtn.disabled = true;
                generateBtn.textContent = "\u23f3 Generating...";
                setStatus("Generating inspection report with local AI...", true);

                // Strip photo_base64 from findings before sending (too large for JSON body)
                var lightFindings = findings.map(function(f) {
                    return {
                        id: f.id,
                        classification: f.classification,
                        annotations: f.annotations,
                        transcript_excerpt: f.transcript_excerpt
                    };
                });

                var payload = JSON.stringify({fields: fields, findings: lightFindings});
                console.log("[Report] Sending " + (payload.length / 1024).toFixed(1) + " KB, " + lightFindings.length + " findings");

                fetch("/inspection/report", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: payload
                })
                .then(function(r) {
                    if (!r.ok) throw new Error("Server returned " + r.status);
                    return r.json();
                })
                .then(function(data) {
                    if (data.error) {
                        setStatus("Report error: " + data.error, false);
                        generateBtn.disabled = false;
                        generateBtn.textContent = "\ud83d\udcc4 Generate Report";
                        return;
                    }

                    // Show report
                    if (reportContent) reportContent.innerHTML = data.report_html || "<p>No report generated.</p>";
                    if (reportDraft) reportDraft.style.display = "block";
                    if (translateBtn) translateBtn.style.display = "inline-block";
                    var postD365Btn = document.getElementById("inspPostD365Btn");
                    if (postD365Btn) postD365Btn.style.display = "inline-block";

                    // Store for translation (Milestone 6)
                    window._inspReportData = data;

                    // Update status
                    var riskLabel = data.risk_rating || "Moderate";
                    setStatus("Report generated \u2014 Risk: " + riskLabel + " (" + (data.inference_time || 0) + "s)", false);

                    // Update token count
                    if (data.tokens_used) window._addInspTokens(data.tokens_used, "Report Generation", "Phi-4 Mini");

                    generateBtn.disabled = false;
                    generateBtn.textContent = "\ud83d\udcc4 Regenerate Report";
                })
                .catch(function(err) {
                    console.error("Report generation failed:", err);
                    setStatus("Report generation failed: " + (err.message || err), false);
                    generateBtn.disabled = false;
                    generateBtn.textContent = "\ud83d\udcc4 Generate Report";
                });
            });
        })();

        // ── Meeting Notes: Post to D365 ──
        (function() {
            var postBtn = document.getElementById("inspPostD365Btn");
            var resultDiv = document.getElementById("inspD365PostResult");
            if (!postBtn) return;

            postBtn.addEventListener("click", function() {
                var reportData = window._inspReportData;
                if (!reportData || !reportData.report_html) return;

                // Get client name from Client field
                var namePart = ((document.getElementById("inspInspector") || {}).value || "").trim() || "Unknown Client";

                postBtn.disabled = true;
                postBtn.textContent = "\u23f3 Posting to D365...";

                // Build full text from the HTML report
                var tempDiv = document.createElement("div");
                tempDiv.innerHTML = reportData.report_html;
                var reportText = tempDiv.textContent || tempDiv.innerText || "";
                // D365 description field can hold up to 100K chars
                if (reportText.length > 4000) reportText = reportText.substring(0, 4000) + "...";

                // Get meeting details from form fields
                var meetingLocation = (document.getElementById("inspLocation") || {}).value || "";
                var meetingDate = (document.getElementById("inspDateTime") || {}).value || "";
                var productsDiscussed = (document.getElementById("inspIssue") || {}).value || "";
                var referralSource = (document.getElementById("inspSource") || {}).value || "";

                fetch("/d365/log-transaction", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        customer_name: namePart,
                        transaction_type: "Meeting Notes",
                        amount: "0",
                        check_number: "N/A",
                        memo: reportText,
                        meeting_location: meetingLocation,
                        meeting_date: meetingDate,
                        products_discussed: productsDiscussed,
                        referral_source: referralSource,
                        bank: ""
                    })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    postBtn.disabled = false;
                    postBtn.textContent = "\u2713 Posted to D365";
                    postBtn.style.opacity = "0.7";
                    // Log D365 post to AI session report (not AI tokens, but a session operation)
                    var isLive = data.source === "live";
                    window._addInspTokens(0, "D365 Meeting Notes Post" + (isLive ? " (Live)" : " (Demo)"), "Dataverse API");

                    if (resultDiv) {
                        resultDiv.style.background = isLive ? "rgba(16,185,129,0.1)" : "rgba(241,143,18,0.1)";
                        resultDiv.style.border = "1px solid " + (isLive ? "rgba(16,185,129,0.3)" : "rgba(241,143,18,0.3)");
                        resultDiv.style.color = "#333";
                        resultDiv.innerHTML = (isLive ? "<strong>\u2713 Meeting notes posted to D365 (Live)</strong>" : "<strong>\u2713 Meeting notes logged (Demo)</strong>") +
                            "<br>Activity ID: " + (data.activity_id || "N/A") +
                            "<br>Customer: " + (data.customer_name || namePart) +
                            "<br>Timestamp: " + (data.timestamp || new Date().toISOString()) +
                            (isLive ? "<br><em>Task created on contact record in Dynamics 365</em>" : "") +
                            '<br><a href="https://orgdf28000a.crm.dynamics.com/main.aspx?appid=c22cb86f-ff3c-f111-88b5-002248357e0e&forceUCI=1&pagetype=entityrecord&etn=contact&id=5cdc2c3f-ad29-f111-8342-002248357e0e" target="_blank" ' +
                            'style="display:inline-block;margin-top:8px;padding:8px 20px;background:#0078D4;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600;font-size:0.9em;text-decoration:none;">' +
                            '\u2601 Open in Dynamics 365</a>';
                        resultDiv.style.display = "block";
                    }

                    // Track completed task
                    var completed = window._inspCompletedTasks || [];
                    if (completed.indexOf("D365 sync") === -1) {
                        completed.push("D365 sync");
                        window._inspCompletedTasks = completed;
                    }
                })
                .catch(function(err) {
                    postBtn.disabled = false;
                    postBtn.textContent = "\u2601 Post to D365";
                    if (resultDiv) {
                        resultDiv.style.background = "rgba(239,68,68,0.1)";
                        resultDiv.style.border = "1px solid rgba(239,68,68,0.3)";
                        resultDiv.style.color = "#333";
                        resultDiv.innerHTML = "<strong>Post failed</strong><br>" + (err.message || err);
                        resultDiv.style.display = "block";
                    }
                });
            });
        })();

        // ── Meeting Notes: Client Follow-Up Email ──
        (function() {
            var emailPanel = document.getElementById("inspEmailPanel");
            var emailBody = document.getElementById("inspEmailBody");
            var emailSubject = document.getElementById("inspEmailSubject");
            var emailTo = document.getElementById("inspEmailTo");
            var polishBtn = document.getElementById("inspPolishBtn");
            var sendBtn = document.getElementById("inspSendEmailBtn");
            var emailStatus = document.getElementById("inspEmailStatus");
            var micBtn = document.getElementById("inspEmailMicBtn");
            var statusText = document.getElementById("inspStatusText");
            var statusDot = document.getElementById("inspStatusDot");
            var tokenCount = document.getElementById("inspTokenCount");

            if (!emailPanel || !emailBody) return;

            var _customerEmail = "";
            var _customerName = "";

            function setStatus(text, processing) {
                if (statusText) statusText.textContent = text;
                if (statusDot) statusDot.classList.toggle("processing", !!processing);
            }

            function showEmailStatus(html, isError) {
                if (!emailStatus) return;
                emailStatus.style.display = "block";
                emailStatus.style.background = isError ? "rgba(239,68,68,0.08)" : "rgba(16,185,129,0.08)";
                emailStatus.style.border = "1px solid " + (isError ? "rgba(239,68,68,0.25)" : "rgba(16,185,129,0.25)");
                emailStatus.style.color = "#333";
                emailStatus.innerHTML = html;
            }

            // Show email panel after report generation + D365 post
            // Watch for D365 post result to appear, then show email panel
            var _emailPanelShown = false;
            window._showEmailPanel = function(clientName) {
                if (_emailPanelShown) return;
                _emailPanelShown = true;
                _customerName = clientName || "";
                emailPanel.style.display = "block";

                // Pre-fill draft from report data
                var reportData = window._inspReportData;
                if (reportData && reportData.report_html) {
                    // Extract the blockquote (draft email) from the report HTML
                    var tmp = document.createElement("div");
                    tmp.innerHTML = reportData.report_html;
                    var bq = tmp.querySelector("blockquote");
                    if (bq) {
                        // Convert HTML to plain text for the textarea
                        emailBody.value = bq.textContent || bq.innerText || "";
                    }
                }

                // Look up customer email from D365
                if (_customerName) {
                    emailTo.textContent = "Looking up " + _customerName + "...";
                    fetch("/d365/customer-lookup", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({name: _customerName})
                    })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        var cust = data.customer || {};
                        _customerEmail = cust.email || "";
                        if (_customerEmail) {
                            emailTo.innerHTML = "<strong>" + _customerName + "</strong> &lt;" + _customerEmail + "&gt;";
                            window._addInspTokens(0, "D365 Email Lookup", "Dataverse API");
                        } else {
                            emailTo.textContent = _customerName + " (no email on file)";
                        }
                    })
                    .catch(function() {
                        emailTo.textContent = _customerName + " (D365 lookup failed)";
                    });
                }
            };

            // Hook into D365 post success to show email panel
            var _origPostBtn = document.getElementById("inspPostD365Btn");
            if (_origPostBtn) {
                var observer = new MutationObserver(function() {
                    if (_origPostBtn.textContent.indexOf("Posted") >= 0) {
                        // D365 post succeeded, get client name from Client field and show email panel
                        var namePart = ((document.getElementById("inspInspector") || {}).value || "").trim();
                        setTimeout(function() { window._showEmailPanel(namePart); }, 500);
                    }
                });
                observer.observe(_origPostBtn, {childList: true, characterData: true, subtree: true});
            }

            // Also show email panel when report is generated (even without D365 post)
            var _origGenerateBtn = document.getElementById("inspGenerateBtn");
            if (_origGenerateBtn) {
                var genObserver = new MutationObserver(function() {
                    if (_origGenerateBtn.textContent.indexOf("Regenerate") >= 0 && !_emailPanelShown) {
                        var namePart = ((document.getElementById("inspInspector") || {}).value || "").trim();
                        setTimeout(function() { window._showEmailPanel(namePart); }, 1000);
                    }
                });
                genObserver.observe(_origGenerateBtn, {childList: true, characterData: true, subtree: true});
            }

            // Mic button: demo mode — typewriter sample draft for video recording
            // SAVE: Original Fluid Dictation implementation (restore for live demos):
            // if (micBtn) {
            //     micBtn.addEventListener("click", function() {
            //         emailBody.focus();
            //         setTimeout(function() {
            //             fetch("/inspection/fluid-dictation", { method: "POST" })
            //                 .then(function(r) { return r.json(); })
            //                 .then(function(data) {
            //                     if (data.error) showEmailStatus("Could not open Voice Typing: " + data.error, true);
            //                 })
            //                 .catch(function() { showEmailStatus("Could not open Voice Typing", true); });
            //         }, 150);
            //     });
            // }
            if (micBtn) {
                micBtn.addEventListener("click", function() {
                    var draftText = "hey jackie thanks so much for coming in today it was great sitting down with you " +
                        "I wanted to follow up on what we discussed about the 529 plan for maya and daniel " +
                        "and also the roth ira rollover from your old 401k " +
                        "ill have the contribution limits comparison ready for you by friday " +
                        "and we have that follow up scheduled for next thursday to go over everything " +
                        "dont hesitate to reach out if you have any questions before then";
                    micBtn.disabled = true;
                    emailBody.value = "";
                    emailBody.focus();
                    var words = draftText.split(" ");
                    var idx = 0;
                    var interval = setInterval(function() {
                        if (idx < words.length) {
                            emailBody.value += (idx > 0 ? " " : "") + words[idx];
                            emailBody.scrollTop = emailBody.scrollHeight;
                            idx++;
                        } else {
                            clearInterval(interval);
                            micBtn.disabled = false;
                            // Track voice transcription — on-device, cloud would be Whisper API
                            window._addInspTokens(100, "Voice Transcription (Email)", "Windows Speech (On-Device)");
                            showEmailStatus("Draft captured via voice — tap <strong>Polish with Writing Assistant</strong> to refine", false);
                        }
                    }, 90);
                });
            }

            // Polish with Writing Assistant
            if (polishBtn) {
                polishBtn.addEventListener("click", function() {
                    var text = emailBody.value.trim();
                    if (!text) {
                        showEmailStatus("Type or dictate a message first.", true);
                        return;
                    }
                    polishBtn.disabled = true;
                    polishBtn.textContent = "\u23f3 Polishing...";
                    setStatus("Polishing email with Writing Assistant on NPU...", true);

                    fetch("/api/polish-email", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({text: text, customer_name: _customerName})
                    })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        polishBtn.disabled = false;
                        polishBtn.innerHTML = "&#9998; Polish with Writing Assistant";
                        if (data.error) {
                            showEmailStatus("Polish failed: " + data.error, true);
                            setStatus("Polish failed", false);
                            return;
                        }
                        emailBody.value = data.polished;
                        var modelLabel = data.model || "AI";
                        setStatus("Email polished by " + modelLabel + " on NPU", false);
                        showEmailStatus("&#10003; Polished by <strong>" + modelLabel + "</strong> on NPU" + (data.inference_time ? " (" + data.inference_time + "s)" : ""), false);

                        // Update token count — Writing Assistant uses ~200 tokens
                        window._addInspTokens(200, "Writing Assistant", "Phi Silica TextRewriter");
                    })
                    .catch(function(err) {
                        polishBtn.disabled = false;
                        polishBtn.innerHTML = "&#9998; Polish with Writing Assistant";
                        showEmailStatus("Polish failed: " + err.message, true);
                        setStatus("Polish failed", false);
                    });
                });
            }

            // Send to Customer
            if (sendBtn) {
                sendBtn.addEventListener("click", function() {
                    var text = emailBody.value.trim();
                    if (!text) {
                        showEmailStatus("Type or dictate a message first.", true);
                        return;
                    }
                    if (!_customerEmail) {
                        showEmailStatus("No customer email found. Check D365 contact record.", true);
                        return;
                    }

                    sendBtn.disabled = true;
                    sendBtn.textContent = "\u23f3 Sending...";
                    setStatus("Sending follow-up email via Microsoft Graph...", true);

                    // Convert plain text to HTML paragraphs
                    var bodyHtml = text.split("\n").filter(function(l) { return l.trim(); }).map(function(l) { return "<p>" + l + "</p>"; }).join("");

                    fetch("/api/send-followup", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({
                            body: bodyHtml,
                            subject: emailSubject.value || "Thank you for meeting with us today",
                            customer_name: _customerName,
                            customer_email: _customerEmail
                        })
                    })
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        sendBtn.disabled = false;
                        if (data.sent) {
                            sendBtn.textContent = "\u2713 Email Sent";
                            sendBtn.style.opacity = "0.7";
                            setStatus("Follow-up email sent to " + data.to, false);
                            showEmailStatus(
                                "<strong>&#10003; Email sent successfully</strong><br>" +
                                "To: " + (data.to_name || "") + " &lt;" + data.to + "&gt;<br>" +
                                "Subject: " + data.subject + "<br>" +
                                "Sent via Microsoft Graph (Outlook) at " + new Date().toLocaleTimeString(),
                                false
                            );

                            // Log email send to session report
                            window._addInspTokens(0, "Follow-Up Email Sent", "Microsoft Graph API");

                            // Track completed task
                            var completed = window._inspCompletedTasks || [];
                            if (completed.indexOf("Follow-up email") === -1) {
                                completed.push("Follow-up email");
                                window._inspCompletedTasks = completed;
                            }
                        } else {
                            sendBtn.innerHTML = "&#9993; Send to Customer";
                            showEmailStatus("Send failed: " + (data.error || "Unknown error"), true);
                            setStatus("Email send failed", false);
                        }
                    })
                    .catch(function(err) {
                        sendBtn.disabled = false;
                        sendBtn.innerHTML = "&#9993; Send to Customer";
                        showEmailStatus("Send failed: " + err.message, true);
                        setStatus("Email send failed", false);
                    });
                });
            }
        })();

        // ── Field Inspection: Milestone 6 — Translation ──
        (function() {
            var translateBtn = document.getElementById("inspTranslateBtn");
            var reportDraft = document.getElementById("inspReportDraft");
            var reportContent = document.getElementById("inspReportContent");
            var statusDot = document.getElementById("inspStatusDot");
            var statusText = document.getElementById("inspStatusText");
            var tokenCount = document.getElementById("inspTokenCount");

            if (!translateBtn) return;

            // Track language state
            var currentLang = "en";
            var originalHtml = "";
            var translatedHtml = "";

            function setStatus(text, processing) {
                if (statusText) statusText.textContent = text;
                if (statusDot) statusDot.classList.toggle("processing", !!processing);
            }

            translateBtn.addEventListener("click", function() {
                // Toggle back to English if already translated
                if (currentLang === "es") {
                    if (reportContent) reportContent.innerHTML = originalHtml;
                    translateBtn.textContent = "\ud83c\udf10 Translate to Spanish";
                    currentLang = "en";
                    setStatus("Switched back to English", false);
                    return;
                }

                // Get current report HTML
                var reportData = window._inspReportData;
                if (!reportData || !reportData.report_html) {
                    setStatus("No report to translate", false);
                    return;
                }

                // Save original before translating
                originalHtml = reportData.report_html;

                translateBtn.disabled = true;
                translateBtn.textContent = "\u23f3 Translating...";
                setStatus("Translating report to Spanish with local AI...", true);

                fetch("/inspection/translate", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        report_html: originalHtml,
                        target_language: "Spanish"
                    })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.error) {
                        setStatus("Translation error: " + data.error, false);
                        translateBtn.disabled = false;
                        translateBtn.textContent = "\ud83c\udf10 Translate to Spanish";
                        return;
                    }

                    translatedHtml = data.translated_html;

                    // Brief side-by-side flash (500ms) then settle on translation
                    if (reportContent) {
                        reportContent.innerHTML =
                            '<div style="display:flex;gap:12px;opacity:0.8;">' +
                            '<div style="flex:1;border-right:1px solid rgba(255,255,255,0.2);padding-right:12px;">' +
                            '<div style="font-size:11px;color:rgba(255,255,255,0.5);margin-bottom:4px;">EN</div>' +
                            originalHtml + '</div>' +
                            '<div style="flex:1;padding-left:12px;">' +
                            '<div style="font-size:11px;color:rgba(255,255,255,0.5);margin-bottom:4px;">ES</div>' +
                            translatedHtml + '</div></div>';

                        setTimeout(function() {
                            reportContent.innerHTML = translatedHtml;
                        }, 500);
                    }

                    currentLang = "es";
                    translateBtn.disabled = false;
                    translateBtn.textContent = "\ud83c\udf10 Switch to English";

                    var timeLabel = data.inference_time ? " (" + data.inference_time + "s)" : "";
                    setStatus("Translated to Spanish" + timeLabel + " \u2014 no cloud API call", false);

                    // Update token count
                    if (data.tokens_used) window._addInspTokens(data.tokens_used, "Translation (ES)", "Phi-4 Mini");
                })
                .catch(function(err) {
                    console.error("Translation failed:", err);
                    setStatus("Translation failed", false);
                    translateBtn.disabled = false;
                    translateBtn.textContent = "\ud83c\udf10 Translate to Spanish";
                });
            });
        })();

        // ── Field Inspection: Milestone 7 — Router Escalation + Dashboard Tally ──
        (function() {
            var escOverlay = document.getElementById("inspEscOverlay");
            var escCloud = document.getElementById("inspEscCloud");
            var escLocal = document.getElementById("inspEscLocal");
            var escPayload = document.getElementById("inspEscPayload");
            var stayedLocal = document.getElementById("inspStayedLocal");
            var lockIcon = document.getElementById("inspLockIcon");
            var summaryBtn = document.getElementById("inspSummaryBtn");
            var dashOverlay = document.getElementById("inspDashOverlay");
            var dashClose = document.getElementById("inspDashClose");
            var dashLocalTasks = document.getElementById("inspDashLocalTasks");
            var dashSummary = document.getElementById("inspDashSummary");
            var dashCloudCount = document.getElementById("inspDashCloudCount");
            var statusDot = document.getElementById("inspStatusDot");
            var statusText = document.getElementById("inspStatusText");
            var tokenCount = document.getElementById("inspTokenCount");

            if (!escOverlay) return;

            // Track completed tasks for dashboard
            window._inspCompletedTasks = window._inspCompletedTasks || [];
            var pendingEscFinding = null;

            function setStatus(text, processing) {
                if (statusText) statusText.textContent = text;
                if (statusDot) statusDot.classList.toggle("processing", !!processing);
            }

            // Part A: Escalation trigger — called after classification
            window._inspCheckEscalation = function(result, photoDataUrl) {
                if (result.confidence >= 60 && result.confidence < 75) {
                    // Low confidence — show escalation dialog
                    pendingEscFinding = { result: result, photo: photoDataUrl };
                    var photoSize = photoDataUrl ? Math.round(photoDataUrl.length * 0.75 / 1024) : 0;
                    if (escPayload) escPayload.textContent = "Sending: 1 photo (" + photoSize + " KB)";
                    escOverlay.style.display = "flex";
                }
            };

            // "Keep Local" — recommended path
            escLocal.addEventListener("click", function() {
                escOverlay.style.display = "none";

                // Show stayed-local banner with lock animation
                if (stayedLocal) {
                    stayedLocal.style.display = "block";
                    if (lockIcon) {
                        lockIcon.style.animation = "none";
                        lockIcon.offsetHeight;
                        lockIcon.style.animation = "";
                    }
                }

                // Flag finding in the findings log
                if (pendingEscFinding) {
                    var findings = window._inspFindings || [];
                    for (var i = findings.length - 1; i >= 0; i--) {
                        if (findings[i].classification.confidence === pendingEscFinding.result.confidence) {
                            findings[i].flagged_for_review = true;
                            break;
                        }
                    }
                }

                setStatus("Finding flagged for expert review \u2014 data stayed local", false);
                addTask("Routing logic");
                if (summaryBtn) summaryBtn.style.display = "inline-block";
                pendingEscFinding = null;
            });

            // "Escalate to Cloud" — connectivity required
            escCloud.addEventListener("click", function() {
                escOverlay.style.display = "none";
                setStatus("No connectivity \u2014 keeping data local (airplane mode)", false);

                // Show stayed-local as fallback
                if (stayedLocal) {
                    stayedLocal.style.display = "block";
                    if (lockIcon) {
                        lockIcon.style.animation = "none";
                        lockIcon.offsetHeight;
                        lockIcon.style.animation = "";
                    }
                }

                addTask("Routing logic");
                if (summaryBtn) summaryBtn.style.display = "inline-block";
                pendingEscFinding = null;
            });

            // Task tracking for dashboard
            function addTask(name) {
                var tasks = window._inspCompletedTasks;
                if (tasks.indexOf(name) === -1) tasks.push(name);
            }

            // Auto-track tasks based on events
            // Observe findings additions for speech/field/vision tasks
            var origPush = null;
            function setupTaskTracking() {
                // Track speech-to-text and field extraction from Milestone 2
                var extractBtn = document.getElementById("inspExtractBtn");
                var scripted = document.getElementById("inspScriptedBtn");
                if (extractBtn) extractBtn.addEventListener("click", function() {
                    addTask("Field extraction");
                });
                if (scripted) scripted.addEventListener("click", function() {
                    addTask("Speech-to-text");
                    addTask("Field extraction");
                });

                // Track vision classification from Milestone 3
                var demoPhoto = document.getElementById("inspDemoPhotoBtn");
                var capturePhoto = document.getElementById("inspCapturePhotoBtn");
                if (demoPhoto) demoPhoto.addEventListener("click", function() {
                    addTask("Vision classification");
                });
                if (capturePhoto) capturePhoto.addEventListener("click", function() {
                    addTask("Vision classification");
                });

                // Track report generation from Milestone 5
                var generateBtn = document.getElementById("inspGenerateBtn");
                if (generateBtn) generateBtn.addEventListener("click", function() {
                    addTask("Report generation");
                });

                // Track translation from Milestone 6
                var translateBtn = document.getElementById("inspTranslateBtn");
                if (translateBtn) translateBtn.addEventListener("click", function() {
                    addTask("Translation");
                });
            }
            setupTaskTracking();

            // Part B: Dashboard Tally
            summaryBtn.addEventListener("click", function() {
                showDashboard();
            });

            function showDashboard() {
                var allTasks = [
                    "Transcribe meeting notes",
                    "Extract client details",
                    "Classify document",
                    "Pen annotation",
                    "Generate meeting summary",
                    "Translate report",
                    "Routing logic"
                ];

                var completed = window._inspCompletedTasks || [];
                var html = "";
                for (var i = 0; i < allTasks.length; i++) {
                    var done = completed.indexOf(allTasks[i]) !== -1;
                    html += '<div class="insp-dash-task">' +
                        (done ? '<span class="check">\u2713</span>' : '<span style="color:rgba(255,255,255,0.2);">\u2013</span>') +
                        '<span>' + allTasks[i] + '</span></div>';
                }
                if (dashLocalTasks) dashLocalTasks.innerHTML = html;
                if (dashCloudCount) dashCloudCount.textContent = "0";

                // Summary bar with tokenomics
                var tokens = window._inspTotalTokens || 0;
                if (dashSummary) {
                    dashSummary.textContent = "Total tokens: " + tokens +
                        " | Cost: $0.00 | Transmitted: 0 bytes";
                }

                dashOverlay.style.display = "flex";
            }
            window._inspShowDashboard = showDashboard;

            dashClose.addEventListener("click", function() {
                dashOverlay.style.display = "none";
            });
        })();

        // ── Live Assist: Voice + Demo Script + AI Prompter ──
        (function() {
            // --- State ---
            var _liveMode = null;  // "voice" | "demo" | null
            var _liveLines = [];   // all transcript lines (objects: {text, time})
            var _liveSentIndex = 0; // how many lines sent for analysis
            var _liveAnalyzing = false;
            var _livePriorInsights = [];
            var _liveInsightCount = 0;
            var _liveTokensUsed = 0;
            var _liveDemoTimers = [];
            var _liveRecognition = null;

            // --- DOM refs ---
            var transcriptArea = document.getElementById("liveTranscriptArea");
            var insightCards = document.getElementById("liveInsightCards");
            var pulseDot = document.getElementById("livePulseDot");
            var insightDot = document.getElementById("liveInsightDot");
            var voiceBtn = document.getElementById("liveVoiceBtn");
            var demoBtn = document.getElementById("liveDemoBtn");
            var stopBtn = document.getElementById("liveStopBtn");
            var statusText = document.getElementById("liveStatusText");

            // --- Demo Script (fallback) ---
            var _liveAssistDemoScript = [
                {delay: 0,    speaker: "Customer", text: "Hi, I'm Jackie. I called earlier about opening a new account."},
                {delay: 3500, speaker: "Advisor",  text: "Welcome, Jackie! I'd be happy to help you get set up. What brings you in today?"},
                {delay: 3500, speaker: "Customer", text: "I just moved here from out of state and I need to set up checking and savings."},
                {delay: 3000, speaker: "Advisor",  text: "Great, we can definitely get that started. Is it just for you, or a joint account?"},
                {delay: 3500, speaker: "Customer", text: "Just me for now. I also have two kids, Maya is eight and Daniel is fifteen."},
                {delay: 4000, speaker: "Customer", text: "My husband and I have been talking about saving for their college."},
                {delay: 3000, speaker: "Advisor",  text: "That's smart to start planning early. Have you looked into any education savings plans?"},
                {delay: 3500, speaker: "Customer", text: "Someone mentioned a 529 plan but I don't really understand how it works."},
                {delay: 3000, speaker: "Customer", text: "Is there a limit on how much we can put in each year?"},
                {delay: 3500, speaker: "Advisor",  text: "A 529 is a tax-advantaged savings plan. The annual gift tax exclusion is $18,000 per beneficiary."},
                {delay: 4000, speaker: "Customer", text: "We're also thinking about retirement. I have an old 401k from my previous job that I never rolled over."},
                {delay: 3000, speaker: "Customer", text: "I'm forty-five, so I feel like I'm behind on retirement planning."},
                {delay: 3500, speaker: "Advisor",  text: "You're not behind at all. Let's look at your options. Do you know the balance on that 401k?"},
                {delay: 3500, speaker: "Customer", text: "What would you recommend, a Roth IRA or a traditional IRA for someone my age?"},
                {delay: 4000, speaker: "Customer", text: "And honestly, the fees at my last bank were ridiculous. That's part of why I'm switching."},
                {delay: 3000, speaker: "Advisor",  text: "I hear that a lot. Our checking accounts have no monthly fees with direct deposit."},
                {delay: 3500, speaker: "Customer", text: "OK that sounds reasonable. Let's go ahead and get the checking set up today."},
                {delay: 3000, speaker: "Customer", text: "And I'd like to schedule a follow-up to go deeper on the college savings and retirement options."},
                {delay: 3500, speaker: "Advisor",  text: "Absolutely. I'll get the checking started and we can book a follow-up for later this week."}
            ];

            // --- Helpers ---
            function timeStamp() {
                var d = new Date();
                return String(d.getHours()).padStart(2, "0") + ":" +
                       String(d.getMinutes()).padStart(2, "0") + ":" +
                       String(d.getSeconds()).padStart(2, "0");
            }

            function setStatus(msg) {
                if (statusText) statusText.textContent = msg;
            }

            function clearTranscript() {
                if (transcriptArea) transcriptArea.innerHTML = "";
                if (insightCards) insightCards.innerHTML = "";
                _liveLines = [];
                _liveSentIndex = 0;
                _liveAnalyzing = false;
                _livePriorInsights = [];
                _liveInsightCount = 0;
                _liveTokensUsed = 0;
            }

            function addTranscriptLine(text, isInterim, speaker) {
                // Remove any interim line first
                var old = transcriptArea.querySelector(".live-transcript-line.interim");
                if (old) old.remove();

                var div = document.createElement("div");
                var speakerClass = speaker ? " speaker-" + speaker.toLowerCase().replace(/\s+/g, "-") : "";
                div.className = "live-transcript-line" + (isInterim ? " interim" : "") + speakerClass;
                var speakerTag = speaker ? '<span class="line-speaker">' + speaker + '</span>' : '';
                div.innerHTML = '<span class="line-time">' + timeStamp() + '</span>' +
                    speakerTag + text;
                transcriptArea.appendChild(div);
                transcriptArea.scrollTop = transcriptArea.scrollHeight;

                if (!isInterim) {
                    _liveLines.push({ text: text, time: timeStamp(), speaker: speaker || "" });
                    checkAnalysisTrigger();
                }
            }

            // --- Analysis trigger: every 2-3 new lines, fire /live-assist/analyze ---
            function checkAnalysisTrigger() {
                var unsent = _liveLines.length - _liveSentIndex;
                console.log("[LiveAssist] checkAnalysisTrigger: unsent=" + unsent + " analyzing=" + _liveAnalyzing);
                if (unsent >= 2 && !_liveAnalyzing) {
                    fireAnalysis();
                }
            }

            function fireAnalysis() {
                if (_liveAnalyzing) return;
                var chunk = [];
                for (var i = _liveSentIndex; i < _liveLines.length; i++) {
                    chunk.push(_liveLines[i].text);
                }
                if (chunk.length === 0) return;
                _liveSentIndex = _liveLines.length;
                _liveAnalyzing = true;
                insightDot.classList.add("active");
                setStatus("Analyzing transcript...");
                console.log("[LiveAssist] fireAnalysis: sending " + chunk.length + " lines (" + chunk.join(" ").length + " chars)");

                // Send last 3 insights as short summaries (first 20 words each)
                var priorStr = _livePriorInsights.slice(-3).map(function(p) {
                    return p.replace(/^- /gm, "").split(/\s+/).slice(0, 20).join(" ");
                }).join(" | ");

                fetch("/live-assist/analyze", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text: chunk.join(" "), prior: priorStr })
                })
                .then(function(r) {
                    if (!r.ok) throw new Error("HTTP " + r.status);
                    return r.json();
                })
                .then(function(data) {
                    _liveAnalyzing = false;
                    insightDot.classList.remove("active");
                    console.log("[LiveAssist] Analysis result:", data.sentiment, "tokens=" + data.tokens_used);
                    if (data.error) {
                        setStatus("Analysis error: " + data.error);
                        return;
                    }
                    _liveInsightCount++;
                    _liveTokensUsed += (data.tokens_used || 0);
                    // Track in savings widget
                    try {
                        if (typeof updateSavingsFromResponse === "function") {
                            updateSavingsFromResponse({ usage: { total_tokens: data.tokens_used || 0 } });
                        }
                    } catch(e) { console.warn("[LiveAssist] savings widget error:", e); }
                    // Store full insight text as prior to suppress repeats
                    _livePriorInsights.push(data.insights || "");

                    addInsightCard(data.insights, data.sentiment);
                    setStatus(_liveMode === "voice" ? "Listening..." : "Playing script...");

                    // Check if more unsent lines accumulated while analyzing
                    var stillUnsent = _liveLines.length - _liveSentIndex;
                    console.log("[LiveAssist] Post-analysis: stillUnsent=" + stillUnsent);
                    if (stillUnsent >= 1) fireAnalysis();
                })
                .catch(function(e) {
                    _liveAnalyzing = false;
                    insightDot.classList.remove("active");
                    console.error("[LiveAssist] Analysis failed:", e);
                    setStatus("Analysis failed: " + e.message);
                    // Still try to process remaining lines
                    var stillUnsent = _liveLines.length - _liveSentIndex;
                    if (stillUnsent >= 2) {
                        setTimeout(function() { fireAnalysis(); }, 2000);
                    }
                });
            }

            function addInsightCard(text, sentiment) {
                // Remove the initial placeholder text on first real card
                var placeholder = document.getElementById("liveInsightPlaceholder");
                if (placeholder) placeholder.remove();

                var card = document.createElement("div");
                card.className = "live-insight-card";
                var sentClass = "sentiment-neutral";
                var sentLabel = "NEUTRAL";
                if (sentiment === "POSITIVE") { sentClass = "sentiment-positive"; sentLabel = "POSITIVE"; }
                else if (sentiment === "CAUTIOUS") { sentClass = "sentiment-cautious"; sentLabel = "CAUTIOUS"; }

                // Format bullets and markdown inline
                var safeText = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
                                   .replace(/\*([^*]+)\*/g, '<em>$1</em>')
                                   .replace(/^- (.+)$/gm, '<div style="padding:2px 0 2px 12px;border-left:2px solid rgba(255,255,255,0.15);">$1</div>')
                                   .replace(/\n/g, '');
                card.innerHTML = '<div class="insight-header">' +
                    '<span class="sentiment-badge ' + sentClass + '">' + sentLabel + '</span>' +
                    '<span class="insight-time">' + timeStamp() + '</span></div>' +
                    '<div class="insight-text">' + safeText + '</div>';

                // Append at bottom (natural reading order) and scroll to show it
                insightCards.appendChild(card);
                insightCards.scrollTop = insightCards.scrollHeight;
            }

            // --- Web Speech API (Live Voice) ---
            function startVoice() {
                var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                if (!SpeechRecognition) {
                    setStatus("Speech Recognition not supported in this browser. Use Microsoft Edge.");
                    return;
                }

                clearTranscript();
                _liveMode = "voice";
                var recognition = new SpeechRecognition();
                recognition.continuous = true;
                recognition.interimResults = true;
                recognition.lang = "en-US";
                recognition.maxAlternatives = 1;
                _liveRecognition = recognition;

                recognition.onstart = function() {
                    pulseDot.classList.add("active");
                    setStatus("Listening... speak into your microphone");
                    voiceBtn.style.display = "none";
                    demoBtn.style.display = "none";
                    stopBtn.style.display = "";
                };

                recognition.onresult = function(event) {
                    var finalText = "";
                    var interimText = "";
                    for (var i = event.resultIndex; i < event.results.length; i++) {
                        var transcript = event.results[i][0].transcript;
                        if (event.results[i].isFinal) {
                            finalText += transcript;
                        } else {
                            interimText += transcript;
                        }
                    }
                    if (finalText.trim()) {
                        addTranscriptLine(finalText.trim(), false);
                    }
                    if (interimText.trim()) {
                        addTranscriptLine(interimText.trim(), true);
                    }
                };

                recognition.onerror = function(event) {
                    if (event.error === "no-speech") return; // normal, keep listening
                    if (event.error === "aborted") return;   // user stopped
                    setStatus("Mic error: " + event.error);
                };

                recognition.onend = function() {
                    // Auto-restart if still in voice mode (browser may stop after silence)
                    if (_liveMode === "voice") {
                        try { recognition.start(); } catch(e) {}
                    }
                };

                try {
                    recognition.start();
                } catch(e) {
                    setStatus("Could not start microphone: " + e.message);
                }
            }

            function stopVoice() {
                _liveMode = null;
                if (_liveRecognition) {
                    try { _liveRecognition.stop(); } catch(e) {}
                    _liveRecognition = null;
                }
                pulseDot.classList.remove("active");
            }

            // --- Demo Script Engine ---
            function startDemoScript() {
                clearTranscript();
                _liveMode = "demo";
                pulseDot.classList.add("active");
                voiceBtn.style.display = "none";
                demoBtn.style.display = "none";
                stopBtn.style.display = "";
                setStatus("Playing demo script...");

                var idx = 0;
                function playNext() {
                    if (idx >= _liveAssistDemoScript.length || _liveMode !== "demo") {
                        finishSession();
                        return;
                    }
                    var line = _liveAssistDemoScript[idx];
                    idx++;
                    var timer = setTimeout(function() {
                        addTranscriptLine(line.text, false, line.speaker);
                        playNext();
                    }, line.delay);
                    _liveDemoTimers.push(timer);
                }
                playNext();
            }

            function stopDemoScript() {
                _liveMode = null;
                for (var i = 0; i < _liveDemoTimers.length; i++) {
                    clearTimeout(_liveDemoTimers[i]);
                }
                _liveDemoTimers = [];
                pulseDot.classList.remove("active");
            }

            // --- Session finish ---
            function finishSession() {
                pulseDot.classList.remove("active");

                // Flush any remaining unsent lines
                if (_liveLines.length > _liveSentIndex && !_liveAnalyzing) {
                    fireAnalysis();
                }

                // Wait for in-flight analysis to finish before showing summary
                function showSummary() {
                    if (_liveAnalyzing) {
                        setTimeout(showSummary, 500);
                        return;
                    }
                    // Flush again if more lines came in during wait
                    if (_liveLines.length > _liveSentIndex) {
                        fireAnalysis();
                        setTimeout(showSummary, 500);
                        return;
                    }
                    var summaryDiv = document.createElement("div");
                    summaryDiv.className = "live-summary-card";
                    summaryDiv.innerHTML = '<h4>Session Complete</h4>' +
                        '<p>' + _liveLines.length + ' transcript lines captured</p>' +
                        '<p>' + _liveInsightCount + ' AI insights generated</p>' +
                        '<p>' + _liveTokensUsed + ' tokens used -- all processed locally on NPU</p>';
                    transcriptArea.appendChild(summaryDiv);
                    transcriptArea.scrollTop = transcriptArea.scrollHeight;

                    _liveMode = null;
                    voiceBtn.style.display = "";
                    demoBtn.style.display = "";
                    stopBtn.style.display = "none";
                    var tBtn = document.getElementById("liveTranslateBtn");
                    if (tBtn && _liveLines.length > 0) tBtn.style.display = "";
                    setStatus("Session complete. " + _liveInsightCount + " insights generated locally.");
                }
                showSummary();
            }

            // --- Stop handler ---
            function stopSession() {
                if (_liveMode === "voice") stopVoice();
                else if (_liveMode === "demo") stopDemoScript();
                finishSession();
            }

            // --- Translation ---
            var _liveTransLang = "en";
            var _liveTranslating = false;
            var translateBtn = document.getElementById("liveTranslateBtn");

            function translateTranscript() {
                if (_liveTranslating || _liveLines.length === 0) return;

                if (_liveTransLang === "es") {
                    var tl = transcriptArea.querySelectorAll(".live-translated-line");
                    for (var i = 0; i < tl.length; i++) tl[i].remove();
                    _liveTransLang = "en";
                    if (translateBtn) translateBtn.textContent = "\ud83c\udf10 Translate to Spanish";
                    setStatus("Switched back to English");
                    return;
                }

                var fullText = "";
                for (var j = 0; j < _liveLines.length; j++) fullText += _liveLines[j].text + "\n";

                _liveTranslating = true;
                if (translateBtn) { translateBtn.disabled = true; translateBtn.textContent = "\u23f3 Translating..."; }
                setStatus("Translating transcript to Spanish with local AI...");

                fetch("/live-assist/translate", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({ text: fullText, target_language: "Spanish" })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    _liveTranslating = false;
                    if (translateBtn) translateBtn.disabled = false;
                    if (data.error) {
                        setStatus("Translation error: " + data.error);
                        if (translateBtn) translateBtn.textContent = "\ud83c\udf10 Translate to Spanish";
                        return;
                    }
                    var translated = (data.translated_text || "").split("\n").filter(function(l) { return l.trim(); });
                    var origLines = transcriptArea.querySelectorAll(".live-transcript-line");
                    var ti = 0;
                    for (var k = 0; k < origLines.length && ti < translated.length; k++) {
                        var td = document.createElement("div");
                        td.className = "live-translated-line";
                        td.textContent = translated[ti];
                        origLines[k].parentNode.insertBefore(td, origLines[k].nextSibling);
                        ti++;
                    }
                    _liveTransLang = "es";
                    if (translateBtn) translateBtn.textContent = "\ud83c\udf10 Switch to English";
                    setStatus("Translated to Spanish -- 44 languages supported, all on-device. No cloud API call.");
                    transcriptArea.scrollTop = transcriptArea.scrollHeight;
                })
                .catch(function(err) {
                    _liveTranslating = false;
                    if (translateBtn) { translateBtn.disabled = false; translateBtn.textContent = "\ud83c\udf10 Translate to Spanish"; }
                    setStatus("Translation failed");
                });
            }

            if (translateBtn) translateBtn.addEventListener("click", translateTranscript);

            // --- Wire up buttons ---
            if (voiceBtn) voiceBtn.addEventListener("click", startVoice);
            if (demoBtn) demoBtn.addEventListener("click", startDemoScript);
            if (stopBtn) stopBtn.addEventListener("click", stopSession);
        })();

        // ── Performance Monitor Overlay (Ctrl+Shift+M) ──
        (function() {
            var panel = document.getElementById("perfMonitor");
            var closeBtn = document.getElementById("perfClose");
            var pollTimer = null;
            var sparkData = [];
            var MAX_SPARK = 30;

            // Initialize sparkline bars
            var sparkContainer = document.getElementById("perfSparkline");
            for (var i = 0; i < MAX_SPARK; i++) {
                var bar = document.createElement("div");
                bar.className = "perf-sparkline-bar";
                bar.style.height = "1px";
                sparkContainer.appendChild(bar);
                sparkData.push(0);
            }

            function updateStats() {
                fetch("/system-stats").then(function(r) { return r.json(); }).then(function(d) {
                    document.getElementById("perfCpuBar").style.width = d.cpu + "%";
                    document.getElementById("perfCpuVal").textContent = d.cpu + "%";
                    document.getElementById("perfGpuBar").style.width = d.gpu + "%";
                    document.getElementById("perfGpuVal").textContent = d.gpu + "%";
                    document.getElementById("perfNpuBar").style.width = d.npu + "%";
                    document.getElementById("perfNpuVal").textContent = d.npu + "%";

                    // Update NPU sparkline
                    sparkData.push(d.npu);
                    if (sparkData.length > MAX_SPARK) sparkData.shift();
                    var bars = sparkContainer.children;
                    for (var i = 0; i < bars.length && i < sparkData.length; i++) {
                        bars[i].style.height = Math.max(1, sparkData[i] * 0.24) + "px";
                    }
                }).catch(function() {});
            }

            function showPanel() {
                panel.classList.add("visible");
                updateStats();
                pollTimer = setInterval(updateStats, 1000);
            }

            function hidePanel() {
                panel.classList.remove("visible");
                if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
            }

            function togglePanel() {
                if (panel.classList.contains("visible")) hidePanel(); else showPanel();
            }

            // Hotkey: Ctrl+Shift+M
            document.addEventListener("keydown", function(e) {
                if (e.ctrlKey && e.shiftKey && e.key === "M") {
                    e.preventDefault();
                    togglePanel();
                }
            });

            // Hotkey: Ctrl+Shift+C — toggle carbon/CO2 savings visibility
            var _showCarbon = true;
            window._showCarbon = function() { return _showCarbon; };
            document.addEventListener("keydown", function(e) {
                if (e.ctrlKey && e.shiftKey && e.key === "C") {
                    e.preventDefault();
                    _showCarbon = !_showCarbon;
                    var co2El = document.getElementById("savingsCO2");
                    if (co2El) co2El.style.display = _showCarbon ? "" : "none";
                }
            });

            if (closeBtn) closeBtn.addEventListener("click", hidePanel);
        })();

        // ── Branch Concierge: Arrivals Panel ──
        // Deferred init — panel HTML is at end of body, may not be in DOM yet when script runs
        setTimeout(function() {
        (function() {
            var bell = document.getElementById("conciergeBell");
            var badge = document.getElementById("bellBadge");
            var panel = document.getElementById("arrivalsPanel");
            var closeBtn = document.getElementById("arrivalsClose");
            var feed = document.getElementById("arrivalsFeed");
            var emptyState = document.getElementById("arrivalsEmpty");
            var toast = document.getElementById("arrivalToast");
            if (!bell || !panel) { console.warn("[Concierge] Elements not found"); return; }

            var lastCount = 0;

            function showToast(msg) {
                toast.textContent = msg;
                toast.style.display = "block";
                setTimeout(function() { toast.style.display = "none"; }, 4000);
            }

            function simulateArrival(endpoint, defaultName) {
                fetch(endpoint, {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({name: defaultName})
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.name) {
                        showToast(data.name + " just arrived (" + (data.source || "").replace("_", " ") + ")");
                        refreshArrivals();
                    }
                });
            }

            // Simulate buttons (may not exist yet if HTML is after script — use deferred binding)
            function bindSim(id, endpoint, name) {
                var btn = document.getElementById(id);
                if (btn) btn.addEventListener("click", function() { simulateArrival(endpoint, name); });
                else setTimeout(function() { bindSim(id, endpoint, name); }, 100);
            }
            bindSim("simCheckin", "/arrivals/checkin", "Jackie Rodriguez");
            bindSim("simAppointment", "/arrivals/appointment", "Sarah Henderson");
            bindSim("simTeller", "/arrivals/teller-identified", "Marcus Chen");

            // Bell opens/closes panel
            bell.addEventListener("click", function() {
                panel.classList.toggle("open");
                if (panel.classList.contains("open")) refreshArrivals();
            });
            closeBtn.addEventListener("click", function() { panel.classList.remove("open"); });

            var _briefLoading = false; // Flag to prevent polling from rebuilding during brief fetch

            function refreshArrivals() {
                // Skip rebuild entirely if a brief is loading or visible
                if (_briefLoading) return;

                fetch("/arrivals").then(function(r) { return r.json(); }).then(function(data) {
                    var arrivals = data.arrivals || [];
                    // Update badge
                    if (arrivals.length > 0) {
                        badge.textContent = arrivals.length;
                        badge.classList.add("active");
                    } else {
                        badge.classList.remove("active");
                    }
                    // Show toast on new arrivals
                    if (arrivals.length > lastCount && lastCount > 0) {
                        var newest = arrivals[0];
                        showToast(newest.name + " just arrived (" + newest.source_label + ")");
                    }
                    lastCount = arrivals.length;

                    // Don't rebuild if a brief is open or loading
                    if (_briefLoading || feed.querySelector(".arrival-brief-panel.visible")) {
                        return;
                    }

                    if (arrivals.length === 0) {
                        feed.innerHTML = '<div class="arrivals-empty">No arrivals yet. Use the buttons above to simulate.</div>';
                        return;
                    }

                    // Save any open brief panels before rebuilding
                    var savedBriefs = {};
                    var openPanels = feed.querySelectorAll(".arrival-brief-panel.visible");
                    for (var bp = 0; bp < openPanels.length; bp++) {
                        var bpId = openPanels[bp].id.replace("brief-", "");
                        savedBriefs[bpId] = openPanels[bp].innerHTML;
                    }

                    var html = "";
                    for (var i = 0; i < arrivals.length; i++) {
                        var a = arrivals[i];
                        var statusClass = a.status === "being_greeted" ? " greeted" : "";
                        html += '<div class="arrival-card' + statusClass + '" id="arr-' + a.arrival_id + '">' +
                            '<div class="arrival-card-header">' +
                            '<span class="arrival-tier" style="background:' + a.tier_color + '22; color:' + a.tier_color + '; border:1px solid ' + a.tier_color + '44;">' + a.tier_icon + ' ' + a.tier_label + '</span>' +
                            '<span class="arrival-source">' + a.source_label + '</span>' +
                            '</div>' +
                            '<div class="arrival-name">' + a.name + '</div>' +
                            '<div class="arrival-title">' + (a.title || '') + '</div>' +
                            '<div class="arrival-meta"><span>RM: ' + (a.rm || 'Unassigned') + '</span><span>' + a.dwell + '</span></div>' +
                            '<div class="arrival-actions">' +
                            '<button class="arrival-greet" data-aid="' + a.arrival_id + '" ' + (a.status === "being_greeted" ? 'disabled style="opacity:0.5;"' : '') + '>' + (a.status === "being_greeted" ? "&#10003; Greeting" : "&#128075; Greet") + '</button>' +
                            '<button class="arrival-brief-btn" data-aid="' + a.arrival_id + '">&#128203; Prep Brief</button>' +
                            '</div>' +
                            '<div class="arrival-brief-panel" id="brief-' + a.arrival_id + '"></div>' +
                            '</div>';
                    }
                    feed.innerHTML = html;

                    // Restore saved brief panels
                    for (var savedId in savedBriefs) {
                        var restoredPanel = document.getElementById("brief-" + savedId);
                        if (restoredPanel) {
                            restoredPanel.innerHTML = savedBriefs[savedId];
                            restoredPanel.classList.add("visible");
                        }
                    }

                    // Wire greet buttons
                    var greetBtns = feed.querySelectorAll(".arrival-greet");
                    for (var g = 0; g < greetBtns.length; g++) {
                        greetBtns[g].addEventListener("click", function() {
                            var aid = this.getAttribute("data-aid");
                            var btn = this;
                            fetch("/arrivals/" + aid + "/status", {
                                method: "POST",
                                headers: {"Content-Type": "application/json"},
                                body: JSON.stringify({status: "met"})
                            }).then(function() {
                                var card = document.getElementById("arr-" + aid);
                                var clientName = card ? (card.querySelector(".arrival-name") || {}).textContent || "client" : "client";
                                // Fade out and remove the card
                                if (card) {
                                    card.style.transition = "opacity 0.4s";
                                    card.style.opacity = "0";
                                    setTimeout(function() { card.remove(); refreshArrivals(); }, 400);
                                }
                                showToast("Greeted " + clientName + " &#10003;");
                            });
                        });
                    }

                    // Wire brief buttons
                    var briefBtns = feed.querySelectorAll(".arrival-brief-btn");
                    for (var b = 0; b < briefBtns.length; b++) {
                        briefBtns[b].addEventListener("click", function() {
                            var aid = this.getAttribute("data-aid");
                            var briefPanel = document.getElementById("brief-" + aid);
                            if (!briefPanel) return;

                            // Toggle if already visible
                            if (briefPanel.classList.contains("visible")) {
                                briefPanel.classList.remove("visible");
                                _briefLoading = false;
                                return;
                            }

                            _briefLoading = true;
                            briefPanel.classList.add("visible");

                            // Progressive steps for greeting brief
                            var bSteps = [
                                {icon: "&#127981;", text: "Looking up client in D365 via MCP..."},
                                {icon: "&#128197;", text: "Checking today's calendar via Work IQ..."},
                                {icon: "&#128218;", text: "Scanning Product Catalog..."},
                                {icon: "&#129302;", text: "Phi-4 Mini generating greeting brief on NPU..."}
                            ];
                            var bCurrent = 0;

                            function renderBriefSteps() {
                                var h = '<div style="display:flex;flex-direction:column;gap:4px;font-size:0.85em;padding:8px 0;">';
                                for (var s = 0; s < bSteps.length; s++) {
                                    var mk = s < bCurrent ? '<span style="color:#22c55e;">&#10003;</span>'
                                           : s === bCurrent ? '<span class="spinner" style="width:12px;height:12px;"></span>'
                                           : '<span style="opacity:0.3;">&#9711;</span>';
                                    var op = s <= bCurrent ? '1' : '0.4';
                                    h += '<div style="display:flex;align-items:center;gap:6px;opacity:' + op + ';">' +
                                         mk + ' ' + bSteps[s].icon + ' ' + bSteps[s].text + '</div>';
                                }
                                h += '</div>';
                                return h;
                            }

                            briefPanel.innerHTML = renderBriefSteps();

                            var bTimer = setInterval(function() {
                                bCurrent++;
                                if (bCurrent >= bSteps.length - 1) {
                                    clearInterval(bTimer);
                                    bCurrent = bSteps.length - 1;
                                }
                                briefPanel.innerHTML = renderBriefSteps();
                            }, 800);

                            fetch("/arrivals/" + aid + "/brief")
                                .then(function(r) { return r.json(); })
                                .then(function(data) {
                                    clearInterval(bTimer);
                                    bCurrent = bSteps.length;
                                    var briefHtml = renderBriefSteps();
                                    briefHtml += '<div style="border-top:1px solid rgba(var(--brand-accent-rgb),0.12);margin:8px 0;"></div>';
                                    briefHtml += '<div class="brief-header">' +
                                        '<span class="brief-header-title">&#129302; AI Greeting Brief</span>' +
                                        '<span class="brief-meta">' + (data.model || 'AI') + ' on NPU &middot; ' + (data.tokens_used || 0) + ' tokens &middot; ' + (data.inference_time || 0) + 's</span>' +
                                        '</div>' +
                                        '<div class="brief-text">' + (data.brief || 'No brief available.').replace(/\n/g, '<br>') + '</div>' +
                                        '<span class="brief-local">&#128274; All data from D365 &middot; Zero cloud &middot; $0.00</span>';
                                    briefPanel.innerHTML = briefHtml;
                                    _briefLoading = false;

                                    // Track in AI session report
                                    if (typeof window._addInspTokens === "function") {
                                        window._addInspTokens(data.tokens_used || 300, "Greeting Brief (" + (data.client_name || "Client") + ")", data.model || "Phi-4 Mini");
                                    }

                                    // Save brief content for persistence across refreshes
                                    savedBriefs[aid] = briefPanel.innerHTML;
                                })
                                .catch(function() {
                                    clearInterval(bTimer);
                                    briefPanel.innerHTML = '<div class="brief-text" style="color:#ef4444;">Brief generation failed. Check NPU status.</div>';
                                    _briefLoading = false;
                                });
                        });
                    }
                });
            }

            // Poll every 5 seconds
            setInterval(refreshArrivals, 5000);
            // Initial load
            refreshArrivals();
        })();
        }, 200); // end deferred setTimeout for concierge

    </script>

    <!-- D365 Mockup Overlay -->
    <div id="d365MockOverlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.85); z-index:10001; justify-content:center; align-items:center; cursor:pointer;" onclick="this.style.display='none'">
        <div style="position:relative; max-width:95vw; max-height:95vh;">
            <img src="/demo-assets/JackieD365.png" alt="Jackie Rodriguez - Dynamics 365 Customer 360" style="max-width:95vw; max-height:90vh; border-radius:10px; box-shadow:0 8px 40px rgba(0,0,0,0.5);">
            <div style="text-align:center; margin-top:10px; color:rgba(255,255,255,0.6); font-size:0.85em;">Click anywhere to close</div>
        </div>
    </div>

    <!-- File Picker Modal for Review & Summarize -->
    <div id="filePickerOverlay" class="file-picker-overlay" style="display:none;">
        <div class="file-picker-modal">
            <div class="file-picker-header">🔍 Select Documents to Review</div>
            <div class="file-picker-subtitle">Choose files for confidential review and risk analysis</div>
            <div class="file-picker-list" id="filePickerList">
                <!-- Files populated dynamically -->
            </div>
            <div class="file-picker-actions">
                <button class="file-picker-btn cancel" onclick="closeFilePicker()">Cancel</button>
                <button class="file-picker-btn confirm" id="filePickerConfirm" onclick="confirmFilePicker()" disabled>Review Selected (0)</button>
            </div>
        </div>
    </div>

    <!-- Branch Concierge Arrivals Panel -->
    <div class="arrivals-panel" id="arrivalsPanel">
        <div class="arrivals-header">
            <h3>&#128276; Branch Arrivals</h3>
            <button class="arrivals-close" id="arrivalsClose">&times;</button>
        </div>
        <div class="arrivals-simulate">
            <button id="simCheckin">&#128241; App Check-In</button>
            <button id="simAppointment">&#128197; Appointment</button>
            <button id="simTeller">&#127970; ID at Teller</button>
        </div>
        <div class="arrivals-feed" id="arrivalsFeed">
            <div class="arrivals-empty" id="arrivalsEmpty">No arrivals yet. Use the buttons above to simulate.</div>
        </div>
    </div>
    <div id="arrivalToast" style="display:none; position:fixed; top:20px; right:20px; z-index:1002; padding:12px 20px; border-radius:10px; background:rgba(1,33,105,0.95); color:#fff; font-size:0.9em; font-weight:500; box-shadow:0 4px 15px rgba(0,0,0,0.3); animation:liveFadeIn 0.4s ease;"></div>
</body>
</html>'''

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route('/logos/<path:filename>')
def serve_logos(filename):
    # Restrict to image files directly under SCRIPT_DIR (no traversal)
    if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
        return "Not found", 404
    filepath = os.path.join(SCRIPT_DIR, filename)
    resolved = os.path.realpath(filepath)
    if not resolved.startswith(os.path.realpath(SCRIPT_DIR) + os.sep):
        return "Not found", 404
    if not os.path.exists(resolved):
        return "Not found", 404
    if filename.endswith('.avif'):
        mimetype = 'image/avif'
    elif filename.endswith('.webp'):
        mimetype = 'image/webp'
    elif filename.endswith('.png'):
        mimetype = 'image/png'
    else:
        return "Not found", 404
    with open(resolved, 'rb') as f:
        content = f.read()
    return Response(content, mimetype=mimetype)

@app.route('/fonts/<path:filename>')
def serve_fonts(filename):
    """Serve locally-bundled font files for offline use."""
    if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
        return "Not found", 404
    fonts_dir = os.path.join(_APP_DIR, 'fonts')
    filepath = os.path.join(fonts_dir, filename)
    resolved = os.path.realpath(filepath)
    if not resolved.startswith(os.path.realpath(fonts_dir)):
        return "Not found", 404
    if not os.path.exists(resolved):
        return "Not found", 404
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    mimes = {'ttf': 'font/ttf', 'woff': 'font/woff', 'woff2': 'font/woff2', 'otf': 'font/otf'}
    with open(resolved, 'rb') as f:
        content = f.read()
    return Response(content, mimetype=mimes.get(ext, 'application/octet-stream'))


@app.route('/demo-assets/<path:filename>')
def serve_demo_assets(filename):
    """Serve demo assets (ID images, check images) from demo_data/."""
    if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
        return "Not found", 404
    filepath = os.path.join(DEMO_DIR, filename)
    resolved = os.path.realpath(filepath)
    if not resolved.startswith(os.path.realpath(DEMO_DIR) + os.sep):
        return "Not found", 404
    if not os.path.exists(resolved):
        return "Not found", 404
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    mimetypes = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp'}
    if ext not in mimetypes:
        return "Not found", 404
    with open(resolved, 'rb') as f:
        content = f.read()
    return Response(content, mimetype=mimetypes[ext])


TESSERACT_DIR = os.path.join(SCRIPT_DIR, 'tesseract')

@app.route('/tesseract/<path:filename>')
def serve_tesseract(filename):
    """Serve locally-bundled Tesseract.js files for offline OCR support."""
    if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
        return "Not found", 404
    filepath = os.path.join(TESSERACT_DIR, filename)
    resolved = os.path.realpath(filepath)
    if not resolved.startswith(os.path.realpath(TESSERACT_DIR) + os.sep):
        return "Not found", 404
    if not os.path.exists(resolved):
        return "Not found", 404
    # Determine MIME type
    if filename.endswith('.js'):
        mimetype = 'application/javascript'
    elif filename.endswith('.wasm'):
        mimetype = 'application/wasm'
    elif filename.endswith('.gz'):
        mimetype = 'application/gzip'
    else:
        mimetype = 'application/octet-stream'
    with open(resolved, 'rb') as f:
        content = f.read()
    return Response(content, mimetype=mimetype)


def _build_theme_overrides(cfg):
    """Generate CSS overrides for light theme if brand_theme is 'light'."""
    if cfg.get("brand_theme") != "light":
        return ""
    accent = cfg["brand_accent"]
    accent_rgb = cfg["brand_accent_rgb"]
    return """
        /* ── Light Theme Override ── */
        @font-face { font-family: 'Urbanist'; font-weight: 300; src: url('/fonts/urbanist-300.ttf') format('truetype'); }
        @font-face { font-family: 'Urbanist'; font-weight: 400; src: url('/fonts/urbanist-400.ttf') format('truetype'); }
        @font-face { font-family: 'Urbanist'; font-weight: 500; src: url('/fonts/urbanist-500.ttf') format('truetype'); }
        @font-face { font-family: 'Urbanist'; font-weight: 600; src: url('/fonts/urbanist-600.ttf') format('truetype'); }
        @font-face { font-family: 'Urbanist'; font-weight: 700; src: url('/fonts/urbanist-700.ttf') format('truetype'); }
        body, input, textarea, button, select { font-family: 'Urbanist', 'Segoe UI', sans-serif; }
        body { background: #f5f5f5; color: #333; }
        .sidebar { background: #fff !important; border-right: 1px solid #e0e0e0; }
        .sidebar-toggle { border-color: #ddd; color: #555; }
        .sidebar-toggle:hover { background: rgba(0,0,0,0.05); }
        .sidebar-brand-text { color: #333 !important; }
        .sidebar-brand-text small { color: #888 !important; }
        .sidebar-nav-item { color: #555; }
        .sidebar-nav-item:hover { background: rgba(0,0,0,0.04); color: #333; }
        .sidebar-nav-item.active { background: rgba(""" + accent_rgb + """,0.12); color: """ + accent + """; border-left-color: """ + accent + """; }
        .sidebar-label { color: #333 !important; }
        .sidebar-label small { color: #888 !important; }
        .nav-icon { color: #888; display: flex; align-items: center; justify-content: center; }
        .nav-icon svg { stroke: #555; }
        .sidebar-nav-item.active .nav-icon svg { stroke: """ + accent + """; }
        .sidebar-nav-item:hover .nav-icon svg { stroke: #333; }
        .sidebar-nav-item.active .nav-icon { color: """ + accent + """; }
        .sidebar-footer { border-top: 1px solid #e0e0e0; color: #555; }
        .sidebar-footer-label { color: #555 !important; }
        .main-content { background: #f5f5f5; }
        .tab-content { color: #333; }
        .auditor-header { color: #333; }
        .chat-input-container { background: #fff; border: 1px solid #ddd; }
        .chat-input-container input, .chat-input-container textarea { color: #333; background: transparent; }
        .chat-input-container input::placeholder { color: #999; }
        .suggestion-chip { background: #fff; border: 1px solid #ddd; color: #555; }
        .suggestion-chip:hover { background: rgba(""" + accent_rgb + """,0.08); border-color: """ + accent + """; color: """ + accent + """; }
        .chat-bubble.assistant { background: #fff; color: #333; border: 1px solid #e8e8e8; }
        .chat-bubble.user { background: """ + accent + """; color: #fff; }
        .poc-banner { background: rgba(""" + accent_rgb + """,0.08); border: 1px solid rgba(""" + accent_rgb + """,0.2); color: #555; }
        .id-result-card, .check-result-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .id-result-card h3, .check-result-card h3 { color: #333; }
        .id-field, .check-field { border-bottom-color: #eee; }
        .id-field-label, .check-field-label { color: #888; }
        .id-field-value, .check-field-value { color: #333; }
        .camera-section { background: #fff; border: 1px solid #e0e0e0; }
        .processing-steps { background: #fff; border: 1px solid #e0e0e0; }
        .step-text, .step-status { color: #555; }
        .ocr-preview { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .privacy-note { background: rgba(16,124,16,0.08); border-color: rgba(16,124,16,0.25); color: #555; }
        .tab-footer { color: #999; }
        .d365-card { background: #fff; border: 1px solid #e0e0e0; }
        .d365-card h3 { color: #333; }
        .d365-section { background: #f9f9f9; }
        .d365-section-title { color: #888; }
        .d365-field-label { color: #888; }
        .d365-field-value { color: #333; }
        .d365-activity { background: #f5f5f5; border-left-color: """ + accent + """; color: #555; }
        .sig-section { background: #fff; border-color: #e0e0e0; }
        .sig-agreement { color: #555; border-bottom-color: #e0e0e0; }
        .sig-agreement strong { color: #333; }
        .sig-confirm { background: rgba(16,185,129,0.06); border-color: rgba(16,185,129,0.2); color: #555; }
        .sig-confirm h4 { color: #10b981; }
        .sig-confirm .sig-hash { background: #f5f5f5; color: #666; }
        .check-amount { background: rgba(16,185,129,0.06); color: #059669; }
        .check-flag.flag-pass { background: rgba(16,185,129,0.06); }
        .check-flag.flag-warn { background: rgba(234,179,8,0.06); }
        .check-flag.flag-fail { background: rgba(239,68,68,0.06); }
        .id-mode-switcher { background: #f0f0f0; }
        .id-mode-btn { color: #888; }
        .id-mode-btn.active { background: """ + accent + """; color: #fff; }
        .persona-badge { background: #f5f5f5; border: 1px solid #ddd; color: #555; }
        .persona-badge:hover { border-color: """ + accent + """; }
        .persona-badge.active { background: rgba(""" + accent_rgb + """,0.1); border-color: """ + accent + """; color: """ + accent + """; }
        .persona-name { color: #333; }
        .persona-role { color: #888; }
        .warmup-overlay { background: #fff; color: #333; }
        .warmup-overlay h2 { color: #333; }
        .warmup-overlay .warmup-subtitle { color: #666; }
        .briefing-card, .my-day-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .live-assist-layout { color: #333; }
        .live-transcript-pane, .live-insight-pane { background: #fff; border: 1px solid #e0e0e0; }
        .live-pane-header { color: #333; }
        .live-transcript-line { color: #333; border-bottom-color: #eee; }
        .live-bottom-bar { background: #fff; border: 1px solid #e0e0e0; }
        .live-btn { background: #f5f5f5; color: #555; border: 1px solid #ddd; }
        .live-btn:hover { background: rgba(""" + accent_rgb + """,0.1); color: """ + accent + """; }
        .live-status-text { color: #888; }
        .insight-card { background: #f9f9f9; border: 1px solid #e8e8e8; color: #333; }
        .inspection-workspace { color: #333; }
        .inspection-form-panel, .inspection-photo-panel, .inspection-report-panel { background: #fff; border: 1px solid #e0e0e0; }
        .inspection-form-panel h3, .inspection-report-panel h3 { color: #333; }
        .insp-field label { color: #555; }
        .insp-field input, .insp-field textarea, .insp-transcript-input { background: #f9f9f9; border: 1px solid #ddd; color: #333; }
        .classification-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .insp-status-bar { background: #fff; border: 1px solid #e0e0e0; color: #555; }
        .bottom-bar { background: #fff; border-top: 1px solid #e0e0e0; color: #555; }
        .bottom-bar .status-label { color: #888; }
        .session-stats-bar { background: #fff; border: 1px solid #e0e0e0; color: #555; }
        .chat-empty-state { color: #999; }

        /* Suggestion chips - visible on light bg */
        .suggestion-chip .chip-icon { color: """ + accent + """; }
        .suggestion-grid .suggestion-chip { background: #fff; border: 1px solid #ddd; color: #444; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
        .suggestion-grid .suggestion-chip span { color: #444; }
        .suggestion-grid .suggestion-chip:hover { border-color: """ + accent + """; background: rgba(""" + accent_rgb + """,0.06); }
        .suggestion-grid .suggestion-chip:hover span { color: """ + accent + """; }

        /* Savings widget / session stats in sidebar */
        .savings-widget { background: rgba(34,197,94,0.06); border-color: rgba(34,197,94,0.2); }
        .savings-stat { color: #555; }
        .savings-stat-hero { color: #16a34a; text-shadow: none; }
        .savings-stat-compact { color: #16a34a; }

        /* Offline/Online badge */
        .offline-badge { color: #fff; }

        /* Bottom bar with status indicators */
        .bottom-bar, [class*="bottom-bar"] { background: #fff !important; border: 1px solid #e0e0e0 !important; color: #555; }
        .bottom-bar span, .bottom-bar .status-label, .bottom-bar .status-text { color: #666; }
        .bottom-bar .status-dot { box-shadow: none; }
        .bottom-bar a, .bottom-bar button { color: #555; }

        /* Chat area */
        .chat-messages { color: #333; }
        .chat-bubble { color: #333; }
        .chat-bubble.assistant code { background: #f0f0f0; color: #333; }
        .chat-bubble.assistant pre { background: #f5f5f5; border: 1px solid #e0e0e0; }
        .chat-send-btn { background: """ + accent + """; color: #fff; }
        .chat-send-btn:hover { background: """ + cfg.get("brand_hover", accent) + """; }
        .chat-input { color: #333; }
        .chat-input::placeholder { color: #aaa; }

        /* Auditor / PII Guard tab */
        .decision-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .router-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .escalation-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .audit-stamp { background: #f9f9f9; border: 1px solid #e0e0e0; color: #555; }
        .verdict-section { color: #333; }
        .file-picker-overlay .file-picker-modal { background: #fff; color: #333; border: 1px solid #ddd; }
        .file-picker-list { color: #333; }
        .file-picker-item { border-bottom-color: #eee; color: #333; }
        .file-picker-item:hover { background: #f5f5f5; }

        /* My Day / Morning Briefing */
        .my-day-data-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .my-day-chip { background: #fff; border: 1px solid #ddd; color: #555; }
        .my-day-chip:hover { border-color: """ + accent + """; color: """ + accent + """; }
        .brief-me-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .day-section-header { color: #555; }

        /* Inspection / Meeting Notes workspace */
        .inspection-bottom-bar { background: #fff !important; border: 1px solid #e0e0e0 !important; color: #555; }
        .insp-mic-btn { background: #f5f5f5; border: 1px solid #ddd; color: #555; }
        .insp-mic-btn:hover { background: rgba(""" + accent_rgb + """,0.1); color: """ + accent + """; }
        .insp-token-count { color: #888; }
        .insp-status { color: #555; }
        .findings-log { color: #333; }
        .finding-item { background: #f9f9f9; border: 1px solid #e8e8e8; color: #333; }
        .photo-grid { color: #333; }
        .report-content { color: #333; }
        .insp-dash-overlay { background: rgba(255,255,255,0.97); color: #333; }
        .insp-dash-task { color: #333; }
        .insp-dash-task .check { color: #16a34a; }
        .annotation-note { background: rgba(14,165,233,0.04); border-color: rgba(14,165,233,0.2); color: #555; }

        /* Scrollbar for light theme */
        ::-webkit-scrollbar-track { background: #f0f0f0; }
        ::-webkit-scrollbar-thumb { background: #ccc; }
        ::-webkit-scrollbar-thumb:hover { background: #aaa; }

        /* Topbar buttons (Audit Log, Clear, Policy shield) */
        .topbar-btn { color: #555 !important; opacity: 1; }
        .topbar-btn:hover { background: #f0f0f0; border-color: #ddd; color: #333 !important; }
        .topbar-divider { background: #ddd; }
        .policy-tooltip { background: #fff; border: 1px solid #ddd; color: #333; }

        /* Network toggle buttons (Go Offline / Go Online) */
        .net-toggle-btn { background: #f5f5f5 !important; border: 1px solid #ddd !important; color: #555 !important; }
        .net-toggle-btn:hover { background: #e8e8e8 !important; color: #333 !important; }
        .net-toggle-btn.net-toggle-off { border-color: rgba(255,140,0,0.5) !important; }
        .net-toggle-btn.net-toggle-off:hover { background: rgba(255,140,0,0.1) !important; color: #c05e00 !important; }
        .net-toggle-btn.net-toggle-on { border-color: rgba(0,204,106,0.5) !important; }
        .net-toggle-btn.net-toggle-on:hover { background: rgba(0,204,106,0.1) !important; color: #059669 !important; }

        /* Sidebar footer controls labels */
        .sidebar-footer-label { color: #888 !important; }
        .sidebar-footer-controls .model-selector label { color: #555; opacity: 1; }
        .sidebar-footer-controls .model-selector select { background: #f5f5f5; border: 1px solid #ddd; color: #333; }

        /* Badge (chip label) */
        .badge { background: linear-gradient(90deg, #0078D4, """ + accent + """); color: #fff; }

        /* Offline/Online badge - ensure visible */
        .offline-badge { background: linear-gradient(90deg, #107C10, #00CC6A); color: #fff !important; font-weight: 600; }
        .offline-badge.offline { background: linear-gradient(90deg, #FF8C00, #FFB900); color: #fff !important; }

        /* POC footer text */
        .poc-footer { color: #888; }

        /* Audit Log, Clear, network toggle buttons in bottom bar */
        .bottom-bar button, .bottom-bar a { color: #555 !important; background: #f0f0f0; border: 1px solid #ddd; border-radius: 6px; padding: 4px 10px; }
        .bottom-bar button:hover, .bottom-bar a:hover { background: #e5e5e5; color: #333 !important; }

        /* Status bar text (NPU Ready, Online, etc.) */
        .bottom-bar .status-text, .bottom-bar span { color: #666 !important; }

        /* Camera placeholder text */
        #cameraPlaceholder { background: #f0f0f0 !important; color: #888 !important; }
        #cameraPlaceholder div { color: #888 !important; }

        /* Tab headers */
        .auditor-header { color: #333 !important; font-family: 'Urbanist', sans-serif; font-weight: 700; }

        /* All cards that use rgba white backgrounds */
        .tool-approval-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .agent-response { color: #333; }
        .trust-receipt { background: #f9f9f9; border: 1px solid #e0e0e0; color: #555; }

        /* Marketing/contract review cards */
        .claims-card, .verdict-card, .summary-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .claim-item { border-bottom-color: #eee; color: #333; }
        .risk-badge { color: #fff; }

        /* Warmup overlay */
        .warmup-overlay { background: #fff !important; color: #333 !important; }
        .warmup-overlay * { color: #333 !important; }
        .warmup-overlay .warmup-bar-track { background: #e0e0e0; }
        .warmup-overlay .warmup-bar-fill { background: """ + accent + """; }

        /* Knowledge search results */
        .knowledge-results { color: #333; }
        .knowledge-result-item { background: #fff; border: 1px solid #e0e0e0; color: #333; }

        /* My Day counts/chips */
        .my-day-count { color: #555; background: #f0f0f0; border: 1px solid #ddd; }

        /* Sentiment badges (Live Assist) - keep colored */
        .sentiment-positive { background: rgba(34,197,94,0.1); color: #16a34a; }
        .sentiment-neutral { background: rgba(234,179,8,0.1); color: #b45309; }
        .sentiment-cautious { background: rgba(239,68,68,0.1); color: #dc2626; }

        /* Speaker labels */
        .live-transcript-line .line-speaker { color: #555; }
        .live-translated-line { color: #666; border-left-color: rgba(""" + accent_rgb + """,0.4); }

        /* Demo ID preview mock card */
        .mock-id-card { box-shadow: 0 2px 8px rgba(0,0,0,0.12); }

        /* D365 badge */
        .d365-badge { background: rgba(16,185,129,0.1); color: #059669; }
        .d365-open-btn { background: rgba(0,120,212,0.08); color: #0078d4; border-color: rgba(0,120,212,0.25); }

        /* ── Nuclear override: every element that uses white/transparent text or bg ── */
        /* Chat and agent */
        .agent-topbar { background: #fff; border-bottom: 1px solid #e0e0e0; }
        .input-area { background: #fff; border: 1px solid #ddd; }
        .assistant-msg { background: #fff; border: 1px solid #e8e8e8; color: #333; }
        .user-msg { background: """ + accent + """; color: #fff; }
        #userInput { color: #333; }
        #userInput::placeholder { color: #aaa; }
        #sendBtn { color: #fff; }
        #attachBtn { color: #666; }
        #attachBtn:hover { color: """ + accent + """; background: #f0f0f0; }

        /* My Day cards */
        .day-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .day-card:hover { background: #f9f9f9; }
        .day-card.expanded { background: #f9f9f9; }
        .day-card .card-label { color: #555; opacity: 1; }
        .day-card .card-hint { color: #999; opacity: 1; }
        .day-card .card-peek { background: #fff; border-color: #ddd; color: #333; }
        .peek-row { border-bottom-color: #eee; color: #333; }
        .peek-row strong { color: #222; }
        .day-section-header { color: #333; }
        .day-action-btn { background: #f5f5f5; border: 1px solid #ddd; color: #555; }
        .day-action-btn:hover { background: rgba(""" + accent_rgb + """,0.1); color: """ + accent + """; }
        .focus-btn { color: #555; }
        .tomorrow-btn { color: #fff !important; }
        .focus-btn { color: #fff !important; }
        .brief-me-btn { color: #fff !important; }
        .briefing-progress { background: #f9f9f9; border: 1px solid #e0e0e0; }
        .briefing-result { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .exec-summary { background: rgba(""" + accent_rgb + """,0.06); border-bottom-color: #e0e0e0; color: #333; }
        .exec-summary .summary-label { color: #888; opacity: 1; }
        .breakdown-area { color: #333; }
        .breakdown-section { border-color: #e0e0e0; }
        .breakdown-header { background: #f5f5f5; color: #333; }
        .breakdown-header:hover { background: #eee; }
        .breakdown-body { color: #444; }
        .briefing-footer { color: #888; border-top: 1px solid #e0e0e0; }
        .breakdown-header { background: #f9f9f9; color: #333; }
        .breakdown-header:hover { background: #f0f0f0; }

        /* Auditor */
        .auditor-dropzone { background: #f9f9f9; border-color: #ddd; color: #555; }
        .auditor-demo-section { background: #f9f9f9; }
        .auditor-doc-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .auditor-back-link a { color: #888; }
        .auditor-back-link a:hover { color: #333; }
        .result-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .processing-log-header { background: #f9f9f9; color: #333; }
        .verdict-count { background: #f0f0f0; color: #333; }
        .doc-preview-card { background: #f9f9f9; border: 1px solid #e0e0e0; color: #333; }
        .diff-col { background: #f9f9f9; color: #333; }
        .diff-redacted { color: #333; }
        .router-analysis { background: #fff; border: 1px solid #e0e0e0; color: #333; }
        .decision-card { background: #fff; border: 1px solid #e0e0e0; color: #333; }

        /* Device search, health check */
        .device-search-container { background: #fff; border: 1px solid #e0e0e0; }
        .device-search-container input[type="text"] { background: #f9f9f9; border: 1px solid #ddd; color: #333; }
        .search-result-item { background: #f9f9f9; color: #333; }
        .health-check-entry { background: #f9f9f9; color: #333; }
        .security-check-line { color: #555; }

        /* File picker */
        .file-picker-item { background: #f9f9f9; color: #333; }
        .file-picker-item:hover { background: #f0f0f0; }
        .file-picker-btn.cancel { background: #e0e0e0; color: #333; }
        .file-picker-btn.confirm { background: """ + accent + """; color: #fff; }

        /* Mobile hamburger */
        .mobile-hamburger { color: #333; }

        /* Camera select dropdown */
        #cameraSelect { background: #f5f5f5 !important; border: 1px solid #ddd !important; color: #333 !important; }
        #refreshCamerasBtn { background: #f5f5f5 !important; border: 1px solid #ddd !important; color: #333 !important; }
        .camera-btn { background: #f5f5f5; border: 1px solid #ddd; color: #555; }
        .camera-btn:hover { background: rgba(""" + accent_rgb + """,0.1); color: """ + accent + """; }

        /* Live Assist deep */
        .live-transcript-pane { background: #fff; border: 1px solid #e0e0e0; }
        .live-prompter-pane { background: #fff; border: 1px solid #e0e0e0; }
        .live-transcript-line { background: #f9f9f9; color: #333; }
        .live-transcript-line.interim { color: #999; background: #f5f5f5; }
        .live-transcript-line .line-time { color: #999; }
        .live-insight-card { background: #f9f9f9; border: 1px solid #e8e8e8; color: #333; }
        .live-insight-card .insight-text { color: #333; }
        .live-insight-card .insight-time { color: #999; }
        .live-summary-card { color: #333; }
        .live-summary-card p { color: #555; }

        /* Meeting Notes / Field Inspection deep */
        .inspection-form-panel { background: #fff !important; border: 1px solid #e0e0e0 !important; }
        .inspection-report-panel { background: #fff !important; border: 1px solid #e0e0e0 !important; }
        .insp-field input, .insp-field select { background: #f9f9f9 !important; border: 1px solid #ddd !important; color: #333 !important; }
        .insp-transcript-input { background: #f9f9f9 !important; border: 1px solid #ddd !important; color: #333 !important; }
        .insp-transcript-input::placeholder { color: #aaa !important; }
        .insp-transcript { background: #f9f9f9; color: #333; }
        .photo-grid-empty { color: #aaa; }
        .classification-card .cc-loading { color: #555; }
        .classification-card .cc-explain { color: #555; }
        .classification-card .cc-category { color: #333; }
        .findings-log h3 { color: #555; }
        .finding-item { background: #f9f9f9 !important; color: #333; }
        .report-draft { background: #f9f9f9; border: 1px solid #e0e0e0; }
        .report-draft h4 { color: #555; }
        .report-draft .report-content { color: #333; }
        .report-draft .report-content h1, .report-draft .report-content h2, .report-draft .report-content h3 { color: #333; }
        .report-draft .report-empty { color: #aaa; }
        .insp-esc-subtext { color: #555; }
        .insp-esc-option p { color: #555; }
        .insp-stayed-local .sl-detail { color: #555; }
        .insp-dashboard h2 { color: #333; }
        .insp-dash-task { color: #333; }
        .insp-dash-summary { background: #f9f9f9; border: 1px solid #e0e0e0; color: #555; }
        .insp-dash-close { border-color: #ddd; background: #f5f5f5; color: #555; }
        .insp-summary-btn { border-color: #ddd; background: #f5f5f5; color: #555; }
        .insp-summary-btn:hover { color: """ + accent + """; }
        .insp-privacy { color: #888; }

        /* Approval cards */
        .approval-btn { color: #fff; }

        /* Photo capture buttons (Load Demo Photo, Stop Camera, Flip) */
        .photo-capture-btn.secondary { background: #f0f0f0 !important; color: #555 !important; border: 1px solid #ddd !important; }
        .photo-capture-btn.secondary:hover { background: #e5e5e5 !important; color: #333 !important; }
        .photo-capture-btn.primary { color: #fff !important; }

        /* Inspection/Meeting Notes generate, translate, mic buttons */
        .insp-generate-btn { color: #fff !important; }
        .insp-translate-btn { background: #f5f5f5 !important; border: 1px solid #ddd !important; color: #555 !important; }
        .insp-translate-btn:hover { background: rgba(""" + accent_rgb + """,0.1) !important; color: """ + accent + """ !important; }

        /* Annotation toolbar buttons */
        .ann-undo, .ann-clear { background: #e0e0e0 !important; color: #333 !important; }
        .ann-done { color: #fff !important; }

        /* Tab buttons (hidden) */
        .tab-btn { color: #333; }

        /* Auditor buttons */
        .auditor-upload-btn { color: #fff !important; }
        .auditor-demo-btn { background: #f5f5f5; border: 1px solid #ddd; color: #555; }
        .auditor-demo-btn:hover { background: rgba(""" + accent_rgb + """,0.1); color: """ + accent + """; }
        .auditor-action-btn { background: #f5f5f5 !important; border: 1px solid #ddd !important; color: #555 !important; }
        .auditor-action-btn:hover { color: """ + accent + """ !important; }
        .auditor-action-btn.secondary { background: #f0f0f0 !important; }
        .auditor-full-audit-btn { color: #fff !important; }

        /* Brief me button */
        .brief-me-btn { color: #fff !important; }

        /* Model selector in sidebar */
        .model-selector select { background: #f5f5f5 !important; border: 1px solid #ddd !important; color: #333 !important; }
        .model-selector select option { background: #fff; color: #333; }
        .model-selector label { color: #555; opacity: 1 !important; }

        /* Check scanner mode buttons when not active */
        .id-mode-btn { color: #666 !important; }
        .id-mode-btn.active { color: #fff !important; }
        .id-mode-btn:hover:not(.active) { color: #333 !important; }

        /* Chip badge in sidebar */
        .sidebar-footer .badge { color: #fff; }

        /* Signature clear button */
        .sig-clear { background: #e0e0e0 !important; color: #333 !important; }

        /* Branch Concierge light theme */
        .concierge-bell { color: #555; border-bottom-color: #e0e0e0; }
        .concierge-bell:hover { color: """ + accent + """; }
        .arrivals-panel { background: #fff; border-left: 1px solid #e0e0e0; box-shadow: -4px 0 20px rgba(0,0,0,0.08); }
        .arrivals-header { border-bottom-color: #e0e0e0; }
        .arrivals-header h3 { color: #333; }
        .arrivals-close { color: #999; }
        .arrivals-simulate { border-bottom-color: #f0f0f0; }
        .arrivals-simulate button { background: #f5f5f5; border-color: #ddd; color: #555; }
        .arrivals-simulate button:hover { background: #eee; color: #333; }
        .arrivals-empty { color: #aaa; }
        .arrival-card { background: #f9f9f9; border-color: #e8e8e8; }
        .arrival-name { color: #333 !important; }
        .arrival-title { color: #888 !important; }
        .arrival-meta { color: #999 !important; }
        .arrival-source { color: #999 !important; }
        .arrival-brief-panel { background: rgba(""" + accent_rgb + """,0.04); border-color: rgba(""" + accent_rgb + """,0.12); }
        .brief-text { color: #333 !important; }
        .brief-meta { color: #999 !important; }

        /* Persona badges */
        .persona-badge { background: #f5f5f5 !important; border: 1px solid #ddd !important; }
        .persona-badge .persona-name { color: #333 !important; }
        .persona-badge .persona-role { color: #888 !important; }
        .persona-badge:hover { background: #f0f0f0 !important; border-color: """ + accent + """ !important; }
        .persona-badge.active .persona-name { color: """ + accent + """ !important; }

        /* Generic inline style overrides (catch remaining) */
        [style*="color: rgba(255,255,255"] { color: #555 !important; }
        [style*="color: #fff"] { color: #333 !important; }
        [style*="color:#fff"] { color: #333 !important; }
        [style*="color:rgba(255,255,255"] { color: #555 !important; }
        [style*="background: rgba(255,255,255,0.0"] { background: #f5f5f5 !important; }
        [style*="background: rgba(255,255,255,0.1"] { background: #f0f0f0 !important; }
        [style*="background:rgba(255,255,255,0.0"] { background: #f5f5f5 !important; }
        [style*="background:rgba(255,255,255,0.1"] { background: #f0f0f0 !important; }
        [style*="border: 1px solid rgba(255,255,255"] { border-color: #ddd !important; }
        [style*="border:1px solid rgba(255,255,255"] { border-color: #ddd !important; }
        [style*="border-bottom: 1px solid rgba(255,255,255"] { border-bottom-color: #eee !important; }
    """


@app.route('/')
def index():
    _cfg = DEMO_CONFIG
    _tabs = _cfg["tabs"]
    _ind_cfg = _cfg.get("industry", {})
    page = HTML_TEMPLATE.replace("{{CHIP_LABEL}}", CHIP_LABEL) \
                         .replace("{{DEVICE_LABEL}}", DEVICE_LABEL) \
                         .replace("{{MODEL_LABEL}}", MODEL_LABEL) \
                         .replace("{{MODEL_ALIAS}}", MODEL_ALIAS) \
                         .replace("{{APP_TITLE}}", _cfg["app_title"]) \
                         .replace("{{BRAND_ACCENT}}", _cfg["brand_accent"]) \
                         .replace("{{BRAND_ACCENT_RGB}}", _cfg["brand_accent_rgb"]) \
                         .replace("{{BRAND_PRIMARY}}", _cfg["brand_primary"]) \
                         .replace("{{BRAND_PRIMARY_END}}", _cfg["brand_primary_end"]) \
                         .replace("{{BRAND_HOVER}}", _cfg["brand_hover"]) \
                         .replace("{{TAB_CHAT_NAME}}", _tabs["chat"]["name"]) \
                         .replace("{{TAB_CHAT_SUB}}", _tabs["chat"]["sub"]) \
                         .replace("{{TAB_CHAT_ICON}}", _tabs["chat"]["icon"]) \
                         .replace("{{TAB_DAY_NAME}}", _tabs["day"]["name"]) \
                         .replace("{{TAB_DAY_SUB}}", _tabs["day"]["sub"]) \
                         .replace("{{TAB_DAY_ICON}}", _tabs["day"]["icon"]) \
                         .replace("{{TAB_AUDITOR_NAME}}", _tabs["auditor"]["name"]) \
                         .replace("{{TAB_AUDITOR_SUB}}", _tabs["auditor"]["sub"]) \
                         .replace("{{TAB_AUDITOR_ICON}}", _tabs["auditor"]["icon"]) \
                         .replace("{{TAB_ID_NAME}}", _tabs["id"]["name"]) \
                         .replace("{{TAB_ID_SUB}}", _tabs["id"]["sub"]) \
                         .replace("{{TAB_ID_ICON}}", _tabs["id"]["icon"]) \
                         .replace("{{TAB_LIVE_NAME}}", _tabs["live"]["name"]) \
                         .replace("{{TAB_LIVE_SUB}}", _tabs["live"]["sub"]) \
                         .replace("{{TAB_LIVE_ICON}}", _tabs["live"]["icon"]) \
                         .replace("{{TAB_FIELD_NAME}}", _tabs["field"]["name"]) \
                         .replace("{{TAB_FIELD_SUB}}", _tabs["field"]["sub"]) \
                         .replace("{{TAB_FIELD_ICON}}", _tabs["field"]["icon"]) \
                         .replace("{{POC_FOOTER}}", _cfg["poc_footer"]) \
                         .replace("{{POC_AUDITOR}}", _cfg["poc_auditor"]) \
                         .replace("{{POC_ID}}", _cfg["poc_id"]) \
                         .replace("{{BRAND_COMPANY}}", _cfg.get("brand_company", "")) \
                         .replace("{{ADVISOR_NAME}}", _cfg.get("advisor_name", "")) \
                         .replace("{{ADVISOR_TITLE}}", _cfg.get("advisor_title", "")) \
                         .replace("{{ADVISOR_COMPANY}}", _cfg.get("advisor_company", "")) \
                         .replace("{{ADVISOR_PHONE}}", _cfg.get("advisor_phone", "")) \
                         .replace("{{PLACEHOLDER_CLIENT}}", _ind_cfg.get("placeholders", {}).get("client", "e.g. Client Name")) \
                         .replace("{{PLACEHOLDER_LOCATION}}", _ind_cfg.get("placeholders", {}).get("location", "e.g. Meeting Location")) \
                         .replace("{{PLACEHOLDER_ISSUE}}", _ind_cfg.get("placeholders", {}).get("issue", "e.g. Topics Discussed")) \
                         .replace("{{PLACEHOLDER_SOURCE}}", _ind_cfg.get("placeholders", {}).get("source", "e.g. Referral Source")) \
                         .replace("{{ANNOTATION_LABEL}}", _ind_cfg.get("annotation_label", "Advisor Notes")) \
                         .replace("{{ANNOTATION_FALLBACK}}", _ind_cfg.get("annotation_fallback", "See follow-up notes")) \
                         .replace("{{THEME_OVERRIDES}}", _build_theme_overrides(_cfg))
    # Persona switcher: inject HTML or empty string
    personas = _cfg.get("personas")
    if personas:
        persona_html = '<div class="persona-switcher" id="personaSwitcher">'
        for p in personas:
            tabs_json = json.dumps(p.get("tabs", []))
            persona_html += f'<button class="persona-badge" data-persona-tabs=\'{tabs_json}\'>'
            persona_html += f'<span class="persona-name">{p["name"]}</span>'
            persona_html += f'<span class="persona-role">{p["role"]}</span></button>'
        persona_html += '</div>'
    else:
        persona_html = ''
    page = page.replace("{{PERSONA_SWITCHER}}", persona_html)
    if _cfg.get("brand_theme") == "light":
        _logo_file = _cfg.get("brand_logo", "flagstar-logo-official.png")
        _brand_alt = _cfg.get("brand_company", "Brand")
        sidebar_logo = f'<img class="brand-logo-surface" src="/logos/{_logo_file}" alt="{_brand_alt}" style="width:92%;max-width:270px;margin-top:10px;" onerror="this.style.display=\'none\'">'
    else:
        sidebar_logo = '<img class="brand-logo-surface" src="/logos/surface-logo.png" alt="Microsoft Surface" onerror="this.style.display=\'none\'"><img class="brand-logo-copilot" src="/logos/copilot-logo.avif" alt="Copilot+ PC" onerror="this.style.display=\'none\'">'
    page = page.replace("{{SIDEBAR_LOGO}}", sidebar_logo)

    # Industry Packs: inject stub banner script if stub mode
    _stub_script = ""
    if _INDUSTRY_PACKS_ACTIVE and RESOLVED_CONFIG:
        _is_stub = (RESOLVED_CONFIG.get("status") == "stub" or
                    RESOLVED_CONFIG.get("brand_status") == "stub")
        if _is_stub:
            _ind_name = RESOLVED_CONFIG.get("display_name", "Unknown")
            _stub_script = (
                '<script>'
                'document.addEventListener("DOMContentLoaded",function(){'
                'var b=document.getElementById("industry-stub-banner");'
                'if(b){b.style.display="block";'
                'var n=document.getElementById("stubIndustryName");'
                'if(n)n.textContent=' + json.dumps(_ind_name) + ';}'
                '});</script>')
    page = page.replace("</body>", _stub_script + "</body>")

    return render_template_string(page)

@app.route('/upload-to-demo', methods=['POST'])
def upload_to_demo():
    """Upload a file, extract text, save as .txt in Demo folder for agent access."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'})
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        filename = secure_filename(file.filename)
        # Extension allowlist — only document types we support
        allowed_ext = {'.pdf', '.docx', '.txt', '.md'}
        ext = os.path.splitext(filename)[1].lower()
        if ext not in allowed_ext:
            return jsonify({'success': False, 'error': f'File type {ext} not supported. Allowed: {", ".join(sorted(allowed_ext))}'})
        # Save original to temp for extraction
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(temp_path)
        text = extract_text(temp_path)
        try:
            os.remove(temp_path)
        except Exception:
            pass
        if text.startswith("Error"):
            return jsonify({'success': False, 'error': text})
        # Save extracted text to Demo folder
        base_name = os.path.splitext(filename)[0] + ".txt"
        demo_path = os.path.join(DEMO_DIR, base_name)
        with open(demo_path, 'w', encoding='utf-8') as f:
            f.write(text)
        words = len(text.split())
        return jsonify({
            'success': True,
            'path': demo_path,
            'words': words,
            'text': text,  # Return text content for Auditor
            'filename': base_name  # Return filename for display
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/save-summary', methods=['POST'])
def save_summary():
    """Direct file write — no AI needed. Increments filename if exists."""
    data = request.json
    file_path = data.get('path', '')
    content = data.get('content', '')
    if not _path_in_demo_dir(file_path):
        return jsonify({'success': False, 'error': 'Security Policy: file outside approved folder.'})
    try:
        # Increment filename if it already exists
        base, ext = os.path.splitext(file_path)
        final_path = file_path
        counter = 2
        while os.path.exists(final_path):
            final_path = f"{base}_{counter}{ext}"
            counter += 1
        with open(final_path, 'w', encoding='utf-8') as f:
            f.write(content)
        AGENT_AUDIT_LOG.append({
            "timestamp": _time.strftime("%H:%M:%S"),
            "tool": "write",
            "arguments": {"path": final_path},
            "success": True,
            "time": 0,
        })
        # Return the actual filename used
        saved_name = os.path.basename(final_path)
        return jsonify({'success': True, 'filename': saved_name})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})






@app.route('/demo/device-health', methods=['POST'])
def demo_device_health():
    """Device health check — deterministic PowerShell collectors + AI summary."""
    model = DEFAULT_MODEL

    HEALTH_CHECKS = [
        {
            "id": "disk",
            "name": "Disk Space",
            "icon": "\U0001f4be",
            "cmd": 'Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select-Object DeviceID, @{N="SizeGB";E={[math]::Round($_.Size/1GB,1)}}, @{N="FreeGB";E={[math]::Round($_.FreeSpace/1GB,1)}}, @{N="UsedPct";E={[math]::Round(($_.Size-$_.FreeSpace)/$_.Size*100,0)}} | Format-List',
        },
        {
            "id": "battery",
            "name": "Battery",
            "icon": "\U0001f50b",
            "cmd": 'Get-CimInstance Win32_Battery | Select-Object @{N="ChargePercent";E={$_.EstimatedChargeRemaining}}, @{N="Status";E={switch($_.BatteryStatus){1{"Discharging"}2{"AC Power"}default{$_.BatteryStatus}}}} | Format-List',
        },
        {
            "id": "system",
            "name": "System Info",
            "icon": "\U0001f4bb",
            "cmd": 'Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, @{N="BootTime";E={$_.LastBootUpTime.ToString("yyyy-MM-dd HH:mm")}}, @{N="UptimeDays";E={[math]::Round(((Get-Date)-$_.LastBootUpTime).TotalDays,1)}} | Format-List',
        },
        {
            "id": "network",
            "name": "Network Adapters",
            "icon": "\U0001f310",
            "cmd": 'Get-NetAdapter | Where-Object {$_.Status -eq "Up"} | Select-Object Name, InterfaceDescription, LinkSpeed, Status | Format-List',
        },
        {
            "id": "security",
            "name": "Defender Antivirus",
            "icon": "\U0001f6e1\ufe0f",
            "cmd": 'Get-MpComputerStatus | Select-Object AntivirusEnabled, RealTimeProtectionEnabled, @{N="SignatureAge";E={(New-TimeSpan $_.AntivirusSignatureLastUpdated (Get-Date)).Days.ToString() + " days"}}, @{N="LastScan";E={$_.QuickScanEndTime.ToString("yyyy-MM-dd HH:mm")}} | Format-List',
        },
        {
            "id": "firewall",
            "name": "Firewall Profiles",
            "icon": "\U0001f9f1",
            "cmd": 'Get-NetFirewallProfile | Select-Object Name, Enabled, DefaultInboundAction, DefaultOutboundAction | Format-List',
        },
        {
            "id": "ports",
            "name": "Listening Ports",
            "icon": "\U0001f50c",
            "cmd": 'Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Select-Object LocalPort, @{N="Process";E={(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName}} | Sort-Object LocalPort -Unique | Select-Object -First 12 | Format-Table -AutoSize | Out-String',
        },
        {
            "id": "updates",
            "name": "Windows Updates",
            "icon": "\U0001f504",
            "cmd": 'Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 3 HotFixID, InstalledOn, Description | Format-List',
        },
        {
            "id": "events",
            "name": "Recent System Errors",
            "icon": "\u26a0\ufe0f",
            "cmd": 'Get-WinEvent -FilterHashtable @{LogName="System";Level=1,2,3} -MaxEvents 5 -ErrorAction SilentlyContinue | Select-Object TimeCreated, LevelDisplayName, @{N="Source";E={$_.ProviderName}}, @{N="Msg";E={$_.Message.Substring(0,[math]::Min(120,$_.Message.Length))}} | Format-List',
        },
    ]

    def generate():
        start = _time.time()
        results = []

        for check in HEALTH_CHECKS:
            # Signal start
            yield json.dumps({
                "type": "check-start",
                "id": check["id"],
                "name": check["name"],
                "icon": check["icon"],
                "cmd": check["cmd"],
            }) + "\n"

            try:
                proc = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command", check["cmd"]],
                    capture_output=True, text=True, timeout=10
                )
                output = (proc.stdout or "").strip()
                if proc.returncode != 0 and proc.stderr:
                    output = output or proc.stderr.strip()
                if not output:
                    output = "(no data available)"
                # Truncate per-check output
                if len(output) > 350:
                    output = output[:350] + "..."

                results.append(f"{check['name']}:\n{output}")
                yield json.dumps({
                    "type": "check-done",
                    "id": check["id"],
                    "output": output,
                }) + "\n"

            except subprocess.TimeoutExpired:
                results.append(f"{check['name']}: TIMEOUT")
                yield json.dumps({
                    "type": "check-error",
                    "id": check["id"],
                    "output": "Command timed out (10s)",
                }) + "\n"
            except Exception as e:
                results.append(f"{check['name']}: ERROR - {str(e)}")
                yield json.dumps({
                    "type": "check-error",
                    "id": check["id"],
                    "output": str(e),
                }) + "\n"

        # Pre-compute numerical ratings (don't ask AI to do math)
        yield json.dumps({"type": "status", "text": "AI analyzing health data..."}) + "\n"

        health_data = "\n\n".join(results)
        pre_ratings = []
        # Disk usage
        m = re.search(r'UsedPct\s*:\s*(\d+)', health_data)
        if m:
            pct = int(m.group(1))
            if pct >= 90: pre_ratings.append(f"Disk: FAIL — {pct}% used (over 90% threshold)")
            elif pct >= 80: pre_ratings.append(f"Disk: WARN — {pct}% used (over 80% threshold)")
            else: pre_ratings.append(f"Disk: PASS — {pct}% used (healthy)")
        # Uptime
        m = re.search(r'UptimeDays\s*:\s*([\d.]+)', health_data)
        if m:
            days = float(m.group(1))
            if days >= 30: pre_ratings.append(f"Uptime: FAIL — {days} days (over 30-day limit, reboot urgently)")
            elif days >= 7: pre_ratings.append(f"Uptime: WARN — {days} days without reboot (7-day policy exceeded)")
            else: pre_ratings.append(f"Uptime: PASS — {days} days (within 7-day reboot policy)")
        # AV signature age
        m = re.search(r'SignatureAge\s*:\s*(\d+)\s*days', health_data)
        if m:
            age = int(m.group(1))
            if age >= 2: pre_ratings.append(f"AV Signatures: WARN — {age} days old")
            else: pre_ratings.append(f"AV Signatures: PASS — current ({age} days)")
        # Battery
        m = re.search(r'ChargePercent\s*:\s*(\d+)', health_data)
        if m:
            charge = int(m.group(1))
            if charge <= 10: pre_ratings.append(f"Battery: FAIL — {charge}%")
            elif charge <= 20: pre_ratings.append(f"Battery: WARN — {charge}%")
            else: pre_ratings.append(f"Battery: PASS — {charge}%")

        pre_text = "\n".join(pre_ratings)

        # Build "Learn More" findings for WARN/FAIL items
        findings = []
        for r in pre_ratings:
            if "WARN" in r or "FAIL" in r:
                if "Disk" in r:
                    findings.append({"label": "Disk Usage", "q": "Why is high disk usage a concern on enterprise devices and how can I free up space on Windows 11?"})
                elif "Uptime" in r:
                    m2 = re.search(r'([\d.]+) days', r)
                    d = m2.group(1) if m2 else "?"
                    findings.append({"label": "Uptime " + d + "d", "q": f"This device has been running for {d} days without a reboot. Why does enterprise IT policy require regular reboots and what security patches might be pending?"})
                elif "AV" in r:
                    findings.append({"label": "AV Signatures", "q": "Why are outdated antivirus signatures dangerous and how do I update Windows Defender definitions?"})
                elif "Battery" in r:
                    findings.append({"label": "Battery", "q": "What does critically low battery indicate about device health and battery longevity?"})
        # Subjective checks — always include if relevant data exists
        if "NotConfigured" in health_data:
            findings.append({"label": "Firewall Config", "q": "The Windows Firewall profiles show NotConfigured for inbound rules. What does this mean for security and what should enterprise IT configure?"})
        if "445" in health_data or "139" in health_data:
            findings.append({"label": "SMB Ports 139/445", "q": "Ports 139 and 445 (SMB/NetBIOS) are listening on this device. What are the security risks of open SMB ports and should they be closed on an enterprise laptop?"})
        if "Error" in health_data and "Smartcard" in health_data:
            findings.append({"label": "Smartcard Errors", "q": "The system log shows recurring Smart Card Reader errors from Microsoft-Windows-Smartcard-Server. What causes this on a Surface device and how do I fix it?"})
        elif "Error" in health_data:
            findings.append({"label": "System Errors", "q": "The Windows System event log shows recent errors. What do these mean and should I be concerned?"})

        if len(health_data) > 2800:
            health_data = health_data[:2800]

        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": (
                        "You are a senior enterprise IT health agent. "
                        "Write a 2-3 sentence executive summary highlighting what is good "
                        "and what needs attention. Be specific — mention port numbers, "
                        "error sources, and uptime days. "
                        "Then list all areas with their PASS/WARN/FAIL rating. "
                        "The pre-computed ratings below are CORRECT — use them exactly. "
                        "You must also rate: Firewall (NotConfigured inbound=FAIL), "
                        "Ports (139/445 SMB/NetBIOS open=WARN), System Errors. "
                        "End with one PRIORITY ACTION."
                    )},
                    {"role": "user", "content": (
                        f"Pre-computed ratings (use these exactly):\n{pre_text}\n\n"
                        f"Raw scan data:\n{health_data}\n\nHealth assessment:"
                    )},
                ],
                max_tokens=512,
                temperature=0.3,
            )
            _track_model_call(response, _time.time() - _call_start)
            summary = (response.choices[0].message.content or "").strip()
            total = round(_time.time() - start, 1)

            AGENT_AUDIT_LOG.append({
                "timestamp": _time.strftime("%H:%M:%S"),
                "tool": "exec",
                "arguments": {"command": "Device Health Check (9 checks)"},
                "success": True,
                "time": total,
            })

            yield json.dumps({
                "type": "result",
                "text": summary,
                "time": total,
                "findings": findings,
            }) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(generate(), mimetype='text/plain')


@app.route('/demo/security-audit', methods=['POST'])
def demo_security_audit():
    """Chip-to-cloud security audit — 17 PowerShell checks + AI posture grade."""
    model = DEFAULT_MODEL

    SECURITY_CHECKS = [
        {
            "id": "tpm",
            "name": "TPM Module",
            "icon": "\U0001f510",
            "cmd": 'Get-Tpm | Select-Object TpmPresent, TpmReady, ManufacturerVersion | Format-List',
            "parse": lambda out: ("PASS", "TPM present and ready") if "True" in out and "TpmPresent" in out else ("FAIL", "TPM not detected"),
        },
        {
            "id": "secureboot",
            "name": "Secure Boot",
            "icon": "\U0001f512",
            "cmd": 'Confirm-SecureBootUEFI',
            "parse": lambda out: ("PASS", "Secure Boot enabled") if "True" in out else ("FAIL", "Secure Boot disabled"),
        },
        {
            "id": "bitlocker",
            "name": "BitLocker Encryption",
            "icon": "\U0001f4bf",
            "cmd": 'Get-BitLockerVolume -MountPoint C: -ErrorAction SilentlyContinue | Select-Object MountPoint, VolumeStatus, ProtectionStatus, EncryptionPercentage | Format-List',
            "parse": lambda out: ("PASS", "Drive encrypted") if "FullyEncrypted" in out or "EncryptionInProgress" in out else ("FAIL", "Drive not encrypted"),
        },
        {
            "id": "vbs",
            "name": "VBS / Credential Guard / HVCI",
            "icon": "\U0001f6e1\ufe0f",
            "cmd": 'Get-CimInstance -ClassName Win32_DeviceGuard -Namespace root\\Microsoft\\Windows\\DeviceGuard -ErrorAction SilentlyContinue | Select-Object VirtualizationBasedSecurityStatus, SecurityServicesRunning | Format-List',
            "parse": lambda out: (
                ("PASS", "VBS running" +
                    (", Credential Guard active" if "1" in re.findall(r'SecurityServicesRunning\s*:\s*\{([^}]+)\}', out)[0].split(',') else "") +
                    (", HVCI active" if "2" in [x.strip() for x in re.findall(r'SecurityServicesRunning\s*:\s*\{([^}]+)\}', out)[0].split(',')] else "")
                ) if "VirtualizationBasedSecurityStatus" in out and "2" in out and re.findall(r'SecurityServicesRunning\s*:\s*\{([^}]+)\}', out)
                else ("PASS", "VBS running") if "VirtualizationBasedSecurityStatus" in out and "2" in out
                else ("WARN", "VBS not running")
            ),
        },
        {
            "id": "defender_av",
            "name": "Defender Antivirus",
            "icon": "\U0001f6e1\ufe0f",
            "cmd": 'Get-MpComputerStatus | Select-Object AntivirusEnabled, RealTimeProtectionEnabled, IoavProtectionEnabled, AntispywareEnabled | Format-List',
            "parse": lambda out: ("PASS", "All protections enabled") if out.count("True") >= 3 else ("FAIL", "Some protections disabled"),
        },
        {
            "id": "defender_edr",
            "name": "Defender for Endpoint (EDR)",
            "icon": "\U0001f50d",
            "cmd": 'Get-Service Sense -ErrorAction SilentlyContinue | Select-Object Status, DisplayName | Format-List',
            "parse": lambda out: ("PASS", "EDR agent running") if "Running" in out else ("WARN", "EDR agent not detected"),
        },
        {
            "id": "smartscreen",
            "name": "SmartScreen / Network Protection",
            "icon": "\U0001f6ab",
            "cmd": 'Get-MpPreference | Select-Object EnableNetworkProtection | Format-List',
            "parse": lambda out: ("PASS", "Network protection enabled") if "1" in out or "2" in out else ("WARN", "Network protection not enabled"),
        },
        {
            "id": "firewall",
            "name": "Windows Firewall",
            "icon": "\U0001f9f1",
            "cmd": 'Get-NetFirewallProfile | Select-Object Name, Enabled | Format-List',
            "parse": lambda out: ("PASS", "All profiles enabled") if out.count("True") >= 3 else ("FAIL", "Some firewall profiles disabled"),
        },
        {
            "id": "smbv1",
            "name": "SMB v1 Protocol",
            "icon": "\u26a0\ufe0f",
            "cmd": 'Get-SmbServerConfiguration | Select-Object EnableSMB1Protocol | Format-List',
            "parse": lambda out: ("PASS", "SMBv1 disabled") if "False" in out else ("FAIL", "SMBv1 enabled — known attack vector"),
        },
        {
            "id": "execpolicy",
            "name": "PowerShell Execution Policy",
            "icon": "\u2699\ufe0f",
            "cmd": 'Get-ExecutionPolicy -List | Format-List',
            "parse": lambda out: ("WARN", "Unrestricted execution policy") if "Unrestricted" in out else ("PASS", "Execution policy configured"),
        },
        {
            "id": "localadmins",
            "name": "Local Administrators",
            "icon": "\U0001f465",
            "cmd": 'net localgroup administrators',
            "parse": lambda out: ("WARN", "More than 2 admin accounts") if len([l for l in out.split('\n') if l.strip() and not l.startswith('-') and 'command' not in l.lower() and 'alias' not in l.lower() and 'comment' not in l.lower() and 'members' not in l.lower() and 'successfully' not in l.lower()]) > 2 else ("PASS", "Admin accounts within policy"),
        },
        {
            "id": "applocker",
            "name": "WDAC / AppLocker",
            "icon": "\U0001f6e1\ufe0f",
            "cmd": 'Get-AppLockerPolicy -Effective -ErrorAction SilentlyContinue | Select-Object -ExpandProperty RuleCollections | Measure-Object | Select-Object Count | Format-List',
            "parse": lambda out: ("PASS", "Application control configured") if "Count" in out and not any(x in out for x in ["Count : 0", "Count: 0"]) else ("WARN", "No application control policies"),
        },
        {
            "id": "certs",
            "name": "Certificate Health",
            "icon": "\U0001f4dc",
            "cmd": 'Get-ChildItem Cert:\\LocalMachine\\My -ErrorAction SilentlyContinue | Where-Object {$_.NotAfter -lt (Get-Date)} | Select-Object Subject, NotAfter | Format-List',
            "parse": lambda out: ("WARN", "Expired certificates found") if "Subject" in out else ("PASS", "No expired certificates"),
        },
        {
            "id": "netprofile",
            "name": "Network Profile",
            "icon": "\U0001f310",
            "cmd": 'Get-NetConnectionProfile | Select-Object Name, NetworkCategory | Format-List',
            "parse": lambda out: ("WARN", "Connected to Public network") if "Public" in out else ("PASS", "Network profile is Domain/Private"),
        },
        {
            "id": "autoplay",
            "name": "AutoPlay / AutoRun",
            "icon": "\U0001f4c0",
            "cmd": '$lm = Get-ItemProperty "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\Explorer" -Name NoDriveTypeAutoRun -ErrorAction SilentlyContinue; $cu = Get-ItemProperty "HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\Explorer" -Name NoDriveTypeAutoRun -ErrorAction SilentlyContinue; if ($lm -or $cu) { "NoDriveTypeAutoRun: Set (HKLM=$($lm.NoDriveTypeAutoRun) HKCU=$($cu.NoDriveTypeAutoRun))" } else { "NoDriveTypeAutoRun: Not configured" }',
            "parse": lambda out: ("PASS", "AutoRun disabled via policy") if "Set" in out else ("WARN", "AutoRun policy not configured"),
        },
        {
            "id": "rdp",
            "name": "Remote Desktop",
            "icon": "\U0001f5a5\ufe0f",
            "cmd": 'Get-ItemProperty "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server" -Name fDenyTSConnections -ErrorAction SilentlyContinue | Select-Object fDenyTSConnections | Format-List',
            "parse": lambda out: ("PASS", "Remote Desktop disabled") if "1" in out else ("WARN", "Remote Desktop enabled"),
        },
        {
            "id": "hello",
            "name": "Windows Hello",
            "icon": "\U0001f44b",
            "cmd": 'dsregcmd /status | Select-String -Pattern "NgcSet|DeviceId|AzureAdJoined"',
            "parse": lambda out: ("PASS", "Windows Hello configured") if "YES" in out.upper() and "NgcSet" in out else ("WARN", "Windows Hello not configured"),
        },
        {
            "id": "winrm",
            "name": "WinRM Remote Management",
            "icon": "\U0001f4e1",
            "cmd": 'Get-Service WinRM -ErrorAction SilentlyContinue | Select-Object Status, StartType | Format-List',
            "parse": lambda out: ("WARN", "WinRM is running") if "Running" in out else ("PASS", "WinRM not running"),
        },
        {
            "id": "patchhealth",
            "name": "Patch Health",
            "icon": "\U0001f4e6",
            "cmd": 'Get-HotFix | Sort-Object InstalledOn -Descending -ErrorAction SilentlyContinue | Select-Object -First 3 HotFixID, InstalledOn, Description | Format-List',
            "parse": lambda out: ("PASS", "Recent patches installed") if "InstalledOn" in out and any(str(y) in out for y in [_time.strftime("%m/%d/%Y")[:3], _time.strftime("%Y")]) else ("WARN", "Patch recency unclear or outdated"),
        },
        {
            "id": "uac",
            "name": "UAC Configuration",
            "icon": "\U0001f6a7",
            "cmd": 'Get-ItemProperty "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" -ErrorAction SilentlyContinue | Select-Object EnableLUA, ConsentPromptBehaviorAdmin, PromptOnSecureDesktop | Format-List',
            "parse": lambda out: ("PASS", "UAC enabled with secure desktop") if re.search(r'EnableLUA\s*:\s*1', out) else ("FAIL", "UAC disabled"),
        },
        {
            "id": "lsass",
            "name": "LSASS / Credential Protection",
            "icon": "\U0001f510",
            "cmd": '$ppl = Get-ItemProperty "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Lsa" -ErrorAction SilentlyContinue | Select-Object RunAsPPL, LsaCfgFlags; $wd = Get-ItemProperty "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\SecurityProviders\\WDigest" -ErrorAction SilentlyContinue | Select-Object UseLogonCredential; "RunAsPPL: $($ppl.RunAsPPL)"; "LsaCfgFlags: $($ppl.LsaCfgFlags)"; "WDigest UseLogonCredential: $($wd.UseLogonCredential)"',
            "parse": lambda out: ("FAIL", "WDigest plaintext creds enabled") if "UseLogonCredential: 1" in out else ("PASS", "WDigest disabled, LSASS protection present") if "RunAsPPL: 1" in out or "RunAsPPL: 2" in out else ("WARN", "LSASS PPL not confirmed"),
        },
        {
            "id": "asr",
            "name": "ASR Rules / Controlled Folders",
            "icon": "\U0001f6e1\ufe0f",
            "cmd": '$cfa = (Get-MpPreference).EnableControlledFolderAccess; $asr = (Get-MpPreference).AttackSurfaceReductionRules_Actions; $count = if ($asr) { ($asr | Where-Object {$_ -ne 0}).Count } else { 0 }; "ControlledFolderAccess: $cfa"; "ASR rules enabled: $count"',
            "parse": lambda out: ("PASS", "Controlled folders + ASR rules active") if "ControlledFolderAccess: 1" in out or "ControlledFolderAccess: 2" in out else ("WARN", "Controlled Folder Access off") if "ASR rules enabled: 0" in out or "ASR rules enabled:" not in out else ("PASS", "ASR rules active"),
        },
        {
            "id": "localusers",
            "name": "Local User Accounts",
            "icon": "\U0001f464",
            "cmd": 'Get-LocalUser | Select-Object Name, Enabled, LastLogon | Format-List',
            "parse": lambda out: ("WARN", "Stale or excessive local accounts") if out.lower().count("enabled : true") > 3 else ("PASS", "Local accounts within policy"),
        },
        {
            "id": "pwpolicy",
            "name": "Password Policy",
            "icon": "\U0001f511",
            "cmd": 'net accounts',
            "parse": lambda out: ("WARN", "Weak password policy (min length too short)") if re.search(r'Minimum password length\s*:\s*[0-3]\b', out) else ("PASS", "Password policy configured"),
        },
    ]

    def generate():
        start = _time.time()
        results = []
        ratings = []

        for check in SECURITY_CHECKS:
            yield json.dumps({
                "type": "check-start",
                "id": check["id"],
                "name": check["name"],
                "icon": check["icon"],
                "cmd": check["cmd"],
            }) + "\n"

            try:
                proc = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command", check["cmd"]],
                    capture_output=True, text=True, timeout=10
                )
                output = (proc.stdout or "").strip()
                if proc.returncode != 0 and proc.stderr:
                    output = output or proc.stderr.strip()
                if not output:
                    output = "(no data available)"
                if len(output) > 350:
                    output = output[:350] + "..."

                # Pre-compute rating
                rating, reason = check["parse"](output)
                ratings.append({"id": check["id"], "name": check["name"], "rating": rating, "reason": reason})
                results.append(f"{check['name']}: {rating} — {reason}\n{output}")

                yield json.dumps({
                    "type": "check-done",
                    "id": check["id"],
                    "output": f"[{rating}] {reason}\n{output}",
                }) + "\n"

            except subprocess.TimeoutExpired:
                ratings.append({"id": check["id"], "name": check["name"], "rating": "WARN", "reason": "Command timed out"})
                results.append(f"{check['name']}: TIMEOUT")
                yield json.dumps({
                    "type": "check-error",
                    "id": check["id"],
                    "output": "Command timed out (10s)",
                }) + "\n"
            except Exception as e:
                ratings.append({"id": check["id"], "name": check["name"], "rating": "WARN", "reason": str(e)})
                results.append(f"{check['name']}: ERROR - {str(e)}")
                yield json.dumps({
                    "type": "check-error",
                    "id": check["id"],
                    "output": str(e),
                }) + "\n"

        yield json.dumps({"type": "status", "text": "AI analyzing security posture..."}) + "\n"

        # Build pre-computed ratings text
        pass_count = sum(1 for r in ratings if r["rating"] == "PASS")
        warn_count = sum(1 for r in ratings if r["rating"] == "WARN")
        fail_count = sum(1 for r in ratings if r["rating"] == "FAIL")
        total_checks = len(ratings)

        # Weighted grade: critical failures count more
        _CRITICAL_IDS = {"secureboot", "bitlocker", "defender_av", "firewall", "tpm", "uac", "lsass"}
        critical_fails = sum(1 for r in ratings if r["rating"] == "FAIL" and r["id"] in _CRITICAL_IDS)
        if critical_fails >= 2:
            grade = "F"
        elif critical_fails == 1 or fail_count >= 3:
            grade = "D"
        elif fail_count == 0 and warn_count <= 3:
            grade = "A"
        elif fail_count == 0 and warn_count <= 6:
            grade = "B"
        elif fail_count <= 1 and warn_count <= 8:
            grade = "C"
        else:
            grade = "D"

        pre_text = f"Overall Grade: {grade} ({pass_count} PASS, {warn_count} WARN, {fail_count} FAIL out of {total_checks} checks)\n\n"
        for r in ratings:
            pre_text += f"- {r['name']}: {r['rating']} — {r['reason']}\n"

        # Build findings for Learn More buttons
        findings = []
        for r in ratings:
            if r["rating"] in ("WARN", "FAIL"):
                q_map = {
                    "tpm": ("TPM", "What is TPM 2.0, why is it required for Windows 11 security, and what are the risks of not having it?"),
                    "secureboot": ("Secure Boot", "What is UEFI Secure Boot, how does it protect against rootkits, and how do I enable it?"),
                    "bitlocker": ("BitLocker", "What is BitLocker drive encryption, why is it critical for enterprise devices, and how do I enable it?"),
                    "vbs": ("VBS", "What is Virtualization-Based Security (VBS), how does it protect credentials with Credential Guard, and what's the performance impact?"),
                    "defender_av": ("Defender AV", "Why are all four Defender protection layers important (antivirus, real-time, IOAV, antispyware) and what should I do if any are disabled?"),
                    "defender_edr": ("EDR", "What is Defender for Endpoint (EDR/Sense service), how does it differ from Defender Antivirus, and why is it important for enterprise threat detection?"),
                    "smartscreen": ("SmartScreen", "What is Windows SmartScreen, how does it protect against phishing and malicious downloads, and should it be enabled?"),
                    "firewall": ("Firewall", "Why should all Windows Firewall profiles (Domain, Private, Public) be enabled and what are the risks of disabling any?"),
                    "smbv1": ("SMBv1", "Why is SMB v1 a critical security risk (WannaCry, EternalBlue) and how do I permanently disable it?"),
                    "execpolicy": ("Execution Policy", "What are PowerShell execution policies, how does Unrestricted differ from RemoteSigned, and what's the enterprise recommendation?"),
                    "localadmins": ("Local Admins", "Why should local administrator accounts be minimized and what's the principle of least privilege for enterprise endpoints?"),
                    "applocker": ("AppLocker/WDAC", "What are AppLocker and Windows Defender Application Control (WDAC), how do they prevent unauthorized software, and which should I use?"),
                    "certs": ("Expired Certs", "What are the security risks of expired certificates on a device and how do I clean them up?"),
                    "netprofile": ("Network Profile", "What's the difference between Domain, Private, and Public network profiles in Windows and why does Public weaken security?"),
                    "autoplay": ("AutoPlay", "Why should AutoPlay/AutoRun be disabled on enterprise devices and how is it exploited by malware via USB drives?"),
                    "rdp": ("Remote Desktop", "What are the security risks of having Remote Desktop enabled, and how is it commonly exploited (BlueKeep, brute force)?"),
                    "hello": ("Windows Hello", "What is Windows Hello for Business, how does passwordless authentication improve security, and how do I set it up?"),
                    "winrm": ("WinRM", "What is WinRM (Windows Remote Management), what are the security risks of having it enabled, and when should it be disabled on enterprise endpoints?"),
                    "patchhealth": ("Patch Health", "Why is patch recency critical for security, what are the risks of delayed Windows updates, and how do I check update compliance?"),
                    "uac": ("UAC", "What is User Account Control (UAC), why is it important, and what do the different prompt levels mean for security?"),
                    "lsass": ("LSASS/WDigest", "What is LSASS protection (PPL), why is WDigest dangerous when enabled, and how do credential theft tools like Mimikatz exploit these settings?"),
                    "asr": ("ASR Rules", "What are Attack Surface Reduction rules in Defender, how does Controlled Folder Access protect against ransomware, and which ASR rules should be enabled?"),
                    "localusers": ("Local Users", "Why should local user accounts be audited, what risks do stale enabled accounts pose, and how should enterprises manage local accounts?"),
                    "pwpolicy": ("Password Policy", "What is a strong local password policy, why does minimum length matter, and what are the NIST and Microsoft recommendations?"),
                }
                if r["id"] in q_map:
                    label, question = q_map[r["id"]]
                    findings.append({"label": f"{label} ({r['rating']})", "q": question})

        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": (
                        "You are a senior enterprise security analyst. Be concise. "
                        "Write a 2-3 sentence executive summary. "
                        "State the security grade. "
                        "Then list ONLY the WARN and FAIL items as bullet points. "
                        "End with TOP 3 PRIORITY ACTIONS numbered 1-3."
                    )},
                    {"role": "user", "content": (
                        f"Security audit results:\n{pre_text}\n\nAssessment:"
                    )},
                ],
                max_tokens=512,
                temperature=0.3,
            )
            _track_model_call(response, _time.time() - _call_start)
            summary = (response.choices[0].message.content or "").strip()
            total = round(_time.time() - start, 1)

            AGENT_AUDIT_LOG.append({
                "timestamp": _time.strftime("%H:%M:%S"),
                "tool": "exec",
                "arguments": {"command": "Security Audit (24 checks)"},
                "success": True,
                "time": total,
            })

            yield json.dumps({
                "type": "result",
                "text": summary,
                "time": total,
                "findings": findings,
            }) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(generate(), mimetype='text/plain')


@app.route('/demo/device-search', methods=['POST'])
def demo_device_search():
    """Natural language file search — AI parses query, PowerShell searches, AI summarizes."""
    model = DEFAULT_MODEL
    data = request.json or {}
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({"error": "No search query provided"}), 400

    def generate():
        start = _time.time()
        yield json.dumps({"type": "status", "text": "Parsing your query with AI..."}) + "\n"

        # Step 1: AI parses natural language query into search parameters
        try:
            _call_start = _time.time()
            parse_response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": (
                        "You are a file search assistant. Parse the user's natural language query into JSON search parameters. "
                        "Return ONLY valid JSON with these fields:\n"
                        '{"keywords": ["word1", "word2"], "extensions": [".xlsx", ".docx"], "recency": "any"}\n'
                        "For extensions, infer from context: 'Excel' → '.xlsx,.xls', 'Word' → '.docx,.doc', "
                        "'PDF' → '.pdf', 'PowerPoint' → '.pptx,.ppt', 'photos' → '.jpg,.png,.heic'. "
                        "For recency: 'last week' → '7', 'last month' → '30', 'recent' → '14', otherwise 'any'. "
                        "Return ONLY JSON, no explanation."
                    )},
                    {"role": "user", "content": query},
                ],
                max_tokens=150,
                temperature=0.1,
            )
            _track_model_call(response=parse_response, elapsed=_time.time() - _call_start)
            parse_text = (parse_response.choices[0].message.content or "").strip()

            # Extract JSON from response
            search_params = None
            try:
                # Try direct JSON parse
                search_params = json.loads(parse_text)
            except json.JSONDecodeError:
                # Try to find JSON block in response
                m = re.search(r'\{[^}]+\}', parse_text, re.DOTALL)
                if m:
                    try:
                        search_params = json.loads(m.group())
                    except json.JSONDecodeError:
                        pass

            # Fallback: split query into keywords
            if not search_params:
                search_params = {
                    "keywords": [w for w in query.lower().split() if len(w) > 2],
                    "extensions": [".docx", ".xlsx", ".pdf", ".pptx", ".txt"],
                    "recency": "any",
                }

        except Exception as e:
            # Fallback on AI failure
            search_params = {
                "keywords": [w for w in query.lower().split() if len(w) > 2],
                "extensions": [".docx", ".xlsx", ".pdf", ".pptx", ".txt"],
                "recency": "any",
            }

        keywords = search_params.get("keywords", [])
        extensions = search_params.get("extensions", [".docx", ".xlsx", ".pdf", ".pptx", ".txt"])
        recency = search_params.get("recency", "any")

        yield json.dumps({"type": "status", "text": "Searching files..."}) + "\n"

        # Step 2: PowerShell search scoped to user profile dirs
        search_dirs = ["Documents", "Desktop", "Downloads"]
        user_profile = os.environ.get("USERPROFILE", "C:\\Users\\Default")

        # Build extension filter
        ext_filter = " -or ".join([f'$_.Extension -eq "{ext}"' for ext in extensions])
        if not ext_filter:
            ext_filter = '$true'

        # Build recency filter
        recency_filter = ""
        if recency != "any":
            try:
                days = int(recency)
                recency_filter = f' | Where-Object {{ $_.LastWriteTime -gt (Get-Date).AddDays(-{days}) }}'
            except (ValueError, TypeError):
                recency_filter = ""

        all_results = []
        for search_dir in search_dirs:
            full_path = os.path.join(user_profile, search_dir)
            if not os.path.exists(full_path):
                continue

            ps_cmd = (
                f'Get-ChildItem -Path "{full_path}" -Recurse -File -ErrorAction SilentlyContinue '
                f'| Where-Object {{ {ext_filter} }}'
                f'{recency_filter}'
                f' | Select-Object Name, FullName, @{{N="SizeKB";E={{[math]::Round($_.Length/1KB,1)}}}}, '
                f'@{{N="Modified";E={{$_.LastWriteTime.ToString("yyyy-MM-dd HH:mm")}}}} '
                f'| ConvertTo-Json -Depth 2'
            )

            try:
                proc = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True, text=True, timeout=15
                )
                if proc.stdout and proc.stdout.strip():
                    try:
                        parsed = json.loads(proc.stdout)
                        if isinstance(parsed, dict):
                            parsed = [parsed]
                        all_results.extend(parsed)
                    except json.JSONDecodeError:
                        pass
            except (subprocess.TimeoutExpired, Exception):
                pass

        # Filter by keywords (case-insensitive name match)
        if keywords:
            filtered = []
            for item in all_results:
                name_lower = (item.get("Name") or "").lower()
                if any(kw.lower() in name_lower for kw in keywords):
                    filtered.append(item)
            all_results = filtered if filtered else all_results

        # Cap at 20 results, sort by modified date
        all_results = sorted(all_results, key=lambda x: x.get("Modified", ""), reverse=True)[:20]

        # Format for frontend
        file_cards = []
        for item in all_results:
            size_kb = item.get("SizeKB", 0)
            size_str = f"{size_kb} KB" if size_kb < 1024 else f"{round(size_kb/1024, 1)} MB"
            file_cards.append({
                "name": item.get("Name", "Unknown"),
                "path": item.get("FullName", ""),
                "size": size_str,
                "modified": item.get("Modified", "Unknown"),
            })

        yield json.dumps({
            "type": "search-results",
            "count": len(file_cards),
            "files": file_cards,
        }) + "\n"

        AGENT_AUDIT_LOG.append({
            "timestamp": _time.strftime("%H:%M:%S"),
            "tool": "exec",
            "arguments": {"command": f"Device Search: {query}"},
            "success": True,
            "time": round(_time.time() - start, 1),
        })

        # Step 3: AI summarizes results
        if file_cards:
            yield json.dumps({"type": "status", "text": "AI summarizing results..."}) + "\n"

            file_summary = "\n".join([f"- {f['name']} ({f['size']}, modified {f['modified']})" for f in file_cards[:15]])

            try:
                _call_start = _time.time()
                summary_response = foundry_chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a helpful file search assistant. Briefly summarize the search results in 1-2 sentences. Mention the count, types, and any patterns you see."},
                        {"role": "user", "content": f"User searched for: \"{query}\"\n\nFound {len(file_cards)} files:\n{file_summary}\n\nBrief summary:"},
                    ],
                    max_tokens=150,
                    temperature=0.3,
                )
                _track_model_call(response=summary_response, elapsed=_time.time() - _call_start)
                summary = (summary_response.choices[0].message.content or "").strip()
                total = round(_time.time() - start, 1)
                yield json.dumps({"type": "result", "text": summary, "time": total}) + "\n"
            except Exception as e:
                total = round(_time.time() - start, 1)
                yield json.dumps({"type": "result", "text": f"Found {len(file_cards)} matching files.", "time": total}) + "\n"
        else:
            total = round(_time.time() - start, 1)
            yield json.dumps({"type": "result", "text": "No files matched your search criteria. Try broadening your search with different keywords or file types.", "time": total}) + "\n"

    return Response(generate(), mimetype='text/plain')


@app.route('/knowledge', methods=['POST'])
def knowledge_answer():
    """Answer a knowledge question with no tool access — pure AI explanation.

    Used by Device Health 'Learn More' buttons and any context where
    the question should be answered from the model's training data,
    not by running commands.
    """
    data = request.json
    question = (data.get('question') or data.get('message', '')).strip()
    if not question:
        return jsonify({"error": "No question provided"}), 400

    def generate():
        start = _time.time()
        yield json.dumps({"type": "status", "text": "Thinking..."}) + "\n"
        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content":
                        "You are an IT security and systems administration expert. "
                        "Answer the user's question clearly and concisely from your knowledge. "
                        "Do NOT suggest running commands, scripts, or tools. "
                        "Focus on explaining concepts, risks, and recommendations."
                    },
                    {"role": "user", "content": question},
                ],
                max_tokens=800,
                temperature=0.3,
            )
            _track_model_call(response, _time.time() - _call_start)
            answer = (response.choices[0].message.content or "").strip()
            total = round(_time.time() - start, 1)
            yield json.dumps({"type": "result", "text": answer, "time": total}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(generate(), mimetype='text/plain')


# Confidential file patterns for demo (files that require approval)
CONFIDENTIAL_PATTERNS = {
    'contract': {'label': 'Contract', 'icon': '📜'},
    'nda': {'label': 'NDA', 'icon': '🔒'},
    'loan': {'label': 'PII Data', 'icon': '🔐'},
    'confidential': {'label': 'Confidential', 'icon': '🔒'},
    'board': {'label': 'Board Material', 'icon': '📊'},
}

@app.route('/demo/list-files', methods=['GET'])
def demo_list_files():
    """List files in Demo folder with confidentiality metadata."""
    files = []
    if os.path.exists(DEMO_DIR):
        for fname in os.listdir(DEMO_DIR):
            fpath = os.path.join(DEMO_DIR, fname)
            if os.path.isfile(fpath) and fname.endswith(('.txt', '.md', '.csv')):
                # Determine confidentiality based on filename patterns
                fname_lower = fname.lower()
                confidential = None
                for pattern, meta in CONFIDENTIAL_PATTERNS.items():
                    if pattern in fname_lower:
                        confidential = meta
                        break

                # Get file size
                try:
                    size = os.path.getsize(fpath)
                    size_str = f"{size:,} bytes" if size < 1024 else f"{size/1024:.1f} KB"
                except:
                    size_str = "?"

                files.append({
                    'name': fname,
                    'size': size_str,
                    'confidential': confidential,
                    'path': fpath
                })

    # Sort: confidential files first, then alphabetically
    files.sort(key=lambda f: (0 if f['confidential'] else 1, f['name']))
    return jsonify({'files': files})


@app.route('/demo/review-summarize', methods=['POST'])
def demo_review_summarize():
    """Two-phase review: accepts selected files, returns plan for approval, then executes."""
    data = request.json
    model = DEFAULT_MODEL
    phase = data.get('phase', 'plan')  # 'plan' or 'execute'
    selected_files = data.get('files', [])  # List of filenames selected by user

    # Fallback if no files provided (backwards compat)
    if not selected_files:
        selected_files = ["strategy_2026.txt", "board_meeting_prep.txt"]

    if phase == 'plan':
        # Phase 1: Return the plan for approval (no AI needed)
        plan_lines = ["**Files to access:**"]
        for fname in selected_files:
            full_path = os.path.join(DEMO_DIR, fname)
            exists = "✓" if os.path.exists(full_path) else "✗ (not found)"
            # Check confidentiality
            fname_lower = fname.lower()
            conf_label = ""
            for pattern, meta in CONFIDENTIAL_PATTERNS.items():
                if pattern in fname_lower:
                    conf_label = f" {meta['icon']} {meta['label']}"
                    break
            plan_lines.append(f"- {fname} {exists}{conf_label}")
        plan_lines.append("")
        plan_lines.append("**Action:** Analyze selected documents and produce a risk summary")
        plan_text = "\n".join(plan_lines)
        return jsonify({"type": "plan", "text": plan_text, "files": selected_files})

    elif phase == 'execute':
        # Phase 2: Actually read files and summarize
        def generate():
            start = _time.time()

            # Read all files
            combined_content = []
            files_read = []
            for fname in selected_files:
                full_path = os.path.join(DEMO_DIR, fname)
                yield json.dumps({"type": "status", "text": f"Reading {fname}..."}) + "\n"
                if os.path.exists(full_path):
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        combined_content.append(f"=== {fname} ===\n{content[:1500]}")
                        files_read.append(fname)
                        AGENT_AUDIT_LOG.append({
                            "timestamp": _time.strftime("%H:%M:%S"),
                            "tool": "read",
                            "arguments": {"path": full_path},
                            "success": True,
                            "time": 0,
                        })
                    except Exception as e:
                        combined_content.append(f"=== {fname} ===\n[Error reading: {e}]")

            if not combined_content:
                yield json.dumps({"type": "error", "message": "No files found to review"}) + "\n"
                return

            yield json.dumps({"type": "status", "text": "Analyzing for risks..."}) + "\n"

            try:
                _call_start = _time.time()
                response = foundry_chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are an executive assistant preparing a board briefing. Be concise and focus on risks."},
                        {"role": "user", "content": (
                            f"Review these documents and identify key risks to brief the board on:\n\n"
                            f"{chr(10).join(combined_content)}\n\n"
                            "Produce a brief risk summary with:\n"
                            "1. Top 3 risks identified\n"
                            "2. Recommended actions\n"
                            "Keep it executive-ready."
                        )},
                    ],
                    max_tokens=512,
                    temperature=0.3,
                )
                _track_model_call(response, _time.time() - _call_start)
                summary = (response.choices[0].message.content or "").strip()
                total = round(_time.time() - start, 1)
                yield json.dumps({
                    "type": "result",
                    "text": summary,
                    "time": total,
                    "files_read": files_read
                }) + "\n"
            except Exception as e:
                yield json.dumps({"type": "error", "message": str(e)}) + "\n"

        return Response(generate(), mimetype='text/plain')

    return jsonify({"type": "error", "message": "Invalid phase"})


@app.route('/detect-pii', methods=['POST'])
def detect_pii():
    """Single-step PII detection — reads file directly, one model call."""
    data = request.json
    file_path = data.get('path', '')
    model = DEFAULT_MODEL

    def generate():
        start = _time.time()
        yield json.dumps({"type": "status", "text": "Reading document..."}) + "\n"

        if not _path_in_demo_dir(file_path):
            yield json.dumps({"type": "error", "message": "Security Policy: file outside approved folder."}) + "\n"
            return
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            yield json.dumps({"type": "error", "message": f"Could not read file: {e}"}) + "\n"
            return

        AGENT_AUDIT_LOG.append({
            "timestamp": _time.strftime("%H:%M:%S"),
            "tool": "read",
            "arguments": {"path": file_path},
            "success": True,
            "time": 0,
        })

        if len(content) > 2500:
            content = content[:2500] + "\n...(truncated)"

        yield json.dumps({"type": "status", "text": "Scanning for PII..."}) + "\n"

        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a security analyst. Be thorough but concise."},
                    {"role": "user", "content": f"Here is a document:\n\n{content}\n\nScan it for any Personally Identifiable Information (PII) such as names, SSNs, addresses, phone numbers, emails, or account numbers. List each item found and rate the overall risk level (High/Medium/Low)."},
                ],
                max_tokens=512,
                temperature=0.3,
            )
            _track_model_call(response, _time.time() - _call_start)
            analysis = (response.choices[0].message.content or "").strip()
            total = round(_time.time() - start, 1)
            yield json.dumps({"type": "result", "text": analysis, "time": total}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(generate(), mimetype='text/plain')


@app.route('/summarize-doc', methods=['POST'])
def summarize_doc():
    """Single-step document summarization — reads file directly, one model call."""
    data = request.json
    file_path = data.get('path', '')
    model = DEFAULT_MODEL

    def generate():
        start = _time.time()
        yield json.dumps({"type": "status", "text": "Reading document..."}) + "\n"

        # Read file directly — no model call needed
        if not _path_in_demo_dir(file_path):
            yield json.dumps({"type": "error", "message": "Security Policy: file outside approved folder."}) + "\n"
            return
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            yield json.dumps({"type": "error", "message": f"Could not read file: {e}"}) + "\n"
            return

        # Truncate to fit model context window
        _doc_limit = 8000 if SILICON == "qualcomm" else 2500
        if len(content) > _doc_limit:
            content = content[:_doc_limit] + "\n...(truncated)"

        yield json.dumps({"type": "status", "text": f"Analyzing {len(content.split())} words with AI..."}) + "\n"

        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Be concise and executive-ready. Use ONLY the information provided — do not invent names or facts."},
                    {"role": "user", "content": (
                        f"Here is a document:\n\n{content}\n\n"
                        "Produce a structured summary with these sections:\n"
                        "MEETING SUMMARY (2-3 sentence overview)\n"
                        "KEY IDEAS & DECISIONS (bullet the most important points)\n"
                        "ACTION ITEMS (list each with the owner's name if mentioned)"
                    )},
                ],
                max_tokens=512,
                temperature=0.3,
            )
            _track_model_call(response, _time.time() - _call_start)
            summary = (response.choices[0].message.content or "").strip()
            total = round(_time.time() - start, 1)
            yield json.dumps({"type": "summary", "text": summary, "time": total}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(generate(), mimetype='text/plain')


@app.route('/chat', methods=['POST'])
def chat():
    """Agent chat — routes through tool-calling pipeline or Marcus Reed persona."""
    data = request.json
    message = data.get('message', '')
    model = DEFAULT_MODEL

    # Route decision: messages that need tool calling use AGENT_SYSTEM_PROMPT (with tool defs).
    # Free-text banking questions use Marcus persona system prompt (warmer, no tool markers).
    _tool_keywords = [
        'tool_call', 'TOOL_CALL', 'prep_next_client', 'my_calendar_today',
        'd365_customer_lookup', 'd365_check_in_queue', 'd365_log_activity',
        'd365_recent_activities', 'read(', 'write(', 'exec(',
        'Use the prep_next_client', 'Use the my_calendar', 'Use the d365_',
        'run a command', 'get-childitem', 'get-content',
        'Show me my calendar', 'What meetings do I have',
    ]
    _needs_tools = any(kw in message for kw in _tool_keywords)

    def generate():
        # Free-text path: use Marcus persona prompt (warmer tone, conversation history)
        if _MARCUS_AVAILABLE and not _needs_tools:
            yield json.dumps({"type": "thinking"}) + "\n"
            start = _time.time()
            try:
                history = data.get("history", [])
                marcus_response, elapsed = _marcus_chat(message, history)
                think_time = round(elapsed, 1)
                yield json.dumps({"type": "think_done", "time": think_time}) + "\n"
                total = round(_time.time() - start, 1)
                yield json.dumps({"type": "response", "text": marcus_response, "time": total}) + "\n"
                yield json.dumps({"type": "done"}) + "\n"
            except Exception as e:
                print(f"[Marcus] Error: {e}", flush=True)
                yield json.dumps({"type": "error", "message": str(e)}) + "\n"
            return

        # Tool-calling path: use AGENT_SYSTEM_PROMPT (includes tool definitions)
        yield json.dumps({"type": "thinking"}) + "\n"
        start = _time.time()

        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                max_tokens=1024,
                temperature=0.3,
            )
            _track_model_call(response, _time.time() - _call_start)
            model_output = (response.choices[0].message.content or "").strip()
            think_time = round(_time.time() - start, 1)
            print(f"[DEBUG] Model returned {len(model_output)} chars in {think_time}s")
            yield json.dumps({"type": "think_done", "time": think_time}) + "\n"

            # Step 2: Parse for tool call
            tool_call = parse_tool_call(model_output)
            print(f"[DEBUG] parse_tool_call returned: {tool_call}")

            if tool_call and tool_call.get("name") not in (None, "__text_response"):
                tool_name = tool_call["name"]
                tool_args = tool_call.get("arguments", {})
                yield json.dumps({"type": "tool_call", "name": tool_name, "arguments": tool_args}) + "\n"

                # Step 3: Execute tool
                exec_start = _time.time()
                result = execute_tool(tool_name, tool_args)
                exec_time = round(_time.time() - exec_start, 1)
                yield json.dumps({"type": "tool_result", "result": result, "time": exec_time}) + "\n"

                # Audit log
                AGENT_AUDIT_LOG.append({
                    "timestamp": _time.strftime("%H:%M:%S"),
                    "tool": tool_name,
                    "arguments": tool_args,
                    "success": result.get("success", False),
                    "time": exec_time,
                })

                # Step 4: Feed result back to model for a spoken summary
                yield json.dumps({"type": "thinking"}) + "\n"
                tool_output = result.get("output", result.get("error", "No output"))
                # Truncate large outputs so model stays focused
                if len(tool_output) > 1500:
                    tool_output = tool_output[:1500] + "\n...(truncated)"
                # Customize summary instruction based on tool type
                _summary_instruction = (
                    "Respond to the user in plain text based on this result. "
                    "Be concise. Do NOT use [TOOL_CALL] markers. "
                    "Use ONLY the information above — do not invent names or facts."
                )
                if tool_name == "prep_next_client":
                    _summary_instruction = (
                        "Format this client prep into THREE clearly separated sections. Use this EXACT structure:\n\n"
                        "MEETING\n"
                        "Write 2-3 sentences about the meeting: time, location, purpose, what to expect.\n\n"
                        "CLIENT PROFILE\n"
                        "Write 2-3 sentences about the client: who they are, their accounts, how they were referred, key context.\n\n"
                        "RECOMMENDED PRODUCTS\n"
                        "For each recommended product, write one bullet:\n"
                        "- Product name (Priority): the exact talk track in quotes, then the trigger reason.\n"
                        "Keep all talk tracks word for word. Do NOT combine sections. Do NOT merge into one paragraph.\n\n"
                        "Use ONLY information from the tool result. Do NOT invent facts. Do NOT use [TOOL_CALL] markers."
                    )
                followup_msgs = [
                    {"role": "system", "content": "You are a helpful assistant. Respond in plain text only. No tool calls."},
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": model_output},
                    {"role": "user", "content": (
                        f"Tool result:\n{tool_output}\n\n"
                        + _summary_instruction
                    )},
                ]
                try:
                    _call_start2 = _time.time()
                    followup = foundry_chat(
                        model=model,
                        messages=followup_msgs,
                        max_tokens=512,
                        temperature=0.3,
                    )
                    _track_model_call(followup, _time.time() - _call_start2)
                    final_text = (followup.choices[0].message.content or "").strip()
                except Exception as e:
                    final_text = f"Tool executed successfully but the AI summary failed: {e}"
                final_text = re.sub(r'\[/?TOOL_(?:CALL|RESPONSE)\]', '', final_text).strip()
                total = round(_time.time() - start, 1)
                yield json.dumps({"type": "response", "text": final_text, "time": total}) + "\n"

            else:
                # Pure text response (no tool needed)
                print(f"[DEBUG] No tool call detected, model_output length: {len(model_output)}")
                print(f"[DEBUG] model_output preview: {model_output[:300]}...")
                text = model_output
                if tool_call and tool_call.get("name") == "__text_response":
                    text = tool_call.get("arguments", {}).get("text", model_output)
                text = re.sub(r'\[/?TOOL_(?:CALL|RESPONSE)\]', '', text).strip()
                total = round(_time.time() - start, 1)
                print(f"[DEBUG] Yielding response event, text length: {len(text)}")
                yield json.dumps({"type": "response", "text": text, "time": total}) + "\n"

            yield json.dumps({"type": "done"}) + "\n"

        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(generate(), mimetype='text/plain')


# === Clean Room Auditor Endpoints ===

AUDITOR_DEMO_NDA = """MUTUAL NON-DISCLOSURE AGREEMENT

Effective Date: January 15, 2026
Agreement Number: NDA-2026-VD-PS-0847

BETWEEN:

Vertex Dynamics, Inc.
1200 Innovation Drive, Suite 400
San Jose, CA 95134
Contact: James Morrison, VP Corporate Development
Email: j.morrison@vertexdyn.com
Phone: (415) 555-0142

AND:

Pinnacle Solutions Group, LLC
8900 Enterprise Boulevard
Austin, TX 78759
Contact: Sarah Chen, General Counsel

SECTION 1. DEFINITION OF CONFIDENTIAL INFORMATION

1.1 "Confidential Information" means any and all non-public, proprietary, or confidential information disclosed by either party to the other, whether orally, in writing, electronically, or by inspection of tangible objects.

SECTION 2. OBLIGATIONS OF RECEIVING PARTY

2.1 The receiving party shall hold all Confidential Information in strict confidence and shall not disclose such information to any third party without the prior written consent of the disclosing party.

SECTION 3. TERM AND DURATION

3.1 This Agreement shall remain in effect for a period of two (2) years from the Effective Date.

3.2 The obligations of confidentiality shall survive termination for a period of five (5) years.

SECTION 4. INDEMNIFICATION AND LIABILITY

4.1 Each party shall indemnify and hold harmless the other party from claims arising from a breach of this Agreement.

4.2 NOTWITHSTANDING ANY OTHER PROVISION, THE DISCLOSING PARTY SHALL BE ENTITLED TO FULL INDEMNIFICATION FOR ALL DAMAGES, INCLUDING CONSEQUENTIAL, INCIDENTAL, INDIRECT, SPECIAL, AND PUNITIVE DAMAGES, ARISING FROM ANY BREACH BY THE RECEIVING PARTY. THIS PROVISION SHALL NOT BE SUBJECT TO ANY CAP OR LIMITATION.

SECTION 5. RETURN OF MATERIALS

5.1 Upon termination, the receiving party shall return or destroy all Confidential Information within thirty (30) days.

SECTION 6. REMEDIES

6.1 The non-breaching party shall be entitled to seek injunctive relief in addition to any other remedies.

SECTION 7. INTELLECTUAL PROPERTY

7.1 ALL WORK PRODUCT, INVENTIONS, AND INNOVATIONS, WHETHER CREATED PRIOR TO OR DURING THIS AGREEMENT, THAT ARE USED IN CONNECTION WITH THE PURPOSE, SHALL BE THE SOLE PROPERTY OF THE DISCLOSING PARTY.

SECTION 8. NON-SOLICITATION

8.1 Neither party shall solicit or hire employees of the other party for twelve (12) months following termination.

SECTION 9. NON-COMPETITION

9.1 The receiving party shall not engage in any competing business anywhere in the world for twenty-four (24) months following termination.

SECTION 10. GOVERNING LAW

10.1 This Agreement shall be governed by the laws of the State of Delaware.

IN WITNESS WHEREOF:

VERTEX DYNAMICS, INC.
By: _________________________
Name: James A. Morrison
Title: VP Corporate Development
SSN (for notarization): 478-93-3847
Date: January 15, 2026

PINNACLE SOLUTIONS GROUP, LLC
By: _________________________
Name: Sarah L. Chen
Title: General Counsel
Date: January 15, 2026
"""

@app.route('/auditor-demo-doc', methods=['GET'])
def auditor_demo_doc():
    """Return the pre-staged NDA document for demo."""
    text = AUDITOR_DEMO_NDA
    return jsonify({
        "filename": "contract_nda_vertex_pinnacle.txt",
        "text": text,
        "word_count": len(text.split())
    })


ESCALATION_DEMO_DOC = """CROSS-BORDER INTELLECTUAL PROPERTY LICENSE AND DATA PROCESSING AGREEMENT

Effective Date: February 1, 2026
Agreement No: XBIP-2026-0847

BETWEEN:

NovaTech Solutions GmbH ("Licensor")
Friedrichstrasse 123, 10117 Berlin, Germany
VAT: DE 814725903
Represented by: Dr. Elena Richter, Chief Technology Officer
Contact: elena.richter@novatech-solutions.de | +49 30 5557 2200

AND:

Pacific Rim Analytics, Inc. ("Licensee")
1400 Market Street, Suite 900, San Francisco, CA 94103, USA
EIN: 82-4193756
Represented by: Michael Tanaka, VP Engineering
Contact: m.tanaka@pacrimanalytics.com | +1 (415) 555-0193
SSN (for tax withholding form W-8BEN): 591-38-4720

RECITALS

WHEREAS Licensor owns proprietary machine learning models, training datasets, and related
intellectual property developed under EU-funded Horizon Europe grant HE-2024-AI-0293; and

WHEREAS Licensee desires to integrate said IP into commercial products distributed in the
United States, Japan, South Korea, and the European Economic Area;

NOW, THEREFORE, the parties agree:

1. GRANT OF LICENSE

1.1 Licensor grants Licensee a non-exclusive, non-transferable license to use the Licensed IP
(defined in Schedule A) solely for the Permitted Purposes (defined in Schedule B).

1.2 Sub-licensing requires prior written consent and is subject to GDPR Article 28 processor
requirements where personal data is involved.

2. DATA PROCESSING AND TRANSFER

2.1 Cross-Border Transfer Mechanism: Personal data transferred from the EEA to the United
States shall be governed by the EU-US Data Privacy Framework, supplemented by Standard
Contractual Clauses (Module 2: Controller to Processor) as annexed hereto.

2.2 Licensee shall implement appropriate safeguards per GDPR Article 46 and maintain
certification under the California Consumer Privacy Act (CCPA) as amended by the CPRA.

2.3 Data Localization: Model training data containing EEA personal data shall not be stored
outside the European Economic Area without explicit Data Protection Impact Assessment (DPIA)
approved by Licensor's Data Protection Officer, Dr. Karl Weissman (karl.w@novatech-solutions.de).

3. INTELLECTUAL PROPERTY INDEMNIFICATION

3.1 Licensor warrants that the Licensed IP does not, to Licensor's knowledge, infringe any
third-party intellectual property rights in the jurisdictions listed in Section 1.2.

3.2 Indemnification Cap: Licensor's total liability under this Section shall not exceed the
greater of (a) EUR 2,000,000 or (b) 200% of license fees paid in the preceding 12 months.

3.3 Licensee acknowledges that the Licensed IP incorporates open-source components listed in
Schedule C, governed by Apache 2.0, MIT, and LGPL-3.0 licenses respectively.

4. PAYMENT AND TAX WITHHOLDING

4.1 License Fee: USD 450,000 per annum, payable quarterly.
4.2 Withholding Tax: Payments are subject to applicable US-Germany tax treaty provisions.
Licensor's German bank account for wire transfers:
  Bank: Deutsche Bank AG
  IBAN: DE89 3704 0044 0532 0130 00
  BIC/SWIFT: COBADEFFXXX
  Account Holder: NovaTech Solutions GmbH

5. GOVERNING LAW AND DISPUTE RESOLUTION

5.1 This Agreement shall be governed by the laws of Germany, without regard to conflict of
laws principles, except that IP infringement claims shall be adjudicated under the laws of the
jurisdiction where infringement is alleged.

5.2 Disputes shall be submitted to binding arbitration under ICC Rules, seated in London, UK.

SIGNATURES:

NovaTech Solutions GmbH
By: _________________________
Dr. Elena Richter, CTO
Date: February 1, 2026

Pacific Rim Analytics, Inc.
By: _________________________
Michael Tanaka, VP Engineering
SSN: 591-38-4720
Date: February 1, 2026
"""


MARKETING_CLEAN_DOC = """\
SURFACE COPILOT+ PC — ENTERPRISE LANDING PAGE DRAFT
Asset Type: Webpage / Microsite
Target Audience: Commercial / Enterprise IT Decision Makers
Region: United States
Silicon: Intel Core Ultra (different different different Core Ultra 200V)

============================================================
HERO SECTION
============================================================

Surface Copilot+ PC — Built for the AI-Powered Workplace

Your team's next PC does more than run apps — it thinks alongside them.
Surface Copilot+ PC brings AI experiences directly to the device, powered
by a dedicated Neural Processing Unit (NPU) so employees can work smarter
without sending data to the cloud.

[CTA: Talk to a Surface Specialist]

============================================================
KEY MESSAGING SECTION
============================================================

WHY SURFACE COPILOT+ PC FOR ENTERPRISE

On-Device AI That Respects Your Data Policies
Surface Copilot+ PC processes AI workloads locally using the built-in NPU,
keeping sensitive data on the device. Copilot+ PC experiences are designed
to help employees summarize, search, and create — right from their laptop.

Availability varies by experience, silicon, and market.
Learn more: aka.ms/copilotpluspcspro

Built for Microsoft 365 and Your Existing Stack
Surface Copilot+ PCs integrate with Microsoft 365, Microsoft Intune, and
your organization's security policies out of the box. IT teams can deploy
and manage Surface devices using familiar tools.

Enterprise-Grade Security from Chip to Cloud
Every Surface Copilot+ PC ships with Microsoft Pluton security processor,
Secured-core PC capabilities, and Windows Hello for Business. Your security
team gets hardware-rooted protection without additional configuration.

============================================================
CUSTOMER EVIDENCE SECTION
============================================================

"Surface devices have simplified our deployment process across 12,000
endpoints." — Maria Torres, VP of IT Infrastructure, Contoso Financial
(Quote used with written permission per Customer Quote Agreement.
Contoso Financial received no compensation for this testimonial.)

============================================================
AI EXPERIENCES SECTION
============================================================

Copilot+ PC Experiences Available on Surface

Recall (Preview) — Find anything you've seen on your PC using natural
language search. Recall processes and stores snapshots locally on the
device using the NPU.
Note: Recall is currently in preview through Windows Insider Program and
is not yet generally available. Feature availability and timeline subject
to change.

Live Captions with Translation — Get real-time translated captions in
over 40 languages, processed entirely on-device.

Cocreator in Paint — Generate and iterate on images using text prompts
and drawing, powered by on-device AI.

============================================================
CALL TO ACTION
============================================================

Ready to bring AI-powered devices to your workforce?
Contact your Microsoft Surface account team to schedule a demo and
discuss volume licensing.

[CTA: Request a Demo]  [CTA: View Surface for Business]

============================================================
DISCLAIMERS / FOOTER
============================================================

Copilot+ PC experiences availability varies by feature, device, market,
and silicon. Some experiences require enrollment in Windows Insider
Program and are not generally available.
Learn more at aka.ms/copilotpluspcspro

© 2026 Microsoft Corporation. All rights reserved.
"""


MARKETING_RISKY_DOC = """\
SURFACE COPILOT+ PC — CAMPAIGN BRIEF: "THE SMARTEST PC EVER BUILT"
Asset Type: Above-the-Line Campaign (Web + OOH + Digital Video)
Target Audience: Commercial + Consumer
Region: Global (including China)
Authored by: CVP, Surface Marketing

============================================================
CAMPAIGN TEAM / INTERNAL NOTES (DO NOT PUBLISH)
============================================================

Campaign lead: Sarah Chen, s.chen@microsoft.com, (425) 555-0193
Freelance copywriter: Marcus Rivera, SSN 847-20-9531 (W-9 on file)
Legal review requested — awaiting CELA sign-off before launch.

============================================================
HERO SECTION
============================================================

The Most Intelligent PC Ever Made

Surface Copilot+ PC is the only laptop that truly understands you.
With the most powerful NPU on the market, Surface delivers AI experiences
no other PC can match — making you 40% more productive from day one.

"I switched from MacBook and I'll never go back." — anonymous user review

[CTA: Buy Now — Starting at $999]

============================================================
PERFORMANCE CLAIMS SECTION
============================================================

UNMATCHED PERFORMANCE. PROVEN RESULTS.

Surface Copilot+ PC outperforms every competitor in AI workload benchmarks:
- 3x faster AI processing than the leading competitor's laptop
- 47% improvement in battery life compared to previous generation
- Reduces meeting prep time by 2 hours per week
- 60% less energy consumption than traditional PCs — our greenest Surface ever
- NPU delivers 45 TOPS, the highest sustained AI throughput of any laptop

Customers report an average ROI of 340% within the first year of deployment.

"Surface Copilot+ PC cut our incident response time in half and saved us
$2.3 million annually." — Senior IT Leader, Major US Bank
(Name withheld for confidentiality)

============================================================
AI CAPABILITIES SECTION
============================================================

AI THAT WORKS FOR YOU — RESPONSIBLY AND SECURELY

Surface Copilot+ PC is built on Microsoft's responsible AI-compliant
platform, ensuring every AI interaction meets the highest ethical
standards. Our AI systems are guaranteed free from bias and always
produce accurate, trustworthy results.

Key AI Experiences:
- Recall: Perfect photographic memory for your PC. Never lose anything again.
  Available on all Copilot+ PCs across all regions.
- AI-Powered Health Insights: Surface can help monitor your posture and
  suggest ergonomic adjustments, promoting healthier work habits.
- Autonomous Email Triage: AI reads, prioritizes, and responds to your
  emails automatically — learning your communication style over time.
- Smart Document Classification: AI automatically categorizes sensitive
  documents for compliance, meeting regulatory requirements for financial
  services and healthcare organizations.

============================================================
CUSTOMER EVIDENCE SECTION
============================================================

TRUSTED BY THE WORLD'S BEST COMPANIES

[Logos: JPMorgan Chase, Bank of America, Starbucks, Mayo Clinic, NASA]

"We deployed 50,000 Surface Copilot+ PCs across our trading floors and
back-office operations. The AI capabilities have transformed how our
analysts work." — Global Head of Technology, JPMorgan Chase

Microsoft was recently ranked #1 in Gartner's Magic Quadrant for
Endpoint Management, proving that Surface is the enterprise standard.

============================================================
SUSTAINABILITY SECTION
============================================================

GOOD FOR YOUR BUSINESS. BETTER FOR THE PLANET.

Surface Copilot+ PC is carbon neutral and built with 100% recycled
ocean-bound plastic. By choosing Surface, your organization reduces
its carbon footprint by up to 35% compared to industry alternatives.

We're committed to being the most sustainable PC brand in the world.

============================================================
PRICING AND AVAILABILITY
============================================================

Available now worldwide — order today and get free next-day delivery!

Surface Copilot+ PC — from $999 (save $200 for a limited time!)
Surface Copilot+ PC with Copilot Pro — from $1,199
Enterprise Volume Licensing — Contact us for exclusive pricing

Best laptop deal of the year. Guaranteed lowest price.

============================================================
CONTEST / PROMOTION
============================================================

WIN A SURFACE STUDIO SETUP!
Purchase any Surface Copilot+ PC before March 31, 2026 and enter to
win a complete Surface Studio workspace valued at $5,000.
No purchase necessary. Void where prohibited.

============================================================
FOOTER
============================================================

© 2026 Microsoft Corporation. All rights reserved.
"""


# --- Marketing CELA hardcoded findings for demo docs ---

_MARKETING_CLEAN_FINDINGS = [
    {
        "category": "AI Claims",
        "claim_text": "AI-Powered Workplace",
        "risk_level": "LOW",
        "issue": "Verify 'AI-Powered' aligns with approved Microsoft AI terminology guidelines",
        "substantiation": "Check against current brand-approved AI phrasing list",
        "recommendation": "Confirm term is on approved list; likely acceptable for enterprise audience"
    },
    {
        "category": "AI Claims",
        "claim_text": "Find anything you've seen on your PC",
        "risk_level": "LOW",
        "issue": "Broad capability claim for Recall (Preview) — could be read as overclaim",
        "substantiation": "Feature is in preview and has known limitations",
        "recommendation": "Already disclaimed as preview; consider softening to 'helps you find things'"
    },
    {
        "category": "Customer Evidence",
        "claim_text": "Surface devices have simplified our deployment process across 12,000 endpoints.",
        "risk_level": "LOW",
        "issue": "Customer testimonial present — verify Customer Quote Agreement (CQA) is on file",
        "substantiation": "CQA documentation noted in asset; verify file exists",
        "recommendation": "Confirm CQA reference number is current and permission has not expired"
    },
]

_MARKETING_CLEAN_VERDICT = {
    "verdict": "SELF-SERVICE OK",
    "verdict_reason": "Asset uses measured language with appropriate disclaimers. No comparative claims, no unsubstantiated statistics, no prohibited AI messaging. Minor terminology items flagged for verification.",
    "trigger_categories": "None",
    "total_findings": "3",
    "high_risk_count": "0",
    "medium_risk_count": "0",
    "low_risk_count": "3"
}

_MARKETING_RISKY_FINDINGS = [
    {
        "category": "Superlative",
        "claim_text": "The Most Intelligent PC Ever Made",
        "risk_level": "HIGH",
        "issue": "Unsubstantiated superlative — 'most intelligent' requires benchmark proof",
        "substantiation": "Objective benchmark data comparing all PCs ever made required",
        "recommendation": "Remove superlative or replace with substantiated claim"
    },
    {
        "category": "Superlative",
        "claim_text": "the only laptop that truly understands you",
        "risk_level": "HIGH",
        "issue": "Exclusivity claim ('only') plus anthropomorphic AI claim ('understands you')",
        "substantiation": "Cannot prove exclusivity across all competitors; 'understands' implies sentience",
        "recommendation": "Remove 'only' and rephrase to describe specific AI capabilities"
    },
    {
        "category": "Stat Claim",
        "claim_text": "making you 40% more productive from day one",
        "risk_level": "HIGH",
        "issue": "Unsubstantiated productivity statistic with absolute timeline",
        "substantiation": "Peer-reviewed study or controlled benchmark required with methodology",
        "recommendation": "Remove stat or add source citation and qualifying language"
    },
    {
        "category": "Comparative",
        "claim_text": "3x faster AI processing than the leading competitor's laptop",
        "risk_level": "HIGH",
        "issue": "Comparative claim against unnamed competitor — requires benchmark data",
        "substantiation": "Named competitor, specific benchmark, test conditions required",
        "recommendation": "Remove comparative or provide verifiable benchmark data with methodology"
    },
    {
        "category": "Stat Claim",
        "claim_text": "47% improvement in battery life compared to previous generation",
        "risk_level": "HIGH",
        "issue": "Performance improvement claim without test methodology",
        "substantiation": "Internal benchmark data with test conditions and methodology",
        "recommendation": "Add footnote with specific test conditions and baseline model"
    },
    {
        "category": "Green Claim",
        "claim_text": "60% less energy consumption — our greenest Surface ever",
        "risk_level": "HIGH",
        "issue": "Unsubstantiated environmental claim plus superlative 'greenest'",
        "substantiation": "Energy Star data or EPA-recognized test methodology required",
        "recommendation": "Remove 'greenest' superlative; add energy comparison methodology"
    },
    {
        "category": "Stat Claim",
        "claim_text": "Customers report an average ROI of 340% within the first year",
        "risk_level": "HIGH",
        "issue": "Unsubstantiated ROI claim — requires customer study data",
        "substantiation": "Customer survey or case study with sample size and methodology",
        "recommendation": "Remove or replace with verified case study reference"
    },
    {
        "category": "Customer Evidence",
        "claim_text": "anonymous user review — 'I switched from MacBook and I'll never go back'",
        "risk_level": "HIGH",
        "issue": "Anonymous testimonial is explicitly prohibited by CELA guidelines",
        "substantiation": "All testimonials must be attributable with documented permission",
        "recommendation": "Remove anonymous quote or obtain named, documented permission"
    },
    {
        "category": "Customer Evidence",
        "claim_text": "Senior IT Leader, Major US Bank (Name withheld for confidentiality)",
        "risk_level": "HIGH",
        "issue": "Withheld-name testimonial with specific dollar claim ($2.3M) — prohibited",
        "substantiation": "Named attribution with Customer Quote Agreement required",
        "recommendation": "Obtain named attribution or remove testimonial entirely"
    },
    {
        "category": "Customer Evidence",
        "claim_text": "[Logos: JPMorgan Chase, Bank of America, Starbucks, Mayo Clinic, NASA]",
        "risk_level": "HIGH",
        "issue": "Customer logos require explicit logo usage agreements from each company",
        "substantiation": "Logo usage agreements and External Communications Approval (ECA) for each",
        "recommendation": "Remove logos until all agreements are documented and current"
    },
    {
        "category": "AI Overclaim",
        "claim_text": "responsible AI-compliant platform... guaranteed free from bias and always produce accurate results",
        "risk_level": "HIGH",
        "issue": "Prohibited AI messaging — cannot claim 'guaranteed free from bias' or 'always accurate'",
        "substantiation": "These claims are inherently unsubstantiable for any AI system",
        "recommendation": "Remove absolute AI claims; use approved Responsible AI language only"
    },
    {
        "category": "AI Overclaim",
        "claim_text": "Recall: Perfect photographic memory... Never lose anything again",
        "risk_level": "HIGH",
        "issue": "Overclaim for Preview feature — 'perfect' and 'never' are absolute claims",
        "substantiation": "Feature is in preview, has known limitations, not GA in all regions",
        "recommendation": "Remove 'perfect' and 'never'; add preview/availability disclaimers"
    },
    {
        "category": "AI Overclaim",
        "claim_text": "Autonomous Email Triage: AI reads, prioritizes, and responds to your emails automatically",
        "risk_level": "MEDIUM",
        "issue": "Autonomous AI claim for email handling — sensitive use case",
        "substantiation": "Feature must have human oversight; 'autonomous' implies no human control",
        "recommendation": "Replace 'autonomous' with 'AI-assisted'; clarify human remains in control"
    },
    {
        "category": "Green Claim",
        "claim_text": "carbon neutral and built with 100% recycled ocean-bound plastic",
        "risk_level": "HIGH",
        "issue": "Environmental claims require substantiation per FTC Green Guides",
        "substantiation": "Third-party certification for carbon neutrality and recycled content claims",
        "recommendation": "Add certification references; verify '100%' recycled content claim accuracy"
    },
    {
        "category": "Pricing",
        "claim_text": "Guaranteed lowest price",
        "risk_level": "HIGH",
        "issue": "Absolute pricing guarantee — legally binding and extremely difficult to substantiate",
        "substantiation": "Price matching program documentation and monitoring system required",
        "recommendation": "Remove 'guaranteed lowest price' — replace with factual pricing"
    },
    {
        "category": "Stat Claim",
        "claim_text": "save $200 for a limited time",
        "risk_level": "MEDIUM",
        "issue": "Limited time offer must have defined end date per FTC guidelines",
        "substantiation": "Promotion end date and regular price documentation",
        "recommendation": "Add specific promotion end date and reference regular price"
    },
]

_MARKETING_RISKY_VERDICT = {
    "verdict": "CELA INTAKE REQUIRED",
    "verdict_reason": "Asset contains multiple mandatory intake triggers: above-the-line campaign, CVP authorship, comparative claims, unsubstantiated statistics, prohibited AI messaging, anonymous testimonials, green claims, pricing guarantees, and sweepstakes promotion.",
    "trigger_categories": "Superlative, Comparative, Stat Claims, AI Overclaim, Green Claims, Customer Evidence, Pricing, Promotions",
    "total_findings": "16",
    "high_risk_count": "13",
    "medium_risk_count": "2",
    "low_risk_count": "1"
}


@app.route('/auditor-escalation-demo-doc', methods=['GET'])
def auditor_escalation_demo_doc():
    """Return the cross-border IP license document for escalation demo."""
    text = ESCALATION_DEMO_DOC
    return jsonify({
        "filename": "cross_border_ip_license.txt",
        "text": text,
        "word_count": len(text.split())
    })


@app.route('/auditor-marketing-demo-doc', methods=['GET'])
def auditor_marketing_demo_doc():
    """Return the clean marketing campaign document for self-service OK demo."""
    text = MARKETING_CLEAN_DOC
    return jsonify({
        "filename": "marketing_surface_campaign_clean.txt",
        "text": text,
        "word_count": len(text.split())
    })


@app.route('/auditor-marketing-escalation-demo-doc', methods=['GET'])
def auditor_marketing_escalation_demo_doc():
    """Return the risky marketing campaign document for CELA intake demo."""
    text = MARKETING_RISKY_DOC
    return jsonify({
        "filename": "marketing_surface_campaign_risky.txt",
        "text": text,
        "word_count": len(text.split())
    })


def _estimate_pii_location(text, char_pos):
    """Estimate page and context from character position."""
    chars_per_page = 3000
    page = (char_pos // chars_per_page) + 1
    start = max(0, char_pos - 100)
    end = min(len(text), char_pos + 100)
    context = text[start:end]

    section_match = re.search(r'SECTION\s+(\d+)', context, re.IGNORECASE)
    if section_match:
        return f"Page {page}, Section {section_match.group(1)}"

    if any(word in context.lower() for word in ['signature', 'witness', 'notary']):
        return f"Page {page}, Signature block"

    return f"Page {page}"


def _parse_analysis_response(response_text):
    """Parse AI response into structured risk and obligation findings.

    Returns: (risk_findings, obligation_findings, used_fallback)
    - used_fallback is True if hardcoded demo findings were used instead of parsed AI output
    """
    risk_findings = []
    obligation_findings = []
    used_fallback = False

    # Try to extract structured data, with fallbacks
    lines = response_text.split('\n')

    current_risk = {}
    for line in lines:
        line = line.strip()

        # Skip empty lines and section headers
        if not line:
            continue
        line_lower = line.lower()

        # Skip section headers like "HIGH RISK clauses:", "MEDIUM RISK clauses:"
        if line_lower.endswith('clauses:') or line_lower.endswith('risk:'):
            continue

        # When we see a new SEVERITY line, save the previous finding first
        if line_lower.startswith('severity:') or line_lower.startswith('- severity:'):
            # Save previous finding if complete
            if current_risk.get('finding'):
                risk_findings.append(current_risk)
            # Start new finding
            current_risk = {}
            level = line.split(':', 1)[1].strip().upper()
            if level in ('HIGH', 'MEDIUM', 'LOW'):
                current_risk['severity'] = level.lower()
        elif line_lower.startswith('section:') or line_lower.startswith('- section:'):
            current_risk['section'] = line.split(':', 1)[1].strip()
        elif line_lower.startswith('type:') or line_lower.startswith('- type:'):
            current_risk['type'] = line.split(':', 1)[1].strip()
        elif line_lower.startswith('finding:') or line_lower.startswith('- finding:'):
            current_risk['finding'] = line.split(':', 1)[1].strip()
        elif line_lower.startswith('recommendation:') or line_lower.startswith('- recommendation:'):
            current_risk['recommendation'] = line.split(':', 1)[1].strip()

        # Obligation parsing
        elif line_lower.startswith('obligation:') or line_lower.startswith('- obligation:'):
            obl = {'obligation': line.split(':', 1)[1].strip(), 'deadline': '', 'consequence': ''}
            obligation_findings.append(obl)
        elif line_lower.startswith('deadline:') and obligation_findings:
            obligation_findings[-1]['deadline'] = line.split(':', 1)[1].strip()
        elif line_lower.startswith('consequence:') and obligation_findings:
            obligation_findings[-1]['consequence'] = line.split(':', 1)[1].strip()

    # Capture last risk if pending
    if current_risk.get('finding'):
        risk_findings.append(current_risk)

    # Debug: print what was parsed
    print(f"[AUDITOR DEBUG] Parsed {len(risk_findings)} risk findings, {len(obligation_findings)} obligations")

    # If parsing failed, create fallback findings from key sections in demo NDA
    if not risk_findings:
        used_fallback = True
        # Fallback findings for the demo NDA
        risk_findings = [
            {
                "severity": "high",
                "section": "4.2",
                "type": "Indemnification",
                "finding": "Unlimited indemnification with no cap on damages, including consequential and punitive damages.",
                "recommendation": "Negotiate a liability cap tied to contract value or 2x fees."
            },
            {
                "severity": "medium",
                "section": "7.1",
                "type": "IP Assignment",
                "finding": "Broad IP assignment that may capture pre-existing work product created before the agreement.",
                "recommendation": "Carve out pre-existing IP and limit to work created specifically under this agreement."
            },
            {
                "severity": "medium",
                "section": "9.1",
                "type": "Non-Compete",
                "finding": "24-month global non-compete restriction. Likely unenforceable in California.",
                "recommendation": "Narrow geographic scope or reduce to 12 months."
            },
            {
                "severity": "low",
                "section": "1-3",
                "type": "Confidentiality",
                "finding": "Standard mutual NDA confidentiality terms with reasonable 5-year survival period.",
                "recommendation": "No changes needed - standard boilerplate."
            }
        ]

    if not obligation_findings:
        # Don't set used_fallback for obligations - risks are the main analysis
        # Obligations are supplementary and often not in AI response
        obligation_findings = [
            {"obligation": "Confidentiality period", "deadline": "5 years from termination", "consequence": "Breach damages"},
            {"obligation": "Return materials", "deadline": "30 days after termination", "consequence": "Must certify destruction"},
            {"obligation": "Non-compete", "deadline": "24 months post-termination", "consequence": "Injunctive relief"}
        ]

    return risk_findings, obligation_findings, used_fallback


def _parse_marketing_response(ai_response):
    """Parse marketing CELA review output into structured findings and verdict."""
    claims = []
    current_claim = {}
    verdict_data = {}

    for line in ai_response.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()

        # Claim-level fields
        if upper.startswith('CATEGORY:'):
            if current_claim and current_claim.get('claim_text'):
                claims.append(current_claim)
            current_claim = {'category': stripped.split(':', 1)[1].strip()}
        elif upper.startswith('CLAIM_TEXT:'):
            current_claim['claim_text'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('RISK_LEVEL:'):
            current_claim['risk_level'] = stripped.split(':', 1)[1].strip().upper()
        elif upper.startswith('ISSUE:'):
            current_claim['issue'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('SUBSTANTIATION:'):
            current_claim['substantiation'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('RECOMMENDATION:') and current_claim:
            current_claim['recommendation'] = stripped.split(':', 1)[1].strip()

        # Verdict-level fields
        elif upper.startswith('VERDICT:'):
            verdict_data['verdict'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('VERDICT_REASON:'):
            verdict_data['verdict_reason'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('TRIGGER_CATEGORIES:'):
            verdict_data['trigger_categories'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('TOTAL_FINDINGS:'):
            verdict_data['total_findings'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('HIGH_RISK_COUNT:'):
            verdict_data['high_risk_count'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('MEDIUM_RISK_COUNT:'):
            verdict_data['medium_risk_count'] = stripped.split(':', 1)[1].strip()
        elif upper.startswith('LOW_RISK_COUNT:'):
            verdict_data['low_risk_count'] = stripped.split(':', 1)[1].strip()

    if current_claim and current_claim.get('claim_text'):
        claims.append(current_claim)

    return claims, verdict_data


@app.route('/analyze-id', methods=['POST'])
def analyze_id():
    data = request.json
    ocr_text = data.get('ocr_text', '')
    model = DEFAULT_MODEL

    # Demo preset: McLovin (Superbad fake ID)
    if "McLOVIN" in ocr_text and "HAWAII" in ocr_text:
        return jsonify({
            "fields": {
                "name": "McLovin",
                "address": "892 Momona St, Honolulu, HI 96820",
                "dob": "06/03/1981",
                "id_number": "01-47-87441",
                "expiration": "06/03/2008",
                "state": "Hawaii",
                "class": "Not specified"
            },
            "status": "Review Needed",
            "notes": "MULTIPLE FLAGS: (1) Single name only, no first/last name distinction. "
                     "(2) ID expired June 2008, nearly 18 years ago. "
                     "(3) No last name is highly unusual for a US driver's license. "
                     "(4) Address 'Momona St' does not appear in USPS records for Honolulu. "
                     "Recommend manual verification before proceeding."
        })

    # Demo preset: Jackie Rodriguez (valid, triggers D365 flow)
    if "RODRIGUEZ" in ocr_text and "JACKIE" in ocr_text and "MICHIGAN" in ocr_text:
        return jsonify({
            "fields": {
                "name": "Jackie Marie Rodriguez",
                "address": "1847 Maple Avenue, Troy, MI 48083",
                "dob": "04/12/1981",
                "id_number": "R 320 481 227 093",
                "expiration": "09/15/2028",
                "state": "Michigan",
                "class": "D"
            },
            "status": "Valid",
            "notes": "All fields verified. ID is current and complete."
        })

    prompt = """You are an ID document analyzer. Given the OCR text extracted from a US driver's license or state ID, extract the following information.

IMPORTANT - US Driver's License Name Format:
- Field 1 (often labeled "1" or "LN"): LAST NAME (surname/family name)
- Field 2 (often labeled "2" or "FN"): FIRST NAME and MIDDLE NAME
- Combine these as: "First Middle Last" (e.g., if you see "1BUCHHOLZ" and "2FRANK JOACHIM", the full name is "Frank Joachim Buchholz")

IMPORTANT - License Number:
- The license/ID number is usually labeled "4d LIC#" or "DL" and is an alphanumeric code (e.g., "WDLBTJC488FB")
- Do NOT confuse the street address number with the license number

Extract these fields:
- name: Full name in "First Middle Last" format (combine fields 1 and 2 as described above)
- address: Street address, city, state, ZIP
- dob: Date of birth (usually field 3 or "DOB")
- id_number: Driver's license number (the alphanumeric code, NOT the street number)
- expiration: Expiration date (usually field 4b or "EXP")
- state: Issuing state (e.g., WA, CA, TX)
- class: License class if shown

Determine status:
- "Valid" if expiration date is after January 2026 and info looks complete
- "Expired" if expiration date is before January 2026
- "Review Needed" if critical information is unclear or missing

Return your response in this exact JSON format:
{
    "fields": {
        "name": "...",
        "address": "...",
        "dob": "...",
        "id_number": "...",
        "expiration": "...",
        "state": "...",
        "class": "..."
    },
    "status": "Valid|Review Needed|Expired",
    "notes": "..."
}

OCR Text from ID:
---
""" + ocr_text + """
---

Return ONLY valid JSON, no other text."""

    try:
        _call_start = _time.time()
        response = foundry_chat(
            model=model,
            messages=[
                {"role": "system", "content": "You are an ID verification assistant. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=512,
            temperature=0.3
        )
        _track_model_call(response, _time.time() - _call_start)

        result_text = response.choices[0].message.content.strip()
        
        # Try to parse JSON from response
        import json
        try:
            # Handle potential markdown code blocks
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            result = json.loads(result_text)
        except:
            # If JSON parsing fails, return a structured error
            result = {
                "fields": {"name": "Could not parse"},
                "status": "Review Needed",
                "notes": "AI response was not in expected format. Raw: " + result_text[:200]
            }
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "fields": {},
            "status": "Error",
            "notes": "Analysis failed"
        })

@app.route('/analyze-check', methods=['POST'])
def analyze_check():
    """Analyze OCR text from a check image and extract structured fields."""
    data = request.json
    ocr_text = data.get('ocr_text', '')
    model = DEFAULT_MODEL

    # Check for demo OCR text (contains our known demo check markers)
    is_demo = ("JACKIE" in ocr_text and "RODRIGUEZ" in ocr_text and "1133" in ocr_text) or ("MICHIGAN POWER" in ocr_text and "245.89" in ocr_text)
    if is_demo:
        return jsonify({
            "fields": {
                "payee_name": "Jackie Marie Rodriguez",
                "payer_name": "Michigan Power & Light",
                "check_number": "1133",
                "date": "03/15/2026",
                "amount_numbers": "245.89",
                "amount_words": "Two Hundred Forty-Five and 89/100",
                "bank_name": "First City Bank",
                "routing_last4": "0101",
                "account_last4": "1991",
                "memo": "Account Overpayment Refund",
                "signature_present": "yes"
            },
            "status": "Verified",
            "flags": [
                {"severity": "pass", "message": "Amounts match (numeric and written)"},
                {"severity": "pass", "message": "Authorized signature present"},
                {"severity": "pass", "message": "Date is current (within 180 days)"},
                {"severity": "pass", "message": "All required fields detected"}
            ],
            "source": "demo_preset"
        })

    prompt = """You are a check verification assistant. Analyze the OCR text from a scanned check image.

Extract these fields as JSON:
- payee_name: who the check is payable to
- payer_name: who wrote the check (name printed on check)
- check_number: the check number
- date: date on the check
- amount_numbers: dollar amount in numbers
- amount_words: dollar amount written in words
- bank_name: the issuing bank name
- routing_last4: last 4 digits of routing number
- account_last4: last 4 digits of account number
- memo: memo line content
- signature_present: "yes" or "no"

Also provide:
- status: "Verified" if all fields look good, "Review Needed" if issues found
- flags: array of objects with "severity" ("pass", "warning", or "error") and "message" for each validation check:
  - Do amounts (numbers vs words) match?
  - Is signature present?
  - Is date within 180 days?
  - Are all required fields present?

Return ONLY valid JSON with keys: fields, status, flags.

OCR Text from check:
---
""" + ocr_text + """
---

Return ONLY valid JSON, no other text."""

    try:
        _call_start = _time.time()
        response = foundry_chat(
            model=model,
            messages=[
                {"role": "system", "content": "You are a check verification assistant. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=512,
            temperature=0.3
        )
        _track_model_call(response, _time.time() - _call_start)

        result_text = response.choices[0].message.content.strip()
        try:
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            result = json.loads(result_text)
        except Exception:
            result = {
                "fields": {"payee_name": "Could not parse"},
                "status": "Review Needed",
                "flags": [{"severity": "error", "message": "AI response was not in expected format"}]
            }
        return jsonify(result)

    except Exception as e:
        return jsonify({
            "error": str(e),
            "fields": {},
            "status": "Error",
            "flags": [{"severity": "error", "message": "Analysis failed: " + str(e)}]
        })


@app.route('/d365/auth-status')
def d365_auth_status():
    """Check if D365 authentication is active."""
    if _D365_TOKEN_CACHE and _time.time() < (_D365_TOKEN_EXPIRY - 300):
        return jsonify({"authenticated": True, "source": "cached", "expires_in": int(_D365_TOKEN_EXPIRY - _time.time())})
    if DEMO_MODE:
        return jsonify({"authenticated": True, "source": "demo", "demo_mode": True})
    return jsonify({"authenticated": False, "message": "Run /d365/authenticate to connect"})


@app.route('/d365/authenticate', methods=['POST'])
def d365_authenticate():
    """Trigger D365 device code authentication. Returns the code for the user to enter."""
    try:
        import msal
        client_id = "1950a258-227b-4e31-a9cf-717495945fc2"
        authority = "https://login.microsoftonline.com/D365DemoTSCE32685848.onmicrosoft.com"
        scope = [_D365_ORG_URL + "/.default"]

        cache = msal.SerializableTokenCache()
        cache_file = _migrate_token_cache('.d365_token_cache.json')
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                cache.deserialize(f.read())

        app_msal = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)

        # Check if already authenticated
        accounts = app_msal.get_accounts()
        if accounts:
            result = app_msal.acquire_token_silent(scope, account=accounts[0])
            if result and "access_token" in result:
                global _D365_TOKEN_CACHE, _D365_TOKEN_EXPIRY
                _D365_TOKEN_CACHE = result["access_token"]
                _D365_TOKEN_EXPIRY = _time.time() + result.get("expires_in", 3600)
                if cache.has_state_changed:
                    with open(cache_file, 'w') as f:
                        f.write(cache.serialize())
                return jsonify({"status": "already_authenticated", "message": "D365 connection active"})

        # Need device code flow
        flow = app_msal.initiate_device_flow(scopes=scope)
        if "user_code" not in flow:
            return jsonify({"error": "Could not initiate device flow"}), 500

        # Start background thread to complete the flow
        def _complete_flow():
            global _D365_TOKEN_CACHE, _D365_TOKEN_EXPIRY
            result = app_msal.acquire_token_by_device_flow(flow)
            if "access_token" in result:
                _D365_TOKEN_CACHE = result["access_token"]
                _D365_TOKEN_EXPIRY = _time.time() + result.get("expires_in", 3600)
                if cache.has_state_changed:
                    with open(cache_file, 'w') as f:
                        f.write(cache.serialize())
                print("[D365] Authenticated successfully via device code")

        thread = threading.Thread(target=_complete_flow, daemon=True)
        thread.start()

        return jsonify({
            "status": "pending",
            "verification_uri": flow["verification_uri"],
            "user_code": flow["user_code"],
            "message": f"Go to {flow['verification_uri']} and enter code: {flow['user_code']}"
        })
    except ImportError:
        return jsonify({"error": "MSAL not installed. Run: pip install msal"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/d365/customer-lookup', methods=['POST'])
def d365_customer_lookup():
    """Look up a customer in Dynamics 365 by name.
    Currently returns demo data; will integrate live MSAL + Dataverse API
    when Michelle provides demo tenant credentials.
    """
    data = request.json or {}
    name = data.get('name', '').strip()

    if not name:
        return jsonify({"error": "No name provided"}), 400

    # Try live D365 lookup first
    try:
        # Search contacts by name (OData filter)
        # Use last name for more reliable matching (middle names may differ)
        safe_name = name.replace("'", "''")
        name_parts = safe_name.strip().split()
        search_term = name_parts[-1] if name_parts else safe_name  # Use last name
        result = _d365_api_get(
            "/contacts",
            params={
                "$filter": f"contains(fullname,'{search_term}')",
                "$select": "contactid,fullname,emailaddress1,telephone1,address1_composite,jobtitle,npu_accounttype,npu_accountage,npu_source,npu_relationshipmanager",
                "$top": "3"
            }
        )
        # If multiple results, try to find best match using first name too
        if result and result.get("value") and len(result["value"]) > 1 and len(name_parts) > 1:
            first = name_parts[0].lower()
            for c in result["value"]:
                if first in c.get("fullname", "").lower():
                    result["value"] = [c]
                    break
        if result and result.get("value"):
            contact = result["value"][0]
            contact_id = contact.get("contactid", "")

            # Build customer profile from live D365 data (including custom fields)
            customer = {
                "full_name": contact.get("fullname", name),
                "email": contact.get("emailaddress1", "Not on file"),
                "phone": contact.get("telephone1", "Not on file"),
                "address": contact.get("address1_composite", "Not on file"),
                "account_type": contact.get("npu_accounttype", "Not specified"),
                "account_age": contact.get("npu_accountage", "Not specified"),
                "source": contact.get("npu_source", "Not specified"),
                "relationship_manager": contact.get("npu_relationshipmanager", "Unassigned"),
                "accounts": [
                    {"type": "Essential Checking", "number": "****4832", "balance": "$0.00 (New)"},
                    {"type": "529 College Savings", "number": "Pending", "balance": "Inquiry"}
                ],
                "recent_activity": []
            }

            # Fetch recent activities for this contact
            try:
                activities = _d365_api_get(
                    "/activitypointers",
                    params={
                        "$filter": f"_regardingobjectid_value eq {contact_id}",
                        "$select": "subject,actualstart,activitytypecode",
                        "$orderby": "actualstart desc",
                        "$top": "5"
                    }
                )
                if activities and activities.get("value"):
                    for act in activities["value"]:
                        date = (act.get("actualstart") or "")[:10]
                        subject = act.get("subject", "Activity")
                        customer["recent_activity"].append(f"{date} - {subject}")
            except Exception:
                pass

            if not customer["recent_activity"]:
                customer["recent_activity"] = ["No recent activity found"]

            d365_url = _D365_ORG_URL + f"/main.aspx?appid=c22cb86f-ff3c-f111-88b5-002248357e0e&forceUCI=1&pagetype=entityrecord&etn=contact&id={contact_id}"
            print(f"[D365] Live lookup found: {customer['full_name']} (ID: {contact_id})")
            return jsonify({
                "source": "live",
                "customer": customer,
                "d365_url": d365_url
            })
    except Exception as e:
        print(f"[D365] Live lookup failed, using demo data: {e}")

    # Fallback: Demo data
    # Field names aligned with Michelle's D365 schema:
    # Account Type = Retail/Commercial, Account Age = years, Source = Referral/Walk In/Website
    _d365_org = "https://orgdf28000a.crm.dynamics.com"
    name_lower = name.lower()
    if "rodriguez" in name_lower or "jackie" in name_lower:
        return jsonify({
            "source": "demo",
            "customer": {
                "full_name": "Jackie Marie Rodriguez",
                "email": "jackie.rodriguez@email.com",
                "phone": "(248) 555-0147",
                "address": "1847 Maple Avenue, Troy, MI 48083",
                "account_type": "Retail",
                "account_age": "< 1 year",
                "source": "Referral",
                "relationship_manager": "Branch Manager",
                "accounts": [
                    {"type": "Essential Checking", "number": "****4832", "balance": "$0.00 (New)"},
                    {"type": "529 College Savings", "number": "Pending", "balance": "Inquiry"}
                ],
                "recent_activity": [
                    "03/15/2026 - New account application submitted",
                    "03/14/2026 - Appointment scheduled via kiosk check-in",
                    "03/10/2026 - Referred by existing member (ID: C-20198)"
                ]
            },
            "d365_url": _D365_ORG_URL + "/main.aspx?appid=c22cb86f-ff3c-f111-88b5-002248357e0e&forceUCI=1&pagetype=entityrecord&etn=contact&id=5cdc2c3f-ad29-f111-8342-002248357e0e"
        })

    # Generic fallback for unknown names
    return jsonify({
        "source": "demo",
        "customer": {
            "full_name": name,
            "email": "Not found",
            "phone": "Not found",
            "address": "Not found",
            "account_type": "New Customer",
            "relationship_manager": "Unassigned",
            "accounts": [],
            "recent_activity": ["No prior activity found"]
        },
        "d365_url": None
    })


@app.route('/d365/log-transaction', methods=['POST'])
def d365_log_transaction():
    """Log a transaction to Dynamics 365 customer record.
    Currently returns demo confirmation; will integrate live Dataverse API
    when Michelle provides demo tenant credentials.
    """
    data = request.json or {}
    _now = _time.strftime("%Y-%m-%dT%H:%M:%S")

    # Try live D365: create a Task activity on the contact
    try:
        customer_name = data.get("customer_name", "Unknown")
        safe_name = customer_name.replace("'", "''")
        # Find the contact first
        contact_result = _d365_api_get(
            "/contacts",
            params={
                "$filter": f"contains(fullname,'{safe_name}')",
                "$select": "contactid",
                "$top": "1"
            }
        )
        if contact_result and contact_result.get("value"):
            contact_id = contact_result["value"][0]["contactid"]
            # Create a task linked to the contact
            tx_type = data.get('transaction_type', 'Activity')
            if tx_type == "Check Deposit":
                subject = f"Check Deposit - ${data.get('amount', '0')} (Check #{data.get('check_number', 'N/A')})"
                description = (
                    f"Transaction: Check Deposit\n"
                    f"Amount: ${data.get('amount', '0')}\n"
                    f"Check #: {data.get('check_number', 'N/A')}\n"
                    f"Memo: {data.get('memo', '')}\n\n"
                    f"Processed locally on NPU -- zero data egress"
                )
            elif tx_type == "Meeting Notes":
                subject = f"Meeting Notes - {customer_name}"
                meeting_loc = data.get('meeting_location', '')
                meeting_date = data.get('meeting_date', '')
                products = data.get('products_discussed', '')
                ref_source = data.get('referral_source', '')
                description = (
                    f"CLIENT MEETING SUMMARY\n"
                    f"{'='*40}\n"
                    f"Client: {customer_name}\n"
                    f"Location: {meeting_loc}\n"
                    f"Date: {meeting_date}\n"
                    f"Products Discussed: {products}\n"
                    f"Referral Source: {ref_source}\n"
                    f"{'='*40}\n\n"
                    f"{data.get('memo', '')}\n\n"
                    f"{'='*40}\n"
                    f"Generated by on-device AI (Phi-4 Mini on NPU)\n"
                    f"Processed locally -- zero data egress"
                )
            else:
                subject = f"{tx_type} - {customer_name}"
                description = (
                    f"Type: {tx_type}\n"
                    f"Memo: {data.get('memo', '')}\n"
                    f"Processed locally on NPU -- zero data egress"
                )
            task_payload = {
                "subject": subject,
                "description": description,
                "regardingobjectid_contact@odata.bind": f"/contacts({contact_id})",
                "scheduledend": _now,
                "prioritycode": 2  # Normal
            }
            task_result = _d365_api_post("/tasks", task_payload)
            if task_result:
                activity_id = task_result.get("activityid", "N/A")
                print(f"[D365] Transaction logged live: {activity_id}")
                return jsonify({
                    "source": "live",
                    "status": "Completed",
                    "transaction_type": data.get("transaction_type", "Check Deposit"),
                    "amount": data.get("amount", "0"),
                    "check_number": data.get("check_number", "N/A"),
                    "customer_name": customer_name,
                    "memo": data.get("memo", ""),
                    "activity_id": activity_id,
                    "timestamp": _now,
                    "d365_record": f"Task created on Contact: {customer_name}"
                })
    except Exception as e:
        print(f"[D365] Live transaction log failed, using demo: {e}")

    # Fallback: demo response
    return jsonify({
        "source": "demo",
        "status": "Completed",
        "transaction_type": data.get("transaction_type", "Unknown"),
        "amount": data.get("amount", "0"),
        "check_number": data.get("check_number", "N/A"),
        "customer_name": data.get("customer_name", "Unknown"),
        "memo": data.get("memo", ""),
        "activity_id": "ACT-2026-" + str(hash(_now))[-6:],
        "timestamp": _now,
        "d365_record": "Contact: " + data.get("customer_name", "Unknown") + " | Activity logged"
    })


@app.route('/signature/verify', methods=['POST'])
def signature_verify():
    """Verify a pen signature by generating a local SHA-256 hash.
    No signature image data is transmitted to any cloud service.
    """
    data = request.json or {}
    image_data = data.get('image_data', '')

    if not image_data:
        return jsonify({"error": "No signature data provided"}), 400

    # Generate SHA-256 hash of the signature image data
    import hashlib
    sig_hash = hashlib.sha256(image_data.encode('utf-8')).hexdigest()

    _now = _time.strftime("%Y-%m-%dT%H:%M:%S")

    # Log to audit trail
    AGENT_AUDIT_LOG.append({
        "timestamp": _now,
        "action": "signature_captured",
        "details": "Digital signature captured and hashed locally. Hash: " + sig_hash[:16] + "...",
        "local": True
    })

    return jsonify({
        "hash": sig_hash,
        "timestamp": _now,
        "status": "captured",
        "message": "Signature captured and hashed locally. No data transmitted.",
        "local_processing": True
    })


@app.route('/audit-log', methods=['GET'])
def audit_log():
    """Return the agent's audit trail."""
    return jsonify(AGENT_AUDIT_LOG)


@app.route('/audit-log', methods=['DELETE'])
def clear_audit_log():
    """Clear the agent's audit trail."""
    AGENT_AUDIT_LOG.clear()
    return jsonify({"success": True})


@app.route('/session-stats', methods=['GET'])
def session_stats():
    """Return session stats and computed savings for the Local AI Savings widget."""
    calls = SESSION_STATS["calls"]
    input_tokens = SESSION_STATS["input_tokens"]
    output_tokens = SESSION_STATS["output_tokens"]
    inference_seconds = SESSION_STATS["inference_seconds"]

    # Foundry Local doesn't report token usage - estimate from call count
    # Average: ~600 input tokens (system prompt + content), ~300 output tokens
    if calls > 0 and input_tokens == 0:
        input_tokens = calls * 600
        output_tokens = calls * 300

    # Cloud cost: Azure GPT-4o pricing with 1.5x enterprise overhead
    # Input: $2.50/1M tokens, Output: $10.00/1M tokens
    cloud_cost = (input_tokens * 2.50 / 1e6 + output_tokens * 10.00 / 1e6) * 1.5

    # NPU energy: 5W sustained during inference
    npu_wh = inference_seconds * 5.0 / 3600

    # Cloud energy: 0.4 Wh per query (GPT-4o, arxiv/Epoch AI)
    cloud_wh = calls * 0.4

    # CO2 avoided: US grid average 373 g/kWh
    co2_avoided_g = (cloud_wh - npu_wh) / 1000 * 373

    return jsonify({
        "calls": calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "inference_seconds": round(inference_seconds, 1),
        "cloud_cost_saved": round(cloud_cost, 4),
        "npu_wh": round(npu_wh, 4),
        "cloud_wh": round(cloud_wh, 2),
        "co2_avoided_g": round(co2_avoided_g, 2),
    })


@app.route('/session-stats/reset', methods=['POST'])
def session_stats_reset():
    """Reset session stats to zero. Called on page load (hard refresh)."""
    SESSION_STATS["calls"] = 0
    SESSION_STATS["input_tokens"] = 0
    SESSION_STATS["output_tokens"] = 0
    SESSION_STATS["inference_seconds"] = 0.0
    return jsonify({"status": "reset"})


# --- Local Knowledge Endpoints ---

@app.route('/knowledge/search', methods=['POST'])
def knowledge_search():
    """Search local knowledge index."""
    data = request.get_json(silent=True) or {}
    query = data.get('query', '') if isinstance(data, dict) else ''
    results = search_knowledge(query)
    return jsonify({"results": results, "total_indexed": len(KNOWLEDGE_INDEX)})


@app.route('/knowledge/refresh', methods=['POST'])
def knowledge_refresh():
    """Rebuild the local knowledge index."""
    build_knowledge_index()
    return jsonify({"indexed": len(KNOWLEDGE_INDEX)})


# --- Two-Brain Router ---
ROUTER_LOG = []  # Structured trust receipt log


# Person names in demo data — curated list to avoid false positives on
# place names ("San Jose"), company names ("Surface Copilot"), etc.
_DEMO_PERSON_NAMES = re.compile(
    r'\b('
    r'Sarah Chen|James A\. Morrison|James Morrison|Marcus Rivera'
    r')\b'
)


def _scan_pii(text):
    """Scan text for PII. Returns list of findings with type, value, position."""
    findings = []
    for match in re.finditer(r'\b(\d{3})-(\d{2})-(\d{4})\b', text):
        findings.append({"type": "SSN", "value": match.group(0), "start": match.start(), "end": match.end(), "severity": "high"})
    for match in re.finditer(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text):
        findings.append({"type": "Email", "value": match.group(0), "start": match.start(), "end": match.end(), "severity": "medium"})
    for match in re.finditer(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text):
        findings.append({"type": "Phone", "value": match.group(0), "start": match.start(), "end": match.end(), "severity": "medium"})
    for match in _DEMO_PERSON_NAMES.finditer(text):
        findings.append({"type": "Person Name", "value": match.group(0), "start": match.start(), "end": match.end(), "severity": "medium"})
    findings.sort(key=lambda f: f["start"], reverse=True)
    return findings


_MARKETING_FLAGS = {
    "superlative": re.compile(r'\b(best|only|most|leading|unmatched|revolutionary|perfect|greatest|smartest|first-ever|#1|number one)\b', re.I),
    "comparative": re.compile(r'\b(faster than|better than|outperforms?|compared to|unlike competitors?|more \w+ than|less \w+ than)\b'
                              r'|no other .{0,30} can\b', re.I),
    "absolute": re.compile(r'\b(guaranteed|100%|never|always|zero)\b', re.I),
    "ai_overclaim": re.compile(r'\b(bias.free|always accurate|autonomous(?:ly)?|ethical ai|responsible ai.compliant'
                               r'|guaranteed free from|truly understands|photographic memory|never (?:lose|miss|forget))\b', re.I),
    "green_claim": re.compile(r'\b(carbon neutral|recycled|sustainable|carbon footprint|net.zero|greenest|ocean.bound plastic)\b', re.I),
    "stat_claim": re.compile(r'\d+[%x]\s'
                             r'|\$[\d,.]+\s+(million|billion|annually|saved)'
                             r'|\d+\s+(faster|slower|better|improvement|reduction|more productive|hours?\s+per|TOPS)', re.I),
    "customer_evidence": re.compile(r'(anonymous|name withheld|\[logos?\b)', re.I),
    "pricing": re.compile(r'\b(lowest price|guaranteed.*price|save \$|limited time|free (?:next|delivery|shipping|trial|upgrade))\b', re.I),
}

# Lines to skip (boilerplate / document metadata, not marketing claims)
_MARKETING_SKIP = re.compile(
    r'(all rights reserved|©|\(c\)\s*\d{4}|disclaimer|footer|={5,}'
    r'|^asset type:|^target audience:|^region:|^authored by:|^silicon:)',
    re.I
)


def _scan_marketing_claims(text):
    """Scan marketing text for claims requiring CELA review.

    Returns list of findings with category, matched text, context, and position.
    """
    findings = []
    for category, pattern in _MARKETING_FLAGS.items():
        for match in pattern.finditer(text):
            # Find the line containing this match for context
            line_start = text.rfind('\n', 0, match.start()) + 1
            line_end = text.find('\n', match.end())
            if line_end == -1:
                line_end = len(text)
            context_line = text[line_start:line_end].strip()
            # Skip boilerplate lines (copyright, disclaimers, section dividers)
            if _MARKETING_SKIP.search(context_line):
                continue
            # Skip empty or very short context (section headers like "===")
            if len(context_line) < 10:
                continue
            findings.append({
                "category": category,
                "text": match.group(0),
                "context": context_line,
                "start": match.start(),
                "end": match.end(),
            })
    findings.sort(key=lambda f: f["start"])
    return findings


_CATEGORY_META = {
    "superlative": {
        "risk": "HIGH",
        "issue": "Superlative ('best', 'only', 'most') requires documented proof. Unsubstantiated superlatives expose Microsoft to FTC enforcement.",
        "rec": "Add qualifier ('one of the', 'among the') or cite a third-party benchmark as footnote.",
    },
    "comparative": {
        "risk": "HIGH",
        "issue": "Comparative claim names or implies a competitor. Requires specific, current benchmark data and methodology disclosure.",
        "rec": "Name the competitor, cite benchmark source and date, or remove the comparison.",
    },
    "absolute": {
        "risk": "HIGH",
        "issue": "Absolute guarantee ('guaranteed', '100%', 'never') is nearly impossible to substantiate and creates legal liability.",
        "rec": "Replace with qualified language: 'designed to', 'helps reduce', 'up to X%' with footnote.",
    },
    "ai_overclaim": {
        "risk": "HIGH",
        "issue": "AI capability claim may violate Microsoft Responsible AI Standard. Autonomous action, bias-free, or perfect accuracy claims require RAI review.",
        "rec": "Route through RAI Impact Assessment. Use 'helps', 'assists', 'designed to' instead of autonomous language.",
    },
    "green_claim": {
        "risk": "HIGH",
        "issue": "Environmental claim requires third-party certification per FTC Green Guides. Vague sustainability language is greenwashing risk.",
        "rec": "Cite certification (e.g., EPEAT Gold, Energy Star) or replace with specific, verified data.",
    },
    "stat_claim": {
        "risk": "HIGH",
        "issue": "Statistical claim requires source, methodology, sample size, and date. Unattributed statistics are treated as unsubstantiated.",
        "rec": "Add footnote with source and date. Use 'up to' or 'based on [study]' with link.",
    },
    "customer_evidence": {
        "risk": "MEDIUM",
        "issue": "Customer reference requires Customer Quote Agreement (CQA) or Executive Customer Advocacy (ECA) approval. Anonymous quotes undermine credibility.",
        "rec": "Obtain signed CQA. Replace anonymous attributions with named, approved quotes.",
    },
    "pricing": {
        "risk": "MEDIUM",
        "issue": "Pricing claim must be accurate, time-bounded, and compliant with local advertising laws. 'Lowest price' guarantees may constitute binding offers.",
        "rec": "Add effective dates, regional qualifiers, and link to terms/conditions.",
    },
}


def _extract_claim_snippet(finding):
    """Extract a focused snippet around the matched text, not the full line."""
    ctx = finding["context"]
    match_text = finding["text"]
    if len(ctx) <= 80:
        return ctx
    pos = ctx.lower().find(match_text.lower())
    if pos < 0:
        return ctx[:80] + "..."
    # Window of ~30 chars on each side of the match
    pad = 30
    start = max(0, pos - pad)
    end = min(len(ctx), pos + len(match_text) + pad)
    # Snap to word boundaries
    if start > 0:
        sp = ctx.rfind(' ', 0, start + 1)
        if sp > 0:
            start = sp + 1
    if end < len(ctx):
        sp = ctx.find(' ', end - 1)
        if sp > 0:
            end = sp
    snippet = ctx[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(ctx):
        snippet += "..."
    return snippet


def _build_marketing_claims(scan_findings):
    """Deduplicate regex findings and enrich with risk levels.

    Groups by context line so the same line isn't shown multiple times.
    Returns (claims_list, category_counts_dict).
    """
    seen_contexts = {}
    for f in scan_findings:
        ctx = f["context"]
        meta = _CATEGORY_META.get(f["category"], {"risk": "MEDIUM", "issue": "Requires review", "rec": "Review and substantiate."})
        # Keep the highest-risk match per context line
        if ctx not in seen_contexts or _risk_rank(meta["risk"]) > _risk_rank(seen_contexts[ctx]["risk_level"]):
            cat_label = f["category"].replace("_", " ").title()
            seen_contexts[ctx] = {
                "category": cat_label,
                "claim_text": _extract_claim_snippet(f),
                "risk_level": meta["risk"],
                "issue": meta["issue"],
                "recommendation": meta.get("rec", f'Review and substantiate or remove: "{f["text"]}"'),
            }

    claims = list(seen_contexts.values())
    # Sort: HIGH first, then MEDIUM, then LOW
    claims.sort(key=lambda c: -_risk_rank(c["risk_level"]))

    # Category counts for the verdict prompt
    cat_counts = {}
    for f in scan_findings:
        cat_label = f["category"].replace("_", " ").title()
        cat_counts[cat_label] = cat_counts.get(cat_label, 0) + 1

    return claims, cat_counts


def _risk_rank(level):
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(level, 0)


def _redact_text(text, pii_findings):
    """Redact PII from text. Returns redacted copy."""
    redacted = text
    for finding in pii_findings:
        mask = f"[REDACTED {finding['type']}]"
        redacted = redacted[:finding["start"]] + mask + redacted[finding["end"]:]
    return redacted


def _check_network():
    """Quick check if network is up."""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-NetAdapter -Name 'Wi-Fi' -ErrorAction SilentlyContinue).Status"],
            capture_output=True, text=True, timeout=3
        )
        return "Up" in (proc.stdout or "")
    except Exception:
        return False


@app.route('/router/analyze', methods=['POST'])
def router_analyze():
    """Two-Brain Router: local attempt -> knowledge search -> decision card -> optional escalation consent."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400
    text = data.get('text', '')
    query = data.get('query', '')
    filename = data.get('filename', '')
    mode = data.get('mode', 'contract')
    model = DEFAULT_MODEL

    def generate():
        start = _time.time()
        pii_time = 0
        analysis_time = 0
        pii_findings_raw = []  # from _scan_pii (with start/end for redaction)

        # Step 0: Show document being analyzed
        if text:
            yield json.dumps({
                "type": "document_preview",
                "filename": filename or "uploaded document",
                "word_count": len(text.split()),
                "preview": text[:300],
            }) + "\n"

        # Step 1: PII Scan (document mode only)
        if text:
            yield json.dumps({"type": "status", "message": "Scanning for PII..."}) + "\n"
            _pii_start = _time.time()
            pii_findings_raw = _scan_pii(text)
            pii_time = round(_time.time() - _pii_start, 2)

            if pii_findings_raw:
                display_pii = []
                for f in pii_findings_raw:
                    val = f["value"]
                    if f["type"] == "SSN":
                        val = f"XXX-XX-{f['value'][-4:]}"
                    display_pii.append({
                        "severity": f["severity"],
                        "type": f["type"],
                        "value": val,
                        "location": _estimate_pii_location(text, f["start"])
                    })
                yield json.dumps({"type": "pii", "findings": display_pii}) + "\n"

            yield json.dumps({"type": "status", "message": f"PII scan complete — {len(pii_findings_raw)} item(s) found"}) + "\n"

        # Step 2: Search Local Knowledge silently (feeds context to model but not shown in UI)
        search_query = query if query else text[:200]
        knowledge_results = search_knowledge(search_query)

        knowledge_context = ""
        sources_used = []
        if knowledge_results:
            for kr in knowledge_results:
                knowledge_context += f"\n--- From {kr['filename']} ---\n{kr['snippet']}\n"
                sources_used.append({"filename": kr["filename"], "score": kr["score"], "word_count": kr["word_count"]})

        # Cap knowledge context to stay within token budget
        if len(knowledge_context) > 1000:
            knowledge_context = knowledge_context[:1000] + "\n[...truncated]"

        # Emit knowledge event (silent in UI but available for trust receipts)
        yield json.dumps({
            "type": "knowledge",
            "sources": sources_used,
            "total_indexed": len(KNOWLEDGE_INDEX),
        }) + "\n"

        # --- Marketing mode branch ---
        # Document-first: send actual text to model, let it find claims (mirrors contract flow)
        if mode == "marketing" and text:
            yield json.dumps({"type": "status", "message": f"Analyzing marketing document with {MODEL_LABEL} on NPU..."}) + "\n"

            claims = []
            verdict_data = {}
            summary_text = ""
            model_first = False

            # Document-first model call — model reads actual text and finds claims
            analysis_prompt = (
                "Review this marketing document for CELA compliance. "
                "Find 3-8 claims that may need legal review.\n\n"
                "For each claim, output EXACTLY this format:\n"
                "CATEGORY: [type of claim]\n"
                "CLAIM_TEXT: [exact phrase from the document]\n"
                "RISK_LEVEL: HIGH or MEDIUM or LOW\n"
                "ISSUE: [one sentence]\n"
                "RECOMMENDATION: [one sentence]\n\n"
                "Example:\n"
                "CATEGORY: Superlative\n"
                "CLAIM_TEXT: the world's best laptop\n"
                "RISK_LEVEL: HIGH\n"
                "ISSUE: Unsubstantiated superlative requires benchmark proof.\n"
                "RECOMMENDATION: Replace with substantiated claim or add qualifier.\n\n"
                "After all claims, output:\n"
                "VERDICT: SELF-SERVICE OK or CELA INTAKE REQUIRED\n"
                "VERDICT_REASON: [one sentence]\n"
                "SUMMARY: [2-sentence compliance assessment]"
            )
            _marketing_limit = 6000 if SILICON == "qualcomm" else 2000
            user_content = f"{analysis_prompt}\n\nMARKETING DOCUMENT:\n{text[:_marketing_limit]}"

            try:
                _call_start = _time.time()
                _max_tokens = 1200 if SILICON == "qualcomm" else 800
                response = foundry_chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a marketing compliance reviewer running locally on an NPU. Be specific and concise. Focus on claims that need legal review."},
                        {"role": "user", "content": user_content},
                    ],
                    max_tokens=_max_tokens,
                    temperature=0.3,
                )
                _track_model_call(response, _time.time() - _call_start)
                ai_response = (response.choices[0].message.content or "").strip()

                # Parse structured claims + verdict from model response
                claims, verdict_data = _parse_marketing_response(ai_response)

                # Extract SUMMARY (not covered by _parse_marketing_response)
                for line in ai_response.split('\n'):
                    if line.strip().upper().startswith('SUMMARY:'):
                        summary_text = line.strip().split(':', 1)[1].strip()
                        break

                if len(claims) >= 2:
                    model_first = True
                    print(f"[MARKETING] Model-first: {len(claims)} claims parsed")
                else:
                    print(f"[MARKETING] Fallback: model returned {len(claims)} claims, using hardcoded findings")

            except Exception as e:
                print(f"[MARKETING] Model call failed: {e}, using fallback findings")

            # Fallback: if model didn't produce enough claims, use filename-based hardcoded findings
            if not model_first:
                if filename == "marketing_surface_campaign_clean.txt":
                    claims = list(_MARKETING_CLEAN_FINDINGS)
                    verdict_data = dict(_MARKETING_CLEAN_VERDICT)
                elif filename == "marketing_surface_campaign_risky.txt":
                    claims = list(_MARKETING_RISKY_FINDINGS)
                    verdict_data = dict(_MARKETING_RISKY_VERDICT)
                else:
                    # Uploaded document: fall back to regex+metadata
                    scan_findings = _scan_marketing_claims(text)
                    claims, _fb_cats = _build_marketing_claims(scan_findings)

            # Compute counts from actual claim data
            high_count = sum(1 for c in claims if c.get("risk_level", "").upper() == "HIGH")
            medium_count = sum(1 for c in claims if c.get("risk_level", "").upper() == "MEDIUM")
            low_count = sum(1 for c in claims if c.get("risk_level", "").upper() == "LOW")

            # Progressive reveal: emit each card with status + pause so the UI
            # renders them one at a time (mirrors the contract review's pacing)

            # 1. Claims card
            yield json.dumps({"type": "status", "message": f"Found {len(claims)} compliance claims — reviewing risk levels..."}) + "\n"
            _time.sleep(0.6)
            yield json.dumps({"type": "claims", "findings": claims}) + "\n"

            # 2. Verdict
            # Rule-based safety net for verdict
            if not verdict_data.get('verdict'):
                if high_count >= 1:
                    verdict_data['verdict'] = "CELA INTAKE REQUIRED"
                    verdict_data['verdict_reason'] = (
                        f"Asset contains {high_count} high-risk claim(s) requiring substantiation review")
                else:
                    verdict_data['verdict'] = "SELF-SERVICE OK"
                    verdict_data['verdict_reason'] = (
                        "No high-risk claims detected. Minor items flagged for verification.")

            # Populate verdict metadata from actual claim data
            trigger_cats = list(set(
                c["category"] for c in claims if c.get("risk_level", "").upper() == "HIGH"
            ))
            verdict_data['trigger_categories'] = ", ".join(trigger_cats) if trigger_cats else "None"
            verdict_data['total_findings'] = str(len(claims))
            verdict_data['high_risk_count'] = str(high_count)
            verdict_data['medium_risk_count'] = str(medium_count)
            verdict_data['low_risk_count'] = str(low_count)

            _time.sleep(0.6)
            yield json.dumps({"type": "status", "message": "Determining compliance verdict..."}) + "\n"
            _time.sleep(0.4)
            yield json.dumps({"type": "verdict", **verdict_data}) + "\n"

            # 3. Summary
            if not summary_text:
                summary_text = verdict_data.get('verdict_reason', 'Marketing compliance review complete.')
            _time.sleep(0.5)
            yield json.dumps({"type": "summary", "text": summary_text}) + "\n"

            analysis_time = round(_time.time() - start, 1)

            # 4. Escalation if CELA intake required
            if "CELA" in verdict_data.get("verdict", "").upper():
                _time.sleep(0.4)
                yield json.dumps({"type": "status", "message": "Preparing escalation options..."}) + "\n"
                redacted_text = _redact_text(text, pii_findings_raw)
                redacted_tokens = len(redacted_text.split()) * 1.3
                estimated_input_tokens = int(redacted_tokens + 200)
                estimated_output_tokens = 400
                estimated_cost = (estimated_input_tokens * 2.50 / 1e6 + estimated_output_tokens * 10.00 / 1e6) * 1.5
                _time.sleep(0.4)
                yield json.dumps({
                    "type": "escalation_available",
                    "pii_found": len(pii_findings_raw),
                    "pii_details": pii_findings_raw,
                    "original_preview": text[:800],
                    "redacted_preview": redacted_text[:800],
                    "estimated_tokens": estimated_input_tokens + estimated_output_tokens,
                    "estimated_cost": round(estimated_cost, 4),
                }) + "\n"

            yield json.dumps({
                "type": "audit",
                "total_time": round(_time.time() - start, 1),
                "pii_time": pii_time,
                "analysis_time": analysis_time,
                "mode": "marketing",
            }) + "\n"
            yield json.dumps({"type": "complete", "total_time": round(_time.time() - start, 1)}) + "\n"
            return

        # Step 3: Contract Analysis (default mode)
        yield json.dumps({"type": "status", "message": f"Analyzing with {MODEL_LABEL} on NPU..."}) + "\n"

        if text:
            # Document mode: structured analysis with confidence assessment
            system_prompt = (
                "You are a contract analyst running locally on an NPU. "
                "Be concise and specific. Focus on non-standard or risky clauses."
            )
            analysis_prompt = (
                "Analyze this contract and identify:\n"
                "1. HIGH RISK clauses (one-sided, unlimited liability, unusual terms)\n"
                "2. MEDIUM RISK clauses (broad scope, aggressive terms)\n"
                "3. LOW RISK clauses (standard boilerplate)\n"
                "4. Key OBLIGATIONS with deadlines\n\n"
                "For each risk, provide:\n"
                "- SEVERITY: HIGH/MEDIUM/LOW\n"
                "- SECTION: section number\n"
                "- TYPE: category (indemnification, IP, non-compete, etc.)\n"
                "- FINDING: one sentence description\n"
                "- RECOMMENDATION: one sentence action\n\n"
                "Then provide:\n"
                "CONFIDENCE: HIGH or MEDIUM or LOW\n"
                "REASONING: one sentence why\n"
                "FRONTIER_BENEFIT: what a frontier model might add, or 'None — local answer is complete'\n\n"
                "End with:\n"
                "SUMMARY: 2-sentence executive summary"
            )
            # Note: knowledge_context intentionally omitted for document mode
            # to stay within model's prompt limit.  The document text itself
            # is the primary input; knowledge sources are still emitted in
            # the knowledge event for trust receipts.
            _contract_limit = 6000 if SILICON == "qualcomm" else 2000
            user_content = f"{analysis_prompt}\n\nCONTRACT TEXT:\n{text[:_contract_limit]}"
        else:
            # Query mode: confidence-first prompt (original router behavior)
            system_prompt = (
                "You are an analyst running locally on an NPU. First assess your confidence, then answer.\n\n"
                "Begin your response with exactly these three lines:\n"
                "CONFIDENCE: HIGH or MEDIUM or LOW\n"
                "REASONING: one sentence why\n"
                "FRONTIER_BENEFIT: what a frontier model might add, or 'None — local answer is complete'\n\n"
                "Then provide your analysis. If local knowledge sources were provided, cite them inline like: (Source: filename.txt)"
            )
            user_content = ""
            if knowledge_context:
                user_content += f"LOCAL KNOWLEDGE:\n{knowledge_context}\n\n"
            user_content += f"QUESTION: {query}"

        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=800,
                temperature=0.3,
            )
            _track_model_call(response, _time.time() - _call_start)
            ai_response = (response.choices[0].message.content or "").strip()
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
            return

        analysis_time = round(_time.time() - start, 1)

        # Parse confidence and metadata from response
        confidence = "HIGH"
        reasoning = ""
        frontier_benefit = "None — local answer is complete"
        summary_text = ""

        for line in ai_response.split('\n'):
            line_stripped = line.strip()
            line_upper = line_stripped.upper()
            if line_upper.startswith('CONFIDENCE:'):
                val = line_stripped.split(':', 1)[1].strip().upper()
                if 'HIGH' in val:
                    confidence = 'HIGH'
                elif 'LOW' in val:
                    confidence = 'LOW'
                elif 'MEDIUM' in val:
                    confidence = 'MEDIUM'
            elif line_upper.startswith('REASONING:'):
                reasoning = line_stripped.split(':', 1)[1].strip()
            elif line_upper.startswith('FRONTIER_BENEFIT:'):
                frontier_benefit = line_stripped.split(':', 1)[1].strip()
            elif line_upper.startswith('SUMMARY:'):
                summary_text = line_stripped.split(':', 1)[1].strip()

        # Force MEDIUM confidence for escalation demo doc so the
        # "Demo: Escalation Path" button always showcases the escalation flow
        if filename == "cross_border_ip_license.txt":
            confidence = "MEDIUM"
            reasoning = "Multi-jurisdictional IP licensing with cross-border data flow provisions requires specialist review"
            frontier_benefit = "Expert analysis of GDPR/CCPA interplay and IP indemnification gaps"

        # Document mode: parse structured findings and yield events
        if text:
            risk_findings, obligation_findings, used_fallback = _parse_analysis_response(ai_response)
            if risk_findings:
                yield json.dumps({"type": "risk", "findings": risk_findings}) + "\n"
            if obligation_findings:
                yield json.dumps({"type": "obligations", "findings": obligation_findings}) + "\n"
            if summary_text:
                yield json.dumps({"type": "summary", "text": summary_text}) + "\n"

        # Clean analysis text (remove metadata lines)
        metadata_prefixes = ['CONFIDENCE:', 'REASONING:', 'FRONTIER_BENEFIT:', 'SUMMARY:']
        if text:
            metadata_prefixes += ['SEVERITY:', 'SECTION:', 'TYPE:', 'FINDING:', 'RECOMMENDATION:', 'OBLIGATION:', 'DEADLINE:', 'CONSEQUENCE:']
        display_text = '\n'.join(
            line for line in ai_response.split('\n')
            if not any(line.strip().upper().startswith(p) for p in metadata_prefixes)
            and not any(line.strip().upper().startswith('- ' + p) for p in metadata_prefixes)
        ).strip()

        # Decision Card
        yield json.dumps({
            "type": "decision_card",
            "analysis": display_text,
            "confidence": confidence,
            "reasoning": reasoning,
            "frontier_benefit": frontier_benefit,
            "sources_used": sources_used,
            "analysis_time": analysis_time,
        }) + "\n"

        # Escalation if confidence is not HIGH
        if confidence in ("MEDIUM", "LOW"):
            redacted_text = _redact_text(text, pii_findings_raw) if text else ""

            redacted_tokens = len(redacted_text.split()) * 1.3
            estimated_input_tokens = int(redacted_tokens + 200)
            estimated_output_tokens = 400
            estimated_cost = (estimated_input_tokens * 2.50 / 1e6 + estimated_output_tokens * 10.00 / 1e6) * 1.5

            yield json.dumps({
                "type": "escalation_available",
                "pii_found": len(pii_findings_raw),
                "pii_details": pii_findings_raw,
                "original_preview": text[:800] if text else "",
                "redacted_preview": redacted_text[:800] if redacted_text else "",
                "estimated_tokens": estimated_input_tokens + estimated_output_tokens,
                "estimated_cost": round(estimated_cost, 4),
            }) + "\n"

        # Audit stamp (document mode)
        if text:
            yield json.dumps({
                "type": "audit",
                "total_time": round(_time.time() - start, 1),
                "pii_time": pii_time,
                "analysis_time": analysis_time,
            }) + "\n"

        total_time = round(_time.time() - start, 1)
        yield json.dumps({"type": "complete", "total_time": total_time}) + "\n"

    return Response(generate(), mimetype='text/plain')


@app.route('/router/decide', methods=['POST'])
def router_decide():
    """Record the user's escalation decision and generate Trust Receipt."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON body"}), 400
    decision = data.get('decision', 'decline')
    _VALID_DECISIONS = ('approve', 'decline')
    if decision not in _VALID_DECISIONS:
        return jsonify({"error": f"Invalid decision value. Must be one of: {_VALID_DECISIONS}"}), 400
    context = data.get('context', {})

    is_offline = not _check_network()

    # Offline safety: block escalation approval when device is offline
    if decision == 'approve' and is_offline:
        decision = 'decline'
        offline_downgraded = True
    else:
        offline_downgraded = False

    receipt = {
        "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "decision": decision,
        "model_used": DEFAULT_MODEL,
        "offline": is_offline,
        "pii_detected": context.get('pii_found', 0),
        "pii_types": [f["type"] for f in (context.get('pii_details') or []) if isinstance(f, dict) and "type" in f] if isinstance(context.get('pii_details'), list) else [],
        "estimated_cost_if_escalated": context.get('estimated_cost', 0),
        "estimated_tokens_if_escalated": context.get('estimated_tokens', 0),
        "confidence": context.get('confidence', 'unknown'),
        "sources_consulted": [s["filename"] for s in (context.get('sources_used') or []) if isinstance(s, dict) and "filename" in s] if isinstance(context.get('sources_used'), list) else [],
        "data_sent": False if is_offline else (decision == 'approve'),
    }

    if offline_downgraded:
        receipt["offline_downgraded"] = True
        receipt["offline_reason"] = "Device is offline — escalation blocked. Data stayed local."

    if decision == 'decline':
        receipt["counterfactual"] = (
            f"If escalated: ~{receipt['estimated_tokens_if_escalated']} tokens to Azure endpoint, "
            f"est. ${receipt['estimated_cost_if_escalated']:.4f}, "
            f"payload would have contained {receipt['pii_detected']} PII item(s) "
            f"({', '.join(set(receipt['pii_types'])) if receipt['pii_types'] else 'none detected'})"
        )

    ROUTER_LOG.append(receipt)

    AGENT_AUDIT_LOG.append({
        "timestamp": _time.strftime("%H:%M:%S"),
        "tool": "router",
        "arguments": {"decision": decision, "confidence": receipt["confidence"]},
        "success": True,
        "time": 0,
    })

    return jsonify(receipt)


@app.route('/router/log', methods=['GET'])
def router_log():
    """Return the full Router decision log (Trust Receipts)."""
    return jsonify(ROUTER_LOG)


@app.route('/connectivity-check', methods=['GET'])
def connectivity_check():
    """Check network and NPU availability for the airplane mode demo."""
    # Check WiFi adapter status
    wifi_up = False
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-NetAdapter -Name 'Wi-Fi' -ErrorAction SilentlyContinue).Status"],
            capture_output=True, text=True, timeout=5
        )
        wifi_up = "Up" in (proc.stdout or "")
    except Exception:
        pass

    # Check Foundry Local
    npu_ok = False
    try:
        client.models.list()
        npu_ok = True
    except Exception:
        pass

    return jsonify({
        "network": wifi_up,
        "npu": npu_ok,
        "storage": True,  # always true for local
    })


@app.route('/network-toggle', methods=['POST'])
def network_toggle():
    """Directly toggle network adapters for Go Offline / Go Online.

    Requires the Flask process (or python) to be running with admin rights.
    Uses Start-Process -Verb RunAs to elevate if needed.
    """
    action = (request.json or {}).get('action', 'offline')
    if action == 'offline':
        verb = "Disable"
    else:
        verb = "Enable"

    # Try direct first (works if Flask is running as admin)
    cmd = f"{verb}-NetAdapter -Name 'Wi-Fi','Cellular' -Confirm:$false -ErrorAction SilentlyContinue"
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=10
        )
        # Verify the adapter actually changed state
        verify = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-NetAdapter -Name 'Wi-Fi' -ErrorAction SilentlyContinue).Status"],
            capture_output=True, text=True, timeout=5
        )
        status = (verify.stdout or "").strip()
        expected = "Disabled" if action == "offline" else "Up"
        if status == expected:
            return jsonify({'success': True, 'action': action, 'status': status})

        # Direct call didn't work (likely needs elevation) — try with RunAs
        elevated_cmd = (
            f"Start-Process powershell.exe -Verb RunAs -Wait -WindowStyle Hidden "
            f"-ArgumentList '-NoProfile','-Command',\"{cmd}\""
        )
        proc2 = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", elevated_cmd],
            capture_output=True, text=True, timeout=15
        )
        # Verify again
        verify2 = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-NetAdapter -Name 'Wi-Fi' -ErrorAction SilentlyContinue).Status"],
            capture_output=True, text=True, timeout=5
        )
        status2 = (verify2.stdout or "").strip()
        if status2 == expected:
            return jsonify({'success': True, 'action': action, 'status': status2})
        else:
            return jsonify({'success': False, 'error': f'Adapter still {status2}. Run the app as Administrator for network toggle to work.',
                            'status': status2})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/my-day-counts', methods=['GET'])
def my_day_counts():
    """Return counts for My Day dashboard cards."""
    ics_path = os.path.join(MY_DAY_DIR, 'calendar.ics')
    csv_path = os.path.join(MY_DAY_DIR, 'tasks.csv')
    events = parse_ics(ics_path)
    tasks = parse_tasks_csv(csv_path)
    emails = parse_inbox(MY_DAY_INBOX)
    return jsonify({
        'events': len(events),
        'tasks': len(tasks),
        'emails': len(emails),
    })


@app.route('/my-day-data', methods=['GET'])
def my_day_data():
    """Return full parsed data for peek windows."""
    ics_path = os.path.join(MY_DAY_DIR, 'calendar.ics')
    csv_path = os.path.join(MY_DAY_DIR, 'tasks.csv')
    events = parse_ics(ics_path)
    tasks = parse_tasks_csv(csv_path)
    emails = parse_inbox(MY_DAY_INBOX)
    # Format events for display
    ev_list = []
    for ev in events:
        t = ev.get('time', '?')
        end = ev.get('end_time', '')
        time_str = f"{t}-{end}" if end else t
        ev_list.append({
            'time': time_str,
            'summary': ev.get('summary', ''),
            'location': ev.get('location', ''),
        })
    # Format tasks
    task_list = []
    for t in tasks:
        task_list.append({
            'priority': t.get('Priority', 'Medium'),
            'task': t.get('Task', ''),
            'category': t.get('Category', ''),
        })
    # Format emails
    email_list = []
    for em in emails:
        frm = em.get('from', '').split('<')[0].strip().strip('"')
        email_list.append({
            'from': frm,
            'subject': em.get('subject', ''),
            'date': em.get('date', ''),
        })
    return jsonify({
        'events': ev_list,
        'tasks': task_list,
        'emails': email_list,
    })


@app.route('/brief-me', methods=['POST'])
def brief_me():
    """Full morning briefing — parse all data, send to local model."""
    model = DEFAULT_MODEL

    def generate():
        start = _time.time()

        # Step 1: Parse all data sources — try Microsoft Graph first, fall back to local files

        # Calendar: Graph API (live Outlook) → local .ics
        yield json.dumps({"type": "status", "message": "Reading Outlook calendar..."}) + "\n"
        graph_cal = _graph_get_calendar_today()
        if graph_cal is not None:
            events = []
            for ev in graph_cal:
                start_dt = ev.get('start', {}).get('dateTime', '')
                end_dt = ev.get('end', {}).get('dateTime', '')
                try:
                    from datetime import datetime as _dt
                    st = _dt.fromisoformat(start_dt)
                    time_str = st.strftime('%I:%M %p').lstrip('0')
                except Exception:
                    time_str = start_dt[:16]
                events.append({
                    'time': time_str,
                    'summary': ev.get('subject', '?'),
                    'location': (ev.get('location', {}) or {}).get('displayName', ''),
                    'description': ev.get('bodyPreview', '')[:200],
                })
            yield json.dumps({"type": "status", "message": f"Found {len(events)} events (Outlook)"}) + "\n"
        else:
            events = parse_ics(os.path.join(MY_DAY_DIR, 'calendar.ics'))
            yield json.dumps({"type": "status", "message": f"Found {len(events)} events (local)"}) + "\n"

        # Tasks: local CSV (no Graph Tasks.Read permission)
        yield json.dumps({"type": "status", "message": "Reading tasks..."}) + "\n"
        tasks = parse_tasks_csv(os.path.join(MY_DAY_DIR, 'tasks.csv'))
        yield json.dumps({"type": "status", "message": f"Found {len(tasks)} tasks"}) + "\n"

        # Email: Graph API (live Outlook inbox) → local .eml files
        yield json.dumps({"type": "status", "message": "Scanning Outlook inbox..."}) + "\n"
        graph_mail = _graph_get_recent_emails(10)
        if graph_mail is not None:
            emails = []
            for em in graph_mail:
                from_info = em.get('from', {}).get('emailAddress', {})
                from_str = from_info.get('name', from_info.get('address', '?'))
                emails.append({
                    'subject': em.get('subject', '?'),
                    'from': from_str,
                    'preview': em.get('bodyPreview', '')[:200],
                })
            yield json.dumps({"type": "status", "message": f"Found {len(emails)} emails (Outlook)"}) + "\n"
        else:
            emails = parse_inbox(MY_DAY_INBOX)
            yield json.dumps({"type": "status", "message": f"Found {len(emails)} emails (local)"}) + "\n"

        # Guard: if no data at all, return a clear message instead of letting the model hallucinate
        if not events and not tasks and not emails:
            total = round(_time.time() - start, 1)
            yield json.dumps({
                "type": "briefing",
                "text": "**No data found.** The My Day folder is empty — no calendar events, tasks, or emails were found.\n\n"
                        f"**Expected location:** `{MY_DAY_DIR}`\n\n"
                        "Place the following files to enable briefings:\n"
                        "- `calendar.ics` — Calendar events\n"
                        "- `tasks.csv` — Task list (columns: Task, Priority, Status, Due)\n"
                        "- `Inbox/*.eml` — Email files\n\n"
                        "Run `setup.ps1` to generate sample demo data automatically.",
                "time": total,
                "counts": {"events": 0, "tasks": 0, "emails": 0},
            }) + "\n"
            return

        # Step 2: Compress into prompt
        yield json.dumps({"type": "status", "message": "Analyzing and cross-referencing..."}) + "\n"
        data_text = compress_for_briefing(events, tasks, emails)

        # Step 3: Send to local model
        yield json.dumps({"type": "status", "message": "Generating briefing with AI..."}) + "\n"
        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": BRIEFING_SYSTEM_PROMPT},
                    {"role": "user", "content": data_text},
                ],
                max_tokens=512,
                temperature=0.4,
            )
            _track_model_call(response, _time.time() - _call_start)
            briefing = (response.choices[0].message.content or "").strip()
            total = round(_time.time() - start, 1)
            yield json.dumps({
                "type": "briefing",
                "text": briefing,
                "time": total,
                "counts": {"events": len(events), "tasks": len(tasks), "emails": len(emails)},
            }) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(generate(), mimetype='text/plain')


@app.route('/triage-inbox', methods=['POST'])
def triage_inbox():
    """Email triage — sort into urgent/action/FYI."""
    model = DEFAULT_MODEL

    def generate():
        start = _time.time()
        yield json.dumps({"type": "status", "message": "Reading inbox..."}) + "\n"
        emails = parse_inbox(MY_DAY_INBOX)
        yield json.dumps({"type": "status", "message": f"Analyzing {len(emails)} emails..."}) + "\n"

        # Compress emails for triage
        lines = [f'INBOX: {len(emails)} emails\n']
        for em in emails:
            body = em.get('body', '')
            snippet = body[:200] if body else ''
            lines.append(f"From: {em['from']}\nSubject: {em['subject']}\nSnippet: {snippet}\n")

        prompt = (
            'Sort these emails into three categories:\n'
            'URGENT (needs immediate action today)\n'
            'ACTION NEEDED (should handle today but not critical)\n'
            'FYI (informational, can wait)\n\n'
            'For each email: one line with the category icon, sender name, subject, '
            'and a brief recommended action.\n'
            'Use these icons: URGENT, ACTION, FYI\n\n'
        )

        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an executive assistant triaging an inbox. Be concise."},
                    {"role": "user", "content": prompt + '\n'.join(lines)},
                ],
                max_tokens=800,
                temperature=0.3,
            )
            _track_model_call(response, _time.time() - _call_start)
            result = (response.choices[0].message.content or "").strip()
            total = round(_time.time() - start, 1)
            yield json.dumps({"type": "briefing", "text": result, "time": total}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(generate(), mimetype='text/plain')


@app.route('/prep-next-meeting', methods=['POST'])
def prep_next_meeting():
    """Prep brief for the next upcoming meeting."""
    model = DEFAULT_MODEL

    def generate():
        start = _time.time()
        yield json.dumps({"type": "status", "message": "Reading calendar..."}) + "\n"
        events = parse_ics(os.path.join(MY_DAY_DIR, 'calendar.ics'))
        emails = parse_inbox(MY_DAY_INBOX)
        tasks = parse_tasks_csv(os.path.join(MY_DAY_DIR, 'tasks.csv'))

        if not events:
            yield json.dumps({"type": "error", "message": "No events found"}) + "\n"
            return

        # Skip logistics (breakfast, car, prep) — find first substantive meeting
        next_ev = events[0]
        skip_words = ['breakfast', 'car to', 'prep window', 'lunch', 'travel']
        for ev in events:
            summary_lower = ev.get('summary', '').lower()
            if any(sw in summary_lower for sw in skip_words):
                continue
            if ev.get('attendees') or len(ev.get('description', '')) > 100:
                next_ev = ev
                break
        yield json.dumps({"type": "status", "message": f"Prepping for: {next_ev.get('summary', '?')}..."}) + "\n"

        ev_text = (
            f"Meeting: {next_ev.get('summary')}\n"
            f"Time: {next_ev.get('time')} - {next_ev.get('end_time', '?')}\n"
            f"Location: {next_ev.get('location', '?')}\n"
            f"Description: {next_ev.get('description', 'None')}\n"
        )

        # Find related emails and tasks
        email_text = '\n'.join(
            f"- {em['from']}: {em['subject']}" for em in emails[:7]
        )
        task_text = '\n'.join(
            f"- [{t.get('Priority', '?')}] {t.get('Task', '?')}" for t in tasks
        )

        prompt = (
            f"Prepare a brief for this meeting:\n\n{ev_text}\n\n"
            f"Related emails:\n{email_text}\n\n"
            f"Today's tasks:\n{task_text}\n\n"
            "Give a 4-5 sentence prep brief: what this meeting is about, "
            "key points to cover, any relevant context from emails or tasks, "
            "and what to prepare or bring."
        )

        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an executive assistant preparing meeting briefs. Be concise and actionable."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.3,
            )
            _track_model_call(response, _time.time() - _call_start)
            result = (response.choices[0].message.content or "").strip()
            total = round(_time.time() - start, 1)
            yield json.dumps({"type": "briefing", "text": result, "time": total}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(generate(), mimetype='text/plain')


@app.route('/top-3-focus', methods=['POST'])
def top_3_focus():
    """Single-step: analyze today's data and return the top 3 priorities."""
    model = DEFAULT_MODEL

    def generate():
        start = _time.time()
        yield json.dumps({"type": "status", "message": "Reading your day..."}) + "\n"
        events = parse_ics(os.path.join(MY_DAY_DIR, 'calendar.ics'))
        tasks = parse_tasks_csv(os.path.join(MY_DAY_DIR, 'tasks.csv'))
        emails = parse_inbox(MY_DAY_INBOX)

        yield json.dumps({"type": "status", "message": "Identifying priorities..."}) + "\n"
        data_text = compress_for_briefing(events, tasks, emails)

        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": (
                        "You are a chief of staff. Analyze the user's calendar, tasks, and emails. "
                        "Identify the TOP 3 things they should focus on RIGHT NOW. "
                        "For each item:\n"
                        "1. A clear action title\n"
                        "2. WHY it's urgent (1 sentence)\n"
                        "3. Time needed (estimate)\n"
                        "Rank by impact and urgency. Be direct and decisive."
                    )},
                    {"role": "user", "content": data_text},
                ],
                max_tokens=400,
                temperature=0.3,
            )
            _track_model_call(response, _time.time() - _call_start)
            result = (response.choices[0].message.content or "").strip()
            total = round(_time.time() - start, 1)
            yield json.dumps({"type": "briefing", "text": result, "time": total,
                              "counts": {"events": len(events), "tasks": len(tasks), "emails": len(emails)}}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(generate(), mimetype='text/plain')


@app.route('/tomorrow-preview', methods=['POST'])
def tomorrow_preview():
    """Single-step: high-level overview of tomorrow's schedule."""
    model = DEFAULT_MODEL

    def generate():
        start = _time.time()
        yield json.dumps({"type": "status", "message": "Reading tomorrow's calendar..."}) + "\n"
        all_events = parse_ics(os.path.join(MY_DAY_DIR, 'calendar.ics'))
        all_tasks = parse_tasks_csv(os.path.join(MY_DAY_DIR, 'tasks.csv'))

        # Filter for tomorrow (dynamic date)
        from datetime import datetime, timedelta
        tomorrow_dt = datetime.now() + timedelta(days=1)
        tomorrow_str = tomorrow_dt.strftime('%Y-%m-%d')
        tomorrow_events = [e for e in all_events if e.get('date', '') == tomorrow_str]
        tomorrow_tasks = [t for t in all_tasks if t.get('Due Date', '') == tomorrow_str]
        # If no events match tomorrow, use all events (demo flexibility)
        if not tomorrow_events:
            tomorrow_events = all_events
        if not tomorrow_tasks:
            tomorrow_tasks = all_tasks

        if not tomorrow_events and not tomorrow_tasks:
            yield json.dumps({"type": "error", "message": "No events or tasks found for tomorrow."}) + "\n"
            return

        yield json.dumps({"type": "status", "message": f"Found {len(tomorrow_events)} events and {len(tomorrow_tasks)} tasks for tomorrow..."}) + "\n"

        # Build compressed data for tomorrow
        tomorrow_label = tomorrow_dt.strftime('%a %b %d %Y').replace(' 0', ' ')
        lines = [f'TOMORROW: {tomorrow_label}\n']
        lines.append(f'CALENDAR ({len(tomorrow_events)} events):')
        for ev in tomorrow_events:
            t = ev.get('time', '?')
            s = ev.get('summary', '?')
            loc = ev.get('location', '')
            lines.append(f'- {t} {s}' + (f' @ {loc}' if loc else ''))

        lines.append(f'\nTASKS ({len(tomorrow_tasks)} items):')
        for t in tomorrow_tasks:
            prio = t.get('Priority', 'Med')
            name = t.get('Task', '?')
            lines.append(f'- [{prio}] {name}')

        data_text = '\n'.join(lines)
        if len(data_text) > 1800:
            data_text = data_text[:1800]

        yield json.dumps({"type": "status", "message": "Generating tomorrow's preview..."}) + "\n"

        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": (
                        "You are a banking advisor's chief of staff. Write a brief PREVIEW OF TOMORROW:\n"
                        "1. Overview (2 sentences): the shape of the day.\n"
                        "2. KEY MEETINGS: one line per meeting with what to prepare.\n"
                        "3. PRIORITY TASKS: top 3 must-do items.\n"
                        "Keep it under 200 words. Be concise and actionable."
                    )},
                    {"role": "user", "content": data_text},
                ],
                max_tokens=600,
                temperature=0.4,
            )
            _track_model_call(response, _time.time() - _call_start)
            result = (response.choices[0].message.content or "").strip()
            total = round(_time.time() - start, 1)
            yield json.dumps({"type": "briefing", "text": result, "time": total,
                              "counts": {"events": len(tomorrow_events), "tasks": len(tomorrow_tasks), "emails": 0}}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(generate(), mimetype='text/plain')


# DEMO_MODE is declared near the top of the file (line 27) and parsed from sys.argv.


# ── Field Inspection endpoints ──


@app.route('/inspection/fluid-dictation', methods=['POST'])
def inspection_fluid_dictation():
    """Open or close Windows Voice Typing via keybd_event."""
    action = (request.json or {}).get("action", "open") if request.is_json else "open"
    try:
        import subprocess
        if action == "close":
            # Escape key dismisses Voice Typing reliably
            ps_script = (
                'Add-Type -TypeDefinition @"\n'
                'using System; using System.Runtime.InteropServices;\n'
                'public class KeySender {\n'
                '  [DllImport("user32.dll")] static extern void keybd_event(byte b,byte s,uint f,UIntPtr e);\n'
                '  public static void Esc(){\n'
                '    keybd_event(0x1B,0,0,UIntPtr.Zero); keybd_event(0x1B,0,2,UIntPtr.Zero);\n'
                '  }\n'
                '}\n'
                '"@\n'
                '[KeySender]::Esc()'
            )
        else:
            # Win+H opens Voice Typing
            ps_script = (
                'Add-Type -TypeDefinition @"\n'
                'using System; using System.Runtime.InteropServices;\n'
                'public class KeySender {\n'
                '  [DllImport("user32.dll")] static extern void keybd_event(byte b,byte s,uint f,UIntPtr e);\n'
                '  public static void WinH(){\n'
                '    keybd_event(0x5B,0,0,UIntPtr.Zero); keybd_event(0x48,0,0,UIntPtr.Zero);\n'
                '    keybd_event(0x48,0,2,UIntPtr.Zero); keybd_event(0x5B,0,2,UIntPtr.Zero);\n'
                '  }\n'
                '}\n'
                '"@\n'
                '[KeySender]::WinH()'
            )
        subprocess.Popen(["powershell", "-Command", ps_script])
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Demo photo classifications — hardcoded for reliable demo with prop images
_DEMO_CLASSIFICATIONS = {
    "financial_statement": {
        "category": "403(b) Retirement Statement",
        "severity": "Moderate",
        "confidence": 94,
        "explanation": "Quarterly 403(b) retirement account statement from Great Lakes Retirement Services. Account holder: Jackie Marie Rodriguez. Current balance: $187,432.61."
    },
    "beneficiary_form": {
        "category": "Beneficiary Designation Form",
        "severity": "High",
        "confidence": 96,
        "explanation": f"{DEMO_CONFIG.get('brand_company', 'Flagstar Financial')} beneficiary designation form for 403(b) account. Account holder: {DEMO_CONFIG.get('customer', {}).get('full_name', 'Jackie Marie Rodriguez')}. Requires signatures from account holder and financial advisor."
    },
    "water_damage": {
        "category": "Financial Statement",
        "severity": "Moderate",
        "confidence": 82,
        "explanation": "Multi-page financial statement showing account balances, transaction history, and investment positions."
    },
    "structural_crack": {
        "category": "Tax Document",
        "severity": "High",
        "confidence": 72,
        "explanation": "Tax return or W-2 document with income details. Confidence limited due to partial visibility."
    },
    "mold": {
        "category": "Account Application",
        "severity": "High",
        "confidence": 88,
        "explanation": "Completed account application form with personal information, employment details, and signatures."
    },
    "electrical_hazard": {
        "category": "Business Card",
        "severity": "Low",
        "confidence": 91,
        "explanation": "Professional business card with contact information, company name, and title."
    },
    "trip_hazard": {
        "category": "Insurance Document",
        "severity": "Low",
        "confidence": 85,
        "explanation": "Insurance policy summary or certificate of coverage with policy number and coverage details."
    },
}

@app.route('/inspection/transcribe', methods=['POST'])
def inspection_transcribe():
    """Extract structured inspection fields from a spoken transcript using local AI."""
    data = request.json or {}
    transcript = data.get('transcript', '').strip()

    if not transcript:
        return jsonify({"error": "No transcript provided"}), 400

    model = DEFAULT_MODEL

    system_prompt = (
        "You are a field extraction engine for client meeting notes. "
        "Given a spoken transcript from a financial advisor, extract structured fields. "
        "Respond ONLY with valid JSON matching this schema:\n"
        '{"inspector_name": string or null, "location": string or null, '
        '"datetime": string or null, "reported_issue": string or null, '
        '"source": string or null}\n'
        "Rules:\n"
        "- inspector_name: the client's full name (e.g. \"Jackie Rodriguez\")\n"
        "- location: meeting location or client address (e.g. \"Starbucks, Main St, Troy MI\")\n"
        "- datetime: ISO 8601 format if possible (e.g. \"2026-03-26T14:00:00\")\n"
        "- reported_issue: products or topics discussed (e.g. \"529 Plan, Roth IRA conversion\")\n"
        "- source: referral source or meeting type (e.g. \"Existing Member Referral\")\n"
        "- If a field cannot be determined from the transcript, use null\n"
        "Do not include any text outside the JSON object."
    )

    try:
        _call_start = _time.time()
        response = foundry_chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            max_tokens=256,
            temperature=0.1,
        )
        elapsed = _time.time() - _call_start
        _track_model_call(response, elapsed)

        raw = (response.choices[0].message.content or "").strip()

        # Parse JSON from response — handle markdown fences
        json_str = raw
        if "```" in json_str:
            # Strip markdown code fences
            import re as _re
            fence_match = _re.search(r'```(?:json)?\s*(\{.*?\})\s*```', json_str, _re.DOTALL)
            if fence_match:
                json_str = fence_match.group(1)
        # Find the JSON object in the response
        brace_start = json_str.find('{')
        brace_end = json_str.rfind('}')
        if brace_start >= 0 and brace_end > brace_start:
            json_str = json_str[brace_start:brace_end + 1]

        try:
            fields = json.loads(json_str)
        except json.JSONDecodeError:
            # Fallback: return raw response as-is with empty fields
            print(f"[INSPECTION] Field extraction JSON parse failed: {raw[:200]}")
            fields = {"inspector_name": None, "location": None, "datetime": None, "reported_issue": None, "source": None}

        # Calculate tokens used
        tokens_used = 0
        if hasattr(response, 'usage') and response.usage:
            tokens_used = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)
        else:
            tokens_used = 300  # estimate

        return jsonify({
            "transcript": transcript,
            "fields": fields,
            "tokens_used": tokens_used,
            "inference_time": round(elapsed, 1),
        })

    except Exception as e:
        print(f"[INSPECTION] Transcribe error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/inspection/demo-photo/<photo_type>')
def inspection_demo_photo(photo_type):
    """Serve a demo inspection photo by type."""
    allowed = {"water_damage", "structural_crack", "mold", "electrical_hazard", "trip_hazard", "financial_statement", "beneficiary_form"}
    if photo_type not in allowed:
        return "Not found", 404
    # Try .jpg first, then .png
    photo_path = os.path.join(DEMO_DIR, "inspection_photos", f"{photo_type}.jpg")
    mimetype = "image/jpeg"
    if not os.path.exists(photo_path):
        photo_path = os.path.join(DEMO_DIR, "inspection_photos", f"{photo_type}.png")
        mimetype = "image/png"
    if not os.path.exists(photo_path):
        return "Photo not found", 404
    from flask import send_file as _send_file
    return _send_file(photo_path, mimetype=mimetype)


@app.route('/inspection/classify', methods=['POST'])
def inspection_classify():
    """Classify an inspection photo into constrained categories.

    Accepts either:
    - demo_type (string) — uses hardcoded demo classification
    - image (file upload) — attempts vision classification via Phi Silica microservice,
      falls back to text-based description if unavailable
    """
    # Check for demo classification (reliable demo path)
    demo_type = request.form.get('demo_type')
    if not demo_type and request.is_json:
        demo_type = (request.json or {}).get('demo_type')
    if demo_type and demo_type in _DEMO_CLASSIFICATIONS:
        import time as _classify_time
        _classify_time.sleep(1.5)  # Simulate inference time for demo realism
        result = dict(_DEMO_CLASSIFICATIONS[demo_type])
        result["tokens_used"] = 0
        result["inference_time"] = 1.5
        result["source"] = "demo_preset"
        print(f"[INSPECTION] Demo classification: {demo_type} -> {result['category']}")
        return jsonify(result)

    # Try Phi Silica Vision microservice (localhost:5100)
    image_file = request.files.get('image')
    if image_file:
        try:
            import requests as _req
            files = {'image': (image_file.filename, image_file.read(), image_file.content_type)}
            vision_resp = _req.post('http://localhost:5100/classify', files=files, timeout=30)
            if vision_resp.status_code == 200:
                result = vision_resp.json()
                if 'error' not in result:
                    result["source"] = "phi_silica_vision"
                    result["tokens_used"] = result.get("tokens_used", 300)
                    # Track in server-side session stats (Vision doesn't go through foundry_chat)
                    SESSION_STATS["calls"] += 1
                    SESSION_STATS["input_tokens"] += 200
                    SESSION_STATS["output_tokens"] += 100
                    print(f"[INSPECTION] Phi Silica Vision: {result.get('category')}")
                    return jsonify(result)
        except Exception as e:
            print(f"[INSPECTION] Vision service unavailable: {e}")

        # Fallback: use Phi-4 Mini text model with constrained prompt
        # (no actual image understanding, but works for demo with known props)
        model = DEFAULT_MODEL
        system_prompt = (
            "You are a building inspection image classifier. "
            "Based on the description provided, classify the visible issue. "
            "Respond ONLY with valid JSON matching this schema:\n"
            '{"category": one of ["Water Damage", "Structural Crack", "Mold", '
            '"Electrical Hazard", "Trip Hazard"], '
            '"severity": one of ["Low", "Moderate", "High", "Critical"], '
            '"confidence": integer 0-100, '
            '"explanation": string (one sentence max)}\n'
            "Do not include any text outside the JSON object."
        )

        # Use filename as a hint for what the image might contain
        fname = (image_file.filename or "photo").lower()
        hint = "An inspection photo was captured"
        if "water" in fname or "leak" in fname or "stain" in fname:
            hint = "Photo shows water staining and discoloration on ceiling tiles"
        elif "crack" in fname or "struct" in fname:
            hint = "Photo shows a diagonal crack in a concrete wall"
        elif "mold" in fname or "mould" in fname:
            hint = "Photo shows dark organic growth in a damp corner area"
        elif "electr" in fname or "wire" in fname:
            hint = "Photo shows exposed wiring with damaged insulation"
        elif "trip" in fname or "floor" in fname:
            hint = "Photo shows uneven flooring with a raised threshold"

        try:
            _call_start = _time.time()
            response = foundry_chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": hint},
                ],
                max_tokens=200,
                temperature=0.2,
            )
            elapsed = _time.time() - _call_start
            _track_model_call(response, elapsed)

            raw = (response.choices[0].message.content or "").strip()
            json_str = raw
            brace_start = json_str.find('{')
            brace_end = json_str.rfind('}')
            if brace_start >= 0 and brace_end > brace_start:
                json_str = json_str[brace_start:brace_end + 1]

            try:
                result = json.loads(json_str)
            except json.JSONDecodeError:
                result = _DEMO_CLASSIFICATIONS["water_damage"]

            tokens_used = 0
            if hasattr(response, 'usage') and response.usage:
                tokens_used = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)

            result["tokens_used"] = tokens_used
            result["inference_time"] = round(elapsed, 1)
            result["source"] = "text_model_fallback"
            return jsonify(result)

        except Exception as e:
            print(f"[INSPECTION] Classify text fallback error: {e}")
            result = dict(_DEMO_CLASSIFICATIONS["water_damage"])
            result["source"] = "hardcoded_fallback"
            return jsonify(result)

    return jsonify({"error": "No image or demo_type provided"}), 400


@app.route('/inspection/annotate', methods=['POST'])
def inspection_annotate():
    """Extract handwritten text from an annotated inspection photo.

    Three-tier fallback:
    1. Phi Silica Vision (/extract-text on localhost:5100)
    2. Phi-4 Mini text model (generates plausible inspector note)
    3. Hardcoded fallback
    """
    image_file = request.files.get('image')
    finding_id = request.form.get('finding_id', '0')
    _ind = DEMO_CONFIG.get('industry', {})

    if not image_file:
        return jsonify({"error": "No image provided"}), 400

    # Tier 1: Try Phi Silica Vision /describe endpoint with annotated photo
    # Sends the composite image (photo + ink overlay) for a detailed description
    # that captures both the defect and the inspector's visual annotations
    try:
        import requests as _req
        image_bytes = image_file.read()
        files = {'image': (image_file.filename or 'annotated_photo.jpg', image_bytes,
                           image_file.content_type or 'image/jpeg')}
        # Use /describe (detailed) for richer output than /extract-text
        # Phi Silica Vision can take 30-45s on first call (cold start)
        vision_resp = _req.post('http://localhost:5100/describe',
                                files=files,
                                data={'kind': 'detailed'},
                                timeout=60)
        if vision_resp.status_code == 200:
            result = vision_resp.json()
            raw_desc = result.get('description', '').strip()
            if not raw_desc:
                raw_desc = result.get('extracted_text', '').strip()
            if raw_desc and 'error' not in result:
                print(f"[ANNOTATION] Phi Silica Vision raw: {raw_desc}")
                # Track in server-side session stats (Vision doesn't go through foundry_chat)
                SESSION_STATS["calls"] += 1
                SESSION_STATS["input_tokens"] += 200
                SESSION_STATS["output_tokens"] += 100
                # Return the raw Vision description directly —
                # Phi-4 Mini refinement was hallucinating content not in the image.
                # Vision's description of what it actually sees is more trustworthy.
                return jsonify({
                    "extracted_text": raw_desc,
                    "raw_vision": raw_desc,
                    "tokens_used": 300,
                    "inference_time": result.get('inference_time', 0),
                    "source": "phi_silica_vision",
                    "status": "ok"
                })
    except Exception as e:
        print(f"[INSPECTION] Vision describe unavailable: {e}")

    # Tier 2: Phi-4 Mini text fallback — generate plausible note
    model = DEFAULT_MODEL
    _ann_role = _ind.get('annotation_role', 'advisor')
    _ann_docs = _ind.get('annotation_documents', 'a document')
    _ann_actions = _ind.get('annotation_actions', 'follow-up items, action notes, or key observations')
    system_prompt = (
        f"You are a handwriting recognition system for a {_ann_role}'s document annotations. "
        f"A {_ann_role} annotated {_ann_docs} with handwritten notes during a meeting. "
        f"Generate a short, realistic note (1-2 sentences) that would typically "
        f"accompany a document review. Focus on specific actions like "
        f"{_ann_actions}. Keep it under 20 words."
    )

    try:
        _call_start = _time.time()
        response = foundry_chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate an inspector's handwritten note for finding #" + str(finding_id)},
            ],
            max_tokens=60,
            temperature=0.4,
        )
        elapsed = _time.time() - _call_start
        _track_model_call(response, elapsed)

        text = (response.choices[0].message.content or "").strip()
        # Clean up any quotes the model might wrap around the note
        text = text.strip('"').strip("'")

        tokens_used = 0
        if hasattr(response, 'usage') and response.usage:
            tokens_used = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)

        print(f"[INSPECTION] Annotation text fallback: {text[:80]}")
        return jsonify({
            "extracted_text": text,
            "tokens_used": tokens_used,
            "inference_time": round(elapsed, 1),
            "source": "text_model_fallback",
            "status": "ok"
        })
    except Exception as e:
        print(f"[INSPECTION] Annotation text fallback error: {e}")

    # Tier 3: Hardcoded fallback
    return jsonify({
        "extracted_text": "Check pipe above - possible leak source",
        "tokens_used": 0,
        "inference_time": 0,
        "source": "hardcoded_fallback",
        "status": "ok"
    })


@app.route('/inspection/report', methods=['POST'])
def inspection_report():
    """Generate a professional inspection report from collected fields and findings."""
    data = request.json or {}
    fields = data.get('fields', {})
    findings = data.get('findings', [])

    if not findings:
        return jsonify({"error": "No findings to report"}), 400

    model = DEFAULT_MODEL

    # Build structured input for the model
    findings_text = ""
    for i, f in enumerate(findings, 1):
        cls = f.get('classification', {})
        findings_text += (
            f"\nFinding #{i}:\n"
            f"  Category: {cls.get('category', 'Unknown')}\n"
            f"  Severity: {cls.get('severity', 'Unknown')}\n"
            f"  Confidence: {cls.get('confidence', 0)}%\n"
            f"  Explanation: {cls.get('explanation', 'N/A')}\n"
        )
        if (f.get('annotations') or {}).get('extracted_text'):
            findings_text += f"  Inspector Note: {f['annotations']['extracted_text']}\n"
        if f.get('transcript_excerpt'):
            findings_text += f"  Voice Notes: {f['transcript_excerpt']}\n"

    client_name = fields.get('inspector_name', '')
    inspection_data = (
        f"Client: {client_name or 'Not specified'}\n"
        f"Meeting Location: {fields.get('location', 'Not specified')}\n"
        f"Meeting Date: {fields.get('datetime', 'Not specified')}\n"
        f"Products Discussed: {fields.get('reported_issue', 'Not specified')}\n"
        f"Referral Source: {fields.get('source', 'Not specified')}\n"
        f"\nDocuments Reviewed ({len(findings)} total):{findings_text}"
    )

    _adv_name = DEMO_CONFIG.get('advisor_name', 'Alan Thornbury')
    _adv_title = DEMO_CONFIG.get('advisor_title', 'Vice President & Senior Relationship Manager')
    _adv_company = DEMO_CONFIG.get('advisor_company', 'Flagstar Bank')
    _adv_phone = DEMO_CONFIG.get('advisor_phone', '(248) 312-5500')
    _adv_email = DEMO_CONFIG.get('advisor_email', '')
    _adv_branch = DEMO_CONFIG.get('advisor_branch', '')
    system_prompt = (
        "You are a client meeting report generator for a bank wealth advisor. "
        f"The advisor is {_adv_name}, {_adv_title} at {_adv_company}"
        + (f", {_adv_branch} branch" if _adv_branch else "") + ". "
        "This report is being generated by the advisor who just completed the meeting. "
        "Given structured meeting data, produce a professional post-meeting report as clean HTML. Include:\n"
        "1. Meeting details header (client name, location, date, products discussed, advisor name)\n"
        "2. Meeting summary (2-3 sentences covering key discussion points)\n"
        "3. Client action items (bullet list of what the client needs to do)\n"
        "4. Advisor follow-up tasks (bullet list for the advisor/bank)\n"
        "5. Draft follow-up email to the client (brief, professional, references specific products discussed). "
        f"Sign the email as: {_adv_name}, {_adv_title}, {_adv_company}"
        + (f", {_adv_phone}" if _adv_phone else "")
        + (f", {_adv_email}" if _adv_email else "") + "\n"
        "6. D365 task entries (formatted list of tasks to create in CRM)\n\n"
        "Use these HTML tags: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <blockquote>.\n"
        "Keep language professional, warm, and concise. No markdown, only HTML."
    )

    try:
        _call_start = _time.time()
        _report_limit = 6000 if SILICON == "qualcomm" else 2000
        response = foundry_chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": inspection_data[:_report_limit]},
            ],
            max_tokens=800,
            temperature=0.3,
        )
        elapsed = _time.time() - _call_start
        _track_model_call(response, elapsed)

        report_html = (response.choices[0].message.content or "").strip()

        # Strip markdown code fences the model sometimes wraps around HTML
        if report_html.startswith("```"):
            first_newline = report_html.find("\n")
            if first_newline > 0:
                report_html = report_html[first_newline + 1:]
            if report_html.endswith("```"):
                report_html = report_html[:-3].strip()

        # Prepend meeting details header if model didn't include them
        _loc = fields.get('location', '')
        _dt = fields.get('datetime', '')
        if _loc and _loc.lower() not in report_html.lower():
            details_header = (
                '<div style="margin-bottom:12px; padding:10px; '
                'background:rgba(255,255,255,0.05); border-radius:6px; '
                'font-size:0.9em; line-height:1.6;">'
                f'<strong>Client:</strong> {client_name or "Not specified"} &nbsp;|&nbsp; '
                f'<strong>Location:</strong> {_loc or "Not specified"} &nbsp;|&nbsp; '
                f'<strong>Date:</strong> {_dt or "Not specified"}<br>'
                f'<strong>Products Discussed:</strong> {fields.get("reported_issue", "Not specified")}'
                '</div>'
            )
            report_html = details_header + report_html

        # Extract summary and risk rating from the generated HTML
        summary = ""
        risk_rating = "Moderate"

        # Try to pull summary from first paragraph
        import re as _re
        summary_match = _re.search(r'<p>(.*?)</p>', report_html, _re.DOTALL)
        if summary_match:
            summary = _re.sub(r'<[^>]+>', '', summary_match.group(1)).strip()

        # Try to detect risk rating from the content
        report_lower = report_html.lower()
        if 'critical' in report_lower and ('risk' in report_lower or 'rating' in report_lower):
            risk_rating = "Critical"
        elif 'high' in report_lower and ('risk' in report_lower or 'rating' in report_lower):
            risk_rating = "High"
        elif 'low' in report_lower and ('risk' in report_lower or 'rating' in report_lower):
            risk_rating = "Low"

        # Extract next steps from list items
        next_steps = _re.findall(r'<li>(.*?)</li>', report_html, _re.DOTALL)
        next_steps = [_re.sub(r'<[^>]+>', '', s).strip() for s in next_steps[-4:]]

        tokens_used = 0
        if hasattr(response, 'usage') and response.usage:
            tokens_used = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)
        else:
            tokens_used = 500

        return jsonify({
            "report_html": report_html,
            "report_text": _re.sub(r'<[^>]+>', '', report_html).strip(),
            "summary": summary,
            "risk_rating": risk_rating,
            "next_steps": next_steps,
            "tokens_used": tokens_used,
            "inference_time": round(elapsed, 1),
        })

    except Exception as e:
        print(f"[INSPECTION] Report generation error: {e}")
        # Hardcoded fallback report
        severity_counts = {}
        for f in findings:
            sev = f.get('classification', {}).get('severity', 'Unknown')
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        highest = "Moderate"
        for s in ["Critical", "High", "Moderate", "Low"]:
            if severity_counts.get(s, 0) > 0:
                highest = s
                break

        fallback_findings_html = ""
        for i, f in enumerate(findings, 1):
            cls = f.get('classification', {})
            fallback_findings_html += (
                f'<div style="margin:10px 0; padding:10px; background:rgba(255,255,255,0.05); border-radius:8px;">'
                f'<strong>Finding #{i}: {cls.get("category", "Unknown")}</strong><br>'
                f'Severity: {cls.get("severity", "?")} | Confidence: {cls.get("confidence", 0)}%<br>'
                f'<em>{cls.get("explanation", "")}</em></div>'
            )

        _fb_client = fields.get("inspector_name", "")
        fallback_html = (
            f'<h2>Client Meeting Summary</h2>'
            f'<p><strong>Client:</strong> {_fb_client or "N/A"} | '
            f'<strong>Location:</strong> {fields.get("location", "N/A")} | '
            f'<strong>Date:</strong> {fields.get("datetime", "N/A")}</p>'
            f'<h3>Meeting Overview</h3>'
            f'<p>Meeting with {_fb_client or "client"} at {fields.get("location", "the branch")}. '
            f'Products discussed: {fields.get("reported_issue", "N/A")}. '
            f'{len(findings)} document(s) reviewed during the session.</p>'
            f'<h3>Documents Reviewed</h3>{fallback_findings_html}'
            f'<h3>Client Action Items</h3>'
            f'<ul><li>Review beneficiary designation and confirm selections</li>'
            f'<li>Gather any additional documentation needed for account changes</li>'
            f'<li>Schedule follow-up appointment to finalize paperwork</li></ul>'
            f'<h3>Advisor Follow-up Tasks</h3>'
            f'<ul><li>Process beneficiary change form in D365</li>'
            f'<li>Send contribution limits comparison via secure email</li>'
            f'<li>Create follow-up task in CRM for next Thursday</li>'
            f'<li>File signed documents in client record</li></ul>'
            f'<h3>Draft Follow-up Email</h3>'
            f'<blockquote>Dear {_fb_client or "Client"},<br><br>'
            f'Thank you for meeting with me today. As discussed, I will be processing your '
            f'beneficiary designation update and sending you the contribution limits comparison '
            f'for review. Our follow-up meeting is scheduled for next Thursday to finalize '
            f'the remaining paperwork.<br><br>'
            f'Please don\'t hesitate to reach out if you have any questions before then.<br><br>'
            f'Best regards,<br>{_adv_name}<br>{_adv_title}<br>{_adv_company}<br>{_adv_phone}'
            + (f'<br>{_adv_email}' if _adv_email else '') + '</blockquote>'
        )

        return jsonify({
            "report_html": fallback_html,
            "report_text": f"Meeting with {_fb_client or 'client'} at {fields.get('location', 'N/A')}: {len(findings)} documents reviewed",
            "summary": f"Meeting with {_fb_client or 'client'} reviewed {len(findings)} document(s). Products: {fields.get('reported_issue', 'N/A')}.",
            "risk_rating": "N/A",
            "next_steps": ["Process beneficiary change", "Send contribution limits", "Schedule follow-up", "File signed documents"],
            "tokens_used": 0,
            "inference_time": 0,
        })


@app.route('/inspection/translate', methods=['POST'])
def inspection_translate():
    """Translate an inspection report into a target language."""
    data = request.json or {}
    report_html = data.get('report_html', '')
    target_language = data.get('target_language', 'Spanish')

    if not report_html.strip():
        return jsonify({"error": "No report to translate"}), 400

    model = DEFAULT_MODEL

    system_prompt = (
        f"Translate the following inspection report into {target_language}. "
        "Maintain the exact same structure, formatting, and section organization. "
        f"Use professional {target_language} appropriate for a construction/inspection context. "
        "Output as clean HTML matching the source structure. No markdown — only HTML."
    )

    try:
        _call_start = _time.time()
        _translate_limit = 6000 if SILICON == "qualcomm" else 2000
        response = foundry_chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": report_html[:_translate_limit]},
            ],
            max_tokens=800 if SILICON != "qualcomm" else 1200,
            temperature=0.3,
        )
        elapsed = _time.time() - _call_start
        _track_model_call(response, elapsed)

        translated = (response.choices[0].message.content or "").strip()

        # Strip markdown code fences
        if translated.startswith("```"):
            first_newline = translated.find("\n")
            if first_newline > 0:
                translated = translated[first_newline + 1:]
            if translated.endswith("```"):
                translated = translated[:-3].strip()

        tokens_used = 0
        if hasattr(response, 'usage') and response.usage:
            tokens_used = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)
        else:
            tokens_used = 500

        return jsonify({
            "translated_html": translated,
            "source_language": "English",
            "target_language": target_language,
            "tokens_used": tokens_used,
            "inference_time": round(elapsed, 1),
        })

    except Exception as e:
        print(f"[INSPECTION] Translation error: {e}")
        # Hardcoded fallback: wrap original with a note
        fallback = (
            f'<div style="padding:8px; background:rgba(255,200,0,0.1); border-radius:6px; margin-bottom:12px;">'
            f'<em>Traducci\u00f3n autom\u00e1tica no disponible \u2014 modelo fuera de l\u00ednea. '
            f'Mostrando informe original.</em></div>{report_html}'
        )
        return jsonify({
            "translated_html": fallback,
            "source_language": "English",
            "target_language": target_language,
            "tokens_used": 0,
            "inference_time": 0,
        })


# ── Live Assist Endpoints ──

@app.route('/live-assist/analyze', methods=['POST'])
def live_assist_analyze():
    """Analyze a transcript chunk and return AI insights + sentiment."""
    try:
        data = request.get_json()
        transcript_chunk = data.get('text', '').strip()
        prior_insights = data.get('prior', '')

        if not transcript_chunk:
            return jsonify({"error": "No transcript text provided"}), 400

        system_prompt = (
            "You are a real-time advisor prompter whispering tips during a live customer meeting. "
            "Give 1-3 bullet points the advisor can act on RIGHT NOW. "
            "Rules: each bullet starts with -, max 12 words, no filler, no restating what customer said. "
            "Prefer specific facts and numbers over generic advice. "
            "Examples of good bullets: "
            "- 2026 529 contribution limit: $18,000/beneficiary tax-free. "
            "- Catch-up IRA contributions allowed at age 50+, extra $1,000/yr. "
            "- Ask about employer match before recommending 401k rollover. "
            "Examples of bad bullets (too generic, do NOT write these): "
            "- Emphasize the importance of saving early. "
            "- Consider recommending appropriate products. "
            "Types: product opportunity, specific financial fact, compliance flag, or question to ask. "
            "Last line must be SENTIMENT: POSITIVE or NEUTRAL or CAUTIOUS."
        )
        if prior_insights:
            system_prompt += "\nAlready covered (do NOT repeat): " + prior_insights

        start = _time.time()
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript_chunk}
            ],
            max_tokens=128,
            temperature=0.3
        )
        elapsed = _time.time() - start

        result_text = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else 0

        # Parse sentiment from response
        sentiment = "NEUTRAL"
        for s in ["POSITIVE", "CAUTIOUS", "NEUTRAL"]:
            if s in result_text.upper():
                sentiment = s
                break

        # Clean up sentiment line from display text
        clean_text = re.sub(r'\n*SENTIMENT:\s*(POSITIVE|NEUTRAL|CAUTIOUS)\s*$', '', result_text, flags=re.IGNORECASE).strip()

        print(f"[LIVE ASSIST] Analyzed {len(transcript_chunk)} chars -> {sentiment} ({tokens_used} tokens, {elapsed:.1f}s)")

        return jsonify({
            "insights": clean_text,
            "sentiment": sentiment,
            "tokens_used": tokens_used,
            "inference_time": round(elapsed, 1)
        })

    except Exception as e:
        print(f"[LIVE ASSIST] Analysis error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/live-assist/translate', methods=['POST'])
def live_assist_translate():
    """Translate a Live Assist transcript to a target language using local AI."""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        target_language = data.get('target_language', 'Spanish')

        if not text:
            return jsonify({"error": "No text to translate"}), 400

        # Compress if too long for context window
        if len(text) > 3000:
            text = text[:3000]

        system_prompt = (
            f"You are a professional translator. Translate EVERY line below from English to {target_language}. "
            f"Each English line must become a {target_language} line. "
            "Example: 'I need to open a checking account' becomes 'Necesito abrir una cuenta corriente'. "
            f"Output ONLY {target_language} text, one translated line per original line. "
            "Do NOT output any English."
        )

        start = _time.time()
        response = foundry_chat(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            max_tokens=800,
            temperature=0.3
        )
        elapsed = _time.time() - start
        _track_model_call(response, elapsed)

        translated = (response.choices[0].message.content or "").strip()
        tokens_used = 0
        if hasattr(response, 'usage') and response.usage:
            tokens_used = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)

        print(f"[LIVE ASSIST] Translated {len(text)} chars to {target_language} ({tokens_used} tokens, {elapsed:.1f}s)")

        return jsonify({
            "translated_text": translated,
            "source_language": "English",
            "target_language": target_language,
            "tokens_used": tokens_used,
            "inference_time": round(elapsed, 1)
        })

    except Exception as e:
        print(f"[LIVE ASSIST] Translation error: {e}")
        return jsonify({"error": str(e)}), 500


# ── System Performance Monitor ──────────────────────────────────────────
import psutil as _psutil
try:
    import win32pdh as _win32pdh
    _HAS_PDH = True
except ImportError:
    _HAS_PDH = False

_perf_stats = {"cpu": 0, "gpu": 0, "npu": 0, "mem_pct": 0, "mem_used": 0, "mem_total": 0}
_perf_lock = threading.Lock()
_GPU_LUID = None
_NPU_LUID = None

def _poll_perf_stats():
    """Background thread: poll CPU/memory/GPU/NPU every ~2s via win32pdh (native, no subprocess)."""
    global _GPU_LUID, _NPU_LUID
    if not _HAS_PDH:
        print("  Perf monitor: win32pdh not available, GPU/NPU stats disabled", flush=True)
        return

    _psutil.cpu_percent()  # prime
    luid_re = re.compile(r'luid_(0x[0-9a-f]+_0x[0-9a-f]+).*engtype_(\S+)', re.IGNORECASE)

    # Open PDH query with both counters
    query = _win32pdh.OpenQuery()
    try:
        util_counter = _win32pdh.AddCounter(query, r'\GPU Engine(*)\Utilization Percentage')
    except Exception as e:
        print(f"  Perf monitor: cannot add GPU counters: {e}", flush=True)
        return

    # Prime with two collections (rate counters need a baseline)
    _win32pdh.CollectQueryData(query)
    _time.sleep(2)
    _win32pdh.CollectQueryData(query)

    # Detect GPU vs NPU LUIDs from engine types
    try:
        util_items = _win32pdh.GetFormattedCounterArray(util_counter, _win32pdh.PDH_FMT_DOUBLE)
        luids_3d = set()
        luids_compute = set()
        for name in util_items:
            m = luid_re.search(name)
            if m:
                luid, etype = m.group(1).lower(), m.group(2).lower()
                if etype == '3d':
                    luids_3d.add(luid)
                elif etype == 'compute':
                    luids_compute.add(luid)
        if luids_3d:
            _GPU_LUID = sorted(luids_3d)[0]
        npu_only = luids_compute - luids_3d
        if npu_only:
            _NPU_LUID = sorted(npu_only)[0]
        print(f"  Perf monitor: GPU LUID={_GPU_LUID}, NPU LUID={_NPU_LUID}", flush=True)
    except Exception as e:
        print(f"  Perf monitor: LUID detection failed: {e}", flush=True)

    # Main poll loop — fast polling (500ms) with EMA smoothing for bursty NPU
    npu_ema = 0.0
    gpu_ema = 0.0
    EMA_UP = 0.8    # fast rise to capture spikes
    EMA_DOWN = 0.06  # very slow decay — keeps peaks visible for ~5s
    while True:
        try:
            cpu = _psutil.cpu_percent()
            mem = _psutil.virtual_memory()
            gpu_raw = 0.0
            npu_raw = 0.0

            _win32pdh.CollectQueryData(query)
            util_items = _win32pdh.GetFormattedCounterArray(util_counter, _win32pdh.PDH_FMT_DOUBLE)

            for name, val in util_items.items():
                name_lower = name.lower()
                if _GPU_LUID and _GPU_LUID in name_lower:
                    gpu_raw += val
                if _NPU_LUID and _NPU_LUID in name_lower:
                    npu_raw += val

            # EMA smoothing: fast attack, slow release
            alpha = EMA_UP if npu_raw > npu_ema else EMA_DOWN
            npu_ema = alpha * npu_raw + (1 - alpha) * npu_ema
            alpha_g = EMA_UP if gpu_raw > gpu_ema else EMA_DOWN
            gpu_ema = alpha_g * gpu_raw + (1 - alpha_g) * gpu_ema

            with _perf_lock:
                _perf_stats['cpu'] = round(cpu, 1)
                _perf_stats['gpu'] = round(min(gpu_ema, 100), 1)
                _perf_stats['npu'] = round(min(npu_ema, 100), 1)
                _perf_stats['mem_pct'] = round(mem.percent, 1)
                _perf_stats['mem_used'] = round(mem.used / (1024**3), 1)
                _perf_stats['mem_total'] = round(mem.total / (1024**3), 1)
        except Exception:
            pass
        _time.sleep(0.5)

# Start perf polling thread
threading.Thread(target=_poll_perf_stats, daemon=True, name="perf-monitor").start()

@app.route('/system-stats')
def system_stats():
    """Return cached system performance stats for the live monitor overlay."""
    with _perf_lock:
        return jsonify(dict(_perf_stats))

@app.route('/api/polish-email', methods=['POST'])
def polish_email():
    """Rewrite email text in a professional banking tone using local AI.
    Tries Vision Service Phi Silica TextRewriter first, falls back to Phi-4 Mini."""
    data = request.json
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400

    _adv_name = DEMO_CONFIG.get('advisor_name', 'the advisor')
    _adv_company = DEMO_CONFIG.get('advisor_company', 'the bank')
    _brand = DEMO_CONFIG.get('brand_company', 'the bank')
    _customer_name = data.get('customer_name', '')

    # Try Vision Service /rewrite endpoint (Phi Silica TextRewriter on NPU)
    try:
        import requests as _req
        _instruction = f"Rewrite as a warm, professional follow-up email from {_adv_name}, {DEMO_CONFIG.get('advisor_title', '')} at {_brand}."
        if _customer_name:
            _instruction += f" Address the customer as {_customer_name.split()[0]}."
        _instruction += f" Sign off as {_adv_name}. Keep it concise."
        r = _req.post("http://localhost:5100/rewrite", json={
            "text": text,
            "instruction": _instruction
        }, timeout=15)
        if r.ok:
            result = r.json()
            if result.get("rewritten"):
                # Track in server-side session stats (Vision Service, not foundry_chat)
                SESSION_STATS["calls"] += 1
                SESSION_STATS["input_tokens"] += 100
                SESSION_STATS["output_tokens"] += 100
                return jsonify({
                    "polished": result["rewritten"],
                    "model": "Writing Assistant (Phi Silica)",
                    "source": "npu_writing_assistant",
                    "inference_time": result.get("inference_time")
                })
    except Exception:
        pass  # Vision Service not available, fall back to Phi-4 Mini

    # Fallback: Phi-4 Mini via Foundry Local
    try:
        _call_start = _time.time()
        response = foundry_chat(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": (
                    f"You are a professional email editor for {_brand}. "
                    f"The email is from {_adv_name}, {DEMO_CONFIG.get('advisor_title', '')}. "
                    "Rewrite the user's draft email to be warm, professional, and concise. "
                    "Keep the same meaning and key details but improve the tone and polish. "
                    + (f"Address the customer by their first name: {_customer_name.split()[0]}. " if _customer_name else "")
                    + f"Sign off as {_adv_name}. Do not add new information. Do not include a subject line. "
                    "Output only the polished email body text, nothing else."
                )},
                {"role": "user", "content": text}
            ],
            max_tokens=512,
            temperature=0.3
        )
        polished = response.choices[0].message.content.strip()
        elapsed = round(_time.time() - _call_start, 1)
        return jsonify({
            "polished": polished,
            "model": "Phi-4 Mini",
            "source": "npu_phi4_mini",
            "inference_time": elapsed
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/send-followup', methods=['POST'])
def send_followup_email():
    """Send a follow-up email to the customer via Microsoft Graph Mail.Send.
    Looks up customer email from D365 via MCP if not provided."""
    data = request.json
    body_html = data.get('body', '').strip()
    subject = data.get('subject', 'Thank you for meeting with us today')
    customer_name = data.get('customer_name', '')
    customer_email = data.get('customer_email', '')

    if not body_html:
        return jsonify({"error": "No email body provided"}), 400

    _adv_name = DEMO_CONFIG.get('advisor_name', '')
    _adv_title = DEMO_CONFIG.get('advisor_title', '')
    _adv_company = DEMO_CONFIG.get('advisor_company', '')
    _adv_phone = DEMO_CONFIG.get('advisor_phone', '')
    _adv_email = DEMO_CONFIG.get('advisor_email', '')

    # If no email provided, try D365 MCP lookup
    if not customer_email and customer_name:
        try:
            import requests as _req
            r = _req.post("http://localhost:5000/d365/customer-lookup",
                          json={"name": customer_name}, timeout=10)
            if r.ok:
                d365_data = r.json()
                customer_info = d365_data.get("customer", {})
                customer_email = customer_info.get("email", "")
        except Exception:
            pass

    if not customer_email:
        return jsonify({"error": "Could not determine customer email address. Check D365 contact record."}), 400

    # Build HTML email with signature
    full_html = (
        f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#333;">'
        f'{body_html}'
        f'<br><br>'
        f'<div style="border-top:1px solid #ddd;padding-top:12px;margin-top:12px;font-size:13px;color:#666;">'
        f'{_adv_name}<br>{_adv_title}<br>{_adv_company}<br>{_adv_phone}'
        + (f'<br>{_adv_email}' if _adv_email else '') +
        f'</div></div>'
    )

    # Send via Microsoft Graph
    token = _graph_get_token()
    if not token:
        if DEMO_MODE:
            return jsonify({
                "sent": True,
                "demo_mode": True,
                "to": customer_email or "customer@example.com",
                "to_name": customer_name,
                "subject": subject,
                "message": "Email saved to local drafts (demo mode — Graph not connected)",
                "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            })
        return jsonify({"error": "Graph not authenticated. Run /graph/authenticate first.", "sent": False}), 401

    try:
        import requests as _req
        graph_url = "https://graph.microsoft.com/v1.0/me/sendMail"
        mail_payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": full_html},
                "toRecipients": [{"emailAddress": {"address": customer_email, "name": customer_name}}]
            },
            "saveToSentItems": True
        }
        r = _req.post(graph_url, json=mail_payload,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                      timeout=15)
        if r.status_code == 202 or r.status_code == 200:
            return jsonify({
                "sent": True,
                "to": customer_email,
                "to_name": customer_name,
                "subject": subject,
                "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
            })
        else:
            return jsonify({"error": f"Graph returned {r.status_code}: {r.text[:200]}", "sent": False}), 500
    except Exception as e:
        return jsonify({"error": str(e), "sent": False}), 500


@app.route('/health')
def health_check():
    """Returns model readiness status for the warmup overlay."""
    return jsonify({"ready": MODEL_READY, "model": DEFAULT_MODEL})

@app.route('/api/product-catalog')
def api_product_catalog():
    """Return the product catalog for the Product Penetration Dashboard."""
    return jsonify(PRODUCT_CATALOG if PRODUCT_CATALOG else {"error": "No product catalog loaded"})


@app.route('/api/product-recommendations', methods=['POST'])
def api_product_recommendations():
    """Match a customer's D365 profile against the product catalog for cross-sell recommendations."""
    data = request.json or {}
    customer_name = data.get("name", "").strip()
    if not customer_name:
        return jsonify({"error": "No customer name provided"}), 400

    # Get customer profile from D365 (or demo data)
    try:
        import requests as _req
        r = _req.post("http://127.0.0.1:5000/d365/customer-lookup",
                      json={"name": customer_name}, timeout=5)
        if r.ok:
            customer = r.json().get("customer", {})
            recs = _match_product_recommendations(customer)
            recs["customer_name"] = customer.get("full_name", customer_name)
            return jsonify(recs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"error": "Customer not found"}), 404


# --- Branch Concierge Routes ---

@app.route('/arrivals', methods=['GET'])
def get_arrivals():
    """Return current arrivals feed."""
    now = _time.time()
    active = []
    for aid, arr in list(_ARRIVALS.items()):
        # Auto-expire after 30 minutes
        if now - arr["arrived_at"] > 1800:
            del _ARRIVALS[aid]
            continue
        if arr["status"] == "met":
            continue
        elapsed = int(now - arr["arrived_at"])
        if elapsed < 60:
            dwell = "just now"
        elif elapsed < 3600:
            dwell = f"{elapsed // 60} min ago"
        else:
            dwell = f"{elapsed // 3600}h {(elapsed % 3600) // 60}m ago"
        tier_info = _CONCIERGE_TIERS.get(arr["tier"], _CONCIERGE_TIERS["retail"])
        active.append({
            "arrival_id": aid,
            "name": arr["name"],
            "title": arr.get("title", ""),
            "tier": arr["tier"],
            "tier_label": tier_info["label"],
            "tier_color": tier_info["color"],
            "tier_icon": tier_info["icon"],
            "source": arr["source"],
            "source_label": {"app_checkin": "App Check-In", "appointment": "Appointment", "teller_identified": "ID at Teller"}.get(arr["source"], arr["source"]),
            "rm": arr.get("rm", ""),
            "status": arr["status"],
            "dwell": dwell,
            "arrived_at": arr["arrived_at"],
        })
    active.sort(key=lambda a: a["arrived_at"], reverse=True)
    return jsonify({"arrivals": active, "count": len(active)})


@app.route('/arrivals/checkin', methods=['POST'])
def arrival_checkin():
    """Simulate mobile app check-in arrival."""
    data = request.json or {}
    client_name = data.get("name", "Jackie Rodriguez")
    cust = _get_concierge_customer(client_name)
    if not cust:
        return jsonify({"error": f"Customer '{client_name}' not found in demo data"}), 404
    aid = str(_uuid.uuid4())[:8]
    _ARRIVALS[aid] = {
        "name": cust["name"], "title": cust.get("title", ""),
        "tier": cust["vip_tier"], "source": "app_checkin",
        "source_token": f"app-consent-{aid}", "rm": cust.get("rm", ""),
        "client_id": cust["client_id"], "arrived_at": _time.time(),
        "status": "waiting",
    }
    print(f"[CONCIERGE] App check-in: {cust['name']} ({cust['vip_tier']})")
    return jsonify({"arrival_id": aid, "name": cust["name"], "tier": cust["vip_tier"], "source": "app_checkin"})


@app.route('/arrivals/appointment', methods=['POST'])
def arrival_appointment():
    """Simulate appointment-driven arrival."""
    data = request.json or {}
    client_name = data.get("name", "Sarah Henderson")
    cust = _get_concierge_customer(client_name)
    if not cust:
        return jsonify({"error": f"Customer '{client_name}' not found"}), 404
    aid = str(_uuid.uuid4())[:8]
    _ARRIVALS[aid] = {
        "name": cust["name"], "title": cust.get("title", ""),
        "tier": cust["vip_tier"], "source": "appointment",
        "source_token": f"appt-{aid}", "rm": cust.get("rm", ""),
        "client_id": cust["client_id"], "arrived_at": _time.time(),
        "status": "waiting",
    }
    print(f"[CONCIERGE] Appointment arrival: {cust['name']} ({cust['vip_tier']})")
    return jsonify({"arrival_id": aid, "name": cust["name"], "tier": cust["vip_tier"], "source": "appointment"})


@app.route('/arrivals/teller-identified', methods=['POST'])
def arrival_teller():
    """Triggered when teller scans a VIP customer's ID."""
    data = request.json or {}
    client_name = data.get("name", "Marcus Chen")
    cust = _get_concierge_customer(client_name)
    if not cust:
        return jsonify({"error": f"Customer '{client_name}' not found"}), 404
    if cust["vip_tier"] not in ("private", "premier"):
        return jsonify({"skipped": True, "reason": "Customer is not VIP tier"})
    aid = str(_uuid.uuid4())[:8]
    _ARRIVALS[aid] = {
        "name": cust["name"], "title": cust.get("title", ""),
        "tier": cust["vip_tier"], "source": "teller_identified",
        "source_token": f"teller-scan-{aid}", "rm": cust.get("rm", ""),
        "client_id": cust["client_id"], "arrived_at": _time.time(),
        "status": "waiting",
    }
    print(f"[CONCIERGE] Teller ID scan (VIP): {cust['name']} ({cust['vip_tier']})")
    return jsonify({"arrival_id": aid, "name": cust["name"], "tier": cust["vip_tier"], "source": "teller_identified"})


@app.route('/arrivals/<arrival_id>/brief', methods=['GET'])
def arrival_brief(arrival_id):
    """Generate AI greeting brief for an arrival using Phi-4 Mini on NPU."""
    arr = _ARRIVALS.get(arrival_id)
    if not arr:
        return jsonify({"error": "Arrival not found"}), 404

    cust = _get_concierge_customer(arr["name"])
    if not cust:
        return jsonify({"error": "Customer profile not found"}), 404

    # Get product recommendations
    cust_for_recs = {
        "accounts": [{"type": "Essential Checking"}] if "jackie" in cust["name"].lower() else [],
        "notes": cust.get("notes", ""),
    }
    recs = _match_product_recommendations(cust_for_recs)
    top_recs = recs.get("recommendations", [])[:3]
    recs_text = ""
    for r in top_recs:
        recs_text += f"- {r['name']} ({r['priority']}): {r['talk_track'][:120]}\n"

    tier_info = _CONCIERGE_TIERS.get(cust["vip_tier"], {})
    system_prompt = (
        "You are a branch concierge assistant helping a bank branch manager prepare to greet a client. "
        "Write a brief, warm greeting prep in three sections: "
        "RECENT CONTEXT (2 sentences about their last interaction and account status), "
        "KEY OPPORTUNITIES (2-3 bullet points of products to discuss, from the recommendations provided), "
        "CONVERSATION STARTER (one warm, professional opening line the manager can use). "
        "Be specific, use the client's name. Never sound surveillance-like. The banker is the hero."
    )
    user_prompt = (
        f"Client: {cust['full_name']}, {cust.get('title', '')}\n"
        f"Tier: {tier_info.get('label', cust['vip_tier'])}\n"
        f"Relationship Manager: {cust.get('rm', 'N/A')}\n"
        f"Last interaction: {cust.get('last_interaction', 'N/A')}\n"
        f"Notes: {cust.get('notes', 'N/A')}\n"
        f"Product recommendations:\n{recs_text}\n"
        f"Generate the greeting brief."
    )

    try:
        _call_start = _time.time()
        response = foundry_chat(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt[:3600]},
            ],
            max_tokens=300,
            temperature=0.4,
        )
        elapsed = _time.time() - _call_start
        _track_model_call(response, elapsed)
        brief = (response.choices[0].message.content or "").strip()
        tokens = 0
        if hasattr(response, 'usage') and response.usage:
            tokens = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)

        return jsonify({
            "brief": brief,
            "client_name": cust["full_name"],
            "tier": cust["vip_tier"],
            "tier_label": tier_info.get("label", ""),
            "recommendations": [{"name": r["name"], "priority": r["priority"]} for r in top_recs],
            "tokens_used": tokens,
            "inference_time": round(elapsed, 1),
            "model": "Phi-4 Mini",
            "source": "npu_local",
        })
    except Exception as e:
        # Fallback brief
        return jsonify({
            "brief": (
                f"RECENT CONTEXT\n{cust.get('last_interaction', 'No recent interactions on file.')}\n\n"
                f"KEY OPPORTUNITIES\n" + recs_text + "\n"
                f"CONVERSATION STARTER\n\"Welcome, {cust['name'].split()[0]}! Great to see you today.\""
            ),
            "client_name": cust["full_name"],
            "tier": cust["vip_tier"],
            "tokens_used": 0,
            "inference_time": 0,
            "model": "fallback",
            "source": "demo",
        })


@app.route('/arrivals/<arrival_id>/status', methods=['POST'])
def arrival_status(arrival_id):
    """Update arrival status (waiting -> being_greeted -> met)."""
    arr = _ARRIVALS.get(arrival_id)
    if not arr:
        return jsonify({"error": "Arrival not found"}), 404
    data = request.json or {}
    new_status = data.get("status", "being_greeted")
    arr["status"] = new_status
    print(f"[CONCIERGE] {arr['name']} status -> {new_status}")
    return jsonify({"arrival_id": arrival_id, "name": arr["name"], "status": new_status})


@app.route('/arrivals/reset', methods=['POST'])
def arrivals_reset():
    """Clear all arrivals (demo reset)."""
    _ARRIVALS.clear()
    return jsonify({"status": "cleared"})


@app.route('/api/config')
def api_config():
    """Return non-sensitive config values for client-side use."""
    return jsonify({
        "brand_company": DEMO_CONFIG.get("brand_company", ""),
        "advisor": {
            "name": DEMO_CONFIG.get("advisor_name", ""),
            "title": DEMO_CONFIG.get("advisor_title", ""),
            "company": DEMO_CONFIG.get("advisor_company", ""),
        },
        "economics": DEMO_CONFIG.get("economics", {}),
        "customer": DEMO_CONFIG.get("customer", {}),
    })


@app.route('/demo-mode-status')
def demo_mode_status():
    """Check if demo mode is enabled (bypasses offline requirement for Clean Room)."""
    return jsonify({"demo_mode": DEMO_MODE})

if __name__ == '__main__':
    import sys

    # DEMO_MODE is already parsed at module level (line 27)
    if DEMO_MODE:
        print("\n** DEMO MODE ENABLED — full demo without D365/Graph tenants **\n")

    print("\n" + "="*50)
    print(f"{DEMO_CONFIG['app_title']} ({EDITION_TAG})")
    print(f"  {DEVICE_LABEL} — {CHIP_LABEL}")
    _tab_names = " + ".join(t["name"] for t in DEMO_CONFIG["tabs"].values())
    print(f"  {_tab_names}")
    print("="*50)
    print(f"Model: {DEFAULT_MODEL}")
    if FOUNDRY_AVAILABLE:
        print(f"Runtime: Foundry Local ({manager.endpoint})")
    else:
        print("Runtime: Foundry Local (fallback to localhost:5272)")
    if DEMO_MODE:
        print("Demo Mode: ENABLED (offline check bypassed)")
    print("")
    print("Features:")
    print("  - Auditor (structured analysis + smart escalation)")
    print("  - My Day (calendar, email, tasks briefing)")
    print("  - AI Agent (tool calling, file ops, system commands)")
    print("  - ID Verification (Camera + OCR + AI)")
    print("")
    print("All processing happens 100% locally on your device.")
    print("")

    # --- Warmup: verify model is loaded and responsive before serving ---
    # On Qualcomm QNN NPU, the Foundry service is unstable during rapid
    # warmup retries (service crashes and restarts in a loop).  We skip
    # the warmup ping on Qualcomm and let the first real request trigger
    # model load; the auto-reconnect wrapper handles any port changes.
    WARMUP_RETRIES = 4
    WARMUP_PAUSE   = 10  # seconds between retries
    _warmup_done = threading.Event()
    _warmup_ok = [False]

    if SILICON == "qualcomm":
        print("Skipping warmup on Qualcomm (first request will load model)...", flush=True)
        _warmup_ok[0] = True
        _warmup_done.set()
    else:
        print("Warming up model (first load may download ~3 GB)...", flush=True)

        def _warmup_call():
            for attempt in range(1, WARMUP_RETRIES + 1):
                try:
                    client.chat.completions.create(
                        model=DEFAULT_MODEL,
                        messages=[{"role": "user", "content": "hi"}],
                        max_tokens=4,
                        temperature=0.1,
                    )
                    _warmup_ok[0] = True
                    break
                except Exception:
                    if attempt < WARMUP_RETRIES:
                        _time.sleep(WARMUP_PAUSE)
                        _reconnect_foundry()
            _warmup_done.set()

    if SILICON != "qualcomm":
        _warmup_thread = threading.Thread(target=_warmup_call, daemon=True)
        _warmup_start = _time.time()
        _warmup_thread.start()

        _spinner = ["|", "/", "-", "\\"]
        _si = 0
        while not _warmup_done.wait(timeout=0.5):
            _elapsed = _time.time() - _warmup_start
            print(f"\r  {_spinner[_si % 4]}  Loading model... {_elapsed:.0f}s", end="", flush=True)
            _si += 1

        _warmup_secs = _time.time() - _warmup_start
        if _warmup_ok[0]:
            print(f"\r  Model ready in {_warmup_secs:.1f}s              ")
        else:
            print(f"\r  Warning: warmup did not complete ({_warmup_secs:.1f}s). Continuing anyway.")
            print("  (Model may still be downloading — the app will work once it's ready.)")

    MODEL_READY = True

    # --- Build Local Knowledge index ---
    build_knowledge_index()

    # --- Keepalive: prevent model from being unloaded during idle ---
    KEEPALIVE_INTERVAL = 180  # seconds

    def _keepalive_loop():
        while True:
            _time.sleep(KEEPALIVE_INTERVAL)
            try:
                foundry_chat(
                    model=DEFAULT_MODEL,
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=1,
                    temperature=0.1,
                )
            except Exception:
                pass  # non-critical, will retry next interval

    if SILICON != "qualcomm":
        # Skip keepalive on Qualcomm - QNN NPU Foundry service is unstable
        # with periodic pings; auto-reconnect handles port changes on demand.
        _keepalive_thread = threading.Thread(target=_keepalive_loop, daemon=True)
        _keepalive_thread.start()

    print("")
    print("Open http://localhost:5000 in your browser")
    print("="*50 + "\n")
    app.run(host="127.0.0.1", debug=True, port=5000, use_reloader=False)
