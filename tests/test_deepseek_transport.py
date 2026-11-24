from __future__ import annotations

import base64
import threading
import tempfile
from pathlib import Path
import unittest

from kira.core.interfaces.reverse_transport import ReverseRequest, TransportState
from kira.reverse_api import TRANSPORTS, DeepSeekBrowserTransport
from kira.reverse_api.deepseek_session import DeepSeekSessionStore


class DeepSeekTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DeepSeekSessionStore(
            self.temp.name,
            encrypt=lambda value: base64.b64encode(value.encode("utf-8")).decode("ascii"),
            decrypt=lambda value: base64.b64decode(value.encode("ascii")).decode("utf-8"),
        )
        self.transport = DeepSeekBrowserTransport(store=self.store)

    def test_builtin_transport_is_registered_and_shared(self):
        factory = TRANSPORTS.resolve("deepseek")
        self.assertIsNotNone(factory)
        self.assertIs(factory({}), factory({}))

    def test_shared_transport_applies_route_configuration(self):
        configured = self.transport.configure({"timeout": 17})
        self.assertIs(configured, self.transport)
        self.assertEqual(self.transport.config["timeout"], 17)

    def test_route_timeout_is_respected_in_milliseconds(self):
        self.transport.configure({"timeout": 5})
        self.assertEqual(self.transport._timeout_ms(), 5_000)
        self.transport.configure({"timeout": 17})
        self.assertEqual(self.transport._timeout_ms(), 17_000)

    def test_status_requires_saved_session(self):
        status = self.transport.status()
        self.assertEqual(status.state, TransportState.DISCONNECTED)

    def test_status_does_not_launch_or_send_a_request(self):
        self.store.save({"cookies": [{"name": "sid", "value": "x"}], "origins": []})
        status = self.transport.status()
        self.assertIn(status.state, {TransportState.CONNECTED, TransportState.UNAVAILABLE})

    def test_stream_diff_holds_mutable_tail_and_does_not_replay_cumulative_text(self):
        original = "a" * 700
        delta, committed = self.transport._stable_stream_delta("", original, "")
        self.assertEqual(delta, "")
        self.assertEqual(committed, "")

        delta, committed = self.transport._stable_stream_delta(original, original, committed)
        self.assertEqual(delta, "a" * 604)
        self.assertEqual(committed, "a" * 604)

        # Re-renders stay inside the 96-character uncommitted tail.
        rewritten = "a" * 650 + "b" * 50
        delta, committed_after_rewrite = self.transport._stable_stream_delta(original, rewritten, committed)
        self.assertEqual(delta, "")
        self.assertEqual(committed_after_rewrite, committed)
        delta, committed_after_stable = self.transport._stable_stream_delta(rewritten, rewritten, committed)
        self.assertEqual(delta, "")
        self.assertEqual(committed_after_stable, committed)

        appended = rewritten + "c" * 600
        delta, next_committed = self.transport._stable_stream_delta(rewritten, appended, committed)
        self.assertEqual(delta, appended[604:700])
        self.assertEqual(next_committed, appended[:700])

        next_snapshot = appended + "d" * 600
        delta, final_committed = self.transport._stable_stream_delta(appended, next_snapshot, next_committed)
        self.assertEqual(delta, next_snapshot[700:1300])
        self.assertEqual(final_committed, next_snapshot[:1300])

    def test_completion_detection_treats_missing_composer_as_unknown(self):
        source = (Path(__file__).resolve().parents[1] / "kira/reverse_api/deepseek_transport.py").read_text(encoding="utf-8")
        self.assertIn("composerPresent: !!composer", source)
        self.assertIn("and composer_present", source)

    def test_warm_browser_is_closed_before_playwright_runtime_stops(self):
        source = (Path(__file__).resolve().parents[1] / "kira/reverse_api/deepseek_transport.py").read_text(encoding="utf-8")
        worker = source.split("class _DeepSeekBrowserWorker:", 1)[1].split("class DeepSeekBrowserTransport:", 1)[0]
        self.assertLess(worker.index("browser.close()"), worker.index("except Exception as exc:  # noqa: BLE001 - unblock waiters"))

    def test_deepseek_streaming_reuses_browser_and_finishes_without_fixed_five_second_wait(self):
        source = (Path(__file__).resolve().parents[1] / "kira/reverse_api/deepseek_transport.py").read_text(encoding="utf-8")
        self.assertIn("_STREAM_HOLDBACK_CHARS = 96", source)
        self.assertIn("_COMPLETION_GRACE_SECONDS = 0.35", source)
        self.assertIn("_NO_STOP_IDLE_SECONDS = 1.5", source)
        self.assertIn("_DeepSeekBrowserWorker", source)
        self.assertIn("browser.new_context(", source)

    def test_selected_deepseek_keeps_a_headless_browser_without_startup_chat_navigation(self):
        transport_source = (Path(__file__).resolve().parents[1] / "kira/reverse_api/deepseek_transport.py").read_text(encoding="utf-8")
        init_source = (Path(__file__).resolve().parents[1] / "kira/reverse_api/__init__.py").read_text(encoding="utf-8")
        runtime_source = (Path(__file__).resolve().parents[1] / "kira/ui/main_window_runtime.py").read_text(encoding="utf-8")
        self.assertIn('"headless": True', transport_source)
        self.assertNotIn('display_page.goto(', transport_source)
        self.assertIn('def activate(self, active: bool)', transport_source)
        self.assertIn('get_conversation_url(job.request.conversation_id)', transport_source)
        self.assertIn('set_conversation_url(', transport_source)
        self.assertIn('storage_state(indexed_db=True)', transport_source)
        self.assertIn('def set_deepseek_browser_active(active: bool)', init_source)
        self.assertIn('set_deepseek_browser_active(bool(selected and selected.get("provider") == "reverse_api"))', runtime_source)

    def test_conversation_url_rejects_home_and_non_deepseek_urls(self):
        self.assertIsNone(self.transport._conversation_url("https://chat.deepseek.com/"))
        self.assertIsNone(self.transport._conversation_url("https://chat.deepseek.com/sign_in"))
        self.assertIsNone(self.transport._conversation_url("https://example.com/chat"))
        self.assertEqual(
            self.transport._conversation_url("https://chat.deepseek.com/a/chat/s/abc"),
            "https://chat.deepseek.com/a/chat/s/abc",
        )

    def test_new_deepseek_chat_is_seeded_from_kira_history_and_mapped_chat_gets_only_new_turn(self):
        request = ReverseRequest(
            prompt="system instructions\nold user\nold answer\nnew user",
            system_prompt="system instructions",
            messages=(
                {"role": "user", "content": "old user"},
                {"role": "assistant", "content": "old answer"},
                {"role": "user", "content": "new user"},
            ),
            model="deepseek",
            conversation_id="local-conversation",
        )
        initial = self.transport._prompt_for_request(request)
        continued = self.transport._prompt_for_request(
            request, has_existing_conversation=True
        )
        self.assertIn("old user", initial)
        self.assertIn("system instructions", continued)
        self.assertIn("new user", continued)
        self.assertNotIn("old user", continued)

    def test_playwright_storage_state_includes_indexed_db_but_excludes_kira_metadata(self):
        state = {
            "cookies": [],
            "origins": [],
            "indexedDB": [{"origin": "https://chat.deepseek.com", "databases": []}],
            "conversation_urls": {"local": "https://chat.deepseek.com/a/chat/s/abc"},
        }
        self.assertEqual(
            self.transport._playwright_storage_state(state),
            {"cookies": [], "origins": [], "indexedDB": state["indexedDB"]},
        )

    def test_refreshed_session_merges_rotated_session_storage(self):
        state = {
            "cookies": [{"name": "rotated", "value": "new-cookie"}],
            "origins": [{"origin": "https://chat.deepseek.com", "localStorage": []}],
            "sessionStorageByOrigin": {
                "https://other.example": [{"name": "keep", "value": "1"}],
                "https://chat.deepseek.com": [{"name": "old", "value": "2"}],
            },
        }
        merged = self.transport._merge_session_storage(
            state,
            {"origin": "https://chat.deepseek.com", "entries": [{"name": "new", "value": "3"}]},
        )
        self.assertEqual(merged["cookies"][0]["value"], "new-cookie")
        self.assertEqual(merged["sessionStorageByOrigin"]["https://other.example"], [{"name": "keep", "value": "1"}])
        self.assertEqual(merged["sessionStorageByOrigin"]["https://chat.deepseek.com"], [{"name": "new", "value": "3"}])

    def test_empty_refreshed_session_storage_removes_stale_origin_entries(self):
        state = {"sessionStorageByOrigin": {"https://chat.deepseek.com": [{"name": "old", "value": "2"}]}}
        merged = self.transport._merge_session_storage(
            state, {"origin": "https://chat.deepseek.com", "entries": []}
        )
        self.assertNotIn("sessionStorageByOrigin", merged)

    def test_session_storage_is_injected_for_matching_origin_only(self):
        state = {
            "sessionStorageByOrigin": {
                "https://chat.deepseek.com": [{"name": "access_token", "value": "secret"}]
            }
        }
        script = self.transport._session_init_script(state)
        self.assertIn("location.origin", script)
        self.assertIn("sessionStorage.setItem", script)
        self.assertIn("chat.deepseek.com", script)
        self.assertIn("access_token", script)

    def test_abort_before_stream_start_is_not_cleared_or_ignored(self):
        self.transport.abort()
        self.assertTrue(self.transport._cancel.is_set())
        self.assertEqual(list(self.transport.stream(None, threading.Event())), [])
        self.assertFalse(self.transport._cancel.is_set())

    def test_request_cancel_before_stream_start_skips_browser_setup(self):
        cancel = threading.Event()
        cancel.set()
        self.assertEqual(list(self.transport.stream(None, cancel)), [])

    def test_abort_sets_cancellation_flag(self):
        self.transport.abort()
        self.assertTrue(self.transport._cancel.is_set())


if __name__ == "__main__":
    unittest.main()
