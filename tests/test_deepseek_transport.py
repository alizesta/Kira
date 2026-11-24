from __future__ import annotations

import tempfile
import unittest

from kira.core.interfaces.reverse_transport import TransportState
from kira.reverse_api import TRANSPORTS, DeepSeekBrowserTransport
from kira.reverse_api.deepseek_session import DeepSeekSessionStore


class DeepSeekTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DeepSeekSessionStore(
            self.temp.name,
            encrypt=lambda value: __import__("base64").b64encode(value.encode("utf-8")).decode("ascii"),
            decrypt=lambda value: __import__("base64").b64decode(value.encode("ascii")).decode("utf-8"),
        )
        self.transport = DeepSeekBrowserTransport(store=self.store)

    def test_builtin_transport_is_registered_and_shared(self):
        factory = TRANSPORTS.resolve("deepseek")
        self.assertIsNotNone(factory)
        self.assertIs(factory({}), factory({}))

    def test_shared_transport_applies_route_configuration(self):
        configured = self.transport.configure({"timeout": 17})
        self.assertIs(configured, self.transport)
        self.assertEqual(self.transport.config["timeout"], 17)

    def test_route_timeout_is_respected_in_milliseconds(self):
        self.transport.configure({"timeout": 5})
        self.assertEqual(self.transport._timeout_ms(), 5_000)
        self.transport.configure({"timeout": 17})
        self.assertEqual(self.transport._timeout_ms(), 17_000)

    def test_status_requires_saved_session(self):
        status = self.transport.status()
        self.assertEqual(status.state, TransportState.DISCONNECTED)

    def test_status_does_not_launch_or_send_a_request(self):
        self.store.save({"cookies": [{"name": "sid", "value": "x"}], "origins": []})
        status = self.transport.status()
        self.assertIn(status.state, {TransportState.CONNECTED, TransportState.UNAVAILABLE})

    def test_stream_diff_helpers_do_not_replay_rewritten_prefixes(self):
        self.assertEqual(self.transport._common_prefix_length("answer part A", "answer part B"), 12)
        self.assertEqual(self.transport._common_prefix_length("same", "same plus"), 4)

    def test_refreshed_session_merges_rotated_session_storage(self):
        state = {
            "cookies": [{"name": "rotated", "value": "new-cookie"}],
            "origins": [{"origin": "https://chat.deepseek.com", "localStorage": []}],
            "sessionStorageByOrigin": {
                "https://other.example": [{"name": "keep", "value": "1"}],
                "https://chat.deepseek.com": [{"name": "old", "value": "2"}],
            },
        }
        merged = self.transport._merge_session_storage(
            state,
            {"origin": "https://chat.deepseek.com", "entries": [{"name": "new", "value": "3"}]},
        )
        self.assertEqual(merged["cookies"][0]["value"], "new-cookie")
        self.assertEqual(merged["sessionStorageByOrigin"]["https://other.example"], [{"name": "keep", "value": "1"}])
        self.assertEqual(merged["sessionStorageByOrigin"]["https://chat.deepseek.com"], [{"name": "new", "value": "3"}])

    def test_empty_refreshed_session_storage_removes_stale_origin_entries(self):
        state = {"sessionStorageByOrigin": {"https://chat.deepseek.com": [{"name": "old", "value": "2"}]}}
        merged = self.transport._merge_session_storage(
            state, {"origin": "https://chat.deepseek.com", "entries": []}
        )
        self.assertNotIn("sessionStorageByOrigin", merged)

    def test_session_storage_is_injected_for_matching_origin_only(self):
        state = {
            "sessionStorageByOrigin": {
                "https://chat.deepseek.com": [{"name": "access_token", "value": "secret"}]
            }
        }
        script = self.transport._session_init_script(state)
        self.assertIn("location.origin", script)
        self.assertIn("sessionStorage.setItem", script)
        self.assertIn("chat.deepseek.com", script)
        self.assertIn("access_token", script)

    def test_abort_sets_cancellation_flag(self):
        self.transport.abort()
        self.assertTrue(self.transport._cancel.is_set())


if __name__ == "__main__":
    unittest.main()
