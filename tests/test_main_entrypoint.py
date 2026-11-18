"""Tests for the modular desktop window and app entry point."""
import unittest
from unittest import mock


class MainEntrypointTests(unittest.TestCase):
    def test_main_delegates_startup_to_the_composition_root(self):
        import kira.main as entrypoint

        with mock.patch("kira.ui.bootstrap.run_application") as run_application:
            entrypoint.main()

        run_application.assert_called_once_with()

    def test_mainwindow_compatibility_export_points_to_modular_ui(self):
        import kira.main as entrypoint
        from kira.ui.main_window import MainWindow as ModularMainWindow

        self.assertIs(entrypoint.MainWindow, ModularMainWindow)
        self.assertNotIn("MainWindow", vars(entrypoint))

    def test_window_is_composed_from_feature_owned_mixins(self):
        from kira.ui.main_window import MainWindow
        from kira.ui.main_window_chat import ChatMixin
        from kira.ui.main_window_runtime import RuntimeMixin
        from kira.ui.main_window_session import SessionMixin

        self.assertTrue(issubclass(MainWindow, ChatMixin))
        self.assertTrue(issubclass(MainWindow, RuntimeMixin))
        self.assertTrue(issubclass(MainWindow, SessionMixin))
        self.assertEqual(MainWindow.send_message.__qualname__, "ChatMixin.send_message")
        self.assertEqual(
            MainWindow._schedule_chat_callback.__qualname__,
            "RuntimeMixin._schedule_chat_callback",
        )

    def test_bootstrap_constructs_the_modular_window_directly(self):
        import inspect
        from kira.app import bootstrap

        source = inspect.getsource(bootstrap.run_application)
        self.assertIn("from ..ui.main_window import MainWindow", source)
        self.assertNotIn("oldmain", source)


if __name__ == "__main__":
    unittest.main()
