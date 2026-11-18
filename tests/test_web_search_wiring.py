"""Static wiring checks for the Web Search application boundary."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebSearchApplicationWiringTests(unittest.TestCase):
    def test_chat_mixin_delegates_policy_to_application_service(self):
        source = (ROOT / "kira/ui/main_window_chat.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        mixin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ChatMixin")
        methods = {
            node.name: node for node in mixin.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for removed in (
            "gemini_credentials", "make_image_query", "_merge_search_content",
            "make_search_query", "_assessment_text",
        ):
            self.assertNotIn(removed, methods)

        for method_name in ("begin_image_search", "begin_web_search", "test_web_search", "add_sources", "on_web_done"):
            self.assertIn("web_search_service", ast.unparse(methods[method_name]))

    def test_bootstrap_injects_the_service_and_direct_window_construction_has_fallback(self):
        bootstrap = (ROOT / "kira/app/bootstrap.py").read_text(encoding="utf-8")
        window = (ROOT / "kira/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("WebSearchApplicationService()", bootstrap)
        self.assertIn("web_search_service=web_search_service", bootstrap)
        self.assertIn("web_search_service=None", window)
        self.assertIn("self.web_search_service = web_search_service or WebSearchApplicationService()", window)

    def test_application_service_has_no_qt_dependency(self):
        source = (ROOT / "kira/app/web_search.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        self.assertFalse(any(name.startswith(("PySide", "PyQt")) for name in imports))


if __name__ == "__main__":
    unittest.main()
