"""Lifecycle and concurrency regression tests for the optional MCP hub."""
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from kira.mcp.hub import McpHub
from kira.mcp import install
from kira.tools.registry import Tool, ToolRegistry


class McpHubLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.registry = mock.Mock()
        self.registry.unregister_where.return_value = 0
        self.hub = McpHub(self.registry, None, lambda: {})

    def tearDown(self):
        self.hub.shutdown()

    def test_unexpected_startup_failure_closes_client_and_records_error(self):
        class BrokenClient:
            closed = False

            def start(self):
                return None

            def initialize(self, timeout):
                return None

            def list_tools(self, timeout):
                raise TypeError("malformed tools payload")

            def stderr_tail(self):
                return ""

            def close(self):
                self.closed = True

        client = BrokenClient()
        config = {
            "name": "broken",
            "timeout": 3,
            "allow": [],
            "deny": [],
            "levels": {},
            "default_level": 3,
            "max_tools": 10,
            "keywords": [],
        }
        with mock.patch("kira.mcp.hub.make_client", return_value=client):
            self.assertFalse(self.hub._connect("broken", config))

        self.assertTrue(client.closed)
        self.assertNotIn("broken", self.hub._clients)
        self.assertEqual(self.hub.state["broken"]["status"], "error")
        self.assertIn("malformed tools payload", self.hub.state["broken"]["error"])

    def test_partial_optional_registration_is_rolled_back_without_removing_existing_tools(self):
        registry = ToolRegistry()
        existing = Tool("agent_status", "existing tool", lambda _args: "keep", ())
        registry.register(existing)

        with mock.patch("kira.mcp.hub.McpHub.refresh_async"):
            result = install(registry, None, lambda: {})

        self.assertIsNone(result)
        self.assertIs(registry.get("agent_status"), existing)
        self.assertIsNone(registry.get("agent_ask"))
        self.assertIsNone(registry.get("mcp_info"))

    def test_calls_to_one_server_are_serialized_across_threads(self):
        class ConcurrentClient:
            def __init__(self):
                self.lock = threading.Lock()
                self.active = 0
                self.max_active = 0

            def alive(self):
                return True

            def call_tool(self, name, args, timeout):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                try:
                    time.sleep(0.04)
                    return {"content": [{"type": "text", "text": "ok"}]}
                finally:
                    with self.lock:
                        self.active -= 1

            def close(self):
                return None

        client = ConcurrentClient()
        self.hub._cfg = {"servers": {"notes": {"timeout": 3}}, "agents": {}, "error": ""}
        self.hub._clients["notes"] = client

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.hub.call("notes", "lookup", {}), range(6)))

        self.assertEqual(len(results), 6)
        self.assertTrue(all("ok" in result for result in results))
        self.assertEqual(client.max_active, 1)


if __name__ == "__main__":
    unittest.main()
