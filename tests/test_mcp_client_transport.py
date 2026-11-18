"""Transport boundary tests for the optional HTTP MCP client."""
import time
import unittest
from unittest import mock

from kira.mcp.client import HttpClient, McpError


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


class McpProtocolResultValidationTests(unittest.TestCase):
    def setUp(self):
        from kira.mcp.client import _Base
        self.client = _Base({})

    def test_initialize_rejects_non_object_result(self):
        with mock.patch.object(self.client, "request", return_value=[]):
            with self.assertRaisesRegex(McpError, "initialize"):
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
        with mock.patch("kira.mcp.client.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(McpError, "total deadline"):
                self.client._post({"jsonrpc": "2.0", "id": 1}, timeout=0.07, want_id=1)

        self.assertTrue(response.closed)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_json_response_size_is_bounded(self):
        response = OversizedJsonResponse()
        with mock.patch("kira.mcp.client.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(McpError, "size limit"):
                self.client._post({"jsonrpc": "2.0", "id": 1}, timeout=1, want_id=1)
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
