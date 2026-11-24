from __future__ import annotations

import base64
import tempfile
import unittest

from kira.reverse_api.deepseek_session import (
    DEEPSEEK_LOGIN_URL,
    DeepSeekSessionError,
    DeepSeekBrowserLogin,
    DeepSeekSessionStore,
    _chrome_candidate_paths,
)


class DeepSeekSessionStoreTests(unittest.TestCase):
    def test_login_uses_explicit_sign_in_page(self):
        self.assertEqual(DEEPSEEK_LOGIN_URL, "https://chat.deepseek.com/sign_in")

    def test_interactive_login_uses_a_temporary_chrome_profile(self):
        from pathlib import Path

        source = Path(__file__).resolve().parents[1] / "kira" / "reverse_api" / "deepseek_session.py"
        code = source.read_text(encoding="utf-8")
        self.assertIn('tempfile.TemporaryDirectory(prefix="kira-deepseek-login-")', code)
        self.assertIn('f"--user-data-dir={profile_dir}"', code)

    def test_standard_windows_chrome_locations_are_checked(self):
        paths = _chrome_candidate_paths({
            "LOCALAPPDATA": r"C:\Users\Kira\AppData\Local",
            "PROGRAMFILES": r"C:\Program Files",
            "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
        })
        self.assertEqual(len(paths), 3)
        self.assertEqual(paths[0].parts[-4:], ("Google", "Chrome", "Application", "chrome.exe"))

    def test_debug_port_is_specific_and_loopback_only(self):
        port = DeepSeekBrowserLogin._reserve_debug_port()
        self.assertGreater(port, 0)
        self.assertLessEqual(port, 65535)

    def test_interactive_login_attaches_to_normal_chrome_instead_of_launching_playwright_chromium(self):
        from pathlib import Path

        source = Path(__file__).resolve().parents[1] / "kira" / "reverse_api" / "deepseek_session.py"
        code = source.read_text(encoding="utf-8")
        self.assertIn('f"--remote-debugging-port={port}"', code)
        self.assertIn('"--remote-debugging-address=127.0.0.1"', code)
        self.assertNotIn('"--remote-debugging-port=0"', code)
        self.assertIn("connect_over_cdp(endpoint", code)
        self.assertNotIn('chromium.launch(channel="chrome"', code)
        self.assertNotIn("headless=False", code)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DeepSeekSessionStore(
            self.temp.name,
            encrypt=lambda value: base64.b64encode(value.encode("utf-8")).decode("ascii"),
            decrypt=lambda value: base64.b64decode(value.encode("ascii")).decode("utf-8"),
        )

    def test_session_is_encrypted_and_round_trips(self):
        state = {
            "cookies": [{"name": "session_token", "value": "secret-cookie"}],
            "origins": [],
        }
        self.store.save(state)
        saved = self.store.path.read_text(encoding="utf-8")
        self.assertNotEqual(saved, "")
        self.assertNotIn("session_token", saved)
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

    def test_indexed_db_storage_state_is_preserved(self):
        state = {
            "cookies": [{"name": "sid", "value": "secret"}],
            "origins": [],
            "indexedDB": [{
                "origin": "https://chat.deepseek.com",
                "databases": [{"name": "auth-db", "version": 1, "stores": []}],
            }],
        }
        self.store.save(state)
        self.assertEqual(self.store.load()["indexedDB"], state["indexedDB"])

    def test_conversation_url_is_encrypted_and_survives_session_refresh(self):
        self.store.save({"cookies": [{"name": "sid", "value": "secret"}], "origins": []})
        url = "https://chat.deepseek.com/a/chat/s/private-chat-id"
        self.assertTrue(self.store.set_conversation_url("local-conversation", url))
        self.assertEqual(self.store.get_conversation_url("local-conversation"), url)
        encrypted = self.store.path.read_text(encoding="utf-8")
        self.assertNotIn("private-chat-id", encrypted)

        self.store.save({"cookies": [{"name": "sid", "value": "rotated"}], "origins": []})
        self.assertEqual(self.store.get_conversation_url("local-conversation"), url)

    def test_missing_session_is_not_an_error(self):
        self.assertIsNone(self.store.load())
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
