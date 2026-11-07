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
        self.assertEqual(s["providers"]["ollama"]["num_ctx"], 4096)   # new key got its default
        self.assertEqual(s["providers"]["ollama"]["keep_alive"], "2m")
        self.assertEqual(s["provider_order"], ["cloudflare", "groq", "mistral", "openrouter", "ollama"])
        self.assertEqual(config.VERSION, "1 stable")

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

    def test_fresh_defaults(self):
        s = helpers.fresh_settings()
        self.assertEqual(s["model"], "qwen3.5:4b")
        self.assertEqual(s["providers"]["ollama"]["num_ctx"], 4096)
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
