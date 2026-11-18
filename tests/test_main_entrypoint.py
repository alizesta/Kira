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

    def test_window_is_a_qt_shell_with_composed_feature_controllers(self):
        from PySide6.QtWidgets import QMainWindow

        from kira.ui.main_window import MainWindow
        from kira.ui.main_window_chat import ChatController
        from kira.ui.main_window_runtime import RuntimeController
        from kira.ui.main_window_session import SessionController
        from kira.ui.window_feature_controller import WindowFeatureController

        self.assertEqual(MainWindow.__bases__, (QMainWindow,))
        self.assertFalse(hasattr(MainWindow, "send_message"))
        self.assertEqual(ChatController.send_message.__qualname__, "ChatController.send_message")
        self.assertEqual(
            RuntimeController._schedule_chat_callback.__qualname__,
            "RuntimeController._schedule_chat_callback",
        )
        self.assertTrue(issubclass(SessionController, WindowFeatureController))

    def test_bootstrap_constructs_the_modular_window_directly(self):
        import inspect
        from kira.ui import bootstrap

        source = inspect.getsource(bootstrap.run_application)
        self.assertIn("from .main_window import MainWindow", source)
        self.assertIn("window = MainWindow()", source)
        self.assertIn("initialize_main_window(", source)
        self.assertNotIn("oldmain", source)


if __name__ == "__main__":
    unittest.main()
