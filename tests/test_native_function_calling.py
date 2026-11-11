import json
import unittest
from unittest import mock

from tests.helpers import Resp
from kira.hybrid_ai import OpenAICompatibleProvider, normalize_messages


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

    def test_native_tool_messages_survive_openai_normalization(self):
        messages = [
            {"role": "user", "content": "Open the browser"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "open_app", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "call_1", "name": "open_app", "content": "[ok] launched"},
        ]
        cleaned = normalize_messages(messages, preserve_tool_messages=True)
        self.assertEqual([m["role"] for m in cleaned], ["user", "assistant", "tool"])
        self.assertEqual(cleaned[-1]["tool_call_id"], "call_1")
        self.assertEqual(cleaned[1]["tool_calls"][0]["function"]["name"], "open_app")


if __name__ == "__main__":
    unittest.main()
