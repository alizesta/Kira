import time
import unittest
from unittest import mock

import requests

from tests import helpers
from tests.helpers import Resp, StreamResp, CANARY, ok_openai, ok_cloudflare, ok_ollama
from kira import hybrid_ai
from kira.hybrid_ai import HybridRouter, ProviderError, normalize_messages, probe_provider

MSGS = [{"role": "user", "content": "سلام"}]
SYS = "persona"


def router(*names, ollama=True):
    s = helpers.enable(helpers.fresh_settings(), *names)
    s["providers"]["ollama"]["enabled"] = ollama
    return HybridRouter(s)


def dispatch(table):
    """requests.post stand-in keyed by a substring of the URL; each value is a Resp, exception, or list (sequence)."""
    calls = []

    def fake(url, headers=None, json=None, timeout=None):
        calls.append((url, json, headers))
        for key, val in table.items():
            if key in url:
                if isinstance(val, list):
                    val = val.pop(0)
                if isinstance(val, Exception):
                    raise val
                return val
        raise AssertionError("unexpected url " + url)
    fake.calls = calls
    return fake


class ProviderTests(unittest.TestCase):
    def test_google_stream_does_not_retry_503_and_spend_daily_quota(self):
        provider = hybrid_ai.OpenAICompatibleProvider({
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "google-test-key",
            "model": "gemini-3.8-flash",
            "timeout": 60,
        }, name="custom-gemini")
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return Resp(503, text="overloaded")

        with mock.patch("requests.post", side_effect=post), mock.patch("kira.hybrid_ai.time.sleep") as sleep:
            with self.assertRaises(ProviderError) as cm:
                provider._open_stream(
                    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                    {"Authorization": "Bearer google-test-key"}, {"model": "gemini-3.8-flash"},
                )
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1]["stream"] is True)
        self.assertEqual(cm.exception.status_code, 503)
        sleep.assert_not_called()

    def test_non_google_provider_does_not_retry_503(self):
        provider = hybrid_ai.OpenAICompatibleProvider({
            "base_url": "https://example.com/v1", "api_key": "custom-test-key", "model": "test-model",
        }, name="custom")
        calls = []

        def post(url, **kwargs):
            calls.append(url)
            return Resp(503, text="unavailable")

        with mock.patch("requests.post", side_effect=post), mock.patch("kira.hybrid_ai.time.sleep") as sleep:
            with self.assertRaises(ProviderError) as cm:
                provider._post_json("https://example.com/v1/chat/completions", {}, {"model": "test-model"})
        self.assertEqual(len(calls), 1)
        self.assertEqual(cm.exception.status_code, 503)
        sleep.assert_not_called()

    def test_google_probe_does_not_repeat_503_generation_requests(self):
        cfg = {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "google-test-key",
            "model": "gemini-3.8-flash",
        }
        get = mock.Mock(return_value=Resp(200, {"models": [{"name": "models/gemini-3.8-flash"}]}))
        post = dispatch({"generativelanguage.googleapis.com": Resp(503, text="overloaded")})
        with mock.patch("requests.get", get), mock.patch("requests.post", post), \\
             mock.patch("kira.hybrid_ai.time.sleep") as sleep:
            ok, message = probe_provider("custom-google", cfg)
        self.assertFalse(ok)
        self.assertIn("503", message)
        self.assertEqual(len(post.calls), 1)
        sleep.assert_not_called()

    def test_probe_does_not_retry_quota_exhausted_429(self):
        cfg = {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "google-test-key",
            "model": "gemini-3.8-flash",
        }
        get = mock.Mock(return_value=Resp(200, {"models": [{"name": "models/gemini-3.8-flash"}]}))
        post = dispatch({"generativelanguage.googleapis.com": Resp(
            429, {"error": {"message": "Quota exceeded for requests per day, limit: 20"}}
        )})
        with mock.patch("requests.get", get), mock.patch("requests.post", post), \\
             mock.patch("kira.hybrid_ai.time.sleep") as sleep:
            ok, message = probe_provider("custom-google", cfg)
        self.assertFalse(ok)
        self.assertIn("429", message)
        self.assertEqual(len(post.calls), 1)
        sleep.assert_not_called()

    def test_provider_extracts_model_id_from_catalog_object(self):
        provider = hybrid_ai.MistralProvider({
            "api_key": "mistral-test-key",
            "model": {"id": "codestral-2508", "name": "Codestral", "context": 256000},
        })
        url, headers, payload = provider._prepare(MSGS, SYS, 0.7, False)
        self.assertEqual(provider.model, "codestral-2508")
        self.assertEqual(payload["model"], "codestral-2508")

    def test_google_model_resource_prefix_is_removed_before_chat_request(self):
        provider = hybrid_ai.OpenAICompatibleProvider({
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "google-test-key",
            "model": "models/gemini-3.8-flash",
        }, name="custom-google-ai-studio")
        url, headers, payload = provider._prepare(MSGS, SYS, 0.7, False)
        self.assertEqual(provider.model, "gemini-3.8-flash")
        self.assertEqual(payload["model"], "gemini-3.8-flash")
        self.assertTrue(url.endswith("/chat/completions"))

    def test_telemetry_records_provider_model_and_duration_without_chat_content(self):
        r = router("groq")
        r.settings["providers"]["groq"]["model"] = "test-model"
        captured = []
        with mock.patch.object(HybridRouter, "_write_telemetry", side_effect=captured.append), \
             mock.patch("requests.post", dispatch({"groq": ok_openai("private reply")})):
            self.assertEqual(r.chat(MSGS, SYS), "private reply")
        self.assertEqual(r.last_provider, "groq")
        self.assertEqual(r.last_model, "test-model")
        self.assertIsInstance(r.last_duration_ms, int)
        self.assertEqual(captured[0]["provider"], "groq")
        self.assertEqual(captured[0]["model"], "test-model")
        serialized = str(captured[0])
        self.assertNotIn("سلام", serialized)
        self.assertNotIn("private reply", serialized)
        self.assertNotIn("api_key", serialized)

    # 5) enable / disable
    def test_05_disabled_provider_is_never_called(self):
        r = router("groq", "cloudflare")
        r.settings["providers"]["groq"]["enabled"] = False
        f = dispatch({"cloudflare": ok_cloudflare("cf"), "groq": AssertionError("must not be called")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "cf")
        self.assertEqual(len(f.calls), 1)
        self.assertEqual(r.last_provider, "cloudflare")

    def test_05b_enabled_without_key_is_skipped(self):
        r = router("cloudflare")
        r.settings["providers"]["groq"].update({"enabled": True, "api_key": ""})
        f = dispatch({"cloudflare": ok_cloudflare("cf")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "cf")

    # 6) priority order
    def test_06_priority_order_respected(self):
        r = router("groq", "cloudflare", "mistral")
        r.settings["provider_order"] = ["mistral", "cloudflare", "groq", "openrouter", "ollama"]
        f = dispatch({"mistral": ok_openai("m"), "cloudflare": ok_cloudflare("c"), "groq": ok_openai("g")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "m")
        self.assertIn("mistral", f.calls[0][0])
        r.settings["provider_order"] = ["groq", "mistral", "cloudflare", "openrouter", "ollama"]
        r2 = HybridRouter(r.settings)
        f2 = dispatch({"mistral": ok_openai("m"), "cloudflare": ok_cloudflare("c"), "groq": ok_openai("g")})
        with mock.patch("requests.post", f2):
            self.assertEqual(r2.chat(MSGS, SYS), "g")

    def test_local_route_can_be_prioritized_before_cloud(self):
        r = router("groq", ollama=True)
        r.settings["provider_order"] = ["ollama", "groq", "cloudflare", "mistral", "openrouter"]
        with mock.patch("kira.hybrid_ai.OllamaClient.from_settings") as local, \
             mock.patch("requests.post", side_effect=AssertionError("cloud route must not run")):
            local.return_value.chat.return_value = "local-first"
            self.assertEqual(r.chat(MSGS, SYS), "local-first")
        self.assertEqual(r.last_provider, "ollama")

    # 7) Groq 429 -> Cloudflare
    def test_07_failover_groq_to_cloudflare(self):
        r = router("groq", "cloudflare")
        f = dispatch({"groq": Resp(429, {"error": {"message": "rate limit"}}), "cloudflare": ok_cloudflare("cf")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "cf")
        self.assertEqual(r.last_provider, "cloudflare")
        self.assertGreater(r.status()[0]["cooldown"], 0)

    # 8) Cloudflare -> OpenRouter (Groq disabled)
    def test_08_failover_cloudflare_to_openrouter(self):
        r = router("cloudflare", "openrouter")
        f = dispatch({"cloudflare": Resp(503, text="down"), "openrouter": ok_openai("or")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "or")
        self.assertEqual(r.last_provider, "openrouter")

    # 9) 429 and cooldown
    def test_09_429_cooldown_skips_provider_then_expires(self):
        r = router("groq", "cloudflare")
        f = dispatch({"groq": [Resp(429, {"error": "slow down"}), ok_openai("g-again")], "cloudflare": ok_cloudflare("cf")})
        with mock.patch("requests.post", f):
            r.chat(MSGS, SYS)                       # groq 429 -> cloudflare
            n = len(f.calls)
            r.chat(MSGS, SYS)                       # groq in cooldown -> not contacted
            self.assertFalse(any("groq" in c[0] for c in f.calls[n:]))
            r.cooldowns["groq"] = time.monotonic() - 1   # cooldown over
            self.assertEqual(r.chat(MSGS, SYS), "g-again")

    def test_09b_retry_after_header_used(self):
        r = router("groq", "cloudflare")
        f = dispatch({"groq": Resp(429, {"error": "x"}, headers={"Retry-After": "120"}), "cloudflare": ok_cloudflare()})
        with mock.patch("requests.post", f):
            r.chat(MSGS, SYS)
        left = r.cooldowns["groq"] - time.monotonic()
        self.assertTrue(100 < left <= 121, left)

    # 10) timeout and network errors
    def test_10_timeout_and_network_error_fail_over(self):
        for exc in (requests.Timeout("t"), requests.ConnectionError("dns failure")):
            r = router("groq", "cloudflare")
            f = dispatch({"groq": exc, "cloudflare": ok_cloudflare("cf")})
            with mock.patch("requests.post", f):
                self.assertEqual(r.chat(MSGS, SYS), "cf")
            self.assertGreater(r.cooldowns["groq"], time.monotonic())

    # 11) invalid API key
    def test_11_invalid_key_is_classified_and_skipped(self):
        r = router("groq", "cloudflare")
        f = dispatch({"groq": Resp(401, {"error": {"message": "Invalid API Key"}}), "cloudflare": ok_cloudflare("cf")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "cf")
        p = hybrid_ai.GroqProvider(r.settings["providers"]["groq"])
        with mock.patch("requests.post", dispatch({"groq": Resp(401, {"error": {"message": "Invalid API Key"}})})):
            with self.assertRaises(ProviderError) as cm:
                p.chat(MSGS, SYS)
        self.assertEqual(cm.exception.kind, "auth")
        self.assertFalse(cm.exception.retryable)

    # 12) invalid model id is NOT reported as a key problem
    def test_12_invalid_model_separated_from_auth(self):
        body = {"error": {"message": "The model `nope` does not exist or you do not have access to it.", "code": "model_not_found"}}
        for status in (404, 400):
            p = hybrid_ai.GroqProvider({"api_key": "k-123456", "model": "nope"})
            with mock.patch("requests.post", dispatch({"groq": Resp(status, body)})):
                with self.assertRaises(ProviderError) as cm:
                    p.chat(MSGS, SYS)
            self.assertEqual(cm.exception.kind, "model", status)
            self.assertIn("nope", str(cm.exception))
        p = hybrid_ai.GroqProvider({"api_key": "k-123456", "model": "m"})
        with mock.patch("requests.post", dispatch({"groq": Resp(400, {"error": {"message": "temperature out of range"}})})):
            with self.assertRaises(ProviderError) as cm:
                p.chat(MSGS, SYS)
        self.assertEqual(cm.exception.kind, "request")

    def test_12b_probe_groq_key_ok_model_missing(self):
        cfg = {"api_key": "gsk-test-key-1", "model": "retired/model"}
        get = mock.Mock(return_value=Resp(200, {"data": [{"id": "openai/gpt-oss-120b"}]}))
        with mock.patch("requests.get", get):
            ok, msg = probe_provider("groq", cfg)
        self.assertFalse(ok)
        self.assertIn("مدل", msg)
        self.assertNotIn("کلید یا دسترسی رد شد", msg)

    def test_12c_probe_groq_bad_key(self):
        get = mock.Mock(return_value=Resp(401, {"error": {"message": "Invalid API Key"}}))
        with mock.patch("requests.get", get):
            ok, msg = probe_provider("groq", {"api_key": "gsk-bad-key-1", "model": "openai/gpt-oss-120b"})
        self.assertFalse(ok)
        self.assertIn("401", msg)

    def test_12d_probe_sends_user_message_and_succeeds(self):
        get = mock.Mock(return_value=Resp(200, {"data": [{"id": "openai/gpt-oss-120b"}]}))
        post = dispatch({"api.groq.com/openai/v1/chat/completions": ok_openai("OK")})
        with mock.patch("requests.get", get), mock.patch("requests.post", post):
            ok, msg = probe_provider("groq", {"api_key": "gsk-good-key-1", "model": "openai/gpt-oss-120b"})
        self.assertTrue(ok, msg)
        roles = [m["role"] for m in post.calls[0][1]["messages"]]
        self.assertEqual(roles, ["system", "user"])          # regression: 1.4.5 sent only a system message
        self.assertTrue(post.calls[0][0].endswith("/chat/completions"))
        self.assertEqual(post.calls[0][2]["Authorization"], "Bearer gsk-good-key-1")

    def test_12e_probe_other_providers_need_user_message(self):
        for name in ("cloudflare", "openrouter"):
            cfg = {"api_key": "key-abcdef", "model": "m/x", "account_id": "acc"}
            post = dispatch({"": ok_cloudflare("OK") if name == "cloudflare" else ok_openai("OK")})
            with mock.patch("requests.post", post):
                ok, msg = probe_provider(name, cfg)
            self.assertTrue(ok, msg)
            self.assertEqual(post.calls[0][1]["messages"][-1]["role"], "user")

    # 13) all clouds fail -> Ollama
    def test_13_all_cloud_fail_goes_to_ollama(self):
        r = router("groq", "cloudflare", "mistral", "openrouter")
        f = dispatch({"groq": Resp(500), "cloudflare": requests.Timeout(), "mistral": Resp(401, {"error": "x"}),
                      "openrouter": Resp(429, {}), "11434": ok_ollama("local")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "local")
        self.assertEqual(r.last_provider, "ollama")
        self.assertIn("groq", r.last_error)

    def test_13b_ollama_disabled_is_respected(self):
        r = router("groq", ollama=False)
        f = dispatch({"groq": Resp(500)})
        with mock.patch("requests.post", f):
            with self.assertRaises(RuntimeError) as cm:
                r.chat(MSGS, SYS)
        self.assertFalse(any("11434" in c[0] for c in f.calls))
        self.assertIn("غیرفعال", str(cm.exception))

    # 14) one provider's failure never escapes / crashes the app
    def test_14_unexpected_exception_in_provider_is_contained(self):
        r = router("groq", "cloudflare")
        f = dispatch({"groq": RuntimeError("boom"), "cloudflare": ok_cloudflare("cf")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "cf")
        f = dispatch({"groq": Resp(200, text="<html>not json</html>"), "cloudflare": ok_cloudflare("cf")})
        r = router("groq", "cloudflare")
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "cf")

    def test_14b_everything_down_raises_one_readable_error(self):
        r = router("groq")
        f = dispatch({"groq": Resp(500), "11434": requests.ConnectionError("refused")})
        with mock.patch("requests.post", f):
            with self.assertRaises(RuntimeError) as cm:
                r.chat(MSGS, SYS)
        msg = str(cm.exception)
        self.assertIn("groq", msg)
        self.assertIn("ollama", msg)
        self.assertIn("Ollama", msg)

    # 15) history + persona identical for every provider
    def test_15_history_and_persona_reach_every_provider(self):
        history = [{"role": "user", "content": "اسم من علی است"}, {"role": "assistant", "content": "[happy]\nباشه"},
                   {"role": "user", "content": "اسمم چی بود؟"}]
        persona = "تو کیرا هستی"
        sent = {}
        for name in ("groq", "mistral", "openrouter", "cloudflare", "ollama"):
            r = router(*([] if name == "ollama" else [name]))
            url_key = {"groq": "groq", "mistral": "mistral", "openrouter": "openrouter", "cloudflare": "cloudflare", "ollama": "11434"}[name]
            reply = {"cloudflare": ok_cloudflare(), "ollama": ok_ollama()}.get(name, ok_openai())
            f = dispatch({url_key: reply})
            with mock.patch("requests.post", f):
                r.chat(history, persona)
            sent[name] = f.calls[0][1]["messages"]
        reference = sent["groq"]
        self.assertEqual(reference[0], {"role": "system", "content": persona})
        self.assertEqual([m["content"] for m in reference[1:]], [m["content"] for m in history])
        for name, msgs in sent.items():
            self.assertEqual(msgs, reference, name)

    def test_15b_normalize_messages(self):
        got = normalize_messages([{"role": "assistant", "content": "orphan"}, {"role": "user", "content": "a"},
                                  {"role": "user", "content": "b"}, {"role": "system", "content": "x"},
                                  {"role": "assistant", "content": "  "}, {"role": "assistant", "content": "ans"}])
        self.assertEqual(got, [{"role": "user", "content": "a\n\nb"}])   # 1.4.5 sent consecutive user turns as-is
        self.assertEqual(normalize_messages([]), [])

    def test_key_never_appears_in_errors(self):
        key = CANARY + "-groq"
        p = hybrid_ai.GroqProvider({"api_key": key, "model": "m"})
        leaks = [Resp(401, {"error": {"message": f"bad key {key}"}}), Resp(400, text=f"echo {key}"),
                 requests.ConnectionError(f"url with {key}")]
        for item in leaks:
            with mock.patch("requests.post", dispatch({"groq": item})):
                with self.assertRaises(ProviderError) as cm:
                    p.chat(MSGS, SYS)
            self.assertNotIn(key, str(cm.exception))
        r = router("groq")
        with mock.patch("requests.post", dispatch({"groq": Resp(401, {"error": {"message": key}}), "11434": requests.ConnectionError("x")})):
            with self.assertRaises(RuntimeError) as cm:
                r.chat(MSGS, SYS)
        self.assertNotIn(key, str(cm.exception))
        self.assertNotIn(key, r.last_error or "")

    def test_status_reports_cooldown_and_enabled(self):
        r = router("groq")
        st = {x["name"]: x for x in r.status()}
        self.assertTrue(st["groq"]["enabled"])
        self.assertFalse(st["mistral"]["enabled"])
        self.assertEqual(st["ollama"]["enabled"], True)


if __name__ == "__main__":
    unittest.main()
