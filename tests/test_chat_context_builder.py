import unittest

from kira.chat.context_builder import ContextBuilder, ContextRequest


class ContextBuilderTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def compose(settings, **kwargs):
            self.calls.append((dict(settings), kwargs))
            profile = kwargs.get("character_profile") or {}
            return f"identity:{profile.get('name', 'unknown')}"

        self.builder = ContextBuilder(compose)

    def test_builds_independent_context_for_three_characters(self):
        results = [
            self.builder.build(ContextRequest(
                character_id=character_id,
                character_profile={"name": name},
                messages=[{"role": "user", "content": "hello"}],
            ))
            for character_id, name in (("kira", "Kira"), ("ren", "Ren"), ("mika", "Mika"))
        ]
        self.assertEqual([item.system_prompt for item in results],
                         ["identity:Kira", "identity:Ren", "identity:Mika"])
        self.assertEqual([item.character_id for item in results], ["kira", "ren", "mika"])

    def test_module_has_no_ui_or_session_imports(self):
        import ast
        from pathlib import Path

        tree = ast.parse(Path("kira/chat/context_builder.py").read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        forbidden = ("PySide6", "MainWindow", "ChatSession", "sqlite", "database")
        self.assertFalse([name for name in imported if any(token in name for token in forbidden)])

    def test_missing_memory_and_history_are_valid(self):
        result = self.builder.build(ContextRequest(character_id="ren"))
        self.assertEqual(result.system_prompt, "identity:unknown")
        self.assertEqual(result.messages, ())
        self.assertEqual(result.retained_context_chars, 0)

    def test_long_context_drops_oldest_messages_and_keeps_current_turn(self):
        messages = [
            {"role": "user", "content": "old" * 10},
            {"role": "assistant", "content": "answer" * 10},
            {"role": "user", "content": "current"},
        ]
        result = self.builder.build(ContextRequest(messages=messages, max_context_chars=20))
        self.assertEqual([m["content"] for m in result.messages], ["current"])
        self.assertEqual(result.dropped_messages, 2)
        self.assertEqual(result.retained_context_chars, 7)

    def test_history_order_is_preserved_when_within_budget(self):
        messages = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
        ]
        result = self.builder.build(ContextRequest(messages=messages, max_context_chars=100))
        self.assertEqual([m["content"] for m in result.messages], ["one", "two", "three"])

    def test_attachment_replaces_current_user_message_without_mutating_source(self):
        original = [{"role": "user", "content": "see file"}]
        result = self.builder.build(ContextRequest(
            messages=original,
            turn_extra={"model": "file text", "images": ["image-data"]},
        ))
        self.assertEqual(result.messages[0]["content"], "file text")
        self.assertEqual(result.messages[0]["images"], ["image-data"])
        self.assertEqual(original, [{"role": "user", "content": "see file"}])

    def test_attachment_without_current_user_message_is_ignored(self):
        result = self.builder.build(ContextRequest(
            messages=[{"role": "assistant", "content": "hello"}],
            turn_extra={"model": "file text", "images": ["image-data"]},
        ))
        self.assertNotIn("images", result.messages[0])

    def test_prompt_layers_keep_legacy_order_and_enrichment(self):
        builder = ContextBuilder(
            lambda *_args, **_kwargs: "base",
            prompt_enricher=lambda prompt: prompt + "\n\nbrain",
        )
        result = builder.build(ContextRequest(
            character_context="character",
            body_context="body",
            tool_context="tools",
            active_capabilities=("vision", "web"),
        ))
        self.assertLess(result.system_prompt.index("base"), result.system_prompt.index("character"))
        self.assertLess(result.system_prompt.index("character"), result.system_prompt.index("body"))
        self.assertLess(result.system_prompt.index("body"), result.system_prompt.index("tools"))
        self.assertLess(result.system_prompt.index("tools"), result.system_prompt.index("vision"))
        self.assertLess(result.system_prompt.index("web"), result.system_prompt.index("brain"))

    def test_sessions_do_not_share_messages_or_character_data(self):
        first = self.builder.build(ContextRequest(
            character_id="kira", character_profile={"name": "Kira"},
            messages=[{"role": "user", "content": "private kira"}],
        ))
        second = self.builder.build(ContextRequest(
            character_id="ren", character_profile={"name": "Ren"},
            messages=[{"role": "user", "content": "private ren"}],
        ))
        self.assertNotIn("private kira", str(second.messages))
        self.assertNotIn("private ren", str(first.messages))
        self.assertEqual(first.character_id, "kira")
        self.assertEqual(second.character_id, "ren")

    def test_missing_prompt_builder_is_rejected(self):
        with self.assertRaises(TypeError):
            ContextBuilder(None)


if __name__ == "__main__":
    unittest.main()
