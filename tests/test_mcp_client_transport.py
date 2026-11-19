"""Transport boundary tests for the optional HTTP MCP client."""
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from kira.mcp.client import HttpClient, McpError, StdioClient, PROTOCOL
from kira.mcp.http_utils import NoRedirectHandler


class SlowSseResponse:
    def __init__(self):
        self.headers = {"Content-Type": "text/event-stream"}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def readline(self, size=-1):
        if self.closed:
            return b""
        time.sleep(0.01)
        return b"noise"

    def close(self):
        self.closed = True


class OversizedJsonResponse:
    def __init__(self):
        self.headers = {"Content-Type": "application/json"}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def read(self, size=-1):
        return b"x" * (size + 1)

    def close(self):
        self.closed = True


class ExternalHttpRedirectTests(unittest.TestCase):
    def test_redirect_handler_never_forwards_authenticated_requests(self):
        handler = NoRedirectHandler()
        request = urllib.request.Request(
            "https://agent.example/ask",
            headers={"Authorization": "Bearer secret", "Mcp-Session-Id": "session"},
        )
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code):
                with self.assertRaises(urllib.error.HTTPError):
                    handler.redirect_request(
                        request, None, code, "redirect", {}, "https://attacker.example/collect"
                    )

class McpJsonRpcEnvelopeTests(unittest.TestCase):
    def test_http_transport_rejects_wrong_id_version_and_missing_result(self):
        client = HttpClient({"url": "https://mcp.example/rpc"})
        responses = (
            {"jsonrpc": "2.0", "id": 99, "result": {}},
            {"jsonrpc": "1.0", "id": 1, "result": {}},
            {"jsonrpc": "2.0", "id": 1},
        )
        for response in responses:
            client._id = 0
            with self.subTest(response=response), mock.patch.object(client, "_post", return_value=response):
                with self.assertRaises(McpError):
                    client.request("tools/list", {}, 1)

    def test_stdio_transport_rejects_wrong_version_for_pending_request(self):
        client = StdioClient({"name": "probe"})
        slot = {"event": threading.Event()}
        client._pending[7] = slot
        client._on_message({"jsonrpc": "1.0", "id": 7, "result": {"tools": []}})
        self.assertTrue(slot["event"].is_set())
        self.assertIn("invalid JSON-RPC", slot["error"]["message"])

    def test_stdio_transport_rejects_response_with_both_result_and_error(self):
        client = StdioClient({"name": "probe"})
        slot = {"event": threading.Event()}
        client._pending[7] = slot
        client._on_message({"jsonrpc": "2.0", "id": 7, "result": {}, "error": {"message": "bad"}})
        self.assertTrue(slot["event"].is_set())
        self.assertIn("malformed", slot["error"]["message"])


class McpProtocolResultValidationTests(unittest.TestCase):
    def setUp(self):
        from kira.mcp.client import _Base
        self.client = _Base({})

    def test_initialize_rejects_non_object_result(self):
        with mock.patch.object(self.client, "request", return_value=[]):
            with self.assertRaisesRegex(McpError, "initialize"):
                self.client.initialize(1)

    def test_initialize_rejects_unsupported_protocol_and_missing_fields(self):
        invalid = (
            {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {}},
            {"protocolVersion": PROTOCOL, "serverInfo": {}},
            {"protocolVersion": PROTOCOL, "capabilities": [] , "serverInfo": {}},
        )
        for result in invalid:
            with self.subTest(result=result), mock.patch.object(self.client, "request", return_value=result):
                with self.assertRaises(McpError):
                    self.client.initialize(1)

        valid = {"protocolVersion": PROTOCOL, "capabilities": {}, "serverInfo": {"name": "server", "version": "1"}}
        with mock.patch.object(self.client, "request", return_value=valid), mock.patch.object(self.client, "notify"):
            self.client.initialize(1)
        self.assertEqual(self.client.server_info["name"], "server")

    def test_initialize_notification_failure_aborts_handshake(self):
        valid = {"protocolVersion": PROTOCOL, "capabilities": {}, "serverInfo": {"name": "server", "version": "1"}}
        with mock.patch.object(self.client, "request", return_value=valid), mock.patch.object(
            self.client, "_post", side_effect=McpError("initialized notification failed")
        ):
            with self.assertRaisesRegex(McpError, "initialized notification failed"):
                self.client.initialize(1)

    def test_tools_list_rejects_missing_or_malformed_tools(self):
        for result in ({}, {"tools": "not-a-list"}, {"tools": [None]}, {"tools": [{"name": ""}]}):
            with self.subTest(result=result), mock.patch.object(self.client, "request", return_value=result):
                with self.assertRaises(McpError):
                    self.client.list_tools(1)

    def test_tools_list_rejects_repeated_pagination_cursor(self):
        page = {"tools": [], "nextCursor": "same"}
        with mock.patch.object(self.client, "request", return_value=page):
            with self.assertRaisesRegex(McpError, "repeated"):
                self.client.list_tools(1)

    def test_tool_call_rejects_non_object_and_malformed_content(self):
        for result in (None, [], {"content": "not-a-list"}, {"content": [None]}):
            with self.subTest(result=result), mock.patch.object(self.client, "request", return_value=result):
                with self.assertRaises(McpError):
                    self.client.call_tool("probe", {}, 1)


class McpHttpTransportTests(unittest.TestCase):
    def setUp(self):
        self.client = HttpClient({"url": "https://mcp.example/rpc"})

    def test_sse_stream_cannot_keep_rpc_alive_past_total_deadline(self):
        response = SlowSseResponse()
        started = time.monotonic()
        with mock.patch("kira.mcp.client.open_no_redirect", return_value=response):
            with self.assertRaisesRegex(McpError, "total deadline"):
                self.client._post({"jsonrpc": "2.0", "id": 1}, timeout=0.07, want_id=1)

        self.assertTrue(response.closed)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_json_response_size_is_bounded(self):
        response = OversizedJsonResponse()
        with mock.patch("kira.mcp.client.open_no_redirect", return_value=response):
            with self.assertRaisesRegex(McpError, "size limit"):
                self.client._post({"jsonrpc": "2.0", "id": 1}, timeout=1, want_id=1)
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
