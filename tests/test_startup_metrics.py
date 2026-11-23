"""Tests for privacy-safe local desktop startup diagnostics."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kira.ui.bootstrap import _write_startup_metrics


class StartupMetricsTests(unittest.TestCase):
    def test_metrics_append_one_json_record_per_launch(self):
        phases = {
            "qt_ready_and_splash_visible": {
                "elapsed_ms": 120.0,
                "since_previous_ms": 120.0,
            },
            "window_shown": {
                "elapsed_ms": 980.0,
                "since_previous_ms": 860.0,
            },
        }
        memory_samples = {
            "window_shown": {
                "working_set_mb": 184.25,
                "peak_working_set_mb": 190.5,
                "private_bytes_mb": 151.0,
            }
        }
        with TemporaryDirectory() as temporary:
            _write_startup_metrics(Path(temporary), phases, memory_samples)
            _write_startup_metrics(Path(temporary), phases, memory_samples)
            log_path = Path(temporary) / "logs" / "startup-performance.jsonl"
            lines = log_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 2)
        record = json.loads(lines[0])
        self.assertEqual(record["phases"], phases)
        self.assertEqual(record["total_ms"], 980.0)
        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(record["memory_samples"], memory_samples)
        self.assertIn("recorded_at", record)

    def test_unwritable_diagnostics_do_not_escape(self):
        with TemporaryDirectory() as temporary:
            file_path = Path(temporary) / "not-a-directory"
            file_path.write_text("occupied", encoding="utf-8")
            _write_startup_metrics(file_path, {})


if __name__ == "__main__":
    unittest.main()
