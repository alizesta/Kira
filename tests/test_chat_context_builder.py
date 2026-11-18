import unittest

from kira.chat.context_builder import ContextBuilder, ContextRequest, latest_user_text


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

    def test_context_budget_drops_complete_oldest_turns(self):
        messages = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "middle"},
            {"role": "assistant", "content": "middle answer"},
            {"role": "user", "content": "latest"},
        ]
        # Removing only the first user message would fit, but would orphan its answer.
        result = self.builder.build(ContextRequest(messages=messages, max_context_chars=35))
        self.assertEqual(
            [item["content"] for item in result.messages],
            ["middle", "middle answer", "latest"],
        )
        self.assertEqual(result.dropped_messages, 2)

    def test_attachment_replaces_current_user_message_without_mutating_source(self):
        original = [{"role": "user", "content": "see file"}]
        result = self.builder.build(ContextRequest(
            messages=original,
            turn_extra={"model": "file text", "images": ["image-data"]},
        ))
        self.assertEqual(result.messages[0]["content"], "file text")
        self.assertEqual(result.messages[0]["images"], ["image-data"])
        self.assertEqual(original, [{"role": "user", "content": "see file"}])

    def test_structured_attachment_content_is_composed_in_context_builder(self):
        result = self.builder.build(ContextRequest(
            messages=[{"role": "user", "content": "stored excerpt"}],
            turn_extra={
                "text": "summarize these",
                "files": [{"name": "notes.txt", "text": "file body", "truncated": False}],
                "images": [{"name": "screen.png", "mime": "image/png", "b64": "encoded"}],
            },
        ))
        message = result.messages[0]
        self.assertIn("summarize these", message["content"])
        self.assertIn("--- فایل ضمیمه: notes.txt ---", message["content"])
        self.assertIn("file body", message["content"])
        self.assertIn("[تصویر ضمیمه: screen.png]", message["content"])
        self.assertEqual(message["images"][0]["name"], "screen.png")

    def test_structured_image_only_uses_context_builder_search_instruction(self):
        result = self.builder.build(ContextRequest(
            messages=[{"role": "user", "content": ""}],
            turn_extra={
                "text": "",
                "files": [],
                "images": [{"name": "picture.png", "mime": "image/png", "b64": "encoded"}],
                "search": True,
            },
        ))
        self.assertIn("این تصویر چیست؟", result.messages[0]["content"])

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

    def test_prompt_dependencies_are_injected_without_builder_ownership(self):
        result = self.builder.build(ContextRequest(
            settings={"temperature": 0.2},
            character_profile={"name": "Mika"},
            memory="relevant memory",
            mood="calm mood",
            voice_input=True,
            mode="task",
            format_hint="format hint",
        ))
        settings, kwargs = self.calls[-1]
        self.assertEqual(settings, {"temperature": 0.2})
        self.assertEqual(kwargs["memory_block"], "relevant memory")
        self.assertEqual(kwargs["mood_block"], "calm mood")
        self.assertTrue(kwargs["voice_input"])
        self.assertEqual(kwargs["mode"], "task")
        self.assertEqual(kwargs["format_hint"], "format hint")
        self.assertEqual(kwargs["character_profile"], {"name": "Mika"})
        self.assertEqual(result.character_id, "")

    def test_system_messages_are_retained_ahead_of_recent_history(self):
        result = self.builder.build(ContextRequest(
            messages=[
                {"role": "system", "content": "system rule"},
                {"role": "user", "content": "old" * 20},
                {"role": "assistant", "content": "old answer" * 10},
                {"role": "user", "content": "latest"},
            ],
            max_context_chars=20,
        ))
        self.assertEqual([item["role"] for item in result.messages], ["system", "user"])
        self.assertEqual(result.messages[0]["content"], "system rule")
        self.assertEqual(result.messages[-1]["content"], "latest")

    def test_latest_user_text_ignores_assistant_messages_and_returns_newest_user(self):
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "assistant text"},
            {"role": "user", "content": "latest"},
        ]
        self.assertEqual(latest_user_text(history), "latest")
        self.assertEqual(latest_user_text([{"role": "assistant", "content": "no user"}]), "")
        self.assertEqual(latest_user_text([]), "")

    def test_missing_prompt_builder_is_rejected(self):
        with self.assertRaises(TypeError):
            ContextBuilder(None)


if __name__ == "__main__":
    unittest.main()
