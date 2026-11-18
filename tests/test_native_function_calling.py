import json
import unittest
from unittest import mock

from tests.helpers import Resp
from kira.hybrid_ai import HybridRouter, OpenAICompatibleProvider, normalize_messages, provider_class
from kira.ollama_client import OllamaClient


class NativeFunctionCallingTests(unittest.TestCase):
    def test_openai_compatible_provider_sends_json_schema_and_parses_native_call(self):
        provider = OpenAICompatibleProvider(
            {"model": "test-model", "api_key": "test-secret", "base_url": "https://example.invalid/v1"},
            name="custom",
        )
        schema = {
            "name": "get_datetime",
            "description": "Read the local date and time",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
        response = Resp(200, {"choices": [{"message": {
            "content": None,
            "tool_calls": [{"id": "call_123", "type": "function",
                            "function": {"name": "get_datetime", "arguments": "{}"}}],
        }}]})
        with mock.patch("requests.post", return_value=response) as post:
            result = provider.chat_with_tools([{"role": "user", "content": "What time is it?"}],
                                              "system", 0.2, [schema])
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(payload["tools"][0]["function"], schema)
        self.assertEqual(result["tool_calls"], [{"id": "call_123", "tool": "get_datetime", "args": {}}])

    def test_google_gemini_route_uses_native_openai_compatible_tools(self):
        cfg = {
            "type": "openai_compat",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "test-google-key",
            "model": "gemini-2.5-flash",
        }
        cls = provider_class("google", cfg)
        self.assertIsNotNone(cls)
        provider = cls(cfg, name="google")
        schema = {"name": "get_datetime", "description": "Read time",
                  "parameters": {"type": "object", "properties": {}, "required": []}}
        response = Resp(200, {"choices": [{"message": {
            "content": None,
            "tool_calls": [{"id": "gemini_call_1", "type": "function",
                            "function": {"name": "get_datetime", "arguments": "{}"}}],
        }}]})
        with mock.patch("requests.post", return_value=response) as post:
            result = provider.chat_with_tools([{"role": "user", "content": "What time is it?"}],
                                              "system", 0.2, [schema])
        self.assertTrue(post.call_args.args[0].startswith(cfg["base_url"] + "/chat/completions"))
        self.assertEqual(post.call_args.kwargs["json"]["tools"][0]["function"], schema)
        self.assertEqual(result["tool_calls"][0]["tool"], "get_datetime")

    def test_ollama_native_tool_call_uses_api_chat_tools_and_parses_arguments(self):
        client = OllamaClient("http://localhost:11434", "qwen3.5:4b")
        schema = {"name": "get_datetime", "description": "Read time",
                  "parameters": {"type": "object", "properties": {}, "required": []}}
        response = Resp(200, {"message": {"content": "", "tool_calls": [
            {"function": {"name": "get_datetime", "arguments": {"timezone": "Asia/Tehran"}}}
        ]}})
        with mock.patch("requests.post", return_value=response) as post:
            result = client.chat_with_tools([{"role": "user", "content": "What time is it?"}],
                                            "system", 0.2, [schema])
        payload = post.call_args.kwargs["json"]
        self.assertTrue(post.call_args.args[0].endswith("/api/chat"))
        self.assertEqual(payload["tools"][0]["function"], schema)
        self.assertEqual(result["tool_calls"], [{"id": "ollama_0", "tool": "get_datetime",
                                                 "args": {"timezone": "Asia/Tehran"}}])

    def test_ollama_native_round_preserves_assistant_and_tool_result_messages(self):
        client = OllamaClient("http://localhost:11434", "qwen3.5:4b")
        messages = [
            {"role": "user", "content": "Open the browser"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "open_app", "arguments": json.dumps({"app": "browser"})}}
            ]},
            {"role": "tool", "tool_call_id": "call_1", "name": "open_app", "content": "[ok] launched"},
            {"role": "user", "content": "Done?"},
        ]
        response = Resp(200, {"message": {"content": "Yes, it is open.", "tool_calls": []}})
        with mock.patch("requests.post", return_value=response) as post:
            result = client.chat_with_tools(messages, "system", 0.2, [
                {"name": "get_datetime", "description": "Read time",
                 "parameters": {"type": "object", "properties": {}, "required": []}}
            ])
        sent = post.call_args.kwargs["json"]["messages"]
        self.assertEqual(sent[2]["tool_calls"][0]["function"]["name"], "open_app")
        self.assertEqual(sent[2]["tool_calls"][0]["function"]["arguments"], {"app": "browser"})
        self.assertEqual(sent[3], {"role": "tool", "content": "[ok] launched"})
        self.assertEqual(result["text"], "Yes, it is open.")

    def test_ollama_models_without_tool_support_return_to_text_fallback(self):
        client = OllamaClient("http://localhost:11434", "old-model")
        response = Resp(400, {"error": "model does not support tools"})
        with mock.patch("requests.post", return_value=response):
            result = client.chat_with_tools([{"role": "user", "content": "Do something"}], "system", 0.2,
                                            [{"name": "get_datetime", "description": "Read time",
                                              "parameters": {"type": "object", "properties": {}, "required": []}}])
        self.assertIsNone(result)

    def test_native_tool_messages_survive_openai_normalization(self):
        messages = [
            {"role": "user", "content": "Open the browser"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "open_app", "arguments": json.dumps({"app": "browser"})}}
            ]},
            {"role": "tool", "tool_call_id": "call_1", "name": "open_app", "content": "[ok] launched"},
        ]
        cleaned = normalize_messages(messages, preserve_tool_messages=True)
        self.assertEqual([m["role"] for m in cleaned], ["user", "assistant", "tool"])
        self.assertEqual(cleaned[-1]["tool_call_id"], "call_1")
        self.assertEqual(cleaned[1]["tool_calls"][0]["function"]["name"], "open_app")


    def test_router_accounts_for_native_function_calling_requests(self):
        router = HybridRouter({})
        route = {"id": "custom-route", "provider": "custom", "model": "test-model"}
        provider = mock.Mock()
        provider.chat_with_tools.return_value = {
            "text": "",
            "tool_calls": [{"id": "call_1", "tool": "get_datetime", "args": {}}],
        }
        provider.last_stats = {"prompt_tokens": 12, "eval_tokens": 7, "eval_ms": 350}
        router._candidates = lambda: [route]
        router.eligibility = lambda _route: (True, "ok")
        router.route_info = lambda _route: {"kind": "cloud", "label": "Test"}
        router._make_provider = lambda _route: provider
        with mock.patch.object(router, "_ledger") as ledger, mock.patch.object(router, "_write_telemetry") as telemetry:
            result = router.chat_with_tools(
                [{"role": "user", "content": "What time is it?"}],
                "system",
                tools=[{"name": "get_datetime", "parameters": {"type": "object"}}],
            )
        self.assertEqual(result["tool_calls"][0]["tool"], "get_datetime")
        ledger.assert_called_once_with(router.last_metrics, "tool_call", provider, provider.last_stats)
        telemetry.assert_called_once()
        self.assertEqual(router.last_metrics["eval_tokens"], 7)
        self.assertEqual(router.last_attempts[-1]["result"], "tool_call")


if __name__ == "__main__":
    unittest.main()
