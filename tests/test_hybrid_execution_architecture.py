"""Regression coverage for hybrid provider execution ownership and cancellation."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import requests

from tests.helpers import fresh_settings
from kira import config
from kira.app.provider_application import ProviderApplicationService
from kira.hybrid_ai import HybridRouter
from kira.hybrid_providers import BaseProvider, OpenAICompatibleProvider, ProviderError
from kira.ollama_client import OllamaClient
from kira.provider_execution import CancellationToken
from kira.provider_retry_policy import ProviderRetryPolicy
from kira.provider_runtime_state import ProviderRuntimeState
from kira.request_trace import reset_request_id, set_request_id, trace


class BlockingResponse:
    status_code = 200
    headers = {}
    text = ""

    def __init__(self):
        self.entered = threading.Event()
        self.closed = threading.Event()

    def json(self):
        self.entered.set()
        if not self.closed.wait(3):
            raise AssertionError("test did not cancel the response")
        raise requests.ConnectionError("response closed by cancellation")

    def close(self):
        self.closed.set()


class HybridExecutionArchitectureTests(unittest.TestCase):
    def test_retry_policy_respects_error_class_repeatability_and_partial_output(self):
        policy = ProviderRetryPolicy()
        transient = ProviderError("provider", "timeout", True, kind="timeout")
        safe = policy.decide(transient, request_repeatable=True)
        self.assertTrue(safe.retryable)
        self.assertTrue(safe.retry_same_target)
        self.assertEqual(safe.reason, "retry_same_target")

        ambiguous = policy.decide(transient, request_repeatable=False)
        self.assertTrue(ambiguous.continue_with_alternative)
        self.assertFalse(ambiguous.retry_same_target)
        self.assertEqual(ambiguous.reason, "alternate_target_only")

        permanent = ProviderError("provider", "bad key", False, 401, "auth")
        decision = policy.decide(permanent, request_repeatable=True)
        self.assertFalse(decision.retryable)
        self.assertFalse(decision.retry_same_target)
        self.assertTrue(decision.continue_with_alternative)
        self.assertEqual(decision.reason, "permanent_auth_alternate_target_only")

        partial = policy.decide(transient, request_repeatable=True, partial_output=True)
        self.assertFalse(partial.continue_with_alternative)
        self.assertEqual(partial.reason, "partial_output_not_replayable")
        cancelled = policy.decide(transient, request_repeatable=True, cancelled=True)
        self.assertFalse(cancelled.continue_with_alternative)
        self.assertEqual(cancelled.reason, "cancelled")

    def test_runtime_state_is_isolated_by_default_and_atomic_when_shared(self):
        first, second = ProviderRuntimeState(), ProviderRuntimeState()
        first.set_cooldown("route-a", 100.0)
        first.set_quota_block(("project", "model"), {"kind": "daily", "expires_at": None})
        first.update_state("route-a", {"health": "down"}, increments={"failures": 1})
        self.assertEqual(second.cooldown_remaining("route-a", now=0), 0)
        self.assertIsNone(second.quota_status(("project", "model"), now=0))
        self.assertEqual(second.state_snapshot("route-a")["failures"], 0)

        shared = ProviderRuntimeState()
        count, increments = 8, 250
        workers = [
            threading.Thread(target=lambda: [
                shared.update_state("route-a", increments={"failures": 1})
                for _ in range(increments)
            ])
            for _ in range(count)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(shared.state_snapshot("route-a")["failures"], count * increments)

    def test_rebuilt_real_session_routers_share_one_locked_owner_but_not_old_cooldowns(self):
        settings = fresh_settings()
        service = ProviderApplicationService()
        previous = HybridRouter(settings)
        previous.runtime_state.update_state("route-a", {"health": "healthy", "last_ms": 12})
        previous.runtime_state.set_cooldown("route-a", 1000.0)
        previous.runtime_state.set_quota_block(("google-project-model", "project-a", "gemini"), {
            "kind": "daily", "expires_at": None,
        })

        class Session:
            def __init__(self, client):
                self.client = client

        sessions = (Session(previous), Session(previous))
        routers = service.rebuild_session_routers(settings, sessions, previous_router=previous)
        self.assertIs(routers[0].runtime_state, routers[1].runtime_state)
        self.assertIsNot(routers[0].runtime_state, previous.runtime_state)
        self.assertEqual(routers[0].runtime_state.state_snapshot("route-a")["health"], "healthy")
        self.assertEqual(routers[0].cooldowns, {})
        self.assertEqual(routers[0].quota_blocks[("google-project-model", "project-a", "gemini")]["kind"], "daily")
        routers[0].runtime_state.update_state("route-a", {"health": "degraded"})
        self.assertEqual(routers[1].runtime_state.state_snapshot("route-a")["health"], "degraded")

    def test_router_falls_through_to_a_provider_that_supports_native_tools(self):
        settings = fresh_settings()
        router = HybridRouter(settings)
        candidates = [
            {"id": "unsupported", "provider": "unsupported", "model": "m"},
            {"id": "capable", "provider": "capable", "model": "m"},
        ]

        class UnsupportedProvider:
            def chat_with_tools(self, messages, system_prompt, temperature, tools):
                return None

        class NativeProvider:
            last_stats = None
            last_usage = None

            def chat_with_tools(self, messages, system_prompt, temperature, tools):
                return {"text": "", "tool_calls": [{"id": "call-1", "tool": "open_app", "args": {"name": "editor"}}]}

        providers = {"unsupported": UnsupportedProvider(), "capable": NativeProvider()}
        router._candidates = lambda: candidates
        router._usage_blocked_providers = lambda _routes: set()
        router.eligibility = lambda _route: (True, "ok")
        router.route_info = lambda route: {
            "route_id": route["id"], "provider": route["provider"],
            "model": route["model"], "kind": "cloud", "label": route["provider"],
        }
        router._provider_cfg = lambda route: {
            "base_url": f"https://{route['id']}.example/v1", "api_key": f"key-{route['id']}",
        }
        router._make_provider = lambda route: providers[route["id"]]
        router._ledger = lambda *args, **kwargs: None

        with mock.patch.object(HybridRouter, "_write_telemetry"):
            result = router.chat_with_tools(
                [{"role": "user", "content": "open editor"}],
                "system",
                tools=[{"name": "open_app", "parameters": {"type": "object"}}],
            )

        self.assertEqual(result["provider"], "capable")
        self.assertEqual(result["tool_calls"][0]["tool"], "open_app")
        self.assertEqual([attempt["route_id"] for attempt in router.last_attempts], ["capable"])

    def test_cancellation_token_combines_router_and_external_events(self):
        internal, external = threading.Event(), threading.Event()
        token = CancellationToken(internal, external)
        self.assertFalse(token.is_set())
        external.set()
        self.assertTrue(token.is_set())
        external.clear()
        internal.set()
        self.assertTrue(token.is_set())

    def test_provider_abort_closes_non_streaming_http_response_during_json_decode(self):
        response = BlockingResponse()
        provider = BaseProvider({"base_url": "https://example.test/v1", "api_key": "secret-key"}, name="test")
        provider.cancel_event = threading.Event()
        failures = []

        def run():
            try:
                provider._post_json("https://example.test/v1/chat", {}, {"model": "m"})
            except Exception as exc:
                failures.append(exc)

        with mock.patch("requests.post", return_value=response) as post:
            worker = threading.Thread(target=run)
            worker.start()
            self.assertTrue(response.entered.wait(2))
            self.assertTrue(post.call_args.kwargs["stream"])
            provider.abort()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(response.closed.is_set())
        self.assertTrue(failures)
        self.assertIsInstance(failures[0], ProviderError)

    def test_ollama_abort_closes_non_streaming_response_during_json_decode(self):
        response = BlockingResponse()
        client = OllamaClient("http://localhost:11434", "test-model")
        client.cancel_event = threading.Event()
        client._no_think = True
        failures = []

        def run():
            try:
                client.chat([{"role": "user", "content": "hello"}], "system")
            except Exception as exc:
                failures.append(exc)

        with mock.patch("requests.post", return_value=response) as post:
            worker = threading.Thread(target=run)
            worker.start()
            self.assertTrue(response.entered.wait(2))
            self.assertTrue(post.call_args.kwargs["stream"])
            client.abort()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(response.closed.is_set())
        self.assertTrue(failures)

    def test_gemini_native_cancellation_never_starts_compatibility_fallback(self):
        cancelled = threading.Event()
        calls = []

        class Response:
            status_code = 400
            headers = {}
            text = "invalid payload"

            def __init__(self):
                self.closed = threading.Event()

            def close(self):
                self.closed.set()

        response = Response()
        provider = OpenAICompatibleProvider({
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "test-key", "model": "gemini-4-hydrogen",
            "gemini_native_fallback": True,
        }, name="google-ai")
        provider.cancel_event = cancelled

        def post(*args, **kwargs):
            calls.append((args, kwargs))
            cancelled.set()
            return response

        with mock.patch("requests.post", side_effect=post):
            with self.assertRaises(RuntimeError):
                provider.chat([{"role": "user", "content": "hello"}], "system")
        self.assertEqual(len(calls), 1)
        self.assertTrue(response.closed.is_set())

    def test_trace_keeps_concurrent_request_ids_and_drops_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            barrier = threading.Barrier(2)

            def worker(request_id):
                token = set_request_id(request_id)
                try:
                    barrier.wait(2)
                    trace(
                        "parallel_request", worker=request_id, route_id="route-a",
                        api_key=f"secret-{request_id}", prompt=f"prompt-{request_id}",
                        response_body=f"body-{request_id}", response_chars=15,
                    )
                finally:
                    reset_request_id(token)

            with mock.patch.object(config, "DATA_DIR", Path(folder)):
                threads = [threading.Thread(target=worker, args=(f"request-{i}",)) for i in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(3)
                    self.assertFalse(thread.is_alive())

            path = Path(folder) / "logs" / "request_trace.jsonl"
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual({record["request_id"] for record in records}, {"request-0", "request-1"})
            for record in records:
                self.assertEqual(record["request_id"], record["worker"])
                self.assertNotIn("api_key", record)
                self.assertNotIn("prompt", record)
                self.assertNotIn("response_body", record)
                self.assertIn("response_chars", record)
            serialized = json.dumps(records)
            self.assertNotIn("secret-request", serialized)
            self.assertNotIn("prompt-request", serialized)
            self.assertNotIn("body-request", serialized)


if __name__ == "__main__":
    unittest.main()
