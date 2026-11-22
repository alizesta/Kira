import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira import config
from kira.request_trace import reset_request_id, set_request_id, trace


class RequestTraceTests(unittest.TestCase):
    def test_trace_writes_correlated_jsonl_without_payloads(self):
        with tempfile.TemporaryDirectory() as folder:
            token = set_request_id("trace-test-123")
            try:
                with mock.patch.object(config, "DATA_DIR", Path(folder)):
                    trace("http_send", provider="custom-google", model="gemini-4-hydrogen",
                          host="generativelanguage.googleapis.com", stream=True, timeout=18)
            finally:
                reset_request_id(token)

            path = Path(folder) / "logs" / "request_trace.jsonl"
            self.assertTrue(path.exists())
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            event = json.loads(lines[0])
            self.assertEqual(event["request_id"], "trace-test-123")
            self.assertEqual(event["phase"], "http_send")
            self.assertEqual(event["model"], "gemini-4-hydrogen")
            self.assertNotIn("api_key", event)
            self.assertNotIn("prompt", event)


if __name__ == "__main__":
    unittest.main()
