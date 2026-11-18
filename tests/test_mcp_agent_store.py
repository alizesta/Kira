"""Persistence regressions for independent MCP agent jobs."""
import json
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from kira.mcp.agents import AgentHttp, JOBS_FILE, JobStore
from kira.tools.registry import ToolError


class JobStoreTests(unittest.TestCase):
    def test_unreadable_job_file_is_not_overwritten_by_new_job(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / JOBS_FILE
            original = b'{"jobs":[broken]}'
            path.write_bytes(original)

            store = JobStore(Path(temp))
            store.add({
                "id": "job-1",
                "agent": "worker",
                "remote_id": "remote-1",
                "state": "progress",
                "created": 1.0,
            })

            self.assertTrue(store._load_failed)
            self.assertEqual(path.read_bytes(), original)
            self.assertIn("job-1", store.jobs)

    def test_agent_http_cannot_be_kept_alive_by_a_slow_response_body(self):
        class SlowResponse:
            def __init__(self):
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

            def read(self, size=-1):
                while not self.closed:
                    time.sleep(0.01)
                return b"{}"

            def close(self):
                self.closed = True

        response = SlowResponse()
        agent = AgentHttp({"url": "https://agent.example", "name": "worker", "timeout": 0.07})
        started = time.monotonic()
        with mock.patch("kira.mcp.agents.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(ToolError, "مهلت کل"):
                agent._call("GET", "/health")

        self.assertTrue(response.closed)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_job_store_writes_valid_json_and_unique_atomic_temp_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = JobStore(root)
            for index in range(20):
                store.add({
                    "id": f"job-{index}",
                    "agent": "worker",
                    "remote_id": f"remote-{index}",
                    "state": "progress",
                    "created": float(index),
                })

            data = json.loads((root / JOBS_FILE).read_text(encoding="utf-8"))
            self.assertEqual(len(data["jobs"]), 20)
            self.assertEqual(len({job["id"] for job in data["jobs"].values()}), 20)
            self.assertFalse(list(root.glob(".kira_jobs.json.*.tmp")))


if __name__ == "__main__":
    unittest.main()
