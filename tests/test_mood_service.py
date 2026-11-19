"""Contract and architecture tests for the complete MoodStateService boundary."""
import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from kira.services.mood_service import MoodStateService


class MoodStateServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = MoodStateService()

    def test_snapshot_and_prompt_forward_shared_timestamp_and_query(self):
        with patch("kira.services.mood_service.mood") as backend:
            backend.current.return_value = {"age": 120}
            backend.build_block.return_value = "mood prompt"
            self.assertEqual(self.service.current(now=1234.5, query="hello"), {"age": 120})
            self.assertEqual(
                self.service.build_block("chat", now=1234.5, query="hello"), "mood prompt"
            )
        backend.current.assert_called_once_with(now=1234.5, query="hello")
        backend.build_block.assert_called_once_with(
            mode_name="chat", now=1234.5, query="hello"
        )

    def test_user_and_assistant_observation_are_forwarded(self):
        with patch("kira.services.mood_service.mood") as backend:
            backend.detect_user_states.return_value = ["joke"]
            backend.on_user_message.return_value = ["joke"]
            self.assertEqual(self.service.detect_user_states("🤣"), ["joke"])
            self.assertEqual(self.service.on_user_message("🤣", now=10.0), ["joke"])
            self.service.on_reply(["happy"], 70, 11.0, "great")
        backend.detect_user_states.assert_called_once_with("🤣")
        backend.on_user_message.assert_called_once_with("🤣", now=10.0)
        backend.on_reply.assert_called_once_with(
            ["happy"], intensity=70, now=11.0, text="great"
        )

    def test_avatar_and_application_events_are_forwarded(self):
        with patch("kira.services.mood_service.mood") as backend:
            backend.avatar_hint.return_value = ("happy", 40)
            backend.on_event.return_value = "recorded"
            self.assertEqual(self.service.avatar_hint(now=12.0), ("happy", 40))
            self.assertEqual(self.service.on_event("notification", {"source": "test"}), "recorded")
        backend.avatar_hint.assert_called_once_with(now=12.0)
        backend.on_event.assert_called_once_with("notification", {"source": "test"})

    def test_character_mutations_and_scope_preserve_legacy_results(self):
        with patch("kira.services.mood_service.mood") as backend:
            backend.set_active_character.return_value = "ren"
            backend.set_character_traits.return_value = {"kind": 1}
            backend.character_scope.return_value = object()
            self.assertEqual(self.service.set_active_character("ren", {"kind": 1}), "ren")
            self.assertEqual(self.service.set_character_traits("ren", {"kind": 1}), {"kind": 1})
            scope = self.service.character_scope("ren", {"kind": 1})
        self.assertIs(scope, backend.character_scope.return_value)
        backend.set_active_character.assert_called_once_with("ren", {"kind": 1})
        backend.set_character_traits.assert_called_once_with("ren", {"kind": 1})
        backend.character_scope.assert_called_once_with("ren", {"kind": 1})

    def test_initiative_marker_and_reset_are_forwarded(self):
        with patch("kira.services.mood_service.mood") as backend:
            self.service.mark_initiative_sent(memory_id="memory-1", now=1234.5)
            self.service.reset()
        backend.mark_initiative_sent.assert_called_once_with(
            memory_id="memory-1", now=1234.5
        )
        backend.reset.assert_called_once_with()

    def test_production_modules_do_not_import_the_legacy_mood_module_directly(self):
        package_root = Path(__file__).resolve().parents[1] / "kira"
        adapter = (package_root / "services" / "mood_service.py").resolve()
        violations = []
        for source in package_root.rglob("*.py"):
            if source.resolve() == adapter:
                continue
            try:
                tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            except (OSError, SyntaxError) as exc:
                self.fail(f"Could not inspect production module {source}: {exc}")
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name == "kira.mood" or alias.name.startswith("kira.mood.") for alias in node.names):
                        violations.append(f"{source}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom):
                    imports_legacy_module = (
                        node.module == "kira.mood"
                        or (node.module is None and node.level > 0 and any(alias.name == "mood" for alias in node.names))
                        or (node.level > 0 and node.module == "mood")
                    )
                    if imports_legacy_module:
                        violations.append(f"{source}:{node.lineno}")
        self.assertEqual(violations, [], "Direct legacy Mood imports found: " + ", ".join(violations))


if __name__ == "__main__":
    unittest.main()
