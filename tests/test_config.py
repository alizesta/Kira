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
            "settings_version": 2, "model": "qwen3.5:4b",
            "role_route_models": {"surface": ["qwen3.5:4b"]},
        })
        self.assertEqual(from_v2["model"], config.LOCAL_UNCENSORED_MODEL)
        self.assertEqual(
            from_v2["role_route_models"]["surface"], [config.LOCAL_UNCENSORED_MODEL]
        )

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
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{this is not json")   # original untouched
        self.assertTrue(list(self.tmp.glob("settings.json.corrupt-*")))
        self.assertTrue(config.LOAD_WARNINGS)

    def test_provider_order_normalisation(self):
        self.assertEqual(config.normalize_provider_order(["mistral", "bogus", "mistral", "ollama", "groq"]),
                         ["mistral", "ollama", "groq", "cloudflare", "openrouter"])
        self.assertEqual(config.normalize_provider_order(None)[-1], "ollama")

    def test_legacy_local_model_migration_also_updates_role_allowlist(self):
        from kira.hybrid_ai import HybridRouter

        legacy = {
            "model": "qwen3.5:4b",
            "providers": {"ollama": {"enabled": True, "model": "qwen3.5:4b"}},
            "routes": [{"id": "ollama", "provider": "ollama", "model": "qwen3.5:4b", "enabled": True}],
            "role_provider_allowlist": {
                "surface": ["ollama"], "deep": ["google"], "reflection": ["google"], "memory": ["ollama"]
            },
            "role_route_models": {"surface": ["qwen3.5:4b"]},
        }
        self.path.write_text(json.dumps(legacy), encoding="utf-8")

        settings = config.load_settings()

        expected = config.LOCAL_UNCENSORED_MODEL
        self.assertEqual(settings["model"], expected)
        self.assertEqual(settings["routes"][0]["model"], expected)
        self.assertEqual(settings["role_route_models"]["surface"], [expected])
        self.assertTrue(any("Abliterated" in warning for warning in config.LOAD_WARNINGS))

        router = HybridRouter(settings)
        with router.role_scope("surface"):
            candidates = router._candidates()
        self.assertEqual([route["id"] for route in candidates], ["ollama"])
        self.assertTrue(all(route["provider"] == "ollama" for route in candidates))

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["role_route_models"]["surface"], [expected])

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
