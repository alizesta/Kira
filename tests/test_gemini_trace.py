"""The dedicated Gemini log (logs/gemini_trace.jsonl) shows where a request goes and how it ended."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira import config
from kira.hybrid_providers import OpenAICompatibleProvider, ProviderError
from tests.helpers import Resp

MESSAGES = [{"role": "user", "content": "سلام SECRET-PROMPT"}]


def make(model="gemini-3.8-flash", base="https://generativelanguage.googleapis.com/v1beta/openai"):
    return OpenAICompatibleProvider({"base_url": base, "api_key": "KEY-12345", "model": model}, name="google-ai")


def events(folder):
    path = Path(folder) / "logs" / "gemini_trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class GeminiTraceTests(unittest.TestCase):
    def test_empty_length_reply_is_logged_with_thinking_tokens_and_a_clear_error(self):
        body = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 48, "total_tokens": 57,
                          "completion_tokens_details": {"reasoning_tokens": 48}}}
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(config, "DATA_DIR", Path(folder)), \
                mock.patch("requests.post", return_value=Resp(200, body)):
            with self.assertRaises(ProviderError) as ctx:
                make().chat(MESSAGES, "system", 0.3)
            ev = events(folder)
        self.assertIn("thinking", str(ctx.exception))
        self.assertEqual([e["phase"] for e in ev], ["request", "response", "result"])
        req, _resp, res = ev
        self.assertEqual(req["model"], "gemini-3.8-flash")
        self.assertEqual(req["host"], "generativelanguage.googleapis.com")
        self.assertEqual(req["path"], "/v1beta/openai/chat/completions")
        self.assertEqual(req["reasoning_effort"], "low")
        self.assertTrue(res["empty"])
        self.assertEqual(res["finish_reason"], "length")
        self.assertEqual(res["thinking_tokens"], 48)
        text = json.dumps(ev, ensure_ascii=False)
        self.assertNotIn("KEY-12345", text)
        self.assertNotIn("SECRET-PROMPT", text)

    def test_http_error_body_message_is_logged(self):
        resp = Resp(429, {"error": {"message": "quota exceeded"}}, headers={"Retry-After": "7"})
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(config, "DATA_DIR", Path(folder)), \
                mock.patch("requests.post", return_value=resp):
            with self.assertRaises(ProviderError):
                make("gemini-4-hydrogen").chat(MESSAGES, "system", 0.3)
            ev = events(folder)
        self.assertEqual(ev[1]["status_code"], 429)
        self.assertEqual(ev[1]["retry_after"], "7")

    def test_non_google_endpoint_writes_no_gemini_log(self):
        body = {"choices": [{"message": {"content": "hi"}}]}
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(config, "DATA_DIR", Path(folder)), \
                mock.patch("requests.post", return_value=Resp(200, body)):
            make(base="https://example.com/v1").chat(MESSAGES, "system", 0.3)
            self.assertEqual(events(folder), [])


if __name__ == "__main__":
    unittest.main()
