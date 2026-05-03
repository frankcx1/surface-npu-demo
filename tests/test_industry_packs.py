"""
Wave 0 tests for the Industry Packs architecture.
Tests: config loader, inheritance resolution, validation, vocabulary substitution,
safety gate registry, signal registry, concierge tiers, agent prompt hybrid,
stub mode, stub banner rendering.

Target: ~55 tests per spec Section 17.
"""

import os
import sys
import json
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

# Patch OpenAI before importing the app module (same pattern as existing tests)
_mock_client_instance = MagicMock()
_mock_client_instance.chat.completions.create.return_value = MagicMock(
    choices=[MagicMock(message=MagicMock(content="Test response"))],
    usage=MagicMock(prompt_tokens=10, completion_tokens=10, total_tokens=20),
)

with patch("openai.OpenAI", return_value=_mock_client_instance):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import npu_demo_flask as app_module


class TestDeepMerge(unittest.TestCase):
    """Section 11: deep merge semantics (4 tests)."""

    def test_dict_merge(self):
        """Nested dicts merge recursively."""
        dst = {"a": {"x": 1, "y": 2}}
        src = {"a": {"y": 3, "z": 4}}
        app_module._deep_merge(dst, src)
        self.assertEqual(dst, {"a": {"x": 1, "y": 3, "z": 4}})

    def test_list_replace(self):
        """Lists replace, not append."""
        dst = {"items": [1, 2, 3]}
        src = {"items": [4, 5]}
        app_module._deep_merge(dst, src)
        self.assertEqual(dst["items"], [4, 5])

    def test_scalar_override(self):
        """Scalar values in src override dst."""
        dst = {"name": "old", "count": 1}
        src = {"name": "new"}
        app_module._deep_merge(dst, src)
        self.assertEqual(dst["name"], "new")
        self.assertEqual(dst["count"], 1)

    def test_nested_override(self):
        """Deep nested override works."""
        dst = {"a": {"b": {"c": 1, "d": 2}, "e": 3}}
        src = {"a": {"b": {"c": 99}}}
        app_module._deep_merge(dst, src)
        self.assertEqual(dst["a"]["b"]["c"], 99)
        self.assertEqual(dst["a"]["b"]["d"], 2)
        self.assertEqual(dst["a"]["e"], 3)


class TestConfigLoader(unittest.TestCase):
    """Section 11: extends chain resolution (5 tests)."""

    def test_single_level_load(self):
        """Brand with no extends loads correctly."""
        # Manufacturing has no vertical, just industry → brand (2 levels)
        resolved, chain = app_module._load_resolved_config("zava-manufacturing")
        self.assertEqual(resolved.get("brand_id"), "zava-manufacturing")
        self.assertGreaterEqual(len(chain), 2)

    def test_two_level_chain(self):
        """Industry → vertical → brand chain resolves."""
        resolved, chain = app_module._load_resolved_config("zava-health")
        self.assertEqual(resolved.get("brand_id"), "zava-health")
        self.assertEqual(resolved.get("industry_id"), "healthcare")
        self.assertGreaterEqual(len(chain), 3)

    def test_three_level_chain(self):
        """Industry → vertical → zava-ref → customer brand resolves."""
        resolved, chain = app_module._load_resolved_config("flagstar")
        self.assertEqual(resolved.get("brand_id"), "flagstar")
        self.assertEqual(resolved.get("industry_id"), "financial-services")
        self.assertEqual(len(chain), 4)

    def test_missing_parent_raises(self):
        """Missing file in extends chain raises RuntimeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brand_dir = os.path.join(tmpdir, "configs", "brands", "bad-brand")
            os.makedirs(brand_dir)
            with open(os.path.join(brand_dir, "demo_config.yaml"), "w") as f:
                f.write("extends: industries/nonexistent/industry.yaml\nbrand_id: bad\n")
            # Temporarily override APP_ROOT
            orig = app_module._APP_ROOT
            app_module._APP_ROOT = tmpdir
            try:
                with self.assertRaises(RuntimeError) as ctx:
                    app_module._load_resolved_config("bad-brand")
                self.assertIn("not found", str(ctx.exception).lower())
            finally:
                app_module._APP_ROOT = orig

    def test_circular_extends_raises(self):
        """Circular extends chain raises RuntimeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brands = os.path.join(tmpdir, "configs", "brands")
            os.makedirs(os.path.join(brands, "loop-a"))
            os.makedirs(os.path.join(brands, "loop-b"))
            with open(os.path.join(brands, "loop-a", "demo_config.yaml"), "w") as f:
                f.write("extends: brands/loop-b/demo_config.yaml\nbrand_id: loop-a\n")
            with open(os.path.join(brands, "loop-b", "demo_config.yaml"), "w") as f:
                f.write("extends: brands/loop-a/demo_config.yaml\nbrand_id: loop-b\n")
            orig = app_module._APP_ROOT
            app_module._APP_ROOT = tmpdir
            try:
                with self.assertRaises(RuntimeError) as ctx:
                    app_module._load_resolved_config("loop-a")
                self.assertIn("circular", str(ctx.exception).lower())
            finally:
                app_module._APP_ROOT = orig


class TestConfigValidation(unittest.TestCase):
    """Section 11: validation rules (12 tests)."""

    def _base_config(self):
        """Return a minimal valid config dict."""
        return {
            "schema_version": 1,
            "status": "active",
            "brand_status": "active",
            "vocabulary": {t: f"test_{t}" for t in app_module._REQUIRED_VOCAB_TOKENS},
            "tabs": {t: {"name": t, "sub": t} for t in app_module._REQUIRED_TAB_IDS},
            "prompts": {p: f"Test prompt for {p}" for p in app_module._REQUIRED_PROMPT_IDS},
            "compliance": {"primary_safety_gate": "passthrough"},
            "concierge": {"enabled": False},
            "pii": {"demo_person_names": ["Test Person"]},
            "demo_data": {"path": "demo_data"},
        }

    def test_valid_config_passes(self):
        """A fully valid config passes validation."""
        app_module._validate_resolved_config(self._base_config())

    def test_wrong_schema_version(self):
        """schema_version != 1 fails."""
        cfg = self._base_config()
        cfg["schema_version"] = 2
        with self.assertRaises(RuntimeError) as ctx:
            app_module._validate_resolved_config(cfg)
        self.assertIn("schema_version", str(ctx.exception))

    def test_missing_vocab_token(self):
        """Missing required vocabulary token fails."""
        cfg = self._base_config()
        del cfg["vocabulary"]["subject"]
        with self.assertRaises(RuntimeError) as ctx:
            app_module._validate_resolved_config(cfg)
        self.assertIn("subject", str(ctx.exception))

    def test_vocab_boolean_value_fails(self):
        """Vocabulary value that's a boolean (YAML 1.1 no→False) fails."""
        cfg = self._base_config()
        cfg["vocabulary"]["subject"] = False  # simulates unquoted 'no' in YAML
        with self.assertRaises(RuntimeError) as ctx:
            app_module._validate_resolved_config(cfg)
        self.assertIn("string", str(ctx.exception).lower())

    def test_vocab_collision_with_html_var(self):
        """Vocabulary token that collides with HTML template var fails."""
        cfg = self._base_config()
        # APP_TITLE is an uppercase HTML var; 'app_title' as vocab would collide
        cfg["vocabulary"]["app_title"] = "test"
        with self.assertRaises(RuntimeError) as ctx:
            app_module._validate_resolved_config(cfg)
        self.assertIn("collides", str(ctx.exception).lower())

    def test_missing_tab(self):
        """Missing required tab ID fails."""
        cfg = self._base_config()
        del cfg["tabs"]["live"]
        with self.assertRaises(RuntimeError) as ctx:
            app_module._validate_resolved_config(cfg)
        self.assertIn("live", str(ctx.exception))

    def test_missing_prompt_active(self):
        """Missing prompt in active config fails."""
        cfg = self._base_config()
        del cfg["prompts"]["brief_me"]
        with self.assertRaises(RuntimeError) as ctx:
            app_module._validate_resolved_config(cfg)
        self.assertIn("brief_me", str(ctx.exception))

    def test_missing_prompt_stub_ok(self):
        """Missing prompt in stub config does not fail."""
        cfg = self._base_config()
        cfg["status"] = "stub"
        del cfg["prompts"]["brief_me"]
        # Should not raise
        app_module._validate_resolved_config(cfg)

    def test_concierge_enabled_no_tiers_fails(self):
        """Concierge enabled but no tiers fails."""
        cfg = self._base_config()
        cfg["concierge"] = {"enabled": True, "tiers": []}
        with self.assertRaises(RuntimeError) as ctx:
            app_module._validate_resolved_config(cfg)
        self.assertIn("concierge", str(ctx.exception).lower())

    def test_concierge_disabled_no_tiers_ok(self):
        """Concierge disabled with no tiers passes."""
        cfg = self._base_config()
        cfg["concierge"] = {"enabled": False}
        app_module._validate_resolved_config(cfg)

    def test_pii_names_not_list_fails(self):
        """pii.demo_person_names as non-list fails."""
        cfg = self._base_config()
        cfg["pii"]["demo_person_names"] = "not a list"
        with self.assertRaises(RuntimeError) as ctx:
            app_module._validate_resolved_config(cfg)
        self.assertIn("list", str(ctx.exception).lower())

    def test_all_real_brands_pass_validation(self):
        """All 10 brand configs in the repo pass validation."""
        brands = [
            "zava-financial", "zava-health", "zava-insurance", "zava-pharma",
            "zava-public-sector", "zava-manufacturing", "zava-retail", "zava-education",
            "flagstar", "bofa",
        ]
        for brand in brands:
            resolved, _ = app_module._load_resolved_config(brand)
            try:
                app_module._validate_resolved_config(resolved)
            except RuntimeError as e:
                self.fail(f"Brand '{brand}' failed validation: {e}")


class TestVocabSubstitution(unittest.TestCase):
    """Section 8: vocabulary substitution (5 tests)."""

    def test_basic_substitution(self):
        """Single token is replaced."""
        result = app_module._render_vocab("Hello {{subject}}", {"subject": "patient"})
        self.assertEqual(result, "Hello patient")

    def test_multi_token(self):
        """Multiple tokens in one string are replaced."""
        template = "The {{practitioner}} meets the {{subject}} at the {{organization}}."
        vocab = {"practitioner": "clinician", "subject": "patient", "organization": "clinic"}
        result = app_module._render_vocab(template, vocab)
        self.assertEqual(result, "The clinician meets the patient at the clinic.")

    def test_missing_token_left_as_is(self):
        """Token not in vocab dict is left unchanged."""
        result = app_module._render_vocab("Hello {{unknown_token}}", {"subject": "patient"})
        self.assertEqual(result, "Hello {{unknown_token}}")

    def test_brand_override(self):
        """Brand-level vocab overrides industry default."""
        resolved, _ = app_module._load_resolved_config("zava-insurance")
        self.assertEqual(resolved["vocabulary"]["subject"], "policyholder")

    def test_no_op_on_empty(self):
        """Empty string and empty vocab return empty string."""
        self.assertEqual(app_module._render_vocab("", {}), "")
        self.assertEqual(app_module._render_vocab(None, {}), "")


class TestGetPrompt(unittest.TestCase):
    """Section 10: prompt retrieval and rendering (3 tests)."""

    def test_get_prompt_financial(self):
        """Financial services brief_me prompt loads and has no unresolved tokens."""
        resolved, _ = app_module._load_resolved_config("zava-financial")
        prompt = app_module._get_prompt("brief_me", resolved_config=resolved)
        self.assertTrue(len(prompt) > 50)
        # All standard vocab tokens should be resolved
        for token in app_module._REQUIRED_VOCAB_TOKENS:
            self.assertNotIn("{{" + token + "}}", prompt,
                             f"Token {{{{{token}}}}} not resolved in brief_me")

    def test_get_prompt_healthcare(self):
        """Healthcare prompt uses healthcare vocabulary."""
        resolved, _ = app_module._load_resolved_config("zava-health")
        prompt = app_module._get_prompt("brief_me", resolved_config=resolved)
        # Should contain healthcare vocab, not banking
        self.assertIn("patient", prompt.lower())

    def test_get_prompt_missing_returns_empty(self):
        """Missing prompt returns empty string (not crash)."""
        resolved, _ = app_module._load_resolved_config("zava-financial")
        # Remove a prompt to test
        saved = resolved["prompts"].pop("brief_me", None)
        prompt = app_module._get_prompt("brief_me", resolved_config=resolved)
        self.assertEqual(prompt, "")
        if saved:
            resolved["prompts"]["brief_me"] = saved


class TestSafetyGateRegistry(unittest.TestCase):
    """Section 9a: safety gate registry (4 tests)."""

    def test_gates_registered(self):
        """All expected gates are registered."""
        expected = {"passthrough", "financial_advice_gate", "clinical_advice_gate",
                    "pharma_promotional_gate", "ferpa_gate", "cui_gate",
                    "export_control_gate", "pci_gate"}
        self.assertTrue(expected.issubset(set(app_module._SAFETY_GATES.keys())))

    def test_financial_gate_blocks_rate_quote(self):
        """Financial advice gate blocks rate quotes."""
        is_safe, _ = app_module._financial_advice_gate(
            "Our savings account offers 4.5% APY right now.")
        self.assertFalse(is_safe)

    def test_clinical_gate_blocks_diagnosis(self):
        """Clinical advice gate blocks definitive diagnoses."""
        is_safe, _ = app_module._clinical_advice_gate(
            "Based on these symptoms, you have type 2 diabetes.")
        self.assertFalse(is_safe)

    def test_passthrough_gate_allows_all(self):
        """Passthrough gate allows everything."""
        is_safe, text = app_module._passthrough_gate("Any text at all")
        self.assertTrue(is_safe)
        self.assertEqual(text, "Any text at all")

    def test_get_active_gate_legacy(self):
        """Legacy path returns financial_advice_gate."""
        # In legacy mode, _INDUSTRY_PACKS_ACTIVE is False
        gate = app_module._get_active_safety_gate()
        self.assertEqual(gate.__name__, "_financial_advice_gate")

    def test_clinical_gate_allows_documentation(self):
        """Clinical gate allows documentation and summaries."""
        is_safe, text = app_module._clinical_advice_gate(
            "The patient reported fatigue and increased urination over the past two months.")
        self.assertTrue(is_safe)

    def test_clinical_gate_blocks_dosing(self):
        """Clinical gate blocks medication dosing recommendations."""
        is_safe, _ = app_module._clinical_advice_gate(
            "I recommend you take 500mg of metformin twice daily.")
        self.assertFalse(is_safe)


class TestSignalRegistry(unittest.TestCase):
    """Section 9b: cross-sell signal registry (4 tests)."""

    def test_signals_registered(self):
        """Banking and healthcare signals are registered."""
        self.assertIn("has_checking_no_savings", app_module._CROSS_SELL_SIGNALS)
        self.assertIn("no_annual_wellness", app_module._CROSS_SELL_SIGNALS)

    def test_banking_signal_matches(self):
        """has_checking_no_savings returns True for appropriate data."""
        data = {"accounts": [{"type": "Essential Checking"}]}
        result = app_module._sig_has_checking_no_savings(data)
        self.assertTrue(result)

    def test_banking_signal_no_match(self):
        """has_checking_no_savings returns False when both exist."""
        data = {"accounts": [{"type": "Checking"}, {"type": "Savings"}]}
        result = app_module._sig_has_checking_no_savings(data)
        self.assertFalse(result)

    def test_healthcare_stub_returns_false(self):
        """Healthcare stub signals return False by default."""
        data = {"accounts": [], "notes": ""}
        self.assertFalse(app_module._sig_no_annual_wellness(data))
        self.assertFalse(app_module._sig_overdue_screenings(data))
        self.assertFalse(app_module._sig_unmanaged_chronic(data))

    def test_evaluate_signals(self):
        """_evaluate_signals matches only triggered signals."""
        data = {"accounts": [{"type": "Checking"}], "notes": ""}
        signal_defs = [
            {"signal": "has_checking_no_savings", "items": ["savings"], "priority": "high"},
            {"signal": "no_credit_card", "items": ["credit_card"], "priority": "medium"},
            {"signal": "nonexistent_signal", "items": ["x"], "priority": "low"},
        ]
        matches = app_module._evaluate_signals(data, signal_defs)
        matched_signals = [m["signal"] for m in matches]
        self.assertIn("has_checking_no_savings", matched_signals)
        self.assertIn("no_credit_card", matched_signals)
        self.assertNotIn("nonexistent_signal", matched_signals)


class TestConciergeTiers(unittest.TestCase):
    """Section 7a: concierge tier configuration (2 tests)."""

    def test_banking_concierge_tiers(self):
        """Financial services has banking-appropriate tiers."""
        resolved, _ = app_module._load_resolved_config("zava-financial")
        tiers = resolved.get("concierge", {}).get("tiers", [])
        self.assertTrue(len(tiers) >= 3)
        tier_ids = [t["id"] for t in tiers]
        # Banking should have private/premier/business/retail
        self.assertTrue(any("priv" in tid for tid in tier_ids) or
                        any("premier" in tid for tid in tier_ids))

    def test_healthcare_concierge_tiers(self):
        """Healthcare has healthcare-appropriate tiers."""
        resolved, _ = app_module._load_resolved_config("zava-health")
        tiers = resolved.get("concierge", {}).get("tiers", [])
        self.assertTrue(len(tiers) >= 3)
        tier_ids = [t["id"] for t in tiers]
        self.assertIn("scheduled", tier_ids)


class TestAgentPromptHybrid(unittest.TestCase):
    """Section 10: agent_system_framing + tool injection (2 tests)."""

    def test_framing_prompt_exists(self):
        """agent_system_framing prompt exists in financial config."""
        resolved, _ = app_module._load_resolved_config("zava-financial")
        prompt = app_module._get_prompt("agent_system_framing", resolved_config=resolved)
        self.assertTrue(len(prompt) > 20)

    def test_framing_uses_vocab(self):
        """agent_system_framing prompt has vocabulary substituted."""
        resolved, _ = app_module._load_resolved_config("zava-health")
        prompt = app_module._get_prompt("agent_system_framing", resolved_config=resolved)
        # Should contain healthcare vocab
        self.assertNotIn("{{practitioner}}", prompt)
        self.assertNotIn("{{organization}}", prompt)


class TestStubMode(unittest.TestCase):
    """Section 12: stub mode behavior (6 tests, one per stub industry)."""

    def _assert_stub(self, brand_id):
        resolved, _ = app_module._load_resolved_config(brand_id)
        status = resolved.get("status", "active")
        brand_status = resolved.get("brand_status", "active")
        is_stub = status == "stub" or brand_status == "stub"
        self.assertTrue(is_stub, f"{brand_id} should be a stub")
        # Stub should still have all 6 tab IDs
        tabs = resolved.get("tabs", {})
        for tid in ["chat", "day", "auditor", "id", "live", "field"]:
            self.assertIn(tid, tabs, f"{brand_id} missing tab {tid}")

    def test_stub_insurance(self):
        self._assert_stub("zava-insurance")

    def test_stub_pharma(self):
        self._assert_stub("zava-pharma")

    def test_stub_public_sector(self):
        self._assert_stub("zava-public-sector")

    def test_stub_manufacturing(self):
        self._assert_stub("zava-manufacturing")

    def test_stub_retail(self):
        self._assert_stub("zava-retail")

    def test_stub_education(self):
        self._assert_stub("zava-education")


class TestStubBannerRendering(unittest.TestCase):
    """Section 12: stub banner in HTML template (1 test)."""

    def test_stub_banner_div_in_template(self):
        """The stub banner div exists in the HTML template."""
        client = app_module.app.test_client()
        resp = client.get("/")
        self.assertIn(b"industry-stub-banner", resp.data)


class TestBrandInheritance(unittest.TestCase):
    """Cross-industry inheritance correctness (5 tests)."""

    def test_flagstar_inherits_banking_vocab(self):
        """Flagstar inherits financial-services vocabulary."""
        resolved, _ = app_module._load_resolved_config("flagstar")
        self.assertEqual(resolved["vocabulary"]["subject"], "client")
        self.assertEqual(resolved["vocabulary"]["practitioner"], "advisor")

    def test_flagstar_overrides_brand(self):
        """Flagstar overrides brand colors from zava-financial."""
        resolved, _ = app_module._load_resolved_config("flagstar")
        self.assertEqual(resolved["brand"]["accent"], "#f18f12")
        self.assertEqual(resolved["brand"]["company_name"], "Flagstar Bank")

    def test_bofa_inherits_prompts(self):
        """BofA inherits prompts from financial-services industry."""
        resolved, _ = app_module._load_resolved_config("bofa")
        self.assertIn("brief_me", resolved.get("prompts", {}))
        prompt = resolved["prompts"]["brief_me"]
        self.assertTrue(len(prompt) > 50)

    def test_pharma_overrides_vocabulary(self):
        """Pharma vertical overrides healthcare vocabulary."""
        resolved, _ = app_module._load_resolved_config("zava-pharma")
        self.assertEqual(resolved["vocabulary"]["practitioner"], "MSL")
        # But subject should still be inherited from healthcare
        self.assertEqual(resolved["vocabulary"]["subject"], "patient")

    def test_insurance_overrides_tabs(self):
        """Insurance vertical overrides tab names."""
        resolved, _ = app_module._load_resolved_config("zava-insurance")
        chat_name = resolved.get("tabs", {}).get("chat", {}).get("name", "")
        self.assertEqual(chat_name, "Adjuster Assistant")


class TestLegacyPathUnchanged(unittest.TestCase):
    """Verify the legacy config path still works when industry packs are off."""

    def test_legacy_config_loads(self):
        """DEMO_CONFIG is populated via legacy path."""
        self.assertIn("app_title", app_module.DEMO_CONFIG)
        self.assertTrue(len(app_module.DEMO_CONFIG["app_title"]) > 0)

    def test_industry_packs_not_active_by_default(self):
        """Industry packs should not be active in normal mode."""
        self.assertFalse(app_module._INDUSTRY_PACKS_ACTIVE)

    def test_existing_routes_still_work(self):
        """Core routes return valid responses."""
        client = app_module.app.test_client()
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
