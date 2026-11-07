"""5.4 stability: hundreds of requests, memory growth, threads, bounded histories, failures that keep happening."""
import gc
import threading
import tracemalloc
import unittest
from unittest import mock

import requests

from tests import helpers
from tests.helpers import Resp, StreamResp, sse, ndjson
from kira import routes
from kira.hybrid_ai import HybridRouter, METRICS_KEEP

MSGS = [{"role": "user", "content": "سلام"}]


def make():
    s = helpers.enable(helpers.fresh_settings(), "groq", "cloudflare")
    s["providers"]["ollama"]["enabled"] = True
    routes.ensure_routes(s)
    return s, HybridRouter(s)


class StabilityTests(unittest.TestCase):
    def test_many_requests_do_not_leak_memory_or_threads(self):
        s, r = make()
        n = {"i": 0}

        def fake(url, **kw):
            n["i"] += 1
            if n["i"] % 7 == 0:
                return Resp(500, text="boom")                               # some failures along the way
            if "groq" in url:
                return StreamResp(sse("x" * 200))
            if "cloudflare" in url:
                return StreamResp(sse({"response": "y" * 200}))
            return StreamResp(ndjson("z" * 200))
        with mock.patch("requests.post", fake):
            for _ in range(60):                                              # warm-up
                r.chat_stream(MSGS, "p")
                r.cooldowns.clear()
            gc.collect()
            threads = threading.active_count()
            tracemalloc.start()
            before = tracemalloc.take_snapshot()
            for _ in range(600):
                r.chat_stream(MSGS, "p")
                r.cooldowns.clear()
            gc.collect()
            after = tracemalloc.take_snapshot()
            tracemalloc.stop()
        growth = sum(stat.size_diff for stat in after.compare_to(before, "filename"))
        self.assertLess(growth, 1_500_000, f"memory grew by {growth} bytes over 600 requests")      # bounded history, no leak
        self.assertEqual(threading.active_count(), threads)
        self.assertEqual(len(r.metrics), METRICS_KEEP)
        self.assertLessEqual(len(r.last_attempts), 10)
        self.assertFalse(r.busy)

    def test_failing_route_every_time_stays_predictable(self):
        s, r = make()
        helpers.enable(s)
        s["providers"]["ollama"]["enabled"] = False
        routes.set_enabled(s, "cloudflare", False)
        with mock.patch("requests.post", return_value=Resp(500, text="down")) as post:
            for i in range(20):
                with self.assertRaises(RuntimeError):
                    r.chat_stream(MSGS, "p")
            self.assertEqual(post.call_count, 1)             # cooldown stops hammering a broken provider
        self.assertFalse(r.busy)
        self.assertLessEqual(len(r.metrics), METRICS_KEEP)

    def test_route_changed_between_requests_takes_effect_immediately(self):
        s, r = make()
        calls = []

        def fake(url, **kw):
            calls.append(url)
            return StreamResp(sse("g")) if "groq" in url else StreamResp(sse({"response": "c"}))
        with mock.patch("requests.post", fake):
            r.chat_stream(MSGS, "p")
            routes.reorder(s, ["cloudflare", "groq"])
            r.chat_stream(MSGS, "p")
            routes.set_manual(s, "groq")
            r.chat_stream(MSGS, "p")
        self.assertEqual([("groq" in u) for u in calls], [True, False, True])

    def test_cancel_flag_does_not_leak_into_the_next_request(self):
        s, r = make()
        r.cancel()                                                           # Stop pressed while nothing is running
        with mock.patch("requests.post", return_value=StreamResp(sse("ok"))):
            self.assertEqual(r.chat_stream(MSGS, "p")["text"], "ok")


if __name__ == "__main__":
    unittest.main()
