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
        cls.chat_input_source = (ROOT / "kira" / "ui_widgets.py").read_text(encoding="utf-8")
        cls.composer_source = (ROOT / "kira" / "ui" / "components" / "chat_composer.py").read_text(encoding="utf-8")

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
        self.assertIn('row_widget.setProperty("active", conversation_id == current_id)', self.refresh)
        self.assertIn("open_button.setFixedHeight(32)", self.refresh)
        self.assertIn("item.setSizeHint(QSize(0, 36))", self.refresh)
        self.assertIn("display_label = label if len(label) <= 19", self.refresh)
        self.assertIn('pin_button.setObjectName("conversationPinIndicator")', self.refresh)
        self.assertIn('more_button.setFixedSize(26, 26)', self.refresh)
        self.assertTrue((ROOT / "assets" / "icons" / "pin.svg").is_file())
        theme = (ROOT / "kira" / "theme.py").read_text(encoding="utf-8")
        self.assertIn("QFrame#chatCard, QFrame#conversationSidebar", theme)
        self.assertIn("background: transparent; border: none; border-radius: 0px;", theme)
        self.assertIn("sidebar_layout.setContentsMargins(0, 0, 0, 0)", self.builder)
        self.assertIn("sidebar_layout.setSpacing(2)", self.builder)
        self.assertIn("self.context.views.conversation_list.setSpacing(0)", self.builder)
        self.assertIn("QListWidget#conversationList", theme)
        self.assertIn("QPushButton#conversationOpenButton", theme)
        self.assertIn('QWidget#conversationRow[active="true"]', theme)
        self.assertIn("background: rgba(255,255,255,0.10)", theme)
        self.assertIn("QWidget#conversationRow[active=\"true\"] QToolButton#conversationMenuButton", theme)
        self.assertIn("QToolButton#conversationMenuButton:hover", theme)
        self.assertIn("QToolButton#conversationPinIndicator", theme)
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

    def test_message_action_icons_use_equal_centered_cells(self):
        self.assertIn('width="16" height="16" align="middle"', self.chat_actions)
        self.assertIn('width="30" height="28" align="center" valign="middle"', self.chat_actions)
        self.assertIn('cellspacing="4" cellpadding="0"', self.chat_actions)
        self.assertNotIn("&nbsp;", self.chat_actions)
        self.assertIn('kira-action://{action}/{key}', self.chat_actions)

    def test_chat_input_has_hidden_scrollbars_and_an_expand_control(self):
        self.assertIn("EXPANDED_MAX_LINES = 16", self.chat_input_source)
        self.assertIn("setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)", self.chat_input_source)
        self.assertIn("setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)", self.chat_input_source)
        self.assertIn("def set_expanded(self, expanded):", self.chat_input_source)
        self.assertIn("self._expanded = bool(expanded)", self.chat_input_source)
        self.assertIn("max_lines = self.EXPANDED_MAX_LINES if self._expanded else self.MAX_LINES", self.chat_input_source)
        self.assertIn('self.expand_btn.setObjectName("expandInputBtn")', self.composer_source)
        self.assertIn('self.expand_btn.setText("EXPAND")', self.composer_source)
        self.assertIn("self.expand_btn.toggled.connect(self._set_input_expanded)", self.composer_source)
        self.assertIn('self.expand_btn.setText("COLLAPSE" if expanded else "EXPAND")', self.composer_source)

    def test_chat_input_has_a_distinct_character_tinted_surface(self):
        theme_source = (ROOT / "kira" / "theme.py").read_text(encoding="utf-8")
        start = theme_source.index("def character_style(")
        style = theme_source[start:]
        input_start = style.index("QPlainTextEdit#chatInput {{")
        input_end = style.index("QToolButton#expandInputBtn {{", input_start)
        input_style = style[input_start:input_end]
        self.assertIn("background: rgba({min(r + 16, 255)},{min(g + 16, 255)},{min(b + 20, 255)},{min(0.98, a_card + 0.10):.2f});", input_style)
        self.assertIn("border: 1px solid rgba({mr},{mg},{mb},0.30);", input_style)
        self.assertIn("QPlainTextEdit#chatInput:hover {{", input_style)
        self.assertIn("QPlainTextEdit#chatInput:focus {{", input_style)
        self.assertNotIn("background: transparent;", input_style)

    def test_chat_surfaces_share_the_avatar_background_without_frames(self):
        self.assertIn('page.setObjectName("chatPage")', self.builder)
        self.assertIn("body.setSpacing(0)", self.builder)
        theme_source = (ROOT / "kira" / "theme.py").read_text(encoding="utf-8")
        self.assertIn("QWidget#chatPage {{", theme_source)
        self.assertIn("background: rgba({r},{g},{b},{a_card});", theme_source)
        self.assertIn("QFrame#avatarCard, QFrame#chatCard, QFrame#conversationSidebar, QFrame#composer {{", theme_source)
        self.assertIn("background: transparent;", theme_source)
        self.assertIn('QWidget#conversationRow[active="true"]', theme_source)
        self.assertIn('QWidget#conversationRow[active="true"] QToolButton#conversationMenuButton', theme_source)
        self.assertIn("QToolButton#conversationPinIndicator", theme_source)
        self.assertIn("border: none;", theme_source)
        self.assertIn("border-radius: 0px;", theme_source)
        self.assertIn("self.context.views.glow_effects = []", self.builder)

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
