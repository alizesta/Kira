"""Gemini 3.8 Flash / 4 Hydrogen are sent to Google's native generateContent API (the OpenAI-compat layer timed out / 503'd)."""
import json
import os
import unittest
from unittest import mock

from kira.hybrid_providers import (OpenAICompatibleProvider, ProviderError, _native_to_openai, _openai_to_native)
from tests.helpers import Resp, StreamResp, sse

MSGS = [{"role": "user", "content": "سلام"}]
BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


def make(model="gemini-4-hydrogen", **extra):
    return OpenAICompatibleProvider({"base_url": BASE, "api_key": "google-test-key", "model": model, **extra}, name="google-ai")


def native_ok(text="OK", **extra):
    return Resp(200, {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
                      "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 2, "thoughtsTokenCount": 30,
                                        "totalTokenCount": 41}, **extra})


class Recorder:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, url, headers=None, json=None, timeout=None, **kw):
        self.calls.append({"url": url, "headers": headers, "json": json, "stream": kw.get("stream")})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class NativeRoutingTests(unittest.TestCase):
    def test_chat_uses_native_url_key_header_and_thinking_level(self):
        rec = Recorder(native_ok("جواب"))
        with mock.patch("requests.post", rec):
            self.assertEqual(make().chat(MSGS, "persona", 0.2), "جواب")
        call = rec.calls[0]
        self.assertEqual(call["url"], "https://generativelanguage.googleapis.com/v1beta/models/gemini-4-hydrogen:generateContent")
        self.assertEqual(call["headers"]["x-goog-api-key"], "google-test-key")
        self.assertNotIn("Authorization", call["headers"])
        body = call["json"]
        self.assertEqual(body["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "persona")
        self.assertEqual(body["contents"], [{"role": "user", "parts": [{"text": "سلام"}]}])

    def test_other_models_and_disabled_flag_keep_openai_compat(self):
        for provider in (make("gemini-3.5-flash"), make(gemini_native=False)):
            rec = Recorder(Resp(200, {"choices": [{"message": {"content": "hi"}}]}))
            with mock.patch("requests.post", rec):
                self.assertEqual(provider.chat(MSGS, "s", 0.2), "hi")
            self.assertTrue(rec.calls[0]["url"].endswith("/v1beta/openai/chat/completions"))
        with mock.patch.dict(os.environ, {"KIRA_GEMINI_NATIVE": "0"}):
            rec = Recorder(Resp(200, {"choices": [{"message": {"content": "hi"}}]}))
            with mock.patch("requests.post", rec):
                make().chat(MSGS, "s", 0.2)
            self.assertTrue(rec.calls[0]["url"].endswith("/chat/completions"))

    def test_plain_400_does_not_silently_fall_back_unless_explicitly_enabled(self):
        bad = Resp(400, {"error": {"message": "Invalid JSON payload"}})
        rec = Recorder(bad)
        with mock.patch("requests.post", rec):
            with self.assertRaises(ProviderError) as caught:
                make().chat(MSGS, "s", 0.2)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(len(rec.calls), 1)
        self.assertIn(":generateContent", rec.calls[0]["url"])

        rec = Recorder(
            Resp(400, {"error": {"message": "Invalid JSON payload"}}),
            Resp(200, {"choices": [{"message": {"content": "fallback"}}]}),
        )
        with mock.patch("requests.post", rec):
            self.assertEqual(make(gemini_native_fallback=True).chat(MSGS, "s", 0.2), "fallback")
        self.assertEqual(len(rec.calls), 2)
        self.assertTrue(rec.calls[1]["url"].endswith("/chat/completions"))

        rec = Recorder(Resp(503, {"error": {"message": "overloaded"}}), native_ok())
        with mock.patch("requests.post", rec):
            with self.assertRaises(ProviderError):
                make(gemini_native_fallback=True).chat(MSGS, "s", 0.2)
        self.assertEqual(len(rec.calls), 1)                       # a 5xx may have counted against quota: no replay


class NativeConversionTests(unittest.TestCase):
    def test_tool_round_trip_images_and_signature(self):
        schema = {"name": "open_app", "description": "d", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}}}
        payload = {"temperature": 0.3, "max_tokens": 77, "reasoning_effort": "low",
                   "tools": [{"type": "function", "function": schema}],
                   "messages": [
                       {"role": "system", "content": "sys"},
                       {"role": "user", "content": [{"type": "text", "text": "ببین"},
                                                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]},
                       {"role": "assistant", "content": None,
                        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "open_app", "arguments": "{\"name\": \"x\"}"}}]},
                       {"role": "tool", "tool_call_id": "c1", "name": "open_app", "content": "[ok] done"}]}
        body = _openai_to_native(payload)
        self.assertEqual(body["generationConfig"], {"temperature": 0.3, "maxOutputTokens": 77, "thinkingConfig": {"thinkingLevel": "low"}})
        self.assertEqual(body["tools"][0]["functionDeclarations"][0]["parametersJsonSchema"], schema["parameters"])
        user, model, result = body["contents"]
        self.assertEqual(user["parts"][1], {"inlineData": {"mimeType": "image/png", "data": "QUJD"}})
        call = model["parts"][0]
        self.assertEqual(call["functionCall"], {"name": "open_app", "args": {"name": "x"}})
        self.assertEqual(call["thoughtSignature"], "skip_thought_signature_validator")
        self.assertEqual(result["role"], "user")
        self.assertEqual(result["parts"][0]["functionResponse"], {"name": "open_app", "response": {"result": "[ok] done"}})

    def test_reply_is_translated_back_with_calls_signature_usage_and_finish(self):
        data = {"candidates": [{"content": {"parts": [
            {"text": "hidden", "thought": True}, {"text": "متن"},
            {"functionCall": {"name": "f", "args": {"a": 1}}, "thoughtSignature": "SIG"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3, "thoughtsTokenCount": 4, "totalTokenCount": 12}}
        out = _native_to_openai(data)
        msg = out["choices"][0]
        self.assertEqual(msg["message"]["content"], "متن")
        self.assertEqual(msg["finish_reason"], "tool_calls")
        call = msg["message"]["tool_calls"][0]
        self.assertEqual(json.loads(call["function"]["arguments"]), {"a": 1})
        self.assertEqual(call["extra_content"]["google"]["thought_signature"], "SIG")
        self.assertEqual(out["usage"]["completion_tokens"], 7)
        self.assertEqual(out["usage"]["completion_tokens_details"]["reasoning_tokens"], 4)
        self.assertEqual(_native_to_openai({"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]})["choices"][0]["finish_reason"], "length")
        blocked = _native_to_openai({"promptFeedback": {"blockReason": "SAFETY"}})
        self.assertEqual(blocked["choices"][0]["finish_reason"], "content_filter")

    def test_chat_with_tools_returns_native_function_call(self):
        reply = Resp(200, {"candidates": [{"content": {"parts": [{"functionCall": {"name": "open_app", "args": {"name": "x"}}}]},
                                           "finishReason": "STOP"}]})
        rec = Recorder(reply)
        with mock.patch("requests.post", rec):
            res = make().chat_with_tools(MSGS, "s", 0.1, [{"name": "open_app", "parameters": {"type": "object", "properties": {}}}])
        self.assertEqual(res["tool_calls"][0]["tool"], "open_app")
        self.assertEqual(res["tool_calls"][0]["args"], {"name": "x"})
        self.assertIn("functionDeclarations", rec.calls[0]["json"]["tools"][0])


class NativeStreamTests(unittest.TestCase):
    def test_stream_uses_sse_endpoint_and_skips_thought_parts(self):
        chunks = [{"candidates": [{"content": {"parts": [{"text": "secret", "thought": True}]}}]},
                  {"candidates": [{"content": {"parts": [{"text": "سلا"}]}}]},
                  {"candidates": [{"content": {"parts": [{"text": "م"}]}, "finishReason": "STOP"}],
                   "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2, "thoughtsTokenCount": 9}}]
        rec = Recorder(StreamResp(sse(*chunks, done=False)))
        with mock.patch("requests.post", rec):
            text = "".join(make().stream(MSGS, "s", 0.2))
        self.assertEqual(text, "سلام")
        self.assertTrue(rec.calls[0]["url"].endswith(":streamGenerateContent?alt=sse"))
        self.assertTrue(rec.calls[0]["stream"])

    def test_stream_400_requires_explicit_compatibility_fallback(self):
        bad = StreamResp([], status=400, body={"error": {"message": "Invalid JSON payload"}})
        rec = Recorder(bad)
        with mock.patch("requests.post", rec):
            with self.assertRaises(ProviderError):
                "".join(make().stream(MSGS, "s", 0.2))
        self.assertEqual(len(rec.calls), 1)
        self.assertIn(":streamGenerateContent", rec.calls[0]["url"])

        rec = Recorder(
            StreamResp([], status=400, body={"error": {"message": "Invalid JSON payload"}}),
            StreamResp(sse("سلام")),
        )
        with mock.patch("requests.post", rec):
            self.assertEqual("".join(make(gemini_native_fallback=True).stream(MSGS, "s", 0.2)), "سلام")
        self.assertEqual(len(rec.calls), 2)
        self.assertTrue(rec.calls[1]["url"].endswith("/chat/completions"))


if __name__ == "__main__":
    unittest.main()
