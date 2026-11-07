"""Real streaming: SSE (OpenAI-style, Cloudflare) and NDJSON (Ollama); failover before the first token; partial answers; Stop."""
import time
import unittest
from unittest import mock

import requests

from tests import helpers
from tests.helpers import Resp, StreamResp, sse, ndjson, CANARY
from kira import routes, hybrid_ai
from kira.hybrid_ai import HybridRouter, ThinkFilter, ProviderError
from kira.ollama_client import OllamaClient, OllamaError

MSGS = [{"role": "user", "content": "سلام"}]
SYS = "persona"


def make(*names, ollama=False):
    s = helpers.enable(helpers.fresh_settings(), *names)
    s["providers"]["ollama"]["enabled"] = ollama
    routes.ensure_routes(s)
    return s, HybridRouter(s)


def post_table(table):
    calls = []

    def fake(url, headers=None, json=None, timeout=None, stream=False, **kw):
        calls.append({"url": url, "json": dict(json) if isinstance(json, dict) else json, "stream": stream, "timeout": timeout})
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


def run(router, **kw):
    chunks, events = [], []
    res = router.chat_stream(MSGS, SYS, 0.7, on_chunk=chunks.append, on_event=events.append, **kw)
    return res, chunks, events


class ThinkFilterTests(unittest.TestCase):
    def test_tags_split_across_chunks_are_removed(self):
        f = ThinkFilter()
        out = "".join(f.feed(p) for p in ["سلام <thi", "nk>فکر کردن</th", "ink> دنیا"]) + f.flush()
        self.assertEqual(out, "سلام  دنیا")

    def test_plain_text_and_partial_angle_bracket_are_kept(self):
        f = ThinkFilter()
        out = f.feed("a < b and <") + f.feed("p> ok") + f.flush()
        self.assertEqual(out, "a < b and <p> ok")


class ProviderStreamTests(unittest.TestCase):
    def test_openai_sse_chunks_in_order_skipping_noise(self):
        lines = [b": OPENROUTER PROCESSING", b"", b'data: {"choices":[{"delta":{"role":"assistant"}}]}', b""] + \
            sse("سل", "ام ", "دنیا") + [b"data: ignored-after-done"]
        resp = StreamResp(lines)
        p = hybrid_ai.GroqProvider({"api_key": "k-123456", "model": "m"})
        with mock.patch("requests.post", post_table({"groq": resp})):
            got = list(p.stream(MSGS, SYS))
        self.assertEqual(got, ["سل", "ام ", "دنیا"])
        self.assertTrue(resp.closed)

    def test_stream_flag_sent_and_streaming_request_made(self):
        f = post_table({"groq": StreamResp(sse("x"))})
        with mock.patch("requests.post", f):
            list(hybrid_ai.GroqProvider({"api_key": "k-123456", "model": "m"}).stream(MSGS, SYS))
        self.assertTrue(f.calls[0]["stream"])
        self.assertTrue(f.calls[0]["json"]["stream"])
        self.assertIsInstance(f.calls[0]["timeout"], tuple)

    def test_chunks_are_delivered_before_the_rest_is_read(self):
        resp = StreamResp(sse("a", "b", "c"))
        p = hybrid_ai.GroqProvider({"api_key": "k-123456", "model": "m"})
        with mock.patch("requests.post", post_table({"groq": resp})):
            it = p.stream(MSGS, SYS)
            self.assertEqual(next(it), "a")
            self.assertLess(resp.consumed, len(resp._lines))          # not read to the end yet: truly incremental
            it.close()
        self.assertTrue(resp.closed)

    def test_cloudflare_sse_response_field(self):
        objs = [{"response": "سلام"}, {"response": " کیرا"}]
        resp = StreamResp(sse(*objs))
        p = hybrid_ai.CloudflareProvider({"api_key": "k-123456", "model": "@cf/m", "account_id": "a"})
        with mock.patch("requests.post", post_table({"cloudflare": resp})):
            self.assertEqual("".join(p.stream(MSGS, SYS)), "سلام کیرا")

    def test_http_errors_are_classified_before_streaming_starts(self):
        for status, kind in ((401, "auth"), (429, "rate"), (500, "server"), (404, "model")):
            p = hybrid_ai.GroqProvider({"api_key": "k-123456", "model": "m"})
            resp = StreamResp([], status=status, body={"error": {"message": "x"}})
            with mock.patch("requests.post", post_table({"groq": resp})):
                with self.assertRaises(ProviderError) as cm:
                    list(p.stream(MSGS, SYS))
            self.assertEqual(cm.exception.kind, kind)
            self.assertTrue(resp.closed)

    def test_mid_stream_error_object_and_dropped_connection(self):
        p = hybrid_ai.GroqProvider({"api_key": "k-123456", "model": "m"})
        resp = StreamResp(sse("a", {"error": {"message": "overloaded"}}, done=False))
        with mock.patch("requests.post", post_table({"groq": resp})):
            it = p.stream(MSGS, SYS)
            self.assertEqual(next(it), "a")
            with self.assertRaises(ProviderError) as cm:
                next(it)
        self.assertEqual(cm.exception.kind, "server")
        resp = StreamResp(sse("a", done=False) + [requests.ConnectionError("reset")])
        with mock.patch("requests.post", post_table({"groq": resp})):
            it = p.stream(MSGS, SYS)
            next(it)
            with self.assertRaises(ProviderError) as cm:
                next(it)
        self.assertEqual(cm.exception.kind, "network")

    def test_key_not_leaked_by_stream_errors(self):
        key = CANARY + "-groq"
        p = hybrid_ai.GroqProvider({"api_key": key, "model": "m"})
        with mock.patch("requests.post", post_table({"groq": requests.ConnectionError(f"url {key}")})):
            with self.assertRaises(ProviderError) as cm:
                list(p.stream(MSGS, SYS))
        self.assertNotIn(key, str(cm.exception))

    def test_ollama_ndjson_stream_strips_think_and_records_stats(self):
        c = OllamaClient("http://localhost:11434", "qwen3.5:4b")
        resp = StreamResp(ndjson("<think>hm", "m</think>سلا", "م!"))
        connected = []
        with mock.patch("requests.post", post_table({"11434": resp})) as _:
            out = list(c.stream(MSGS, SYS, 0.5, on_connect=lambda: connected.append(1)))
        self.assertEqual("".join(out), "سلام!")
        self.assertEqual(connected, [1])
        self.assertEqual(c.last_stats["eval_tokens"], 10)
        self.assertEqual(c.last_stats["load_ms"], 2000)
        self.assertTrue(resp.closed)

    def test_ollama_stream_payload_and_think_fallback_and_missing_model(self):
        c = OllamaClient("http://localhost:11434", "m", num_ctx=2048, keep_alive="5m", num_predict=100)
        first = StreamResp([], status=400, body={"error": "model does not support think"}, headers={})
        first.text = "does not support think"
        second = StreamResp(ndjson("ok"))
        f = post_table({"11434": [first, second]})
        with mock.patch("requests.post", f):
            self.assertEqual("".join(c.stream(MSGS, SYS)), "ok")
        self.assertIn("think", f.calls[0]["json"])
        self.assertNotIn("think", f.calls[1]["json"])
        self.assertEqual((f.calls[1]["json"]["stream"], f.calls[1]["json"]["keep_alive"], f.calls[1]["json"]["options"]["num_ctx"]), (True, "5m", 2048))
        gone = StreamResp([], status=404, body={"error": "model not found"})
        with mock.patch("requests.post", post_table({"11434": gone})), mock.patch("requests.get", side_effect=requests.ConnectionError("x")):
            with self.assertRaises(OllamaError) as cm:
                list(c.stream(MSGS, SYS))
        self.assertEqual(cm.exception.kind, "missing")

    def test_ollama_offline_and_mid_stream_drop(self):
        c = OllamaClient("http://localhost:11434", "m")
        with mock.patch("requests.post", side_effect=requests.ConnectionError("refused")):
            with self.assertRaises(OllamaError) as cm:
                list(c.stream(MSGS, SYS))
        self.assertEqual(cm.exception.kind, "offline")
        resp = StreamResp(ndjson("a", stats=False) + [requests.ConnectionError("reset")])
        with mock.patch("requests.post", post_table({"11434": resp})):
            it = c.stream(MSGS, SYS)
            self.assertEqual(next(it), "a")
            with self.assertRaises(OllamaError) as cm:
                next(it)
        self.assertEqual(cm.exception.kind, "network")


class RouterStreamTests(unittest.TestCase):
    def test_events_follow_connecting_waiting_streaming_with_real_route(self):
        s, r = make("groq")
        with mock.patch("requests.post", post_table({"groq": StreamResp(sse("a", "b"))})):
            res, chunks, events = run(r)
        self.assertEqual(chunks, ["a", "b"])
        self.assertEqual(res["text"], "ab")
        self.assertEqual([e["phase"] for e in events], ["connecting", "waiting", "streaming"])
        self.assertTrue(all(e["provider"] == "groq" and e["model"] == "openai/gpt-oss-120b" and e["kind"] == "cloud" for e in events))
        m = res["metrics"]
        self.assertEqual((res["stopped"], res["interrupted"], m["retries"], m["failovers"]), (False, None, 0, 0))
        self.assertLessEqual(m["connect_ms"], m["first_token_ms"])
        self.assertLessEqual(m["first_token_ms"], m["total_ms"])
        self.assertEqual(r.last_provider, "groq")
        self.assertFalse(r.busy)

    def test_failover_before_first_token_then_streams_from_next_route(self):
        s, r = make("groq", "cloudflare")
        f = post_table({"groq": Resp(500), "cloudflare": StreamResp(sse({"response": "cf"}))})
        with mock.patch("requests.post", f):
            res, chunks, events = run(r)
        self.assertEqual(chunks, ["cf"])
        self.assertEqual(res["provider"], "cloudflare")
        self.assertEqual(res["metrics"]["failovers"], 1)
        phases = [(e["phase"], e["provider"]) for e in events]
        self.assertEqual(phases[0], ("connecting", "groq"))
        self.assertIn(("failover", "cloudflare"), phases)
        self.assertEqual(phases[-1], ("streaming", "cloudflare"))

    def test_empty_stream_counts_as_failure_and_fails_over(self):
        s, r = make("groq", "cloudflare")
        f = post_table({"groq": StreamResp(sse(done=True)), "cloudflare": StreamResp(sse({"response": "ok"}))})
        with mock.patch("requests.post", f):
            res, chunks, _ = run(r)
        self.assertEqual(res["text"], "ok")
        self.assertEqual(r.states["groq"]["last_kind"], "empty")

    def test_connection_lost_after_partial_text_never_repeats_or_fails_over(self):
        s, r = make("groq", "cloudflare")
        groq = StreamResp(sse("نیمه‌ی ", "اول", done=False) + [requests.ConnectionError("reset by peer")])
        f = post_table({"groq": groq, "cloudflare": AssertionError("must NOT restart the answer elsewhere")})
        with mock.patch("requests.post", f):
            res, chunks, events = run(r)
        self.assertEqual(res["text"], "نیمه‌ی اول")
        self.assertEqual(chunks, ["نیمه‌ی ", "اول"])                    # shown once, exactly as received
        self.assertIsNotNone(res["interrupted"])
        self.assertEqual(len(f.calls), 1)
        self.assertEqual(res["metrics"]["result"], "interrupted")
        self.assertEqual(r.states["groq"]["health"], "degraded")
        self.assertFalse(r.busy)

    def test_stop_button_keeps_partial_text_and_does_not_penalise_the_route(self):
        s, r = make("groq", "cloudflare")
        resp = StreamResp(sse("a", "b", "c", "d", done=False))
        chunks = []

        def on_chunk(c):
            chunks.append(c)
            if len(chunks) == 2:
                r.cancel()                                          # user presses Stop after two chunks
        with mock.patch("requests.post", post_table({"groq": resp, "cloudflare": AssertionError("no failover on Stop")})):
            res = r.chat_stream(MSGS, SYS, on_chunk=on_chunk)
        self.assertTrue(res["stopped"])
        self.assertEqual(res["text"], "ab")
        self.assertTrue(resp.closed)
        self.assertNotIn("groq", r.cooldowns)
        self.assertEqual(res["metrics"]["result"], "stopped")
        with mock.patch("requests.post", post_table({"groq": StreamResp(sse("fresh"))})):
            res2, _, _ = run(r)                                      # next request starts clean
        self.assertEqual(res2["text"], "fresh")
        self.assertFalse(res2["stopped"])

    def test_stop_before_any_token_returns_empty_stopped_result(self):
        s, r = make("groq", "cloudflare")

        calls = []

        def fake(url, **kw):
            calls.append(url)
            r.cancel()
            raise requests.ConnectionError("closed by abort")
        with mock.patch("requests.post", fake):
            res = r.chat_stream(MSGS, SYS)
        self.assertTrue(res["stopped"])
        self.assertEqual(res["text"], "")
        self.assertEqual(len(calls), 1)

    def test_ollama_route_streams_and_reports_resolved_model_and_stats(self):
        s, r = make(ollama=True)
        resp = StreamResp(ndjson("س", "لام"))
        with mock.patch("requests.post", post_table({"11434": resp})):
            res, chunks, events = run(r)
        self.assertEqual(res["text"], "سلام")
        self.assertEqual((res["provider"], res["kind"]), ("ollama", "local"))
        self.assertEqual(res["metrics"]["load_ms"], 2000)
        self.assertEqual(events[0]["kind"], "local")

    def test_cloud_429_before_stream_sets_cooldown_and_next_route_answers(self):
        s, r = make("groq", "mistral")
        f = post_table({"groq": Resp(429, {"error": "x"}, headers={"Retry-After": "90"}), "mistral": StreamResp(sse("m"))})
        with mock.patch("requests.post", f):
            res, _, _ = run(r)
        self.assertEqual(res["provider"], "mistral")
        self.assertTrue(80 < r.cooldowns["groq"] - time.monotonic() <= 91)

    def test_all_routes_fail_raises_one_readable_error_and_releases_lock(self):
        s, r = make("groq")
        with mock.patch("requests.post", post_table({"groq": requests.ConnectionError("down")})):
            with self.assertRaises(RuntimeError) as cm:
                r.chat_stream(MSGS, SYS)
        self.assertIn("تمام Routeهای فعال ناموفق", str(cm.exception))
        self.assertFalse(r.busy)
        self.assertEqual(r.metrics[-1]["result"], "failed")

    def test_retry_index_is_recorded_and_duplicate_stream_refused(self):
        s, r = make("groq")
        inner = {}

        def lines():
            try:
                r.chat_stream(MSGS, SYS)
            except RuntimeError as exc:
                inner["err"] = str(exc)
        resp = StreamResp(sse("a") )
        resp._lines.insert(0, lines)
        with mock.patch("requests.post", post_table({"groq": resp})):
            res, _, _ = run(r, retry_index=1)
        self.assertEqual(res["metrics"]["retries"], 1)
        self.assertIn("تکراری", inner["err"])

    def test_telemetry_of_streamed_request_has_timings_and_no_text(self):
        s, r = make("groq")
        cap = []
        with mock.patch.object(HybridRouter, "_write_telemetry", side_effect=lambda rec, *a: cap.append(rec)), \
                mock.patch("requests.post", post_table({"groq": StreamResp(sse("private streamed text"))})):
            run(r)
        rec = cap[0]
        self.assertTrue(rec["stream"])
        self.assertIsNotNone(rec["first_token_ms"])
        for bad in ("private streamed text", "سلام", CANARY):
            self.assertNotIn(bad, str(rec))

    def test_benchmark_runs_routes_one_by_one_and_reports_speed(self):
        s, r = make("groq", "cloudflare", ollama=True)
        order = []

        def fake(url, **kw):
            order.append(url)
            if "groq" in url:
                return StreamResp(sse("x" * 20, "y" * 20))
            if "cloudflare" in url:
                return Resp(500, text="down")
            return StreamResp(ndjson("hello", " world"))
        progress = []
        ps = Resp(200, {"models": [{"name": "qwen3.5:4b", "size": 4_000_000_000, "size_vram": 3_000_000_000}]})
        with mock.patch("requests.post", fake), mock.patch("requests.get", return_value=ps):
            rows = r.benchmark(["groq", "cloudflare", "ollama"], on_progress=progress.append)
        self.assertEqual((rows[2]["gpu_pct"], rows[2]["model_gb"]), (75, 4.0))          # RAM/VRAM split of the local model
        self.assertEqual([x["route_id"] for x in rows], ["groq", "cloudflare", "ollama"])
        self.assertEqual(len(order), 3)                                  # sequential, one request per route
        self.assertTrue(rows[0]["ok"] and rows[0]["first_token_ms"] is not None)
        self.assertFalse(rows[1]["ok"])
        self.assertTrue(rows[2]["ok"] and rows[2]["unit"] == "tok/s" and rows[2]["speed"] == 10.0)
        self.assertEqual([p["phase"] for p in progress].count("done"), 3)
        self.assertEqual(len(r.benchmarks), 3)

    def test_benchmark_never_leaks_key(self):
        s, r = make("groq")
        with mock.patch("requests.post", post_table({"groq": requests.ConnectionError(f"x {CANARY}-groq")})):
            rows = r.benchmark(["groq"])
        self.assertNotIn(CANARY, str(rows))


if __name__ == "__main__":
    unittest.main()
