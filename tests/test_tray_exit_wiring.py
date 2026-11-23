"""Regression checks for the system tray exit action."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TrayExitWiringTests(unittest.TestCase):
    def test_exit_action_defers_shutdown_until_tray_menu_closes(self):
        source = (ROOT / "kira/ui/main_window_lifecycle.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        controller = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "LifecycleController"
        )
        refresh = next(
            node for node in controller.body
            if isinstance(node, ast.FunctionDef) and node.name == "refresh_tray_menu"
        )
        exit_action = next(
            node for node in ast.walk(refresh)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "exit_action" for target in node.targets)
        )
        self.assertIsInstance(exit_action.value, ast.Call)
        self.assertEqual(exit_action.value.func.attr, "addAction")
        self.assertEqual(ast.literal_eval(exit_action.value.args[0]), "خروج")
        self.assertTrue(any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "singleShot"
            for node in ast.walk(refresh)
        ))

    def test_quit_handler_enters_the_normal_window_shutdown_path(self):
        source = (ROOT / "kira/ui/main_window_lifecycle.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        controller = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LifecycleController")
        quit_app = next(node for node in controller.body if isinstance(node, ast.FunctionDef) and node.name == "quit_app")
        calls = [node for node in ast.walk(quit_app) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        self.assertTrue(any(node.func.attr == "close" for node in calls))


if __name__ == "__main__":
    unittest.main()
