from __future__ import annotations

import tempfile
import unittest

from kira.reverse_api.deepseek_session import DeepSeekSessionError, DeepSeekSessionStore


class DeepSeekSessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DeepSeekSessionStore(
            self.temp.name,
            encrypt=lambda value: "encrypted:" + value,
            decrypt=lambda value: value.removeprefix("encrypted:"),
        )

    def test_session_is_encrypted_and_round_trips(self):
        state = {
            "cookies": [{"name": "session_token", "value": "secret-cookie"}],
            "origins": [],
        }
        self.store.save(state)
        saved = self.store.path.read_text(encoding="utf-8")
        self.assertTrue(saved.startswith("encrypted:"))
        self.assertNotIn("secret-cookie", saved)
        self.assertEqual(self.store.load(), state)
        self.assertTrue(self.store.has_session())

    def test_rejects_empty_or_invalid_session_state(self):
        with self.assertRaises(DeepSeekSessionError):
            self.store.save({})
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store.path.write_text("encrypted:not-json", encoding="utf-8")
        with self.assertRaises(DeepSeekSessionError):
            self.store.load()

    def test_session_storage_only_state_is_valid(self):
        state = {
            "cookies": [],
            "origins": [],
            "sessionStorageByOrigin": {
                "https://chat.deepseek.com": [{"name": "token", "value": "private"}]
            },
        }
        self.store.save(state)
        self.assertEqual(self.store.load(), state)
        self.assertNotIn("private", self.store.path.read_text(encoding="utf-8"))

    def test_missing_session_is_not_an_error(self):        self.assertIsNone(self.store.load())
        self.assertFalse(self.store.has_session())

    def test_clear_removes_only_session_file(self):
        self.store.save({"cookies": [{"name": "sid", "value": "x"}], "origins": []})
        unrelated = self.store.path.parent / "keep.txt"
        unrelated.write_text("keep", encoding="utf-8")
        self.assertTrue(self.store.clear())
        self.assertFalse(self.store.path.exists())
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
