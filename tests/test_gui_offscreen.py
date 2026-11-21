"""GUI tests run with Qt's *offscreen* platform: they prove the widgets, wiring and logic work, but they are
NOT a substitute for opening the real program on Windows 11 (see README_FA, section 'تست روی ویندوز')."""
from tests.ui_helpers import main_window_source, patch_ui
import os
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import helpers
from tests.helpers import Resp, ok_openai, ok_cloudflare, CANARY, StreamResp, sse

try:
    from PySide6.QtWidgets import QApplication, QPushButton
    from PySide6.QtCore import QCoreApplication
    HAVE_QT = True
except Exception:                                    # pragma: no cover
    HAVE_QT = False

import requests
from kira import config, memory
from kira.personality import build_system_prompt
from kira import routes as route_model

if HAVE_QT:
    APP = QApplication.instance() or QApplication([])


def pump(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class GuiTests(unittest.TestCase):
    def setUp(self):
        d = config.DATA_DIR / "gui_case"
        d.mkdir(exist_ok=True)
        self.path = d / "settings.json"
        if self.path.exists():
            self.path.unlink()
        prot, unprot = helpers.fake_dpapi()
        self.patches = [mock.patch.object(config, "CONFIG_PATH", self.path),
                        mock.patch.object(config, "protect", prot), mock.patch.object(config, "unprotect", unprot),
                        mock.patch("requests.get", side_effect=requests.ConnectionError("ollama off"))]
        for p in self.patches:
            p.start()
        memory.init_db()
        memory.clear_memory()
        from tests.window_factory import make_window
        from kira.theme import STYLE
        APP.setStyleSheet(STYLE)
        self.win = make_window()
        self.win.show()
        APP.processEvents()

    def tearDown(self):
        self.win.speaker.stop()
        self.win.companion.close()
        self.win.close()
        APP.processEvents()
        for p in self.patches:
            p.stop()

    def select_route_row(self, rid):
        for i in range(self.win.route_list.count()):
            if self.win.route_list.item(i).data(0x100) == rid:
                self.win.route_list.setCurrentRow(i)
                return
        raise AssertionError(rid)

    def reply_ready(self):
        return not self.win.busy

    # 18) start with Ollama off
    def test_18_starts_with_ollama_off_and_says_so(self):
        self.assertIn("Ollama", self.win.status.text())
        self.assertTrue(self.win.isVisible())

    def test_tray_route_menu_refresh_lists_routes_without_runtime_menu_limit(self):
        from PySide6.QtWidgets import QMenu

        lifecycle = self.win.controllers.require("lifecycle")
        lifecycle._tray_menu = QMenu(self.win)
        lifecycle.refresh_tray_menu()

        actions = lifecycle._tray_menu.actions()
        self.assertEqual(actions[-1].text(), "خروج")
        model_menu = next((action.menu() for action in actions if action.text() == "تعویض مدل"), None)
        self.assertIsNotNone(model_menu)

        routes = lifecycle.context.session.client.available_routes()
        expected = ["خودکار (بر اساس اولویت)"]
        expected.extend(
            f"{str(route.get('label') or route.get('provider') or 'Provider').strip()} / {str(route.get('model') or '').strip()}"
            if str(route.get("model") or "").strip()
            else str(route.get("label") or route.get("provider") or "Provider").strip()
            for route in routes
        )
        if not routes:
            expected.append("هیچ Route فعالی نیست")
        self.assertEqual([action.text() for action in model_menu.actions()], expected)

    def test_model_table_price_and_action_controls_are_centered_in_their_cells(self):
        from PySide6.QtWidgets import QLabel
        from kira.ui.components.models_panel import ModelsPanel, price_pill

        cases = [
            (price_pill("free"), QLabel),
            (ModelsPanel._button("تست", lambda: None), QPushButton),
            (ModelsPanel._button("منسوخ", lambda: None), QPushButton),
        ]
        for cell, child_type in cases:
            cell.resize(82, 36)
            cell.layout().activate()
            child = cell.findChild(child_type)
            self.assertIsNotNone(child)
            geometry = child.geometry()
            self.assertGreaterEqual(geometry.left(), 0)
            self.assertGreaterEqual(geometry.top(), 0)
            self.assertLessEqual(geometry.right(), cell.width())
            self.assertLessEqual(geometry.bottom(), cell.height())
            self.assertLessEqual(abs(geometry.center().x() - cell.rect().center().x()), 2)
            self.assertLessEqual(abs(geometry.center().y() - cell.rect().center().y()), 2)

    def test_neon_glass_theme_uses_soft_single_pixel_outlines(self):
        from kira.theme import CHARACTER_THEMES, build_style, character_style

        style = build_style("off", {"glow": 58})
        group_start = style.rfind("QGroupBox {")
        group_end = style.find("QGroupBox::title", group_start)
        group_rule = style[group_start:group_end]
        self.assertIn("border: 1px solid rgba(145,166,207,", group_rule)
        self.assertNotIn("border-top:", group_rule)
        self.assertNotIn("border-bottom:", group_rule)

        self.assertIn("border: 1px solid rgba(208,224,248,0.22)", style)
        self.assertNotIn("border-bottom: 2px solid rgba(255,102,220", style)
        self.assertIn("border: 1px solid rgba(166,187,220,0.20)", style)

        character_css = character_style(CHARACTER_THEMES["kira"], appearance={"glow": 58})
        self.assertIn("border: 1px solid rgba(156,123,255,0.26)", character_css)
        self.assertIn("border: 1px solid rgba(53,217,242,0.24)", character_css)
        self.assertNotIn("0.75);", character_css)

    def test_model_tables_fit_without_horizontal_scroll_and_route_list_shows_five_rows(self):
        from PySide6.QtCore import Qt

        for table in self.win.models_panel.tables.values():
            table.fit_columns()
            self.assertEqual(table.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
            viewport_width = table.viewport().width()
            if viewport_width > 0:  # inactive model tabs may not have received geometry yet
                self.assertLessEqual(
                    sum(table.columnWidth(index) for index in range(table.columnCount())),
                    viewport_width,
                )

        self.assertGreaterEqual(self.win.route_list.minimumHeight(), 176)
        self.assertEqual(self.win.route_list.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)

    def test_extracted_settings_pages_own_their_widgets(self):
        from kira.ui.components import ApiPanel, ModelsPanel, McpRegistryPanel, OllamaProviderPanel, RouteEditor
        from kira.ui.pages import AssistantPage, AppearancePage, CharactersPage, HelpPage, PreferencesPage, VoicePage

        window = self.win
        self.assertIsInstance(window.api_panel, ApiPanel)
        self.assertTrue(window.api_panel.isAncestorOf(window.api_key_edit))
        self.assertTrue(window.api_panel.isAncestorOf(window.api_table))
        self.assertIsInstance(window.models_panel, ModelsPanel)
        from kira.ui.components import ChatHeader
        self.assertIsInstance(window.chat_header, ChatHeader)
        self.assertTrue(window.chat_header.isAncestorOf(window.title))
        self.assertTrue(window.chat_header.isAncestorOf(window.mood_emotion_icon))
        self.assertTrue(window.chat_header.isAncestorOf(window.mood_indicator))
        self.assertTrue(window.chat_header.isAncestorOf(window.companion_btn))
        from kira.ui.components import ChatComposer
        self.assertIsInstance(window.chat_composer, ChatComposer)
        self.assertEqual(window.chat_composer.parent().objectName(), "chatCard")
        for widget in (
            window.input,
            window.send_btn,
            window.attach_btn,
            window.screen_capture_btn,
            window.game_mode_btn,
            window.search_btn,
            window.gen_stop_btn,
        ):
            self.assertTrue(window.chat_composer.isAncestorOf(widget))
        from PySide6.QtGui import QAction
        self.assertIsInstance(window.web_btn, QAction)
        self.assertIsInstance(window.img_search_btn, QAction)
        self.assertIs(window.screen_capture_btn, window.game_mode_btn)
        self.assertIsNot(window.web_btn, window.img_search_btn)
        self.assertTrue(window.voice_btn.isCheckable())
        self.assertIsNotNone(window.voice_btn.property("voiceOnIcon"))
        self.assertIsNotNone(window.voice_btn.property("voiceOffIcon"))
        self.assertIsInstance(window.wake_btn, QAction)
        self.assertIsNone(window.mic_btn.menu())
        self.assertIn(window.wake_btn, window.game_mode_menu.actions())
        toolbar = window.chat_composer.layout().itemAt(4).layout()
        # RTL reverses the visual order of QHBoxLayout items.
        self.assertLess(toolbar.indexOf(window.mic_btn), toolbar.indexOf(window.voice_btn))
        self.assertIs(window.screen_capture_btn, window.game_mode_btn)
        self.assertTrue(window.game_mode_btn.isVisible())
        self.assertEqual(window.game_mode_btn.property("kiraIconName"), "monitor")
        self.assertEqual(window.game_mode_btn.toolButtonStyle(), Qt.ToolButtonIconOnly)
        self.assertTrue(window.game_mode_btn.text() == "")
        self.assertFalse(hasattr(window, "stop_btn"))
        window.build_badge_menu()
        expected_models = [str(route.get("model") or route.get("label") or route.get("provider") or "Provider").strip()
                           for route in window.presentation_context.session.client.available_routes()]
        self.assertEqual([action.text() for action in window.route_menu.actions()][1:], expected_models)
        self.assertEqual(window.search_menu.actions()[0].text(), "جست‌وجوی وب")
        self.assertEqual(window.search_menu.actions()[1].text(), "جست‌وجوی تصویری عکس ارسالی")
        self.assertEqual(window.game_mode_menu.actions()[0].text(), "گرفتن تصویر از صفحه")

        from kira.ui.controllers import ChatAttachmentController
        self.assertIsInstance(window.attachment_controller, ChatAttachmentController)
        self.assertIs(window._tiles, window.attachment_controller.tiles)
        self.assertIs(window._load_tiles, window.attachment_controller.loading_tiles)
        self.assertIs(window.attachment_controller.attach_strip, window.chat_composer.attach_strip)
        self.assertIsInstance(window.mcp_registry_panel, McpRegistryPanel)
        self.assertTrue(window.mcp_registry_panel.isAncestorOf(window.mcp_registry_list))
        self.assertTrue(window.mcp_registry_panel.isAncestorOf(window.mcp_registry_query))
        self.assertIsInstance(window.ollama_panel, OllamaProviderPanel)
        self.assertTrue(window.ollama_panel.isAncestorOf(window.route_ollama_enabled))
        self.assertTrue(window.ollama_panel.isAncestorOf(window.ollama_url_edit))
        self.assertIsInstance(window.route_editor, RouteEditor)
        self.assertTrue(window.route_editor.isAncestorOf(window.route_list))
        self.assertTrue(window.route_editor.isAncestorOf(window.route_model_edit))
        self.assertIsInstance(window.preferences_page, PreferencesPage)
        self.assertTrue(window.preferences_page.isAncestorOf(window.ui_lang))
        self.assertTrue(window.preferences_page.isAncestorOf(window.tavily_key))
        self.assertIsInstance(window.assistant_page, AssistantPage)
        # The Assistant tab is gone: identity/persona live in the Character tab,
        # the local Ollama model group lives in Connections & Models.
        self.assertTrue(window.character_page.isAncestorOf(window.persona))
        self.assertTrue(window.character_page.isAncestorOf(window.name))
        ai_tab = window.tabs.widget(window.tab_keys.index("tab_ai"))
        self.assertTrue(ai_tab.isAncestorOf(window.model))
        self.assertTrue(ai_tab.isAncestorOf(window.url))
        self.assertTrue(ai_tab.isAncestorOf(window.conn_btn))
        self.assertNotIn("tab_assistant", window.tab_keys)
        self.assertFalse(window.assistant_page.isVisible())
        self.assertIsInstance(window.appearance_page, AppearancePage)
        self.assertIsInstance(window.character_page, CharactersPage)
        self.assertIsInstance(window.voice_page, VoicePage)
        self.assertFalse(hasattr(window, "window_effect"))
        self.assertFalse(hasattr(window, "character_combo"))
        self.assertFalse(hasattr(window, "mic_device"))
        self.assertEqual(
            set(window.character_page.personality_sliders),
            {
                "playfulness", "warmth", "curiosity", "confidence", "assertiveness",
                "teasing", "empathy", "independence", "patience", "carefulness",
            },
        )
        character_ids = {
            window.character_page.character_combo.itemData(i)
            for i in range(window.character_page.character_combo.count())
        }
        self.assertTrue({"kira", "ren", "mika"}.issubset(character_ids))

    # 17) hamburger menu
    def test_17_hamburger_visible_and_menu_complete(self):
        w = self.win
        self.assertTrue(w.menu_btn.isVisible())
        self.assertTrue(w.tabs.tabBar().isHidden())               # tab strip hidden, button must remain
        top_left = w.menu_btn.mapTo(w, w.menu_btn.rect().topLeft())
        self.assertTrue(w.rect().contains(top_left))
        self.assertTrue(w.rect().contains(w.menu_btn.mapTo(w, w.menu_btn.rect().bottomRight())))
        texts = [a.text() for a in w._menu_actions]
        self.assertEqual(texts, ["گفتگو", "صدا و میکروفون", "شخصیت", "ظاهر", "عمومی", "اتصال‌ها و مدل‌ها"])
        self.assertNotIn("Ai1 Code", [a.text() for a in w.nav_menu.actions()])      # Ai1 Code lives inside Kira's chat now
        for i, action in enumerate(w._menu_actions):
            action.trigger()
            self.assertEqual(w.tabs.currentIndex(), i)

    def test_17b_menu_texts_follow_language(self):
        w = self.win
        w.settings["ui_lang"] = "en"
        w.retranslate()
        self.assertEqual(w._menu_actions[-1].text(), "Connections & Models")
        w.settings["ui_lang"] = "fa"
        w.retranslate()

    # 16) API management panel (API Manager: Add API / Registered APIs / details)
    def test_16_api_panel_structure(self):
        w = self.win
        self.assertEqual(w.api_table.rowCount(), 0)                         # no key saved yet -> nothing registered
        self.assertTrue(hasattr(w, "api_key_edit") and hasattr(w, "api_add_btn") and hasattr(w, "models_panel"))
        self.assertFalse(hasattr(w, "provider_widgets"))                    # the per-provider boxes are gone
        self.assertEqual(route_model.find_route(w.settings, "groq")["model"], "openai/gpt-oss-120b")   # model lives in the Route

    def test_16b_save_encrypts_and_key_survives_edits(self):
        w = self.win
        w.settings["providers"]["groq"].update({"enabled": True, "api_key": f"{CANARY}-groq"})
        w.apply_settings()
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn(CANARY, raw)
        self.assertIn("dpapi:", raw)
        self.assertEqual(config.load_settings()["providers"]["groq"]["api_key"], f"{CANARY}-groq")
        self.select_route_row("groq")
        w.route_model_edit.setText("openai/gpt-oss-20b")            # model is edited on the Route, not on the provider
        w.route_edit_changed()
        w.apply_settings()
        loaded = config.load_settings()
        self.assertEqual(loaded["providers"]["groq"]["api_key"], f"{CANARY}-groq")        # previous key preserved
        self.assertEqual(route_model.find_route(loaded, "groq")["model"], "openai/gpt-oss-20b")
        w.apply_api_edit("groq", {"label": None, "account_id": None, "base_url": None}, "NEWKEY-0123456789", None)   # replacing works
        self.assertEqual(config.load_settings()["providers"]["groq"]["api_key"], "NEWKEY-0123456789")

    def test_16c_settings_survive_restart(self):
        w = self.win
        w.settings["providers"]["cloudflare"]["account_id"] = "acc999"
        from PySide6.QtCore import QModelIndex
        ids = lambda: [w.route_list.item(i).data(0x100) for i in range(w.route_list.count())]          # noqa: E731
        w.route_list.model().moveRow(QModelIndex(), ids().index("cloudflare"), QModelIndex(), 0)       # drag cloudflare to the top
        APP.processEvents()
        w.route_list.model().moveRow(QModelIndex(), ids().index("groq"), QModelIndex(), 1)            # then groq to second place
        APP.processEvents()
        w.apply_settings()
        from tests.window_factory import make_window
        w2 = make_window()
        self.assertEqual(w2.settings["providers"]["cloudflare"]["account_id"], "acc999")
        self.assertEqual(w2.settings["provider_order"][:2], ["cloudflare", "groq"])
        self.assertEqual(w2.settings["provider_order"][-1], "ollama")
        w2.companion.close()
        w2.close()

    def test_16d_save_failure_is_shown_not_silent(self):
        with patch_ui("save_settings", side_effect=OSError("disk full")), \
                mock.patch("PySide6.QtWidgets.QMessageBox.critical") as box:
            self.win.apply_settings()
        box.assert_called_once()
        self.assertIn("disk full", box.call_args[0][2])

    def test_16e_add_api_detects_provider_registers_and_masks_key(self):
        w = self.win
        resp = mock.Mock(status_code=200, headers={}, text="")
        resp.json.return_value = {"data": [{"id": "openai/gpt-oss-120b", "context_window": 131072}]}
        key = "gsk_" + "a" * 40
        with mock.patch("kira.discovery.requests.get", return_value=resp):
            w.api_key_edit.setText(key)
            w.api_add()
            self.assertTrue(pump(lambda: "✓" in w.api_add_status.text()))
        self.assertEqual(w.api_table.rowCount(), 1)
        self.assertEqual(w.api_key_edit.text(), "")
        self.assertEqual(w.settings["providers"]["groq"]["api_key"], key)
        self.assertNotIn(key, w.api_add_status.text() + w.api_table.item(0, 0).text())   # never shown in full
        w.api_key_edit.setText("short")
        w.api_add()
        self.assertIn("✕", w.api_add_status.text())                                                              # rejected before any request

    # Ollama panel
    def test_ollama_options_saved_and_validated(self):
        w = self.win
        w.route_ollama_enabled.setChecked(False)
        w.num_ctx.setValue(2048)
        w.keep_alive.setCurrentText("5m")
        w.apply_settings()
        o = config.load_settings()["providers"]["ollama"]
        self.assertEqual((o["enabled"], o["num_ctx"], o["keep_alive"]), (False, 2048, "5m"))
        self.assertEqual(w.client.settings["providers"]["ollama"]["enabled"], False)
        w.keep_alive.setCurrentText("banana")
        w.apply_settings()
        self.assertEqual(config.load_settings()["providers"]["ollama"]["keep_alive"], "2m")
        self.assertIn("Keep-alive", w.chat.toPlainText())

    def test_use_qwen_button_changes_field_only_until_saved(self):
        w = self.win
        w.model.setText("qwen2.5:3b")
        w.apply_settings()
        w.use_qwen_btn.click()
        self.assertEqual(w.model.text(), "qwen3.5:4b")
        self.assertEqual(config.load_settings()["model"], "qwen2.5:3b")   # nothing overwritten without Save

    def test_check_connection_with_ollama_off_shows_clear_error(self):
        w = self.win
        w.conn_btn.click()
        self.assertTrue(pump(lambda: w.conn_btn.isEnabled() and w.conn_lbl.text().startswith("✕")))
        self.assertIn("Ollama", w.conn_lbl.text())

    # 15 / 14 end-to-end through the real window + router + SQLite history
    def send(self, text):
        self.win.input.setText(text)
        self.win.send_message()
        self.assertTrue(pump(self.reply_ready))

    def enable_cloud(self, *names):
        helpers.enable(self.win.settings, *names)
        from kira.hybrid_ai import HybridRouter
        self.win.client = HybridRouter(self.win.settings)

    def test_15_chat_end_to_end_keeps_history_across_provider_switch(self):
        w = self.win
        w.voice_btn.setChecked(False)
        w.set_voice_enabled(False)
        self.enable_cloud("groq", "cloudflare")
        seen = []

        def fake_post(url, headers=None, json=None, timeout=None, **kw):
            seen.append((url, json))
            if "groq" in url:
                return StreamResp(sse("[happy]\nسلام، من کیرا هستم.")) if len(seen) == 1 else Resp(429, {"error": "limit"})
            return StreamResp(sse({"response": "[neutral]\nاسمت علی بود."}))
        with mock.patch("requests.post", fake_post):
            self.send("اسم من علی است")
            self.send("اسمم چی بود؟")
        self.assertIn("سلام، من کیرا هستم.", w.chat.toPlainText())
        self.assertIn("اسمت علی بود.", w.chat.toPlainText())
        last_url, last_payload = seen[-1]
        self.assertIn("cloudflare", last_url)
        contents = [m["content"] for m in last_payload["messages"]]
        self.assertTrue(contents[0].startswith(build_system_prompt(w.settings, "")[:200]))   # Kira core identity
        self.assertTrue(any("اسم من علی است" in c for c in contents))               # earlier turn survived the switch
        self.assertEqual(last_payload["messages"][-1]["content"], "اسمم چی بود؟")
        self.assertEqual(len(memory.recent_messages(10)), 4)

    def test_14_all_providers_down_app_stays_usable(self):
        w = self.win
        w.set_voice_enabled(False)
        self.enable_cloud("groq")
        with mock.patch("requests.post", side_effect=requests.ConnectionError("down")):
            self.send("سلام")
        self.assertFalse(w.busy)
        self.assertTrue(w.send_btn.isEnabled())
        self.assertIn(w.t("error"), w.chat.toPlainText())
        self.assertIn("Ollama", w.chat.toPlainText())
        post = mock.Mock(side_effect=lambda *a, **k: StreamResp(sse("[happy]\nحالا کار می‌کند")))
        self.enable_cloud("groq")
        with mock.patch("requests.post", post):
            self.send("دوباره")
        self.assertIn("حالا کار می‌کند", w.chat.toPlainText())

    def test_phase1_persian_chat_is_rtl_and_input_follows_script(self):
        from PySide6.QtCore import Qt
        w = self.win
        w.add_chat("user", "سلام کیرا، حالت چطوره؟")
        blocks = []
        b = w.chat.document().begin()
        while b.isValid():
            if "حالت چطوره" in b.text():
                blocks.append(b)
            b = b.next()
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].blockFormat().layoutDirection(), Qt.RightToLeft)
        w.input.setText("hello")
        self.assertEqual(w.input.layoutDirection(), Qt.LeftToRight)
        w.input.setText("سلام")
        self.assertEqual(w.input.layoutDirection(), Qt.RightToLeft)

    def test_stage1_history_is_restored_after_restart(self):
        w = self.win
        memory.add_message("user", "اسم من علی است")
        memory.add_message("assistant", "[happy]\nسلام علی، خوشحالم!")
        from tests.window_factory import make_window
        w2 = make_window()
        text = w2.chat.toPlainText()
        self.assertIn("اسم من علی است", text)
        self.assertIn("سلام علی، خوشحالم!", text)
        self.assertNotIn("[happy]", text)                       # mood tag is not shown
        self.assertIn(w2.t("history_restored"), text)
        self.assertNotIn(w2.t("greeting"), text)                 # greeting only for an empty history
        w2.companion.close()
        w2.close()
        memory.clear_memory()
        w3 = make_window()
        self.assertIn(w3.t("greeting"), w3.chat.toPlainText())
        w3.companion.close()
        w3.close()

    def test_stage1_model_dropdown_lists_installed_and_latest_alias_counts_as_installed(self):
        w = self.win
        w.model.setText("qwen3.5:4b")

        def fake_get(url, timeout=None, **kw):
            if url.endswith("/api/version"):
                return Resp(200, {"version": "0.40.0"})
            if url.endswith("/api/tags"):
                return Resp(200, {"models": [{"name": "qwen3.5:latest"}, {"name": "llama3.2:3b"}]})
            return Resp(200, {"models": []})
        with mock.patch("requests.get", fake_get):
            w.conn_btn.click()
            self.assertTrue(pump(lambda: w.conn_btn.isEnabled() and w.conn_lbl.text().startswith("✓")))
            self.assertEqual([w.model.itemText(i) for i in range(w.model.count())], ["qwen3.5:latest", "llama3.2:3b"])
            self.assertEqual(w.model.text(), "qwen3.5:4b")        # the user's own value is not replaced
            self.assertIn("qwen3.5:latest", w.conn_lbl.text())
            w.settings["providers"]["groq"]["enabled"] = False
            w.ollama_client = type(w.ollama_client).from_settings(w.settings)
            w.check_status()
        self.assertEqual(w._status[0], "st_ok")

    def test_voice_input_during_generation_is_queued_not_dropped(self):
        w = self.win
        w._pending.clear()
        w.busy = True
        try:
            w.on_heard("سلام کیرا")
            self.assertEqual(w._pending, [("سلام کیرا", None, True)])
        finally:
            w.busy = False
            w._pending.clear()

    def test_voice_stop_command_is_handled_immediately_while_busy(self):
        w = self.win
        w._pending.clear()
        w.busy = True
        try:
            with mock.patch.object(w, "safe_stop_speaker") as stop:
                w.on_heard("بس کن")
            stop.assert_called_once_with()
            self.assertEqual(w._pending, [])
        finally:
            w.busy = False
            w._pending.clear()

    def test_stage1b_voice_error_is_shown_once_not_after_every_reply(self):
        w = self.win
        for _ in range(3):
            w.speaker.error.emit("edge-tts: getaddrinfo failed")
        self.assertEqual(w.chat.toPlainText().count("getaddrinfo failed"), 1)
        w._voice_err_at -= 700                       # ten minutes later it may be shown again
        w.speaker.error.emit("edge-tts: getaddrinfo failed")
        self.assertEqual(w.chat.toPlainText().count("getaddrinfo failed"), 2)

    def test_stage1b_speed_test_button_and_predict_setting(self):
        w = self.win
        w.num_predict.setValue(256)
        w.apply_settings()
        self.assertEqual(config.load_settings()["providers"]["ollama"]["num_predict"], 256)
        d = {"total_duration": 3e9, "load_duration": 1e9, "prompt_eval_count": 20, "prompt_eval_duration": 1e9,
             "eval_count": 24, "eval_duration": 1e9, "message": {"content": "x"}}
        get = mock.Mock(return_value=Resp(200, {"models": []}))
        with mock.patch("requests.post", mock.Mock(return_value=Resp(200, d))), mock.patch("requests.get", get):
            w.speed_btn.click()
            self.assertTrue(pump(lambda: w.speed_btn.isEnabled() and w.conn_lbl.text().startswith("✓")))
        self.assertIn("24.0 توکن/ثانیه", w.conn_lbl.text())

    def test_stage1c_audio_device_change_does_not_break_voice(self):
        sp = self.win.speaker
        self.assertIsNone(sp._devices)                    # not created at start-up: no audio backend is touched until speaking
        sp._on_devices_changed()                          # what happens when Qt reports a changed/invalidated output
        self.assertIsNone(sp._fx)
        errors = []
        sp.error.connect(errors.append)
        from PySide6.QtMultimedia import QSoundEffect

        class Fake:                                       # plain stand-in: real QSoundEffect needs an audio backend
            def status(self):
                return QSoundEffect.Error

            def stop(self):
                pass

            def deleteLater(self):
                pass
        sp._fx = Fake()
        sp._on_sound_status()
        self.assertIsNone(sp._fx)
        self.assertTrue(errors and "دستگاه" in errors[0])

    # 19) character, face, reactions, companion untouched and working
    def test_19_character_voice_and_reactions_still_work(self):
        w = self.win
        from kira.rig import MOODS
        for mood in MOODS:
            w.animator.set_expression(mood, hold=1)
            APP.processEvents()
        w.animator.set_expression("happy", hold=2)
        self.assertEqual(w.animator.expr, "happy")
        w.companion.show()
        APP.processEvents()
        self.assertTrue(w.companion.isVisible())
        w.companion.hide()
        w.on_region_clicked("face")                               # click reaction from reactions.json
        self.assertTrue(w.reactions)
        self.assertTrue(hasattr(w.speaker, "speak") and hasattr(w.speaker, "stop"))
        w.voice_btn.click()
        w.voice_btn.click()

    def test_19b_active_character_changes_chat_page_and_companion_art(self):
        w = self.win
        from kira.face import AvatarView
        self.assertIsInstance(w.avatar, AvatarView)
        a = w.animator
        try:
            for cid in ("ren", "mika"):
                serial = a.art_serial
                w.character_combo.setCurrentIndex(w.character_combo.findData(cid))
                APP.processEvents()
                self.assertEqual(w.settings["active_character_id"], cid)
                self.assertGreater(a.art_serial, serial)
                self.assertFalse(a.face_overlays)               # Kira's eyelid/mouth overlays only on Kira's art
                self.assertIsNotNone(a.clip_rect)
                self.assertFalse(w.character_portrait.pixmap().isNull())
                self.assertEqual(w.character_portrait.pixmap().size(), w.character_portrait.size())
                w.avatar.resize(234, 420)
                self.assertFalse(w.avatar.grab().isNull())
                w.companion.show()
                APP.processEvents()
                self.assertAlmostEqual(w.companion.height() / w.companion.width(), a.window_ratio, delta=0.05)
                w.companion.hide()
            w.character_combo.setCurrentIndex(w.character_combo.findData("kira"))
            APP.processEvents()
            self.assertTrue(a.face_overlays)
            self.assertIsNone(a.clip_rect)
            self.assertFalse(w.avatar.grab().isNull())
        finally:
            w.character_combo.setCurrentIndex(w.character_combo.findData("kira"))


if __name__ == "__main__":
    unittest.main()
