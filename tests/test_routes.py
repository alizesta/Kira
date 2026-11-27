"""Route Manager data model (kira/routes.py): migration, add/edit/delete, ordering, default/manual, persistence."""
import json
import unittest
from copy import deepcopy
from unittest import mock

from tests import helpers
from tests.helpers import CANARY
from kira import config, routes
from kira.app.detected_capabilities import DetectedCapabilities


def legacy_settings():
    s = helpers.fresh_settings()
    helpers.enable(s, "groq", "cloudflare")
    s["provider_order"] = ["cloudflare", "ollama", "groq", "mistral", "openrouter"]
    s["model"] = "qwen2.5:3b"
    s["providers"]["groq"]["model"] = "openai/gpt-oss-20b"
    return s


class RouteModelTests(unittest.TestCase):
    def setUp(self):
        self.capabilities = DetectedCapabilities()

    def test_display_groups_identical_cloud_models_but_keeps_provider_routes_and_quota_slots(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        model = "gemini-3.8-flash"
        routes.update_route(s, "groq", model=model, enabled=True)
        routes.update_route(s, "cloudflare", model=model, enabled=True)
        apinex = routes.add_provider(s, "APInex", "https://api.apinex.bond/v1", api_key="test-apinex-key")
        apinex_route = routes.add_route(s, apinex, "free/" + model, enabled=True)
        before = deepcopy(routes.get_routes(s))

        groups = routes.group_routes_for_display(
            s, status_by_id={
                "groq": {"enabled": True},
                "cloudflare": {"enabled": True},
                apinex_route["id"]: {"enabled": False},
            }
        )
        matching = [group for group in groups if group["model"].casefold() == model.casefold()]

        self.assertEqual(len(matching), 1)
        group = matching[0]
        self.assertEqual(set(group["provider_ids"]), {"groq", "cloudflare", apinex})
        self.assertEqual(len(group["route_ids"]), 3)
        self.assertEqual(group["active_count"], 2)
        self.assertEqual(group["model"], model)  # the APInex free/ prefix is presentation metadata
        self.assertEqual(routes.get_routes(s), before)  # display grouping never merges execution routes

    def test_display_grouping_strips_apinex_and_google_provider_prefixes(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        model = "gemenai-4-hydrogen"

        apinex = routes.add_provider(
            s, "APInex", "https://api.apinex.bond/v1", api_key="test-apinex-key"
        )
        google = routes.add_provider(
            s, "Google", "https://generativelanguage.googleapis.com/v1beta/openai",
            api_key="test-google-key"
        )
        apinex_route = routes.add_route(s, apinex, "free/" + model, enabled=True)
        google_route = routes.add_route(s, google, "goole/" + model, enabled=True)
        before = deepcopy(routes.get_routes(s))

        groups = routes.group_routes_for_display(s)
        matching = [group for group in groups if group["model"].casefold() == model.casefold()]

        self.assertEqual(len(matching), 1)
        group = matching[0]
        self.assertEqual(set(group["provider_ids"]), {apinex, google})
        self.assertEqual(set(group["route_ids"]), {apinex_route["id"], google_route["id"]})
        self.assertEqual(group["model"], model)
        self.assertEqual(routes.get_routes(s), before)
        self.assertEqual(apinex_route["model"], "free/" + model)
        self.assertEqual(google_route["model"], "goole/" + model)

    def test_provider_namespace_matching_does_not_strip_every_label_word(self):
        cfg = {"label": "Google AI Studio"}
        self.assertEqual(
            routes.normalize_display_model_id("goole/model-x", "custom-google-ai-studio", cfg),
            "model-x",
        )
        self.assertEqual(
            routes.normalize_display_model_id("studio/model-x", "custom-google-ai-studio", cfg),
            "studio/model-x",
        )
    def test_display_grouping_keeps_unrelated_publisher_namespace(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        model = "meta-llama/llama-4-hydrogen"
        route = routes.add_route(s, "openrouter", model, enabled=True)

        groups = routes.group_routes_for_display(s)
        matching = [group for group in groups if route["id"] in group["route_ids"]]

        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["model"], model)
    def test_display_grouping_keeps_same_named_local_model_separate_from_cloud(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        model = "gemini-3.8-flash"
        routes.update_route(s, "groq", model=model, enabled=True)
        routes.update_route(s, "ollama", model=model, enabled=True)

        groups = routes.group_routes_for_display(s)
        matching = [group for group in groups if group["model"].casefold() == model.casefold()]

        self.assertEqual(len(matching), 2)
        self.assertEqual({group["kind"] for group in matching}, {"cloud", "local"})
        self.assertEqual(sorted(len(group["route_ids"]) for group in matching), [1, 1])
    def test_migration_keeps_order_models_keys_and_providers_untouched(self):
        s = legacy_settings()
        before = deepcopy(s["providers"])
        routes.ensure_routes(s)
        self.assertEqual([r["id"] for r in s["routes"]], ["cloudflare", "ollama", "groq", "mistral", "openrouter"])
        by = {r["id"]: r for r in s["routes"]}
        self.assertEqual(by["groq"]["model"], "openai/gpt-oss-20b")
        self.assertEqual(by["ollama"]["model"], "qwen2.5:3b")
        self.assertEqual(s["providers"], before)                       # API keys / options not modified
        self.assertEqual(s["providers"]["groq"]["api_key"], f"{CANARY}-groq")

    def test_ensure_routes_collapses_duplicate_local_models_and_preserves_selection(self):
        s = legacy_settings()
        model = "kira-qwen3.5-9b-abliterated:q4_k_m"
        s["routes"] = [
            {"id": "ollama", "provider": "ollama", "model": model, "enabled": False, "num_ctx": 2048},
            {"id": "ollama-2", "provider": "ollama", "model": model, "enabled": True, "num_ctx": 8192,
             "num_predict": 256},
            {"id": "ollama-3", "provider": "ollama", "model": model, "enabled": False},
        ]
        s["manual_route_id"] = "ollama-3"
        s["default_route_id"] = "ollama-2"
        self.capabilities.mapping_set("route_notes", "ollama-3", "previous local error")

        routes.ensure_routes(s, capabilities=self.capabilities)

        local = [r for r in routes.get_routes(s) if r["provider"] == "ollama"]
        self.assertEqual(len(local), 1)
        self.assertEqual(local[0]["id"], "ollama")
        self.assertTrue(local[0]["enabled"])
        self.assertEqual(local[0]["num_ctx"], 8192)
        self.assertEqual(local[0]["num_predict"], 256)
        self.assertEqual(s["manual_route_id"], "ollama")
        self.assertEqual(s["default_route_id"], "ollama")
        self.assertEqual(self.capabilities.mapping_get("route_notes", "ollama"), "previous local error")
        self.assertNotIn("route_notes", s)
        self.assertNotIn("ollama-2", {r["id"] for r in routes.get_routes(s)})
        self.assertNotIn("ollama-3", {r["id"] for r in routes.get_routes(s)})

    def test_migration_is_idempotent_and_keeps_user_edits(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        routes.update_route(s, "groq", timeout=40, cooldown=10)
        once = deepcopy(s["routes"])
        routes.ensure_routes(s)
        self.assertEqual(s["routes"], once)

    def test_ensure_routes_removes_retired_reverse_api_settings(self):
        settings = {
            "providers": {
                "ollama": {"enabled": True},
                "reverse_api": {"type": "reverse_api", "transport": "deepseek", "enabled": True},
            },
            "routes": [
                {"id": "reverse_api", "provider": "reverse_api", "model": "deepseek-web", "enabled": True},
                {"id": "ollama", "provider": "ollama", "model": "qwen3.5:4b", "enabled": True},
            ],
            "manual_route_id": "reverse_api",
            "default_route_id": "reverse_api",
        }
        self.capabilities.mapping_set("route_notes", "reverse_api", "retired")
        self.capabilities.mapping_set("route_notes", "ollama", "keep")

        routes.ensure_routes(settings, capabilities=self.capabilities)

        self.assertNotIn("reverse_api", settings["providers"])
        self.assertNotIn("reverse_api", {item["provider"] for item in settings["routes"]})
        self.assertEqual(settings["manual_route_id"], "")
        self.assertEqual(settings["default_route_id"], "ollama")
        self.assertEqual(self.capabilities.mapping_get("route_notes", "ollama"), "keep")
        self.assertIsNone(self.capabilities.mapping_get("route_notes", "reverse_api"))
        self.assertNotIn("route_notes", settings)
        self.assertNotIn("reverse_api", settings["provider_order"])

    def test_derived_routes_do_not_write_into_settings(self):
        s = legacy_settings()
        self.assertEqual([r["id"] for r in routes.get_routes(s)][:2], ["cloudflare", "ollama"])
        self.assertNotIn("routes", s)

    def test_provider_and_route_are_separate_one_provider_many_models(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        a = routes.add_route(s, "groq", "openai/gpt-oss-120b", timeout=30)
        b = routes.add_route(s, "groq", "llama-x", enabled=False, cooldown=5)
        self.assertEqual((a["id"], b["id"]), ("groq-2", "groq-3"))
        self.assertEqual(sum(r["provider"] == "groq" for r in s["routes"]), 3)
        self.assertEqual(len([k for k in s["providers"] if k == "groq"]), 1)      # still ONE provider (one key)
        self.assertEqual((a["timeout"], b["cooldown"], b["enabled"]), (30, 5, False))
        with self.assertRaises(ValueError):
            routes.add_route(s, "groq", "llama-x")                              # same provider + model twice
        with self.assertRaises(ValueError):
            routes.add_route(s, "groq", "  ")

    def test_model_catalog_objects_are_normalized_to_provider_ids(self):
        model = {"id": "codestral-2508", "name": "Codestral", "context": 256000}
        route = routes.make_route("mistral-2", "mistral", model)
        self.assertEqual(route["model"], "codestral-2508")
        self.assertEqual(routes.normalize_model_id(str(model)), "codestral-2508")

    def test_ensure_routes_repairs_legacy_stringified_model_objects(self):
        s = legacy_settings()
        s["routes"] = [
            {"id": "mistral-object", "provider": "mistral",
             "model": "{'id': 'codestral-2508', 'name': 'Codestral'}", "enabled": True},
            {"id": "openrouter-object", "provider": "openrouter",
             "model": {"id": "aion-labs/aion-2.0", "name": "Aion-2.0"}, "enabled": True},
        ]
        routes.ensure_routes(s)
        by_id = {route["id"]: route["model"] for route in s["routes"]}
        self.assertEqual(by_id["mistral-object"], "codestral-2508")
        self.assertEqual(by_id["openrouter-object"], "aion-labs/aion-2.0")

    def test_update_route_normalizes_model_object(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        routes.update_route(s, "mistral", model={"id": "mistral-small-latest", "name": "Mistral Small"})
        self.assertEqual(routes.find_route(s, "mistral")["model"], "mistral-small-latest")

    def test_delete_route_keeps_provider_and_key(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        routes.remove_route(s, "groq")
        self.assertFalse(routes.find_route(s, "groq"))
        self.assertEqual(s["providers"]["groq"]["api_key"], f"{CANARY}-groq")
        with self.assertRaises(KeyError):
            routes.remove_route(s, "groq")

    def test_add_route_refuses_case_insensitive_duplicate_model_ids(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        first = routes.add_route(s, "groq", "Example-Model")
        with self.assertRaises(ValueError):
            routes.add_route(s, "groq", "example-model")
        matching = [
            route for route in routes.get_routes(s)
            if route["provider"] == "groq" and route["model"].casefold() == "example-model"
        ]
        self.assertEqual([route["id"] for route in matching], [first["id"]])

    def test_removing_last_route_clears_default_manual_and_health_note(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        for route in list(routes.get_routes(s)):
            if route["id"] != "groq":
                routes.remove_route(s, route["id"])
        s["manual_route_id"] = "groq"
        s["default_route_id"] = "groq"
        self.capabilities.mapping_set("route_notes", "groq", "stale")
        routes.remove_route(s, "groq", capabilities=self.capabilities)
        self.assertFalse(routes.get_routes(s))
        self.assertEqual(s["manual_route_id"], "")
        self.assertEqual(s["default_route_id"], "")
        self.assertIsNone(self.capabilities.mapping_get("route_notes", "groq"))

    def test_remove_provider_clears_default_and_route_notes(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        pid = routes.add_provider(s, "Temporary", "http://localhost:1234/v1", local=True)
        route = routes.add_route(s, pid, "temporary-model")
        s["manual_route_id"] = route["id"]
        s["default_route_id"] = route["id"]
        self.capabilities.mapping_set("route_notes", route["id"], "stale")
        removed = routes.remove_provider(s, pid, capabilities=self.capabilities)
        self.assertEqual(removed, [route["id"]])
        self.assertEqual(s["manual_route_id"], "")
        self.assertNotEqual(s["default_route_id"], route["id"])
        self.assertIsNone(self.capabilities.mapping_get("route_notes", route["id"]))

    def test_add_edit_remove_custom_provider(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        pid = routes.add_provider(s, "LM Studio", "http://localhost:1234/v1/", local=True)
        self.assertTrue(pid.startswith("custom-lm-studio"))
        self.assertEqual(s["providers"][pid]["base_url"], "http://localhost:1234/v1")
        self.assertEqual(routes.provider_kind(pid, s["providers"][pid]), "local")
        r = routes.add_route(s, pid, "qwen2.5-7b")
        self.assertEqual(r["timeout"], routes.DEFAULT_LOCAL_TIMEOUT)
        pid2 = routes.add_provider(s, "LM Studio", "https://x.example/v1", api_key="abc123456")
        self.assertNotEqual(pid, pid2)                                          # duplicate label gets a unique id
        with self.assertRaises(ValueError):
            routes.add_provider(s, "Bad", "ftp://nope")
        with self.assertRaises(ValueError):
            routes.add_provider(s, "", "http://x")
        with self.assertRaises(ValueError):
            routes.remove_provider(s, "groq")                                     # built-ins cannot be deleted
        routes.set_manual(s, r["id"])
        removed = routes.remove_provider(s, pid)
        self.assertEqual(removed, [r["id"]])
        self.assertNotIn(pid, s["providers"])
        self.assertEqual(s["manual_route_id"], "")

    def test_enabling_ollama_route_also_enables_shared_provider(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        s["providers"]["ollama"]["enabled"] = False

        # Enabling an existing route must not leave its provider-level gate off.
        routes.set_enabled(s, "ollama", True)
        self.assertTrue(s["providers"]["ollama"]["enabled"])

        # Creating an explicitly enabled local route follows the same rule.
        s["providers"]["ollama"]["enabled"] = False
        routes.add_route(s, "ollama", "llama3.2:3b", enabled=True)
        self.assertTrue(s["providers"]["ollama"]["enabled"])

        # Auto-discovery creates OFF routes and must not activate the provider.
        s["providers"]["ollama"]["enabled"] = False
        added = routes.add_ollama_models(s, ["gemma3:4b"])
        self.assertFalse(added[0]["enabled"])
        self.assertFalse(s["providers"]["ollama"]["enabled"])

    def test_disabling_ollama_provider_switches_off_all_local_routes(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        extra = routes.add_route(s, "ollama", "llama3.2:3b", enabled=True)
        self.assertTrue(s["providers"]["ollama"]["enabled"])

        routes.set_provider_enabled(s, "ollama", False)
        self.assertFalse(s["providers"]["ollama"]["enabled"])
        self.assertFalse(any(
            route["provider"] == "ollama" and route["enabled"]
            for route in routes.get_routes(s)
        ))

        routes.set_provider_enabled(s, "ollama", True)
        self.assertTrue(s["providers"]["ollama"]["enabled"])
        self.assertFalse(routes.find_route(s, extra["id"])["enabled"])

    def test_enable_disable_keeps_all_route_settings(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        routes.update_route(s, "groq", timeout=33, cooldown=7)
        routes.set_enabled(s, "groq", False)
        r = routes.find_route(s, "groq")
        self.assertEqual((r["enabled"], r["timeout"], r["cooldown"], r["model"]), (False, 33, 7, "openai/gpt-oss-20b"))
        self.assertEqual(s["providers"]["groq"]["api_key"], f"{CANARY}-groq")

    def test_last_unavailable_route_can_be_disabled(self):
        s = helpers.fresh_settings()
        routes.ensure_routes(s)
        # Simulate the user's only enabled route being a missing local model.
        for route in s["routes"]:
            route["enabled"] = route["provider"] == "ollama"
        s["providers"]["ollama"]["enabled"] = True

        self.assertTrue(routes.disable_route(
            s, "ollama", "مدل روی سیستم نصب نیست", capabilities=self.capabilities
        ))
        self.assertFalse(routes.find_route(s, "ollama")["enabled"])
        self.assertEqual(
            routes.route_note(s, "ollama", capabilities=self.capabilities),
            "مدل روی سیستم نصب نیست",
        )
        self.assertNotIn("route_notes", s)

    def test_reorder_drag_drop_default_and_manual(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        order = routes.reorder(s, ["ollama", "mistral", "groq"])
        self.assertEqual(order[:3], ["ollama", "mistral", "groq"])
        self.assertEqual(set(order), {"cloudflare", "ollama", "groq", "mistral", "openrouter"})   # none lost
        self.assertEqual(s["provider_order"][0], "ollama")                                       # legacy order mirrored
        routes.set_default(s, "openrouter")
        self.assertEqual((s["routes"][0]["id"], s["default_route_id"]), ("openrouter", "openrouter"))
        routes.set_manual(s, "groq")
        self.assertEqual(s["manual_route_id"], "groq")
        routes.set_manual(s, "")
        self.assertEqual(s["manual_route_id"], "")
        with self.assertRaises(KeyError):
            routes.set_manual(s, "nope")
        routes.move_route(s, "groq", 99)
        self.assertEqual(s["routes"][-1]["id"], "groq")

    def test_ollama_scan_adds_missing_models_disabled(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        added = routes.add_ollama_models(s, ["qwen2.5:3b", "llama3.2:3b", "gemma3:4b", "llama3.2:3b"])
        self.assertEqual([r["model"] for r in added], ["llama3.2:3b", "gemma3:4b"])
        self.assertTrue(all(r["provider"] == "ollama" and not r["enabled"] for r in added))

    def test_timeouts_and_cooldown_are_clamped_per_kind(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        routes.update_route(s, "groq", timeout=9999, cooldown=-5)
        routes.update_route(s, "ollama", timeout=1)
        self.assertEqual(routes.find_route(s, "groq")["timeout"], routes.CLOUD_TIMEOUT[1])
        self.assertEqual(routes.find_route(s, "groq")["cooldown"], 0)
        self.assertEqual(routes.find_route(s, "ollama")["timeout"], routes.LOCAL_TIMEOUT[0])

    def test_per_route_ollama_overrides(self):
        s = legacy_settings()
        routes.ensure_routes(s)
        r = routes.add_route(s, "ollama", "llama3.2:3b", num_ctx=2048, num_predict=128)
        self.assertEqual((r["num_ctx"], r["num_predict"]), (2048, 128))
        routes.update_route(s, r["id"], num_ctx=0)
        self.assertNotIn("num_ctx", routes.find_route(s, r["id"]))


class RoutePersistenceTests(unittest.TestCase):
    def setUp(self):
        d = config.DATA_DIR / "routes_case"
        d.mkdir(exist_ok=True)
        self.path = d / "settings.json"
        if self.path.exists():
            self.path.unlink()
        prot, unprot = helpers.fake_dpapi()
        self.patches = [mock.patch.object(config, "CONFIG_PATH", self.path),
                        mock.patch.object(config, "protect", prot), mock.patch.object(config, "unprotect", unprot)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_fresh_install_gets_routes_and_old_file_is_migrated_on_load(self):
        s = config.load_settings()
        self.assertEqual([r["id"] for r in s["routes"]], ["groq", "cloudflare", "mistral", "openrouter", "ollama"])
        old = {"model": "qwen2.5:3b", "provider_order": ["ollama", "groq"],
               "providers": {"groq": {"enabled": True, "api_key": "plain-old-key-123", "model": "m1"}}}
        self.path.write_text(json.dumps(old), encoding="utf-8")
        s = config.load_settings()
        self.assertEqual([r["id"] for r in s["routes"]][:2], ["ollama", "groq"])
        self.assertEqual(s["providers"]["groq"]["api_key"], "plain-old-key-123")
        self.assertEqual(routes.find_route(s, "ollama")["model"], "qwen2.5:3b")

    def test_custom_provider_routes_order_and_encrypted_keys_survive_restart(self):
        s = config.load_settings()
        pid = routes.add_provider(s, "Together", "https://api.together.xyz/v1", api_key=f"{CANARY}-together")
        routes.add_route(s, pid, "meta/llama")
        routes.add_route(s, "groq", "openai/gpt-oss-20b")
        routes.reorder(s, [pid + "", "groq-2", "groq"])
        routes.set_manual(s, "groq-2")
        routes.update_route(s, "groq-2", timeout=33, enabled=False)
        config.save_settings(s)
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn(CANARY, raw)                              # custom provider key is encrypted too
        again = config.load_settings()
        self.assertEqual(again["providers"][pid]["api_key"], f"{CANARY}-together")
        self.assertEqual([r["id"] for r in again["routes"]][:3], [r["id"] for r in s["routes"]][:3])
        r = routes.find_route(again, "groq-2")
        self.assertEqual((r["timeout"], r["enabled"]), (33, False))
        self.assertEqual(again["manual_route_id"], "groq-2")

    def test_old_enabled_ollama_route_repairs_disabled_provider_on_load(self):
        s = config.load_settings()
        routes.update_route(s, "ollama", enabled=True)
        # Recreate the exact inconsistent state written by old versions:
        # route on, but Ollama provider-level switch off.
        s["providers"]["ollama"]["enabled"] = False
        config.save_settings(s)

        again = config.load_settings()
        self.assertTrue(again["providers"]["ollama"]["enabled"])
        self.assertTrue(routes.find_route(again, "ollama")["enabled"])
        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(persisted["providers"]["ollama"]["enabled"])

    def test_old_ollama_2048_context_is_migrated_to_8192_on_load(self):
        s = config.load_settings()
        s["providers"]["ollama"]["num_ctx"] = 2048
        routes.update_route(s, "ollama", num_ctx=2048)
        config.save_settings(s)

        again = config.load_settings()
        self.assertEqual(again["providers"]["ollama"]["num_ctx"], 8192)
        self.assertEqual(routes.find_route(again, "ollama")["num_ctx"], 8192)
        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["providers"]["ollama"]["num_ctx"], 8192)

    def test_orphan_routes_of_missing_provider_are_dropped_on_load(self):
        s = config.load_settings()
        s["routes"].append({"id": "ghost", "provider": "custom-gone", "model": "m", "enabled": True})
        config.save_settings(s)
        again = config.load_settings()
        self.assertFalse(routes.find_route(again, "ghost"))


if __name__ == "__main__":
    unittest.main()
