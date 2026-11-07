"""Route-based router (non-streaming path): priority, manual choice, per-route cooldown/timeout, failover scenarios."""
import time
import unittest
from unittest import mock

import requests

from tests import helpers
from tests.helpers import Resp, CANARY, ok_openai, ok_cloudflare, ok_ollama
from kira import routes
from kira.hybrid_ai import HybridRouter

MSGS = [{"role": "user", "content": "سلام"}]
SYS = "persona"


def make(*names, ollama=True):
    s = helpers.enable(helpers.fresh_settings(), *names)
    s["providers"]["ollama"]["enabled"] = ollama
    routes.ensure_routes(s)
    return s, HybridRouter(s)


def dispatch(table):
    calls = []

    def fake(url, headers=None, json=None, timeout=None, **kw):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
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


class RouterRouteTests(unittest.TestCase):
    def test_two_models_of_one_provider_are_independent_routes(self):
        s, r = make("groq")
        routes.add_route(s, "groq", "second-model")
        routes.reorder(s, ["groq-2", "groq"])
        f = dispatch({"groq": [Resp(500), ok_openai("from-first-route")]})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "from-first-route")
        self.assertEqual([c["json"]["model"] for c in f.calls], ["second-model", "openai/gpt-oss-120b"])
        self.assertEqual(r.last_route_id, "groq")
        self.assertEqual(r.last_model, "openai/gpt-oss-120b")

    def test_cooldown_is_per_route_not_per_provider(self):
        s, r = make("groq")
        routes.add_route(s, "groq", "other")
        routes.reorder(s, ["groq", "groq-2"])
        f = dispatch({"groq": [Resp(429, {"error": "x"}), ok_openai("second"), ok_openai("again")]})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "second")           # groq cools down, groq-2 answers
            self.assertGreater(r.cooldowns["groq"], time.monotonic())
            self.assertNotIn("groq-2", r.cooldowns)
            self.assertEqual(r.chat(MSGS, SYS), "again")            # next time groq is skipped, groq-2 used directly
        self.assertEqual(len(f.calls), 3)
        self.assertEqual(f.calls[2]["json"]["model"], "other")

    def test_disabled_route_is_skipped_but_keeps_settings(self):
        s, r = make("groq", "cloudflare")
        routes.set_enabled(s, "groq", False)
        f = dispatch({"cloudflare": ok_cloudflare("cf"), "groq": AssertionError("must not run")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "cf")
        self.assertEqual(s["providers"]["groq"]["api_key"], f"{CANARY}-groq")
        routes.set_enabled(s, "groq", True)
        with mock.patch("requests.post", dispatch({"groq": ok_openai("g")})):
            self.assertEqual(r.chat(MSGS, SYS), "g")

    def test_manual_choice_beats_priority_and_failover_still_works(self):
        s, r = make("groq", "cloudflare", "mistral")
        routes.set_manual(s, "mistral")
        f = dispatch({"mistral": ok_openai("m"), "groq": ok_openai("g")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "m")
        self.assertIn("mistral", f.calls[0]["url"])
        f = dispatch({"mistral": Resp(500), "groq": ok_openai("g")})
        r.reset_cooldowns()
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "g")                # failover moves on in priority order
        self.assertEqual(r.last_provider, "groq")

    def test_manual_choice_without_failover_never_leaves_the_chosen_route(self):
        s, r = make("groq", "cloudflare")
        routes.set_manual(s, "cloudflare")
        s["failover_enabled"] = False
        f = dispatch({"cloudflare": Resp(500), "groq": AssertionError("no failover allowed")})
        with mock.patch("requests.post", f):
            with self.assertRaises(RuntimeError) as cm:
                r.chat(MSGS, SYS)
        self.assertIn("cloudflare", str(cm.exception))
        self.assertEqual(len(f.calls), 1)

    def test_manual_route_that_is_disabled_falls_back_to_auto(self):
        s, r = make("groq", "cloudflare")
        routes.set_manual(s, "cloudflare")
        routes.set_enabled(s, "cloudflare", False)
        with mock.patch("requests.post", dispatch({"groq": ok_openai("g")})):
            self.assertEqual(r.chat(MSGS, SYS), "g")

    def test_per_route_timeout_reaches_requests_and_cooldown_override(self):
        s, r = make("groq", "cloudflare")
        routes.update_route(s, "groq", timeout=7, cooldown=0)
        f = dispatch({"groq": requests.Timeout("t"), "cloudflare": ok_cloudflare("cf")})
        with mock.patch("requests.post", f):
            r.chat(MSGS, SYS)
        self.assertEqual(f.calls[0]["timeout"], 7)
        self.assertEqual(f.calls[1]["timeout"], 18)
        self.assertNotIn("groq", r.cooldowns)                      # cooldown=0 -> may be retried immediately

    def test_custom_local_provider_works_without_key(self):
        s, r = make()
        pid = routes.add_provider(s, "LM Studio", "http://localhost:1234/v1", local=True)
        routes.add_route(s, pid, "qwen-7b")
        routes.set_manual(s, pid + "")
        f = dispatch({"localhost:1234": ok_openai("lm")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "lm")
        self.assertNotIn("Authorization", f.calls[0]["headers"])
        self.assertTrue(f.calls[0]["url"].endswith("/v1/chat/completions"))
        self.assertEqual(r.last_kind, "local")

    def test_custom_cloud_provider_needs_key(self):
        s, r = make()
        pid = routes.add_provider(s, "Together", "https://api.together.xyz/v1", api_key="")
        routes.add_route(s, pid, "m")
        with mock.patch("requests.post", side_effect=AssertionError("no key -> never called")):
            with self.assertRaises(RuntimeError):
                r.chat(MSGS, SYS)

    def test_duplicate_request_is_refused_while_one_is_running(self):
        s, r = make("groq")
        inner = {}

        def slow(url, headers=None, json=None, timeout=None, **kw):
            try:
                r.chat(MSGS, SYS)                                    # a second request while the first is in flight
            except RuntimeError as exc:
                inner["err"] = str(exc)
            return ok_openai("first")
        with mock.patch("requests.post", slow):
            self.assertEqual(r.chat(MSGS, SYS), "first")
        self.assertIn("تکراری", inner["err"])
        self.assertFalse(r.busy)

    def test_lock_is_released_after_failure(self):
        s, r = make("groq", ollama=False)
        with mock.patch("requests.post", dispatch({"groq": Resp(500)})):
            with self.assertRaises(RuntimeError):
                r.chat(MSGS, SYS)
        self.assertFalse(r.busy)

    def test_preview_route_available_routes_and_status_health(self):
        s, r = make("groq", "cloudflare")
        self.assertEqual(r.preview_route()["route_id"], "groq")
        routes.set_manual(s, "cloudflare")
        self.assertEqual(r.preview_route()["route_id"], "cloudflare")
        self.assertEqual({x["route_id"] for x in r.available_routes()}, {"groq", "cloudflare", "ollama"})
        routes.set_manual(s, "")
        with mock.patch("requests.post", dispatch({"groq": Resp(401, {"error": "bad"}), "cloudflare": ok_cloudflare("c")})):
            r.chat(MSGS, SYS)
        st = {x["name"]: x for x in r.status()}
        self.assertEqual(st["groq"]["health"], "down")
        self.assertIn("401", st["groq"]["last_error"])
        self.assertEqual(st["cloudflare"]["health"], "healthy")
        self.assertIsInstance(st["cloudflare"]["last_ms"], int)
        self.assertEqual(r.preview_route()["route_id"], "cloudflare")     # groq is cooling down -> not offered as next

    def test_ollama_offline_has_no_cooldown_but_ollama_timeout_does(self):
        s, r = make(ollama=True)
        with mock.patch("requests.post", side_effect=requests.ConnectionError("refused")):
            with self.assertRaises(RuntimeError):
                r.chat(MSGS, SYS)
        self.assertNotIn("ollama", r.cooldowns)
        with mock.patch("requests.post", side_effect=requests.Timeout("slow")):
            with self.assertRaises(RuntimeError):
                r.chat(MSGS, SYS)
        self.assertIn("ollama", r.cooldowns)

    def test_second_ollama_model_route_sends_its_own_model(self):
        s, r = make(ollama=True)
        routes.add_route(s, "ollama", "llama3.2:3b", num_ctx=2048, num_predict=96)
        routes.set_manual(s, "ollama-2")
        f = dispatch({"11434": ok_ollama("local-2")})
        with mock.patch("requests.post", f):
            self.assertEqual(r.chat(MSGS, SYS), "local-2")
        sent = f.calls[0]["json"]
        self.assertEqual((sent["model"], sent["options"]["num_ctx"], sent["options"]["num_predict"]), ("llama3.2:3b", 2048, 96))
        self.assertEqual(r.last_model, "llama3.2:3b")

    def test_test_route_updates_health_without_leaking_key(self):
        s, r = make("groq")
        get = mock.Mock(return_value=Resp(401, {"error": {"message": f"bad {CANARY}-groq"}}))
        with mock.patch("requests.get", get):
            ok, msg, ms = r.test_route("groq")
        self.assertFalse(ok)
        self.assertNotIn(CANARY, msg)
        self.assertEqual(r.states["groq"]["health"], "down")
        get = mock.Mock(return_value=Resp(200, {"data": [{"id": "openai/gpt-oss-120b"}]}))
        with mock.patch("requests.get", get), mock.patch("requests.post", dispatch({"groq": ok_openai("OK")})):
            ok, msg, ms = r.test_route("groq")
        self.assertTrue(ok)
        self.assertEqual(r.states["groq"]["health"], "healthy")
        self.assertFalse(r.test_route("nope")[0])

    # ---- 5.2 failover scenarios: every one must end predictably (answer from the next route, or ONE readable error) ----
    def test_failover_scenarios_are_predictable(self):
        cases = {
            "internet down": requests.ConnectionError("Failed to resolve"),
            "invalid key 401": Resp(401, {"error": {"message": "Invalid API Key"}}),
            "rate limit 429": Resp(429, {"error": "slow"}),
            "server 500": Resp(500, text="boom"),
            "timeout": requests.Timeout("t"),
            "garbage body": Resp(200, text="<html>"),
            "provider crashes": RuntimeError("boom"),
        }
        for name, failure in cases.items():
            s, r = make("groq", "cloudflare")
            with mock.patch("requests.post", dispatch({"groq": failure, "cloudflare": ok_cloudflare("backup")})):
                self.assertEqual(r.chat(MSGS, SYS), "backup", name)
            self.assertEqual(r.last_provider, "cloudflare", name)
            self.assertIn("groq", r.last_error, name)
            self.assertFalse(r.busy, name)
            s2, r2 = make("groq", ollama=False)
            with mock.patch("requests.post", dispatch({"groq": failure})):
                with self.assertRaises(RuntimeError) as cm:
                    r2.chat(MSGS, SYS)
            self.assertIn("تمام Routeهای فعال ناموفق", str(cm.exception), name)
            self.assertNotIn(CANARY, str(cm.exception), name)

    def test_provider_disabled_and_cooldown_active_and_ollama_down(self):
        s, r = make("groq", "cloudflare")
        s["providers"]["groq"]["enabled"] = False
        with mock.patch("requests.post", dispatch({"cloudflare": ok_cloudflare("cf")})):
            self.assertEqual(r.chat(MSGS, SYS), "cf")
        s["providers"]["groq"]["enabled"] = True
        r.cooldowns["groq"] = time.monotonic() + 100
        with mock.patch("requests.post", dispatch({"cloudflare": ok_cloudflare("cf2"), "groq": AssertionError("cooling")})):
            self.assertEqual(r.chat(MSGS, SYS), "cf2")
        self.assertTrue(any(a.get("result") == "cooldown" for a in r.last_attempts))
        s3, r3 = make(ollama=True)
        with mock.patch("requests.post", side_effect=requests.ConnectionError("refused")):
            with self.assertRaises(RuntimeError) as cm:
                r3.chat(MSGS, SYS)
        self.assertIn("Ollama", str(cm.exception))

    def test_telemetry_has_speed_fields_and_no_content_or_key(self):
        s, r = make("groq")
        cap = []
        with mock.patch.object(HybridRouter, "_write_telemetry", side_effect=lambda rec, *a: cap.append(rec)), \
                mock.patch("requests.post", dispatch({"groq": ok_openai("private reply")})):
            r.chat(MSGS, SYS, 0.7)
        rec = cap[0]
        for key in ("request_id", "route_id", "kind", "connect_ms", "first_token_ms", "total_ms", "retries", "failovers"):
            self.assertIn(key, rec)
        text = str(rec)
        for bad in ("private reply", "سلام", CANARY, "api_key"):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
