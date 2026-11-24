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
            encrypt=lambda value: "encrypted:" + value,
            decrypt=lambda value: value.removeprefix("encrypted:"),
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

    def test_status_requires_saved_session(self):
        status = self.transport.status()
        self.assertEqual(status.state, TransportState.DISCONNECTED)

    def test_status_does_not_launch_or_send_a_request(self):
        self.store.save({"cookies": [{"name": "sid", "value": "x"}], "origins": []})
        status = self.transport.status()
        self.assertIn(status.state, {TransportState.CONNECTED, TransportState.UNAVAILABLE})

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