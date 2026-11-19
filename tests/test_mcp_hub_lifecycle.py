"""Lifecycle and concurrency regression tests for the optional MCP hub."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from kira.mcp.hub import McpHub, _params_from_schema
from kira.mcp import install
from kira.tools.registry import Tool, ToolRegistry, ToolError


class McpHubLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.registry = mock.Mock()
        self.registry.unregister_where.return_value = 0
        self.hub = McpHub(self.registry, None, lambda: {})

    def tearDown(self):
        self.hub.shutdown()

    def test_mcp_tool_schema_must_be_well_formed_and_representable(self):
        valid = _params_from_schema({
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "query", "enum": ["a", "b"]},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        })
        self.assertEqual([param.name for param in valid], ["query", "limit"])
        self.assertTrue(valid[0].required)

        invalid_schemas = (
            None,
            {"type": "array"},
            {"type": "object", "properties": []},
            {"type": "object", "properties": {"x": {"type": "unsupported"}}},
            {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["missing"]},
            {"type": "object", "properties": {"x": {"type": "string", "enum": [1]}}},
            {"type": "object", "properties": {"x": {"type": "string", "enum": []}}},
        )
        for schema in invalid_schemas:
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                _params_from_schema(schema)

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

        with tempfile.TemporaryDirectory() as temp:
            with mock.patch("kira.mcp.hub.McpHub.refresh_async"):
                result = install(registry, Path(temp), lambda: {})

        self.assertIsNone(result)
        self.assertIs(registry.get("agent_status"), existing)
        self.assertIsNone(registry.get("agent_ask"))
        self.assertIsNone(registry.get("mcp_info"))

    def test_mcp_mode_off_disables_independent_agent_endpoints_too(self):
        settings = {"mcp_mode": "auto"}
        registry = ToolRegistry()
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch("kira.mcp.McpHub.refresh_async"):
                hub = install(registry, Path(temp), lambda: settings)
            hub._cfg = {
                "servers": {},
                "agents": {"worker": {"name": "worker", "url": "https://agent.example", "timeout": 1}},
                "error": "",
            }
            self.assertIsNotNone(hub.agents._agent("worker"))
            settings["mcp_mode"] = "off"

            with self.assertRaises(ToolError):
                hub.agents._agent("worker")

            hub.shutdown()

    def test_disabling_mcp_disconnects_clients_and_unregisters_tools(self):
        class Client:
            closed = False
            def close(self):
                self.closed = True

        client = Client()
        self.hub.settings_fn = lambda: {"mcp_mode": "off"}
        self.hub._clients["notes"] = client
        self.hub.state["notes"] = {"status": "ready", "tools": 1}

        self.hub.refresh_async()
        self.hub._thread.join(timeout=2)

        self.assertFalse(self.hub._thread.is_alive())
        self.assertTrue(client.closed)
        self.assertEqual(self.hub.state["_hub"]["status"], "disabled")
        self.registry.unregister_where.assert_called()

    def test_disabled_mcp_cannot_execute_an_already_registered_tool(self):
        class Client:
            calls = 0
            def alive(self):
                return True
            def call_tool(self, *_args):
                self.calls += 1
                return {"content": []}

        client = Client()
        self.hub.settings_fn = lambda: {"mcp_mode": "off"}
        self.hub._cfg = {"servers": {"notes": {"timeout": 3}}, "agents": {}, "error": ""}
        self.hub._clients["notes"] = client

        with self.assertRaises(ToolError):
            self.hub.call("notes", "lookup", {})

        self.assertEqual(client.calls, 0)

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
