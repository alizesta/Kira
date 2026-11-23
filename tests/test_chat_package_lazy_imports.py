"""Regression checks for lazy package-level Chat exports."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ChatPackageLazyImportTests(unittest.TestCase):
    def test_importing_a_leaf_chat_module_does_not_import_the_chat_graph(self):
        code = """
import sys
import kira.chat.events
forbidden = {
    "kira.chat.application_service",
    "kira.chat.persistence",
    "kira.chat.sqlite_repository",
    "kira.chat.attachments",
    "kira.chat.commands",
    "kira.chat.search",
    "kira.chat.transfer",
    "kira.chat.organization",
    "kira.chat.conversation_lifecycle",
    "kira.chat.session_manager",
    "kira.chat.coordinator",
    "kira.chat.response_handler",
}
loaded = forbidden.intersection(sys.modules)
assert not loaded, sorted(loaded)
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_historical_exports_resolve_on_demand(self):
        code = """
import sys
from kira.chat import ChatApplicationService
assert ChatApplicationService.__name__ == "ChatApplicationService"
assert "kira.chat.application_service" in sys.modules
assert "kira.chat.sqlite_repository" not in sys.modules
from kira.chat import SqliteChatRepository
assert SqliteChatRepository.__name__ == "SqliteChatRepository"
assert "kira.chat.sqlite_repository" in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
