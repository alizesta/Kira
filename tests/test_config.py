import json
import os
import unittest
from unittest import mock

from tests import helpers
from tests.helpers import CANARY
from kira import config, secret_store


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = config.DATA_DIR / "cfg_case"
        self.tmp.mkdir(exist_ok=True)
        self.path = self.tmp / "settings.json"
        if self.path.exists():
            self.path.unlink()
        self.p = mock.patch.object(config, "CONFIG_PATH", self.path)
        self.p.start()
        prot, unprot = helpers.fake_dpapi()
        self.p1 = mock.patch.object(config, "protect", prot)
        self.p2 = mock.patch.object(config, "unprotect", unprot)
        self.p1.start(); self.p2.start()

    def tearDown(self):
        self.p.stop(); self.p1.stop(); self.p2.stop()

    def test_ui_language_defaults_to_english_and_preserves_saved_persian(self):
        self.path.write_text(json.dumps({"assistant_name": "Kira"}), encoding="utf-8")
        self.assertEqual(config.load_settings()["ui_lang"], "en")

        self.path.write_text(json.dumps({"ui_lang": "fa"}), encoding="utf-8")
        self.assertEqual(config.load_settings()["ui_lang"], "fa")

    # 1) settings written by an older version still load; new keys appear, user values survive
    def test_01_old_settings_load(self):
        old = {"model": "qwen2.5:3b", "assistant_name": "Mina", "ollama_url": "http://localhost:11434",
               "provider_order": ["cloudflare", "groq"],
               "providers": {"groq": {"enabled": True, "api_key": "plain-old-key-123", "model": "openai/gpt-oss-120b"},
                             "ollama": {"enabled": True, "base_url": "http://localhost:11434", "model": "qwen2.5:3b"}}}
        self.path.write_text(json.dumps(old), encoding="utf-8")
        s = config.load_settings()
        self.assertEqual(s["model"], "qwen2.5:3b")            # user's model is NOT overwritten
        self.assertEqual(s["assistant_name"], "Mina")
        self.assertEqual(s["providers"]["groq"]["api_key"], "plain-old-key-123")
        self.assertEqual(s["providers"]["ollama"]["num_ctx"], 6144)   # new key got its default
        self.assertEqual(s["providers"]["ollama"]["keep_alive"], "2m")
        self.assertEqual(s["provider_order"], ["cloudflare", "groq", "mistral", "openrouter", "ollama"])
        self.assertEqual(s["settings_version"], config.SETTINGS_SCHEMA_VERSION)

    def test_01a_unversioned_explicit_local_voice_choice_is_preserved(self):
        self.path.write_text(json.dumps({"voice_engine": "local"}), encoding="utf-8")
        settings = config.load_settings()
        self.assertEqual(settings["voice_engine"], "local")
        self.assertEqual(settings["settings_version"], config.SETTINGS_SCHEMA_VERSION)

    def test_each_supported_settings_version_runs_forward_migrations(self):
        legacy_voice = config._migrate_settings({
            "voice_engine": "local", "web_engine": "retired",
            "providers": {"groq": {"model": "llama-3.3-70b-versatile"}},
        })
        self.assertEqual(legacy_voice["settings_version"], config.SETTINGS_SCHEMA_VERSION)
        self.assertEqual(legacy_voice["voice_engine"], "local")
        self.assertNotIn("web_engine", legacy_voice)
        self.assertEqual(
            legacy_voice["providers"]["groq"]["model"], "openai/gpt-oss-120b"
        )

        from_v1 = config._migrate_settings({
            "settings_version": 1,
            "providers": {"groq": {"model": "llama-3.1-8b-instant"}},
        })
        self.assertEqual(from_v1["providers"]["groq"]["model"], "openai/gpt-oss-20b")

        from_v2 = config._migrate_settings({
            "settings_version": 2,
            "model": "qwen3.5:4b",
            "providers": {"ollama": {"enabled": False, "model": "qwen3.5:4b"}},
            "routes": [{
                "id": "ollama", "provider": "ollama",
                "model": "qwen3.5:4b", "enabled": True,
            }],
            "role_route_models": {"surface": ["qwen3.5:4b"]},
        })
        self.assertEqual(from_v2["model"], "qwen3.5:4b")
        self.assertEqual(
            from_v2["providers"]["ollama"]["model"], "qwen3.5:4b"
        )
        self.assertEqual(
            from_v2["role_route_models"]["surface"], ["qwen3.5:4b"]
        )
        self.assertTrue(from_v2["providers"]["ollama"]["enabled"])

    def test_current_version_route_repair_is_persisted(self):
        self.path.write_text(
            json.dumps({
                "settings_version": config.SETTINGS_SCHEMA_VERSION,
                "routes": [{
                    "id": "ollama", "provider": "ollama", "model": "custom-model",
                    "enabled": True, "num_ctx": "broken",
                }]
            }),
            encoding="utf-8",
        )
        config.load_settings()
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        route = next(item for item in saved["routes"] if item["id"] == "ollama")
        self.assertNotIn("num_ctx", route)

    def test_v3_migration_removes_runtime_observations_but_preserves_user_values(self):
        source = {
            "settings_version": 3,
            "assistant_name": "My Kira",
            "voice_engine": "local",
            "providers": {"groq": {"api_key": "preserve-me"}},
            "api_registry": {"groq": {"status": "valid"}},
            "model_catalog_refreshed_at": 12345,
            "model_tests": {"groq::model": {"ok": True}},
            "user_extension": {"enabled": True},
        }
        migrated = config._migrate_settings(source)
        self.assertEqual(migrated["settings_version"], config.SETTINGS_SCHEMA_VERSION)
        self.assertEqual(migrated["assistant_name"], "My Kira")
        self.assertEqual(migrated["voice_engine"], "local")
        self.assertEqual(migrated["providers"]["groq"]["api_key"], "preserve-me")
        self.assertEqual(migrated["user_extension"], {"enabled": True})
        for runtime_key in ("api_registry", "model_catalog_refreshed_at", "model_tests"):
            self.assertNotIn(runtime_key, migrated)
        self.assertEqual(source["api_registry"]["groq"]["status"], "valid")

    def test_save_settings_validates_nested_values_without_mutating_caller(self):
        settings = helpers.fresh_settings()
        settings["providers"]["ollama"]["num_ctx"] = "invalid"
        settings["temperature"] = 99
        config.save_settings(settings)

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["providers"]["ollama"]["num_ctx"], config.DEFAULTS["providers"]["ollama"]["num_ctx"])
        self.assertEqual(saved["temperature"], config.DEFAULTS["temperature"])
        self.assertEqual(settings["providers"]["ollama"]["num_ctx"], "invalid")
        self.assertEqual(settings["temperature"], 99)

    def test_save_settings_never_persists_detected_capabilities(self):
        settings = helpers.fresh_settings()
        settings.update({
            "api_registry": {"groq": {"status": "valid"}},
            "model_catalog_refreshed_at": 12345,
            "model_tests": {"groq::model": {"ok": True}},
        })
        config.save_settings(settings)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("api_registry", saved)
        self.assertNotIn("model_catalog_refreshed_at", saved)
        self.assertNotIn("model_tests", saved)

    def test_migration_warnings_are_explicit_and_idempotent(self):
        source = {
            "providers": {"groq": {"model": "llama-3.3-70b-versatile"}},
            "voice_engine": "local",
        }
        warnings = []
        once = config._migrate_settings(source, warnings=warnings)
        first_warnings = list(warnings)
        twice = config._migrate_settings(once, warnings=warnings)

        self.assertEqual(once, twice)
        self.assertEqual(warnings, first_warnings)
        self.assertEqual(source["providers"]["groq"]["model"], "llama-3.3-70b-versatile")
        self.assertEqual(source["voice_engine"], "local")

    def test_old_voice_api_key_and_unknown_settings_survive_full_load_and_save(self):
        selected_model = "qwen3.5:4b"
        legacy = {
            "voice_engine": "local",
            "local_voice_asr_backend": "shenava",
            "local_voice_asr_model": "custom/shenava-model",
            "voice_volume": 0.72,
            "mic_gain": 145,
            "model": selected_model,
            "providers": {
                "groq": {"enabled": True, "api_key": f"{CANARY}-legacy", "model": "openai/gpt-oss-120b"},
                "ollama": {"enabled": True, "model": selected_model},
            },
            "user_extension": {"enabled": True, "label": "keep"},
        }
        self.path.write_text(json.dumps(legacy), encoding="utf-8")
        settings = config.load_settings()

        self.assertEqual(settings["voice_engine"], "local")
        self.assertEqual(settings["local_voice_asr_backend"], "shenava")
        self.assertEqual(settings["local_voice_asr_model"], "custom/shenava-model")
        self.assertEqual(settings["voice_volume"], 0.72)
        self.assertEqual(settings["mic_gain"], 145)
        self.assertEqual(settings["model"], selected_model)
        self.assertEqual(settings["providers"]["ollama"]["model"], selected_model)
        self.assertEqual(settings["providers"]["groq"]["api_key"], f"{CANARY}-legacy")
        self.assertEqual(settings["user_extension"], {"enabled": True, "label": "keep"})

        config.save_settings(settings)
        restored = config.load_settings()
        self.assertEqual(restored["voice_engine"], "local")
        self.assertEqual(restored["local_voice_asr_model"], "custom/shenava-model")
        self.assertEqual(restored["providers"]["groq"]["api_key"], f"{CANARY}-legacy")
        self.assertEqual(restored["user_extension"], {"enabled": True, "label": "keep"})

    def test_voice_page_uses_canonical_schema_defaults_and_ranges(self):
        from kira.settings_schema import (
            DEFAULTS as SCHEMA_DEFAULTS,
            SETTING_RANGES,
            SETTING_CHOICES,
        )
        from kira.ui.pages.voice_page import (
            SETTINGS_DEFAULTS,
            SETTINGS_RANGES,
            SETTINGS_CHOICES,
        )

        self.assertIs(SETTINGS_DEFAULTS, SCHEMA_DEFAULTS)
        self.assertIs(SETTINGS_RANGES, SETTING_RANGES)
        self.assertIs(SETTINGS_CHOICES, SETTING_CHOICES)
        self.assertEqual(SETTING_RANGES["wake_timeout"], (5, 120))
        self.assertEqual(SETTING_RANGES["voice_rate"], (-30, 30))
        self.assertEqual(SETTINGS_DEFAULTS["wake_timeout"], 25)
        self.assertEqual(SETTING_CHOICES["stt_language"], frozenset({"fa", "en", "auto"}))

    def test_settings_migration_is_idempotent(self):
        original = {"voice_engine": "local", "providers": {"ollama": {"num_ctx": 8192}}}
        once = config._migrate_settings(original)
        twice = config._migrate_settings(once)
        self.assertEqual(once, twice)
        self.assertEqual(original["voice_engine"], "local")
        self.assertEqual(once["providers"]["ollama"]["num_ctx"], 8192)

    def test_user_num_ctx_values_survive_load_without_migration(self):
        for value in (2048, 8192):
            self.path.write_text(json.dumps({"providers": {"ollama": {"num_ctx": value}}}), encoding="utf-8")
            self.assertEqual(config.load_settings()["providers"]["ollama"]["num_ctx"], value)

    def test_invalid_setting_choices_and_ranges_are_repaired(self):
        self.path.write_text(
            json.dumps({"voice_engine": "not-an-engine", "temperature": 99}),
            encoding="utf-8",
        )
        settings = config.load_settings()
        self.assertEqual(settings["voice_engine"], config.DEFAULTS["voice_engine"])
        self.assertEqual(settings["temperature"], config.DEFAULTS["temperature"])
        warning = " ".join(config.LOAD_WARNINGS)
        self.assertIn("voice_engine", warning)
        self.assertIn("temperature", warning)

    def test_invalid_known_setting_is_repaired_from_schema_default(self):
        self.path.write_text(json.dumps({"temperature": "hot"}), encoding="utf-8")
        settings = config.load_settings()
        self.assertEqual(settings["temperature"], config.DEFAULTS["temperature"])
        self.assertTrue(any("temperature" in warning for warning in config.LOAD_WARNINGS))

    def test_01aa_intentional_local_voice_selection_survives_migration(self):
        self.path.write_text(
            json.dumps({"voice_engine": "local", "voice_engine_migrated": True}),
            encoding="utf-8",
        )
        settings = config.load_settings()
        self.assertEqual(settings["voice_engine"], "local")

    def test_01b_retired_groq_models_migrate(self):
        for old, new in (("llama-3.3-70b-versatile", "openai/gpt-oss-120b"), ("llama-3.1-8b-instant", "openai/gpt-oss-20b")):
            self.path.write_text(json.dumps({"providers": {"groq": {"model": old}}}), encoding="utf-8")
            s = config.load_settings()
            self.assertEqual(s["providers"]["groq"]["model"], new)
            self.assertTrue(config.LOAD_WARNINGS)
        self.path.write_text(json.dumps({"providers": {"groq": {"model": "openai/gpt-oss-20b"}}}), encoding="utf-8")
        self.assertEqual(config.load_settings()["providers"]["groq"]["model"], "openai/gpt-oss-20b")

    # 2) save + reload round trip ("after closing and reopening the app")
    def test_02_save_and_restore(self):
        s = helpers.fresh_settings()
        s["assistant_name"] = "Rin"
        s["providers"]["ollama"]["num_ctx"] = 2048
        s["provider_order"] = ["openrouter", "groq", "cloudflare", "mistral", "ollama"]
        config.save_settings(s)
        again = config.load_settings()
        self.assertEqual(again["assistant_name"], "Rin")
        self.assertEqual(again["providers"]["ollama"]["num_ctx"], 2048)
        self.assertEqual(again["provider_order"][0], "openrouter")
        self.assertEqual(again["provider_order"][-1], "ollama")

    # 3) key encryption path: not plaintext on disk, decrypts back
    def test_03_keys_encrypted_on_disk_and_decrypted(self):
        s = helpers.enable(helpers.fresh_settings(), "groq", "cloudflare")
        config.save_settings(s)
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn(CANARY, raw)
        self.assertIn("dpapi:", raw)
        again = config.load_settings()
        self.assertEqual(again["providers"]["groq"]["api_key"], f"{CANARY}-groq")
        self.assertEqual(again["providers"]["cloudflare"]["api_key"], f"{CANARY}-cloudflare")
        self.assertFalse(list(config.DATA_DIR.glob("**/*.tmp")) and self.path.with_suffix(".json.tmp").exists())

    @unittest.skipUnless(os.name == "nt", "real Windows DPAPI only exists on Windows (run this on the PC)")
    def test_03b_real_dpapi_roundtrip_windows(self):
        blob = secret_store.protect("my-secret-value-123")
        self.assertTrue(blob.startswith("dpapi:"))
        self.assertNotIn("my-secret-value-123", blob)
        self.assertEqual(secret_store.unprotect(blob), "my-secret-value-123")

    def test_03c_undecryptable_key_does_not_crash(self):
        data = helpers.fresh_settings()
        data["providers"]["groq"]["api_key"] = "dpapi:AAAA"
        data["providers"]["groq"]["enabled"] = True
        self.path.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch.object(config, "unprotect", side_effect=OSError("decrypt failed")):
            s = config.load_settings()
        self.assertEqual(s["providers"]["groq"]["api_key"], "")
        self.assertTrue(any("groq" in w for w in config.LOAD_WARNINGS))

    def test_03d_corrupt_file_is_backed_up_not_lost(self):
        self.path.write_text("{this is not json", encoding="utf-8")
        s = config.load_settings()
        self.assertEqual(s["model"], config.DEFAULTS["model"])
        self.assertEqual(s["settings_version"], config.SETTINGS_SCHEMA_VERSION)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{this is not json")   # original untouched
        self.assertTrue(list(self.tmp.glob("settings.json.corrupt-*")))
        self.assertTrue(config.LOAD_WARNINGS)

    def test_provider_order_normalisation(self):
        self.assertEqual(config.normalize_provider_order(["mistral", "bogus", "mistral", "ollama", "groq"]),
                         ["mistral", "ollama", "groq", "cloudflare", "openrouter"])
        self.assertEqual(config.normalize_provider_order(None)[-1], "ollama")

    def test_legacy_local_model_selection_is_preserved_across_migrations(self):
        from kira.hybrid_ai import HybridRouter

        selected_model = "qwen3.5:4b"
        legacy = {
            "model": selected_model,
            "providers": {"ollama": {"enabled": True, "model": selected_model}},
            "routes": [{"id": "ollama", "provider": "ollama", "model": selected_model, "enabled": True}],
            "role_provider_allowlist": {
                "surface": ["ollama"], "deep": ["google"], "reflection": ["google"], "memory": ["ollama"]
            },
            "role_route_models": {"surface": [selected_model]},
        }
        self.path.write_text(json.dumps(legacy), encoding="utf-8")

        settings = config.load_settings()

        self.assertEqual(settings["model"], selected_model)
        self.assertEqual(settings["providers"]["ollama"]["model"], selected_model)
        route = next(route for route in settings["routes"] if route["id"] == "ollama")
        self.assertEqual(route["model"], selected_model)
        self.assertEqual(settings["role_route_models"]["surface"], [selected_model])
        self.assertFalse(any("Abliterated" in warning for warning in config.LOAD_WARNINGS))

        router = HybridRouter(settings)
        with router.role_scope("surface"):
            candidates = router._candidates()
        self.assertEqual([route["id"] for route in candidates], ["ollama"])
        self.assertTrue(all(route["model"] == selected_model for route in candidates))

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["role_route_models"]["surface"], [selected_model])

    def test_partial_nested_settings_restore_missing_schema_fields(self):
        self.path.write_text(
            json.dumps({"appearance": {"brightness": 75}}),
            encoding="utf-8",
        )
        settings = config.load_settings()
        self.assertEqual(settings["appearance"]["brightness"], 75)
        self.assertEqual(
            settings["appearance"]["background_color"],
            config.DEFAULTS["appearance"]["background_color"],
        )
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIn("glow", saved["appearance"])

    def test_nested_provider_values_are_validated_and_repaired_on_disk(self):
        self.path.write_text(
            json.dumps({"providers": {"ollama": {"num_ctx": "huge", "keep_alive": []}}}),
            encoding="utf-8",
        )
        settings = config.load_settings()
        defaults = config.DEFAULTS["providers"]["ollama"]
        self.assertEqual(settings["providers"]["ollama"]["num_ctx"], defaults["num_ctx"])
        self.assertEqual(settings["providers"]["ollama"]["keep_alive"], defaults["keep_alive"])
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["providers"]["ollama"]["num_ctx"], defaults["num_ctx"])
        self.assertTrue(any("providers.ollama.num_ctx" in warning for warning in config.LOAD_WARNINGS))

    def test_invalid_route_overrides_are_repaired_before_route_normalization(self):
        self.path.write_text(
            json.dumps({
                "routes": [{
                    "id": "ollama", "provider": "ollama", "model": "custom-model",
                    "enabled": True, "num_ctx": "not-a-number", "num_predict": -4,
                }]
            }),
            encoding="utf-8",
        )
        settings = config.load_settings()
        route = next(item for item in settings["routes"] if item["id"] == "ollama")
        self.assertNotIn("num_ctx", route)
        self.assertNotIn("num_predict", route)
        self.assertTrue(any("routes[0].num_ctx" in warning for warning in config.LOAD_WARNINGS))

    def test_route_and_provider_defaults_are_derived_from_canonical_schema(self):
        from kira import api_manager, ollama_client, routes
        from kira.settings_schema import DEFAULTS as SCHEMA_DEFAULTS, PROVIDER_DEFAULT_MODELS

        self.assertIs(config.DEFAULTS, SCHEMA_DEFAULTS)
        self.assertEqual(routes.DEFAULT_ORDER, SCHEMA_DEFAULTS["provider_order"])
        self.assertEqual(routes.BUILTIN["ollama"]["model"], SCHEMA_DEFAULTS["providers"]["ollama"]["model"])
        self.assertEqual(routes.DEFAULT_CLOUD_TIMEOUT, SCHEMA_DEFAULTS["providers"]["groq"]["timeout"])
        self.assertEqual(routes.DEFAULT_LOCAL_TIMEOUT, SCHEMA_DEFAULTS["providers"]["ollama"]["timeout"])
        self.assertEqual(routes.DEFAULT_COOLDOWN, SCHEMA_DEFAULTS["route_cooldown"])
        for provider, preferred_models in PROVIDER_DEFAULT_MODELS.items():
            self.assertEqual(api_manager.SERVICES[provider]["default_models"], preferred_models)
        ollama_defaults = SCHEMA_DEFAULTS["providers"]["ollama"]
        self.assertEqual(ollama_client.DEFAULT_NUM_CTX, ollama_defaults["num_ctx"])
        self.assertEqual(ollama_client.DEFAULT_KEEP_ALIVE, ollama_defaults["keep_alive"])
        self.assertEqual(ollama_client.DEFAULT_NUM_PREDICT, ollama_defaults["num_predict"])

    def test_fresh_defaults(self):
        s = helpers.fresh_settings()
        self.assertEqual(s["model"], config.LOCAL_UNCENSORED_MODEL)
        self.assertEqual(s["providers"]["ollama"]["num_ctx"], config.DEFAULTS["providers"]["ollama"]["num_ctx"])
        for n in ("groq", "cloudflare", "mistral", "openrouter"):
            self.assertFalse(s["providers"][n]["enabled"])
            self.assertEqual(s["providers"][n]["api_key"], "")


if __name__ == "__main__":
    unittest.main()


class TrayDefaultsTests(unittest.TestCase):
    def test_tray_defaults(self):
        from kira import config
        self.assertTrue(config.DEFAULTS["minimize_to_tray"])
        self.assertFalse(config.DEFAULTS["close_to_tray"])
