import unittest
from unittest import mock

import requests

from tests import helpers
from tests.helpers import Resp, StreamResp, ok_ollama
from kira.ollama_client import (OllamaClient, OllamaError, parse_keep_alive, clamp_num_ctx, model_installed, fit_messages)

MSGS = [{"role": "user", "content": "سلام"}]


def capture(resp):
    cap = {}

    def fake(url, json=None, timeout=None, **kw):
        cap["url"], cap["payload"], cap["timeout"] = url, json, timeout
        return resp
    return cap, fake


class OllamaTests(unittest.TestCase):
    # 18) Ollama switched off: clear message, no crash
    def test_18_ollama_off_status_and_chat(self):
        c = OllamaClient("http://localhost:11434", "qwen3.5:4b")
        with mock.patch("requests.get", side_effect=requests.ConnectionError("refused")):
            ok, detail = c.status()
            self.assertFalse(ok)
            self.assertIn("Ollama", detail)
            ok, text = c.describe()
            self.assertFalse(ok)
            self.assertIn("ollama serve", text)
        with mock.patch("requests.post", side_effect=requests.ConnectionError("refused")):
            with self.assertRaises(OllamaError) as cm:
                c.chat(MSGS, "sys")
        self.assertEqual(cm.exception.kind, "offline")
        self.assertIn("11434", str(cm.exception))

    def test_model_not_installed_gives_pull_command(self):
        c = OllamaClient("http://localhost:11434", "qwen3.5:4b")
        with mock.patch("requests.post", return_value=Resp(404, {"error": "model 'qwen3.5:4b' not found"})), \
                mock.patch("requests.get", return_value=Resp(200, {"models": [{"name": "llama3.2:3b"}]})):
            with self.assertRaises(OllamaError) as cm:
                c.chat(MSGS, "sys")
        self.assertEqual(cm.exception.kind, "missing")
        self.assertIn("llama3.2:3b", str(cm.exception))            # tells the user what IS installed
        self.assertIn("ollama pull qwen3.5:4b", str(cm.exception))

    def test_game_friendly_options_are_sent(self):
        c = OllamaClient("http://localhost:11434", "qwen3.5:4b", num_ctx=4096, keep_alive="2m")
        cap, fake = capture(ok_ollama("hi"))
        with mock.patch("requests.post", fake):
            self.assertEqual(c.chat(MSGS, "persona", 0.5), "hi")
        p = cap["payload"]
        self.assertEqual(p["options"]["num_ctx"], 4096)
        self.assertEqual(p["keep_alive"], "2m")
        self.assertIs(p["think"], False)
        self.assertEqual(p["options"]["num_predict"], 512)           # runaway generation is capped
        self.assertEqual(p["messages"][0], {"role": "system", "content": "persona"})
        self.assertEqual(p["messages"][1]["content"], "سلام")
        self.assertFalse(p["stream"])

    def test_chat_retries_context_overflow_with_larger_window(self):
        c = OllamaClient("http://localhost:11434", "local-model", num_ctx=2048)
        responses = [
            Resp(400, {"error": "request (6038 tokens) exceeds the available context size (2048 tokens), try increasing it"}),
            ok_ollama("پاسخ محلی"),
        ]
        seen = []

        def fake(url, json=None, timeout=None, **kw):
            seen.append(json["options"]["num_ctx"])
            return responses.pop(0)

        with mock.patch("requests.post", fake):
            self.assertEqual(c.chat(MSGS, "system prompt"), "پاسخ محلی")
        self.assertEqual(seen, [2048, 8192])
        self.assertEqual(c.num_ctx, 8192)

    def test_tool_chat_retries_context_overflow(self):
        c = OllamaClient("http://localhost:11434", "local-model", num_ctx=2048)
        responses = [
            Resp(400, {"error": "request (6038 tokens) exceeds the available context size (2048 tokens)"}),
            ok_ollama("tool-ready"),
        ]
        seen = []

        def fake(url, json=None, timeout=None, **kw):
            seen.append(json["options"]["num_ctx"])
            return responses.pop(0)

        with mock.patch("requests.post", fake):
            result = c.chat_with_tools(
                MSGS, "system prompt", tools=[{"name": "lookup", "parameters": {"type": "object"}}]
            )
        self.assertEqual(result["text"], "tool-ready")
        self.assertEqual(seen, [2048, 8192])

    def test_stream_retries_context_overflow(self):
        c = OllamaClient("http://localhost:11434", "local-model", num_ctx=2048)
        responses = [
            StreamResp([], status=400, body={"error": "request (6038 tokens) exceeds the available context size (2048 tokens)"}),
            StreamResp([b'{"message":{"content":"streamed"},"done":true}']),
        ]
        seen = []

        def fake(url, json=None, timeout=None, stream=False, **kw):
            seen.append((json["options"]["num_ctx"], stream))
            return responses.pop(0)

        with mock.patch("requests.post", fake):
            text = "".join(c.stream(MSGS, "system prompt"))
        self.assertEqual(text, "streamed")
        self.assertEqual(seen, [(2048, True), (8192, True)])

    def test_think_unsupported_retries_once_and_remembers(self):
        c = OllamaClient("http://localhost:11434", "qwen2.5:3b")
        seq = [Resp(400, text='{"error":"\\"qwen2.5:3b\\" does not support thinking"}'), ok_ollama("ok"), ok_ollama("ok2")]
        payloads = []

        def fake(url, json=None, timeout=None, **kw):
            payloads.append(dict(json))
            return seq.pop(0)
        with mock.patch("requests.post", fake):
            self.assertEqual(c.chat(MSGS, "s"), "ok")
            self.assertEqual(c.chat(MSGS, "s"), "ok2")
        self.assertIn("think", payloads[0])
        self.assertNotIn("think", payloads[1])
        self.assertNotIn("think", payloads[2])         # remembered: no wasted request next time

    def test_thinking_only_reply_is_an_error_not_silent(self):
        c = OllamaClient("http://localhost:11434", "m")
        r = Resp(200, {"message": {"content": "<think>x</think>", "thinking": "reasoning"}})
        with mock.patch("requests.post", return_value=r):
            with self.assertRaises(OllamaError):
                c.chat(MSGS, "s")

    def test_from_settings_resolves_options(self):
        s = helpers.fresh_settings()
        s["model"] = "qwen2.5:3b"
        s["providers"]["ollama"].update({"num_ctx": 2048, "keep_alive": "30s"})
        c = OllamaClient.from_settings(s)
        self.assertEqual((c.model, c.num_ctx, c.keep_alive), ("qwen2.5:3b", 2048, "30s"))

    def test_unload_and_preload_payloads(self):
        c = OllamaClient("http://localhost:11434", "qwen3.5:4b", 4096, "2m")
        cap, fake = capture(Resp(200, {}))
        with mock.patch("requests.post", fake):
            c.unload()
            self.assertEqual(cap["url"], "http://localhost:11434/api/generate")
            self.assertEqual(cap["payload"], {"model": "qwen3.5:4b", "keep_alive": 0})
            c.preload()
            self.assertEqual(cap["payload"]["keep_alive"], "2m")
            self.assertEqual(cap["payload"]["options"]["num_ctx"], 4096)

    def test_describe_reports_gpu_share(self):
        c = OllamaClient("http://localhost:11434", "qwen3.5:4b")
        ps = {"models": [{"name": "qwen3.5:4b", "size": 4000000000, "size_vram": 2000000000, "expires_at": "soon"}]}

        def fake_get(url, timeout=None, **kw):
            if url.endswith("/api/version"):
                return Resp(200, {"version": "0.40.0"})
            if url.endswith("/api/tags"):
                return Resp(200, {"models": [{"name": "qwen3.5:4b"}]})
            return Resp(200, ps)
        with mock.patch("requests.get", fake_get):
            ok, text = c.describe()
        self.assertTrue(ok)
        self.assertIn("0.40.0", text)
        self.assertIn("50٪ روی GPU", text)
        self.assertIn("CPU", text)
        ps["models"] = []
        with mock.patch("requests.get", fake_get):
            self.assertIn("آزاد", c.describe()[1])

    def test_helpers(self):
        self.assertEqual(parse_keep_alive("2m"), ("2m", True))
        self.assertEqual(parse_keep_alive("0"), (0, True))
        self.assertEqual(parse_keep_alive("-1"), (-1, True))
        self.assertEqual(parse_keep_alive("abc"), ("2m", False))
        self.assertEqual(parse_keep_alive(""), ("2m", False))
        self.assertEqual(clamp_num_ctx(10), 1024)
        self.assertEqual(clamp_num_ctx(10 ** 9), 32768)
        self.assertEqual(clamp_num_ctx("x"), 8192)
        self.assertTrue(model_installed(["qwen3.5:4b"], "qwen3.5:4b"))
        self.assertTrue(model_installed(["qwen3.5:4b"], "qwen3.5"))
        self.assertFalse(model_installed(["qwen3.5:9b"], "qwen3.5:4b"))
        self.assertFalse(model_installed([], "x"))

    # Real-world case reported on the PC: configured qwen3.5:4b, installed as qwen3.5:latest
    def test_resolve_model_accepts_latest_alias_but_not_other_sizes(self):
        from kira.ollama_client import resolve_model
        self.assertEqual(resolve_model(["qwen3.5:latest"], "qwen3.5:4b"), "qwen3.5:latest")
        self.assertEqual(resolve_model(["qwen35:latest"], "qwen3.5:4b"), "qwen35:latest")
        self.assertEqual(resolve_model(["Qwen3.5:latest"], "qwen3.5:4b"), "Qwen3.5:latest")
        self.assertEqual(resolve_model(["qwen3.5:4b", "qwen3.5:latest"], "qwen3.5:4b"), "qwen3.5:4b")   # exact wins
        self.assertEqual(resolve_model(["qwen3.5:latest"], "qwen3.5"), "qwen3.5:latest")
        self.assertIsNone(resolve_model(["qwen3.5:9b"], "qwen3.5:4b"))
        self.assertIsNone(resolve_model(["llama3.2:latest"], "qwen3.5:4b"))
        self.assertIsNone(resolve_model([], "qwen3.5:4b"))

    def test_chat_falls_back_to_installed_latest_tag_and_remembers(self):
        c = OllamaClient("http://localhost:11434", "qwen3.5:4b")
        sent = []

        def fake_post(url, json=None, timeout=None, **kw):
            sent.append(json["model"])
            return Resp(404, {"error": "model not found"}) if json["model"] == "qwen3.5:4b" else ok_ollama("جواب")
        get = mock.Mock(return_value=Resp(200, {"models": [{"name": "qwen3.5:latest"}]}))
        with mock.patch("requests.post", fake_post), mock.patch("requests.get", get):
            self.assertEqual(c.chat(MSGS, "s"), "جواب")
            self.assertEqual(c.chat(MSGS, "s"), "جواب")
        self.assertEqual(sent, ["qwen3.5:4b", "qwen3.5:latest", "qwen3.5:latest"])   # second chat: no wasted 404
        self.assertEqual(c.active_model, "qwen3.5:latest")

    def test_describe_mentions_alias_in_use(self):
        c = OllamaClient("http://localhost:11434", "qwen3.5:4b")

        def fake_get(url, timeout=None, **kw):
            if url.endswith("/api/version"):
                return Resp(200, {"version": "0.40.0"})
            if url.endswith("/api/tags"):
                return Resp(200, {"models": [{"name": "qwen3.5:latest"}]})
            return Resp(200, {"models": []})
        with mock.patch("requests.get", fake_get):
            ok, text = c.describe()
        self.assertTrue(ok)
        self.assertIn("qwen3.5:latest", text)
        self.assertIn("از آن استفاده می‌شود", text)

    def test_benchmark_reports_speed_and_warns_when_cpu_slow(self):
        c = OllamaClient("http://localhost:11434", "qwen3.5:4b")
        d = {"total_duration": 40e9, "load_duration": 8e9, "prompt_eval_count": 30, "prompt_eval_duration": 10e9,
             "eval_count": 24, "eval_duration": 20e9, "message": {"content": "سلام"}}   # 1.2 tokens/s
        cap, fake = capture(Resp(200, d))
        ps = {"models": [{"name": "qwen3.5:4b", "size": 4000000000, "size_vram": 0}]}

        def fake_get(url, timeout=None, **kw):
            if url.endswith("/api/tags"):
                return Resp(200, {"models": [{"name": "qwen3.5:4b"}]})
            return Resp(200, ps)
        with mock.patch("requests.post", fake), mock.patch("requests.get", fake_get):
            ok, text = c.benchmark()
        self.assertTrue(ok)
        self.assertEqual(cap["payload"]["options"]["num_predict"], 24)
        self.assertIn("1.2 توکن/ثانیه", text)
        self.assertIn("0٪", text)                                  # GPU share
        self.assertIn("CPU", text)                                 # slow-speed warning
        with mock.patch("requests.post", side_effect=requests.ConnectionError("x")):
            ok, text = c.benchmark()
        self.assertFalse(ok)
        self.assertIn("Ollama", text)

    def test_history_is_trimmed_to_context_budget(self):
        big = "ا" * 3000
        history = [{"role": "user" if i % 2 == 0 else "assistant", "content": big + str(i)} for i in range(12)]
        history.append({"role": "user", "content": "آخرین پرسش"})
        kept = fit_messages(history, "s" * 600, 4096)
        self.assertEqual(kept[-1]["content"], "آخرین پرسش")           # newest always kept
        self.assertLess(len(kept), len(history))
        self.assertLessEqual(sum(len(m["content"]) for m in kept) + 600, (4096 - 768) * 2)
        c = OllamaClient("http://localhost:11434", "m", 4096)
        cap, fake = capture(ok_ollama())
        with mock.patch("requests.post", fake):
            c.chat(history, "s" * 600)
        self.assertEqual(cap["payload"]["messages"][-1]["content"], "آخرین پرسش")
        self.assertEqual(cap["payload"]["messages"][0]["role"], "system")
        huge = fit_messages([{"role": "user", "content": "x" * 50000}], "s", 4096)
        self.assertLess(len(huge[0]["content"]), 7000)


if __name__ == "__main__":
    unittest.main()
