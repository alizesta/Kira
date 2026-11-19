"""Regression coverage for the extracted desktop UI ownership boundaries."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]


class _Registry:
    def __init__(self, **controllers):
        self.controllers = controllers

    def require(self, name):
        return self.controllers[name]


class FacadeRegressionTests(unittest.TestCase):
    def test_composer_owner_routes_callbacks_and_rejects_unowned_aliases(self):
        from kira.ui.components.composer_owner import ComposerOwner

        callback = object()
        context = SimpleNamespace(
            host=object(),
            views=SimpleNamespace(_allowed=frozenset({"send_btn"}), send_btn=None),
            services=SimpleNamespace(settings={"web_search": True}, vision_application_service=object()),
            controllers=_Registry(chat=SimpleNamespace(send_message=callback)),
        )
        owner = ComposerOwner(context)
        button = object()

        owner.send_btn = button

        self.assertIs(context.views.send_btn, button)
        self.assertIs(owner.send_message, callback)
        self.assertIs(owner.widget, context.host)
        self.assertIs(owner.settings, context.services.settings)
        with self.assertRaises(AttributeError):
            owner.attach_btn = object()

    def test_code_chat_host_exposes_the_shared_tool_execution_guard(self):
        from kira.ui.components.code_chat_host import CodeChatHost

        tool_agent = object()
        session_controller = SimpleNamespace(
            _as=object(), accent=object(), add_chat=object(), set_status=object()
        )
        runtime_controller = SimpleNamespace(
            save_message=object(), finish_request=object(), _send_next_pending=object()
        )
        chat_controller = SimpleNamespace(submit=object())
        session = SimpleNamespace(busy=False, _voice_next=False, view=object())
        context = SimpleNamespace(
            host=object(),
            settings={},
            services=SimpleNamespace(settings={}, tool_agent=tool_agent),
            state=SimpleNamespace(sessions={}, cur=session, front=session, _closing=False),
            views=SimpleNamespace(status=object(), gen_stop_btn=object()),
            session=session,
            controllers=_Registry(
                session=session_controller, runtime=runtime_controller, chat=chat_controller
            ),
        )
        host = CodeChatHost(context)

        self.assertIs(host.tool_agent, tool_agent)
        self.assertIs(host._as, session_controller._as)
        self.assertIs(host.submit, chat_controller.submit)
        self.assertIs(host.chat, session.view)

    def test_worker_resources_are_registered_for_shutdown(self):
        context_source = (ROOT / "kira/ui/window_presentation_context.py").read_text(encoding="utf-8")
        runtime_source = (ROOT / "kira/ui/main_window_runtime.py").read_text(encoding="utf-8")
        composition_source = (ROOT / "kira/ui/main_window_composition.py").read_text(encoding="utf-8")

        for name in ("_model_catalog_worker", "_local_stt_test_listener", "_mcp_registry_worker"):
            self.assertIn(f'"{name}": ("state", "{name}")', context_source)
            self.assertIn(f'"{name}"', runtime_source)
            self.assertIn(f'"{name}"', composition_source)
        self.assertIn('stop_local_stt_test(update_ui=False)', runtime_source)

    def test_stt_callbacks_are_queued_to_the_gui_thread_and_check_sender_identity(self):
        source = (ROOT / "kira/ui/main_window_voice_settings.py").read_text(encoding="utf-8")
        self.assertIn("listener.heard.connect(self._on_local_stt_test_heard)", source)
        self.assertIn("listener.error.connect(self._on_local_stt_test_error)", source)
        self.assertIn("listener.state.connect(self._on_local_stt_test_state)", source)
        self.assertIn("listener.finished.connect(self._on_local_stt_test_finished)", source)
        self.assertIn("@Slot(str)\n    def _on_local_stt_test_heard", source)
        self.assertIn("@Slot()\n    def _on_local_stt_test_finished", source)
        self.assertIn("self.context.state._local_stt_test_listener is not listener", source)
        self.assertIn('"توقف تست STT" if current is not None and current.isRunning() else "تست STT"', source)

    def test_taskworker_results_use_gui_thread_slots(self):
        provider = (ROOT / "kira/ui/main_window_provider_settings.py").read_text(encoding="utf-8")
        voice = (ROOT / "kira/ui/main_window_voice_settings.py").read_text(encoding="utf-8")
        chat = (ROOT / "kira/ui/main_window_chat.py").read_text(encoding="utf-8")
        lifecycle = (ROOT / "kira/ui/main_window_lifecycle.py").read_text(encoding="utf-8")

        self.assertIn("worker.done.connect(self._relay_api_worker_done)", provider)
        self.assertIn("@Slot(object)\n    def _relay_api_worker_done", provider)
        self.assertNotIn("_api_worker.done.connect(lambda", provider)
        self.assertIn("worker.done.connect(self._on_local_voice_worker_done)", voice)
        self.assertIn("worker.finished.connect(self._on_local_voice_worker_finished)", voice)
        self.assertIn("@Slot(object)\n    def _on_local_voice_worker_done", voice)
        self.assertIn("@Slot(object)\n    def on_web_test_done", chat)
        self.assertIn("@Slot(bool, str)\n    def on_ollama_task_done", lifecycle)

    def test_attachment_worker_signals_use_qobject_slots(self):
        source = (ROOT / "kira/ui/controllers/chat_attachments.py").read_text(encoding="utf-8")
        self.assertIn("class ChatAttachmentController(QObject)", source)
        self.assertIn("self.worker.progress.connect(self.on_progress)", source)
        self.assertIn("@Slot(int, int)\n    def on_progress", source)
        self.assertIn("@Slot(int, dict)\n    def on_loaded", source)
        self.assertIn("@Slot(int, str)\n    def on_failed", source)
        self.assertIn("self.worker.finished.connect(self._on_worker_finished)", source)

    def test_window_shutdown_does_not_block_waiting_for_workers(self):
        source = (ROOT / "kira/ui/main_window_runtime.py").read_text(encoding="utf-8")
        codechat = (ROOT / "kira/chat_code_ui.py").read_text(encoding="utf-8")
        tree = ast.parse(codechat)
        code_chat_class = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "CodeChat"
        )
        shutdown = next(
            node for node in code_chat_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "shutdown"
        )
        called_methods = {
            node.func.attr for node in ast.walk(shutdown)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("wait", called_methods)
        self.assertNotIn("waitForFinished", called_methods)
        self.assertNotIn("terminate", called_methods)
        self.assertIn("def background_workers(self)", codechat)
        self.assertIn("workers.extend(code_chat.background_workers())", source)
        self.assertIn("worker.finished.connect(self._resume_close_after_workers)", source)
        self.assertNotIn("w.wait(3000)", source)
        self.assertNotIn("w.wait(5000)", source)

    def test_codechat_job_signals_are_relayed_to_qobject_slots(self):
        source = (ROOT / "kira/chat_code_ui.py").read_text(encoding="utf-8")
        self.assertIn("job.chunk.connect(self._relay_job_chunk)", source)
        self.assertIn("job.done.connect(self._relay_job_done)", source)
        self.assertIn("job.failed.connect(self._relay_job_failed)", source)
        self.assertNotIn("job.chunk.connect(lambda", source)
        self.assertNotIn("job.done.connect(lambda", source)
        self.assertNotIn("job.failed.connect(lambda", source)
        self.assertIn("@Slot(str)\n    def _relay_job_chunk", source)
        self.assertIn("@Slot(object)\n    def _relay_job_done", source)
        self.assertIn("@Slot(str)\n    def _relay_job_failed", source)
        self.assertIn("@Slot(str, object)\n    def _ask_approval", source)
        self.assertIn("self._class_jobs.append(job)", source)
        self.assertIn("class_jobs, self._class_jobs = list(self._class_jobs), []", source)

    def test_mcp_registry_search_worker_is_drained_on_window_close(self):
        context_source = (ROOT / "kira/ui/window_presentation_context.py").read_text(encoding="utf-8")
        controller_source = (ROOT / "kira/ui/main_window_character_settings.py").read_text(encoding="utf-8")
        self.assertIn('"_mcp_registry_worker": ("state", "_mcp_registry_worker")', context_source)
        self.assertIn("self.context.state._mcp_registry_worker = worker", controller_source)
        self.assertIn("def _clear_mcp_registry_worker", controller_source)
        self.assertIn("if self.context.state._closing:", controller_source)

    def test_game_audio_stop_is_nonblocking_and_restart_is_serialized(self):
        source = (ROOT / "kira/game_audio.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        listener = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GameAudioListener")
        stop = next(node for node in listener.body if isinstance(node, ast.FunctionDef) and node.name == "stop")
        calls = {
            node.func.attr for node in ast.walk(stop)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("wait", calls)
        self.assertIn("self._run = False", ast.get_source_segment(source, stop))

        controller = (ROOT / "kira/ui/main_window_attachments_vision.py").read_text(encoding="utf-8")
        self.assertIn("_game_audio_restart_pending = True", controller)
        self.assertIn("listener.finished.connect(self._on_game_audio_listener_finished)", controller)
        self.assertIn("@Slot()\n    def _on_game_audio_listener_finished", controller)
        self.assertIn("QTimer.singleShot(0, self._start_game_audio_listener)", controller)


try:
    from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QInputDialog
    HAVE_QT = True
except Exception:  # pragma: no cover - optional GUI dependency
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 is required for widget regressions")
class WidgetRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_attachment_controller_is_a_gui_thread_qobject(self):
        from PySide6.QtCore import QObject
        from kira.ui.controllers import ChatAttachmentController

        self.assertTrue(issubclass(ChatAttachmentController, QObject))

    def test_assistant_page_preserves_custom_finite_temperature(self):
        from kira.ui.pages.assistant_page import AssistantPage

        def build(value):
            return AssistantPage(
                {"temperature": value, "model": ""},
                lambda key: key,
                model_combo_factory=lambda text: QLineEdit(str(text)),
                num_ctx=4096,
                num_predict=512,
                keep_alive="5m",
            )

        page = build(0.35)
        self.assertEqual(page.temp.currentText(), "0.35")
        page.deleteLater()

        for invalid in ("nan", "inf", "not-a-number", True):
            page = build(invalid)
            self.assertEqual(page.temp.currentText(), "0.7")
            page.deleteLater()

    def test_memory_delete_requires_confirmation(self):
        from kira.ui.dialogs.memory import MemoryDialog

        class Memory:
            def __init__(self):
                self.items = [{"id": "m1", "group": "fact", "text": "test note"}]
                self.delete_calls = 0

            def list_items(self, _character_id):
                return list(self.items)

            def delete_item(self, _character_id, item_id):
                self.delete_calls += 1
                self.items = [item for item in self.items if item["id"] != item_id]
                return True

        class Mood:
            def current(self):
                return {"emotion": "calm", "intensity": 20}

            def reset(self):
                pass

        memory = Memory()
        dialog = MemoryDialog(
            character_id="ren", memory_service=memory, mood_service=Mood()
        )
        dialog.items.setCurrentRow(0)

        with mock.patch("kira.ui.dialogs.memory.QMessageBox.question", return_value=QMessageBox.No):
            dialog.delete_item()
        self.assertEqual(memory.delete_calls, 0)

        with mock.patch("kira.ui.dialogs.memory.QMessageBox.question", return_value=QMessageBox.Yes):
            dialog.delete_item()
        self.assertEqual(memory.delete_calls, 1)
        dialog.close()

    def test_memory_service_false_return_is_visible(self):
        from kira.ui.dialogs.memory import MemoryDialog

        class Memory:
            def list_items(self, _character_id):
                return []

            def add_note(self, _character_id, _text):
                return False

        class Mood:
            def current(self):
                return {"emotion": "calm", "intensity": 20}

            def reset(self):
                pass

        dialog = MemoryDialog(
            character_id="ren", memory_service=Memory(), mood_service=Mood()
        )
        with (
            mock.patch("kira.ui.dialogs.memory.QInputDialog.getText", return_value=("not saved", True)),
            mock.patch("kira.ui.dialogs.memory.QMessageBox.warning") as warning,
        ):
            dialog.add_note()
        warning.assert_called_once()
        dialog.close()


if __name__ == "__main__":
    unittest.main()
