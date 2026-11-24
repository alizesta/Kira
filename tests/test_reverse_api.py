"""Reverse API core: provider contract, lazy registry resolution, router integration and error handling.

The transport used here is a test double implementing the ReverseTransport contract; production transports
(browser / DeepSeek session) are Tasks 2 and 3.
"""
from __future__ import annotations

import os
import tempfile
import threading
import unittest
from unittest import mock

from kira import routes as route_model
from kira.core.interfaces import ChatProvider
from kira.core.interfaces.reverse_transport import ReverseTransportError, TransportState, TransportStatus
from kira.hybrid_ai import HybridRouter, ProviderError, provider_class
from kira.infrastructure.providers import ProviderRegistry
from kira.reverse_api import TRANSPORTS, TransportRegistry
from kira.reverse_api.prompt import build_prompt
from kira.reverse_api.provider import ReverseApiProvider

SECRET = "SECRET-TOKEN-123"
USER = [{"role": "user", "content": "hi"}]


class _Transport:
    """Test double for the ReverseTransport contract."""

    def __init__(self, pieces=("Hel", "lo"), state=TransportState.CONNECTED, error=None, images=False):
        self.pieces, self.state, self.error, self.images = list(pieces), state, error, images
        self.requests, self.aborted = [], False

    def status(self):
        return TransportStatus(self.state, "", self.images)

    def stream(self, request, cancel):
        self.requests.append(request)
        yield ""                                   # connection-open signal
        for piece in self.pieces:
            if cancel.is_set():
                return
            yield piece
        if self.error:
            raise self.error

    def abort(self):
        self.aborted = True


def _provider(transport=None, **cfg):
    registry = TransportRegistry()
    if transport is not None:
        registry.register("t", lambda config: transport)
    config = {"enabled": True, "transport": "t", "model": "web", "type": "reverse_api", "session_token": SECRET, **cfg}
    return ReverseApiProvider(config, name="reverse_api", registry=registry)


class ReverseApiProviderTests(unittest.TestCase):
    def test_satisfies_chat_provider_contract_without_native_tools(self):
        provider = _provider(_Transport())
        self.assertIsInstance(provider, ChatProvider)
        self.assertFalse(hasattr(provider, "chat_with_tools"))   # tools use Kira's shared path

    def test_lazy_registry_resolves_reverse_api_and_keeps_unknown_none(self):
        self.assertIs(ProviderRegistry().resolve("reverse_api"), ReverseApiProvider)
        self.assertIs(provider_class("reverse_api", {"type": "reverse_api"}), ReverseApiProvider)
        self.assertIsNone(ProviderRegistry().resolve("nope"))

    def test_prompt_keeps_persona_then_history_order(self):
        prompt = build_prompt([{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "hi"},
                               {"role": "user", "content": "x"}], "PERSONA")
        order = [prompt.index(s) for s in ("PERSONA", "User: سلام", "Assistant: hi", "User: x")]
        self.assertEqual(order, sorted(order))
        self.assertTrue(prompt.endswith("Assistant:"))

    def test_stream_passes_shared_context_and_signals_connect_once(self):
        transport = _Transport()
        calls = []
        chunks = list(_provider(transport).stream(USER, "PERSONA", 0.3, on_connect=lambda: calls.append(1), max_tokens=50))
        self.assertEqual("".join(chunks), "Hello")
        self.assertEqual(calls, [1])
        request = transport.requests[0]
        self.assertEqual((request.system_prompt, request.model, request.temperature, request.max_tokens),
                         ("PERSONA", "web", 0.3, 50))
        self.assertIn("PERSONA", request.prompt)
        self.assertEqual(request.messages[0]["content"], "hi")

    def test_chat_returns_text_and_empty_answer_is_an_error(self):
        self.assertEqual(_provider(_Transport()).chat(USER, "s"), "Hello")
        with self.assertRaises(ProviderError) as ctx:
            _provider(_Transport(pieces=())).chat(USER, "s")
        self.assertEqual(ctx.exception.kind, "empty")

    def test_connection_states_map_to_provider_error_kinds(self):
        cases = {TransportState.DISCONNECTED: ("auth", False), TransportState.UNAVAILABLE: ("missing", False),
                 TransportState.CONNECTING: ("network", True), TransportState.ERROR: ("network", True)}
        for state, (kind, retryable) in cases.items():
            with self.subTest(state=state), self.assertRaises(ProviderError) as ctx:
                _provider(_Transport(state=state)).stream(USER, "s")
            self.assertEqual((ctx.exception.kind, ctx.exception.retryable), (kind, retryable))

    def test_unregistered_transport_is_reported_not_faked(self):
        with self.assertRaises(ProviderError) as ctx:
            _provider(None).stream(USER, "s")
        self.assertEqual(ctx.exception.kind, "missing")
        self.assertFalse(_provider(None).enabled())
        self.assertTrue(_provider(_Transport()).enabled())

    def test_images_rejected_unless_transport_supports_them(self):
        with_image = [{"role": "user", "content": "x", "images": [{"b64": "AAAA", "mime": "image/png"}]}]
        with self.assertRaises(ProviderError) as ctx:
            _provider(_Transport()).stream(with_image, "s")
        self.assertEqual(ctx.exception.kind, "request")
        self.assertEqual("".join(_provider(_Transport(images=True)).stream(with_image, "s")), "Hello")

    def test_errors_keep_kind_and_never_leak_credentials(self):
        failing = _Transport(pieces=(), error=ReverseTransportError(f"bad {SECRET}", kind="rate"))
        with self.assertRaises(ProviderError) as ctx:
            list(_provider(failing).stream(USER, "s"))
        self.assertEqual(ctx.exception.kind, "rate")
        self.assertNotIn(SECRET, str(ctx.exception))
        crashing = _Transport(pieces=(), error=RuntimeError(f"boom {SECRET}"))
        with self.assertRaises(ProviderError) as ctx:
            list(_provider(crashing).stream(USER, "s"))
        self.assertEqual(ctx.exception.kind, "server")
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_abort_stops_stream_and_reaches_transport(self):
        transport = _Transport(pieces=("a", "b", "c"))
        provider = _provider(transport)
        stream = provider.stream(USER, "s")
        self.assertEqual(next(stream), "a")
        provider.abort()
        self.assertEqual(list(stream), [])
        self.assertTrue(transport.aborted)

    def test_external_cancel_event_stops_before_any_text(self):
        provider = _provider(_Transport())
        provider.cancel_event = threading.Event()
        provider.cancel_event.set()
        self.assertEqual(list(provider.stream(USER, "s")), [])

    def test_probe_reports_session_state_without_generating(self):
        transport = _Transport()
        self.assertTrue(_provider(transport).probe()[0])
        transport.state = TransportState.DISCONNECTED
        self.assertFalse(_provider(transport).probe()[0])
        self.assertEqual(transport.requests, [])


class ReverseApiRoutingTests(unittest.TestCase):
    def _settings(self, transport_id):
        settings = {"providers": {"ollama": {"enabled": False}}}
        route_model.add_reverse_api_provider(settings, transport_id, enabled=True)
        route_model.add_route(settings, "reverse_api", "web-model")
        route_model.set_manual(settings, "reverse_api")
        return settings

    def _router(self, transport):
        tid = "router-test-transport"
        TRANSPORTS.register(tid, lambda config: transport, replace=True)
        self.addCleanup(TRANSPORTS.unregister, tid)
        env = mock.patch.dict(os.environ, {"KIRA_LOG_DIR": tempfile.mkdtemp()})
        env.start()
        self.addCleanup(env.stop)
        return HybridRouter(self._settings(tid))

    def test_router_streams_through_standard_path(self):
        transport = _Transport(pieces=("Hi ", "there"))
        router = self._router(transport)
        chunks = []
        result = router.chat_stream(USER, "PERSONA", 0.5, on_chunk=chunks.append)
        self.assertEqual(result["text"].strip(), "Hi there")
        self.assertEqual((result["provider"], result["route_id"]), ("reverse_api", "reverse_api"))
        self.assertEqual(transport.requests[0].system_prompt, "PERSONA")

    def test_router_reports_disconnected_session_and_cools_down(self):
        router = self._router(_Transport(state=TransportState.DISCONNECTED))
        with self.assertRaises(RuntimeError):
            router.chat_stream(USER, "PERSONA")
        self.assertEqual(router._state("reverse_api")["last_kind"], "auth")
        self.assertEqual(router._state("reverse_api")["health"], "down")

    def test_router_never_selects_disabled_reverse_provider(self):
        settings = self._settings("unused")
        settings["providers"]["reverse_api"]["enabled"] = False
        self.assertEqual(HybridRouter(settings).eligibility(settings["routes"][-1])[1], "provider_off")


class ReverseApiSettingsTests(unittest.TestCase):
    def test_requires_key_rules_are_unchanged_except_reverse_api(self):
        self.assertFalse(route_model.requires_key("reverse_api", {"type": "reverse_api"}))
        self.assertTrue(route_model.requires_key("groq", {}))
        self.assertTrue(route_model.requires_key("custom-x", {"type": "openai_compat"}))
        self.assertFalse(route_model.requires_key("ollama", {}))

    def test_add_reverse_api_provider_is_off_by_default_and_keyless(self):
        settings = {}
        self.assertEqual(route_model.add_reverse_api_provider(settings, "Some-Transport"), "reverse_api")
        cfg = settings["providers"]["reverse_api"]
        self.assertEqual((cfg["type"], cfg["transport"], cfg["enabled"]), ("reverse_api", "some-transport", False))
        self.assertNotIn("api_key", cfg)
        cfg["enabled"] = True
        route_model.add_reverse_api_provider(settings, "other")      # re-point keeps the switch
        self.assertEqual((cfg["transport"], cfg["enabled"]), ("other", True))
        with self.assertRaises(ValueError):
            route_model.add_reverse_api_provider(settings, " ")

    def test_builtin_providers_are_untouched(self):
        self.assertEqual(set(route_model.BUILTIN), {"groq", "cloudflare", "mistral", "openrouter", "ollama"})
        self.assertEqual(route_model.DEFAULT_ORDER, ["groq", "cloudflare", "mistral", "openrouter", "ollama"])


if __name__ == "__main__":
    unittest.main()
