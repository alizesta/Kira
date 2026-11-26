"""Regression contracts for the durable conversation history sidebar.

These checks are deliberately Qt-free: they protect the persistence and UI wiring
without requiring a desktop display to be available in CI.
"""
import ast
from pathlib import Path
import unittest

from kira.chat_sessions import ChatSession


ROOT = Path(__file__).resolve().parents[1]


def _method_source(path, class_name, method_name):
    source = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    owner = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node for node in owner.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    )
    return ast.get_source_segment(source, method)


class ConversationSidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.new_chat = _method_source(
            "kira/ui/main_window_session.py", "SessionController", "new_chat"
        )
        cls.refresh = _method_source(
            "kira/ui/main_window_session.py", "SessionController", "refresh_conversation_list"
        )
        cls.switch = _method_source(
            "kira/ui/main_window_session.py", "SessionController", "switch_conversation"
        )
        cls.delete = _method_source(
            "kira/ui/main_window_session.py", "SessionController", "delete_conversation"
        )
        cls.builder = _method_source(
            "kira/ui/main_window_voice_settings.py",
            "VoiceSettingsController",
            "build_chat_tab",
        )
        cls.context = (
            ROOT / "kira" / "ui" / "window_presentation_context.py"
        ).read_text(encoding="utf-8")

    def test_new_chat_creates_a_new_record_without_deleting_old_history(self):
        self.assertIn("service.create_conversation(session.cid)", self.new_chat)
        self.assertIn("session.conversation_id = str(conversation_id)", self.new_chat)
        self.assertIn("self.refresh_conversation_list()", self.new_chat)
        for destructive_operation in (
            "delete_conversation(",
            "permanently_delete_conversation(",
            "clear_history(",
            "clear_memory(",
        ):
            self.assertNotIn(destructive_operation, self.new_chat)

    def test_sidebar_lists_durable_conversations_for_the_active_character(self):
        self.assertIn('service.list_conversations(', self.refresh)
        self.assertIn('statuses=("active", "closed")', self.refresh)
        self.assertIn('status not in ("active", "closed")', self.refresh)
        self.assertIn("service.recent_messages(", self.refresh)
        self.assertIn("conversation_id=conversation_id", self.refresh)
        self.assertIn("item.setData(Qt.UserRole, conversation_id)", self.refresh)

    def test_reopening_checks_ownership_and_reads_only_that_conversation(self):
        self.assertIn("service.get_conversation(target_id)", self.switch)
        service = (ROOT / "kira" / "chat" / "application_service.py").read_text(encoding="utf-8")
        facade = (ROOT / "kira" / "chat" / "history_facade.py").read_text(encoding="utf-8")
        lifecycle = (ROOT / "kira" / "chat" / "conversation_lifecycle.py").read_text(encoding="utf-8")
        self.assertIn("return self._history.get_conversation(conversation_id)", service)
        self.assertIn("return self._require_conversation_lifecycle().get_conversation(conversation_id)", facade)
        self.assertIn("return self._repository.get_conversation(conv_id)", lifecycle)
        self.assertIn('record.get("character_id")', self.switch)
        self.assertIn('record.get("status")', self.switch)
        self.assertIn('not in ("active", "closed")', self.switch)
        self.assertIn("service.message_count(session.cid, target_id)", self.switch)
        self.assertIn("service.get_messages(", self.switch)
        self.assertIn("conversation_id=target_id", self.switch)
        self.assertIn("session.conversation_id = target_id", self.switch)
        self.assertIn("service.pending_count(session.session_id)", self.switch)
        self.assertNotIn("delete_conversation(", self.switch)

    def test_chat_page_contains_a_vertical_clickable_history_list(self):
        self.assertIn("QVBoxLayout(conversation_sidebar)", self.builder)
        self.assertIn("QListWidget(conversation_sidebar)", self.builder)
        self.assertIn("chat_area_widget.setLayoutDirection(Qt.LeftToRight)", self.builder)
        self.assertLess(
            self.builder.index('lang = self.context.services.settings.get("ui_lang", "en")'),
            self.builder.index("conversation_sidebar.setLayoutDirection("),
        )
        self.assertIn("chat_area.setDirection(QHBoxLayout.LeftToRight)", self.builder)
        self.assertIn("chat_area.setSpacing(0)", self.builder)
        self.assertIn("conversation_sidebar.setFixedWidth(154)", self.builder)
        self.assertIn("chat_area.addWidget(conversation_sidebar", self.builder)
        self.assertIn("chat_area.addWidget(chat_card", self.builder)
        self.assertIn('label = title or preview or ("گفتگوی جدید" if lang == "fa" else "New chat")', self.refresh)
        self.assertIn('record.get("updated_at") or record.get("created_at")', self.refresh)
        self.assertIn("date_tooltip = (", self.refresh)
        self.assertIn("items.sort(key=lambda item: item[0], reverse=True)", self.refresh)
        self.assertIn("open_button.setMinimumHeight(42)", self.refresh)
        self.assertIn("textwrap.wrap(", self.refresh)
        theme = (ROOT / "kira" / "theme.py").read_text(encoding="utf-8")
        self.assertIn("QFrame#chatCard, QFrame#conversationSidebar", theme)
        self.assertIn("QListWidget#conversationList", theme)
        self.assertIn("QPushButton#conversationOpenButton", theme)
        self.assertIn("QToolButton#conversationMenuButton", theme)
        self.assertIn("cv.addWidget(self.context.views.chat_stack, 1)", self.builder)
        self.assertIn("open_button.clicked.connect", self.refresh)
        self.assertIn("switch_conversation(cid)", self.refresh)
        self.assertIn('more_button.setText("⋯")', self.refresh)
        self.assertIn("rename_action.triggered.connect", self.refresh)
        self.assertIn("share_action.triggered.connect", self.refresh)
        self.assertIn("pin_action.triggered.connect", self.refresh)
        self.assertIn("delete_action.triggered.connect", self.refresh)
        self.assertIn("rename_conversation(cid)", self.refresh)
        self.assertIn("share_conversation(cid)", self.refresh)
        self.assertIn("pin_conversation(cid)", self.refresh)
        self.assertIn("delete_conversation(cid)", self.refresh)

    def test_rename_share_and_pin_actions_have_real_handlers(self):
        rename = _method_source("kira/ui/main_window_session.py", "SessionController", "rename_conversation")
        share = _method_source("kira/ui/main_window_session.py", "SessionController", "share_conversation")
        pin = _method_source("kira/ui/main_window_session.py", "SessionController", "pin_conversation")
        self.assertIn("QInputDialog.getText(", rename)
        self.assertIn("service.update_conversation(str(conversation_id), title=title)", rename)
        self.assertIn("service.get_messages(", share)
        self.assertIn("QApplication.clipboard().setText(transcript)", share)
        self.assertIn('metadata["_ui_pinned"] = pinned', pin)
        self.assertIn("service.update_conversation(str(conversation_id), metadata=metadata)", pin)
        service = (ROOT / "kira" / "chat" / "application_service.py").read_text(encoding="utf-8")
        facade = (ROOT / "kira" / "chat" / "history_facade.py").read_text(encoding="utf-8")
        self.assertIn("return self._history.update_conversation(conversation_id, **changes)", service)
        self.assertIn("return updater(conversation_id, **changes)", facade)

    def test_delete_button_uses_owned_conversation_trash_lifecycle(self):
        self.assertIn("service.get_conversation(target_id)", self.delete)
        self.assertIn('record.get("character_id")', self.delete)
        self.assertIn('record.get("status")', self.delete)
        self.assertIn("QMessageBox.question(", self.delete)
        self.assertIn("service.trash_conversation(target_id)", self.delete)
        self.assertIn('getattr(result, "success", False)', self.delete)
        self.assertNotIn("permanently_delete_conversation(", self.delete)

    def test_qt_sidebar_widgets_are_reexported_into_their_feature_controllers(self):
        voice_controller = (
            ROOT / "kira" / "ui" / "main_window_voice_settings.py"
        ).read_text(encoding="utf-8")
        voice_support = (
            ROOT / "kira" / "ui" / "main_window_voice_settings_support.py"
        ).read_text(encoding="utf-8")
        session_controller = (
            ROOT / "kira" / "ui" / "main_window_session.py"
        ).read_text(encoding="utf-8")
        session_support = (
            ROOT / "kira" / "ui" / "main_window_session_support.py"
        ).read_text(encoding="utf-8")

        self.assertIn("    QListWidget,", voice_controller)
        self.assertIn("QGraphicsDropShadowEffect, QListWidget", voice_support)
        self.assertIn("    QListWidgetItem,", session_controller)
        self.assertIn("QSizePolicy, QListWidgetItem", session_support)
        self.assertIn("    QInputDialog,", session_controller)
        self.assertIn("    QMenu,", session_controller)
        self.assertIn("QMessageBox, QInputDialog, QMenu", session_support)

    def test_sidebar_views_are_declared_and_granted_to_both_owners(self):
        self.assertIn('"conversation_list"', self.context)
        self.assertIn('"conversation_list_title"', self.context)
        session_access = self.context.split('"session": {', 1)[1].split('"lifecycle": {', 1)[0]
        voice_access = self.context.split('"voice_settings": {', 1)[1].split('\n }', 1)[0]
        self.assertIn('"conversation_list"', session_access)
        self.assertIn('"conversation_list_title"', session_access)
        self.assertIn('"conversation_list"', voice_access)
        self.assertIn('"conversation_list_title"', voice_access)

    def test_conversation_drafts_are_isolated_per_character_session(self):
        kira = ChatSession("kira")
        ren = ChatSession("ren")
        kira._conversation_drafts["conversation-a"] = "unsent draft"
        self.assertEqual(kira._conversation_drafts["conversation-a"], "unsent draft")
        self.assertEqual(ren._conversation_drafts, {})


if __name__ == "__main__":
    unittest.main()
