import tempfile
import unittest
from pathlib import Path

from kira.code_agent import (
    build_project_context, project_tree, safe_project_file,
    extract_replacement, PATCH_START, PATCH_END, CodeAgentEngine,
)


class CodeAgentContextTests(unittest.TestCase):
    def test_project_tree_excludes_secrets_and_runtime_folders(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "main.py").write_text("print('ok')", encoding="utf-8")
            (root / ".env").write_text("SECRET=not-for-agent", encoding="utf-8")
            (root / "settings.json").write_text("{}", encoding="utf-8")
            (root / ".venv").mkdir()
            (root / ".venv" / "hidden.py").write_text("pass", encoding="utf-8")
            tree = project_tree(root)
            self.assertIn("main.py", tree)
            self.assertNotIn(".env", tree)
            self.assertNotIn("settings.json", tree)
            self.assertNotIn(".venv", tree)

    def test_context_includes_selected_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file = root / "app.py"
            file.write_text("def answer(): return 42", encoding="utf-8")
            context = build_project_context(root, file)
            self.assertIn("SELECTED FILE: app.py", context)
            self.assertIn("return 42", context)

    def test_secret_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            secret = root / ".env"
            secret.write_text("TOKEN=abc", encoding="utf-8")
            with self.assertRaises(ValueError):
                safe_project_file(root, secret)

    def test_inline_credentials_are_redacted_from_context(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "config.py"
            source.write_text('api_key = "sk-test-secret-value"\\npassword = "hunter2"\\n', encoding="utf-8")
            context = build_project_context(root, source)
            self.assertNotIn("sk-test-secret-value", context)
            self.assertNotIn("hunter2", context)
            self.assertIn("[REDACTED]", context)

    def test_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            outside = Path(temp) / "outside.txt"
            root.mkdir()
            outside.write_text("not project", encoding="utf-8")
            with self.assertRaises(ValueError):
                safe_project_file(root, outside)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            outside = Path(temp) / "outside.py"
            outside.write_text("secret", encoding="utf-8")
            link = root / "link.py"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink unavailable")
            with self.assertRaises(ValueError):
                safe_project_file(root, link)


    def test_extract_replacement_requires_exact_markers(self):
        source = "print('hello')"
        response = "proposal\n" + PATCH_START + "\n" + source + "\n" + PATCH_END
        self.assertEqual(extract_replacement(response), source)

    def test_extract_replacement_rejects_missing_or_empty_content(self):
        with self.assertRaises(ValueError):
            extract_replacement("just an explanation")
        with self.assertRaises(ValueError):
            extract_replacement(PATCH_START + PATCH_END)


    def test_patch_proposal_is_blocked_when_context_contains_redacted_secret(self):
        class NoCallRouter:
            def chat_stream(self, *args, **kwargs):
                raise AssertionError("router must not receive secret-bearing patch context")
        engine = CodeAgentEngine(NoCallRouter())
        with self.assertRaises(ValueError):
            engine.propose_replacement("edit config", "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
