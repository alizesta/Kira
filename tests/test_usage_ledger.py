"""Concurrency and cache-invalidation regressions for the usage ledger."""
from pathlib import Path
import tempfile
import unittest

from kira import usage


class UsageLedgerCacheTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self._old_path = usage._db_path
        self._old_ready = usage._ready
        self._old_settings = usage._settings
        self._old_cache = dict(usage._cache)
        usage._db_path = Path(self._temp.name) / "usage.sqlite3"
        usage._ready = False
        usage.configure({"usage_limits": {}})

    def tearDown(self):
        usage._db_path = self._old_path
        usage._ready = self._old_ready
        usage._settings = self._old_settings
        usage._cache.clear()
        usage._cache.update(self._old_cache)
        self._temp.cleanup()

    def test_committed_request_invalidates_cached_daily_usage(self):
        self.assertEqual(usage._today("provider", "test-provider"), (0, 0))
        usage.record({
            "request_id": "request-1",
            "provider": "test-provider",
            "model": "test-model",
            "status": "success",
            "tokens_in": 12,
            "tokens_out": 7,
            "tokens_source": "provider",
        })
        self.assertEqual(usage._today("provider", "test-provider"), (1, 19))

        usage.record({
            "request_id": "request-2",
            "provider": "test-provider",
            "model": "test-model",
            "status": "success",
            "tokens_in": 5,
            "tokens_out": 3,
            "tokens_source": "provider",
        })
        self.assertEqual(usage._today("provider", "test-provider"), (2, 27))

    def test_configure_invalidates_cached_usage_limits(self):
        usage._cache[("provider", "test-provider")] = (usage.time.monotonic(), (99, 999))
        usage.configure({"usage_limits": {"provider:test-provider": {"requests_per_day": 1, "action": "block"}}})
        self.assertEqual(usage.limit_state("provider", "test-provider"), "")


if __name__ == "__main__":
    unittest.main()
