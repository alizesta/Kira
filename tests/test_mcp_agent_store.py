"""Persistence regressions for independent MCP agent jobs."""
import json
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

from kira.mcp.agents import AgentHttp, AgentHub, JOBS_FILE, JobStore
from kira.tools.registry import ToolError


class JobStoreTests(unittest.TestCase):
    def test_unreadable_job_file_is_not_overwritten_by_new_job(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / JOBS_FILE
            original = b'{"jobs":[broken]}'
            path.write_bytes(original)

            store = JobStore(Path(temp))
            persisted = store.add({
                "id": "job-1",
                "agent": "worker",
                "remote_id": "remote-1",
                "state": "progress",
                "created": 1.0,
            })

            self.assertFalse(persisted)
            self.assertTrue(store._load_failed)
            self.assertEqual(path.read_bytes(), original)
            self.assertIn("job-1", store.jobs)

    def test_job_store_rejects_non_finite_timestamps_and_unknown_states(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / JOBS_FILE
            path.write_text(
                '{"jobs": {'
                '"bad-time": {"id": "bad-time", "agent": "worker", "remote_id": "r1", "state": "progress", "created": NaN},'
                '"bad-state": {"id": "bad-state", "agent": "worker", "remote_id": "r2", "state": "mystery", "created": 1},'
                '"bad-text": {"id": "bad-text", "agent": "worker", "remote_id": "r3", "state": "progress", "created": 1, "text": []}'
                '}}',
                encoding="utf-8",
            )
            store = JobStore(Path(temp))

        self.assertTrue(store._load_failed)
        self.assertEqual(store.jobs, {})

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
        with mock.patch("kira.mcp.agents.open_no_redirect", return_value=response):
            with self.assertRaisesRegex(ToolError, "مهلت کل"):
                agent._call("GET", "/health")

        self.assertTrue(response.closed)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_agent_http_does_not_read_response_that_arrives_after_timeout(self):
        class LateResponse:
            def __init__(self):
                self.closed = False
                self.read_called = False

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

            def read(self, size=-1):
                self.read_called = True
                return b"{}"

            def close(self):
                self.closed = True

        response = LateResponse()
        agent = AgentHttp({"url": "https://agent.example", "name": "worker", "timeout": 0.03})

        def delayed_open(*_args, **_kwargs):
            time.sleep(0.08)
            return response

        with mock.patch("kira.mcp.agents.open_no_redirect", side_effect=delayed_open):
            with self.assertRaisesRegex(ToolError, "مهلت کل"):
                agent._call("GET", "/health")

        deadline = time.monotonic() + 0.5
        while not response.closed and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(response.closed)
        self.assertFalse(response.read_called)

    def test_agent_http_call_has_queue_import_and_parses_json(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return None
            def read(self, _size=-1):
                return b'{"ok": true}'

        agent = AgentHttp({"url": "https://agent.example", "name": "worker", "timeout": 1})
        with mock.patch("kira.mcp.agents.open_no_redirect", return_value=Response()):
            self.assertEqual(agent._call("GET", "/health"), {"ok": True})

    def test_agent_http_rejects_non_object_and_empty_json_responses(self):
        class Response:
            def __init__(self, body):
                self.body = body
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return None
            def read(self, _size=-1):
                return self.body

        agent = AgentHttp({"url": "https://agent.example", "name": "worker", "timeout": 1})
        for body in (b"[]", b"", b"null"):
            with self.subTest(body=body), mock.patch(
                "kira.mcp.agents.open_no_redirect", return_value=Response(body)
            ), self.assertRaisesRegex(ToolError, "شیء JSON"):
                agent._call("GET", "/health")

    def test_agent_answer_and_stop_require_positive_acknowledgement(self):
        agent = AgentHttp({"url": "https://agent.example", "name": "worker", "timeout": 1})
        with mock.patch.object(agent, "_call", return_value={"ok": False}):
            with self.assertRaisesRegex(ToolError, "تأیید نکرد"):
                agent.answer("remote-1", "answer", True)
            with self.assertRaisesRegex(ToolError, "تأیید نکرد"):
                agent.stop("remote-1")
        with mock.patch.object(agent, "_call", return_value={"ok": True}):
            self.assertEqual(agent.answer("remote-1", "answer", True), {"ok": True})
            self.assertEqual(agent.stop("remote-1"), {"ok": True})

    def test_agent_job_ids_are_url_encoded_with_parse_quote(self):
        agent = AgentHttp({"url": "https://agent.example", "name": "worker", "timeout": 1})
        with mock.patch.object(agent, "_retry_get", side_effect=lambda path: path):
            self.assertEqual(agent.status("job/a b"), "/status/job%2Fa%20b")

        calls = []
        with mock.patch.object(agent, "_call", side_effect=lambda method, path, body=None: calls.append((method, path, body))):
            agent.answer("job/a b", "answer", True)
            agent.stop("job/a b")
        self.assertEqual(calls[0][1], "/answer/job%2Fa%20b")
        self.assertEqual(calls[1][1], "/stop/job%2Fa%20b")

    def test_agent_hub_shutdown_stops_background_poller_and_can_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            hub = AgentHub(mock.Mock(), Path(temp), lambda: {"worker": {"name": "worker"}})
            hub._ensure_poller()
            first = hub._poller
            self.assertTrue(first.is_alive())
            hub.shutdown()
            self.assertFalse(first.is_alive())

            hub._ensure_poller()
            second = hub._poller
            self.assertTrue(second.is_alive())
            hub.shutdown()
            self.assertFalse(second.is_alive())

    def test_agent_poller_rechecks_configuration_before_thread_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            config = mock.Mock(side_effect=[{"worker": {"name": "worker"}}, {}])
            hub = AgentHub(mock.Mock(), Path(temp), config)
            hub._ensure_poller()
            self.assertIsNone(hub._poller)

    def test_agent_poller_does_not_start_without_enabled_agent_config(self):
        with tempfile.TemporaryDirectory() as temp:
            hub = AgentHub(mock.Mock(), Path(temp), lambda: {})
            hub._ensure_poller()
            self.assertIsNone(hub._poller)

    def test_missing_health_ok_field_is_not_treated_as_healthy(self):
        with tempfile.TemporaryDirectory() as temp:
            hub = AgentHub(mock.Mock(), Path(temp), lambda: {})
            agent = mock.Mock()
            agent.cfg = {"name": "worker"}
            agent.health.return_value = {}

            with self.assertRaises(ToolError):
                hub._probe(agent)

            with mock.patch.object(hub, "_agent", return_value=agent):
                status = hub.health_text({"agent": "worker"})
            self.assertIn("آماده نیست", status)

    def test_string_false_health_value_is_not_truthy(self):
        with tempfile.TemporaryDirectory() as temp:
            hub = AgentHub(mock.Mock(), Path(temp), lambda: {})
            agent = mock.Mock()
            agent.cfg = {"name": "worker-string"}
            agent.health.return_value = {"ok": "false"}

            with self.assertRaises(ToolError):
                hub._probe(agent)

            with mock.patch.object(hub, "_agent", return_value=agent):
                status = hub.health_text({"agent": "worker-string"})
            self.assertIn("آماده نیست", status)

    def test_unknown_remote_job_state_is_marked_as_error_not_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            hub = AgentHub(mock.Mock(), Path(temp), lambda: {})
            job = {
                "id": "job-1",
                "agent": "worker",
                "remote_id": "remote-1",
                "state": "progress",
                "text": "",
                "question": "",
                "created": 1.0,
                "updated": 1.0,
            }
            hub.store.add(job)
            agent = mock.Mock()
            agent.status.return_value = {"state": "done", "text": "finished"}

            with mock.patch.object(hub, "_agent", return_value=agent):
                updated = hub._refresh(job)

            self.assertEqual(updated["state"], "error")
            self.assertIn("وضعیت نامعتبر", updated["text"])

    def test_agent_answer_sends_the_literal_user_quote_not_normalized_text(self):
        with tempfile.TemporaryDirectory() as temp:
            hub = AgentHub(mock.Mock(), Path(temp), lambda: {"worker": {"name": "worker"}})
            hub.store.add({
                "id": "job-1",
                "agent": "worker",
                "remote_id": "remote-1",
                "state": "approval",
                "created": time.time(),
            })
            agent = mock.Mock()
            raw_quote = "Yes,   I APPROVE this."
            with mock.patch.object(hub, "_agent", return_value=agent), mock.patch.object(hub, "_ensure_poller"):
                hub.answer(
                    {"job_id": "job-1", "user_quote": raw_quote},
                    lambda: "Please proceed: " + raw_quote,
                )

            agent.answer.assert_called_once_with("remote-1", raw_quote, True)

    def test_agent_ask_discloses_when_new_job_cannot_be_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            hub = AgentHub(mock.Mock(), Path(temp), lambda: {"worker": {"name": "worker"}})
            agent = mock.Mock()
            agent.cfg = {"name": "worker"}
            agent.ask.return_value = {"job_id": "remote-1"}
            with mock.patch.object(hub, "_agent", return_value=agent), mock.patch.object(hub, "_probe"), mock.patch.object(
                hub.store, "find_open", return_value=None
            ), mock.patch.object(hub.store, "add", return_value=False), mock.patch.object(hub, "_ensure_poller"):
                result = hub.ask({"agent": "worker", "task": "run a task"})

            self.assertIn("job_id=", result)
            self.assertIn("پس از بسته‌شدن برنامه بازیابی آن تضمین‌شده نیست", result)

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
