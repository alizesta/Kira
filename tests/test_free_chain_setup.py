"""Automatic free-chain setup: routes are created disabled, only healthy probed ones are enabled in chain order."""
import unittest

from kira import api_manager as am
from kira import routes as rm
from tests.test_api_manager import GOOGLE_KEY, fresh, _TEST_CAPABILITIES as CAPS

MODELS = [{"id": m} for m in (
    "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
    "gemma-4-31b-it", "gemini-4-hydrogen", "gemini-2.5-pro")]


def setup():
    s = fresh()
    det = am.Detection("ok", "google", "", MODELS, rate_limit={})
    pid = am.register(s, det, GOOGLE_KEY, capabilities=CAPS)
    return s, pid


class FreeChainTests(unittest.TestCase):
    def test_prepare_creates_disabled_routes_and_skips_unlisted_and_deep_model(self):
        s, pid = setup()
        ids = am.prepare_free_chain(s, pid, capabilities=CAPS)
        models = [rm.find_route(s, i)["model"] for i in ids]
        self.assertEqual(models, ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite",
                                  "gemini-3.1-flash-lite", "gemma-4-31b-it"])   # gemma-4-26b not listed; hydrogen not probed
        deep = [r for r in rm.get_routes(s) if r["provider"] == pid and r["model"] == "gemini-4-hydrogen"]
        self.assertEqual(len(deep), 1)
        self.assertFalse(deep[0]["enabled"])
        self.assertEqual(am.prepare_free_chain(s, pid, capabilities=CAPS), ids)    # idempotent: no duplicate routes

    def test_only_successful_probes_are_enabled_first_in_chain_order(self):
        s, pid = setup()
        ids = am.prepare_free_chain(s, pid, capabilities=CAPS)
        rows = [{"route_id": rid, "model": rm.find_route(s, rid)["model"], "ok": True} for rid in ids]
        rows[0] = {**rows[0], "ok": False, "error": "429 quota"}           # 3.8 is rate-limited right now
        out = am.apply_chain_probe(s, pid, rows, capabilities=CAPS)
        self.assertEqual(out["enabled"], ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-31b-it"])
        self.assertEqual(out["failed"][0][0], "gemini-3.8-flash")
        self.assertFalse(rm.find_route(s, ids[0])["enabled"])
        self.assertEqual(rm.get_routes(s)[0]["model"], "gemini-3.6-flash")
        self.assertEqual(s["default_route_id"], rm.get_routes(s)[0]["id"])


if __name__ == "__main__":
    unittest.main()
