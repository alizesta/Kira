from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPORT_SCRIPT = ROOT / "scripts" / "analyze_startup_performance.py"


def _record(index: int) -> dict:
    return {
        "schema_version": 2,
        "recorded_at": f"2026-11-23T10:0{index}:00+03:30",
        "phases": {
            "window_shown": {"elapsed_ms": 1000.0 + index * 100},
            "event_loop_first_tick": {"elapsed_ms": 2000.0 + index * 100},
        },
        "memory_samples": {
            "window_shown": {
                "working_set_mb": 200.0 + index * 10,
                "peak_working_set_mb": 210.0 + index * 10,
                "private_bytes_mb": 100.0 + index * 10,
            },
            "event_loop_first_tick": {
                "working_set_mb": 220.0 + index * 10,
                "peak_working_set_mb": 230.0 + index * 10,
                "private_bytes_mb": 120.0 + index * 10,
            },
        },
    }


class StartupPerformanceReportTests(unittest.TestCase):
    def _run_report(self, path: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPORT_SCRIPT), str(path), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_default_report_uses_latest_five_complete_windows_launches(self):
        with TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "startup-performance.jsonl"
            lines = [json.dumps(_record(index)) for index in range(6)]
            lines.append("{ malformed json")
            lines.append(json.dumps({"schema_version": 1, "phases": {}}))
            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            result = self._run_report(log_path)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Complete launches analyzed: 5", result.stdout)
        self.assertIn("Skipped malformed lines: 1", result.stdout)
        self.assertIn("Skipped incomplete/unsupported records: 1", result.stdout)
        self.assertIn("1300.00 ms", result.stdout)
        self.assertIn("2300.00 ms", result.stdout)
        self.assertIn("230.00 MB", result.stdout)

    def test_report_requires_the_requested_number_of_complete_windows_runs(self):
        with TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "startup-performance.jsonl"
            log_path.write_text(
                json.dumps(_record(0)) + "\n" + json.dumps(_record(1)) + "\n",
                encoding="utf-8",
            )
            result = self._run_report(log_path, "--runs", "5")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Need 5 complete Windows launches; found 2", result.stderr)

    def test_report_rejects_missing_log_file_with_actionable_error(self):
        with TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "missing.jsonl"
            result = self._run_report(log_path)

        self.assertEqual(result.returncode, 2)
        self.assertIn("Cannot open startup log", result.stderr)


if __name__ == "__main__":
    unittest.main()
