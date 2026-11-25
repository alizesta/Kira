"""Architecture regression tests for the production Composition Root."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def parse(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)


class CompositionRootContractTests(unittest.TestCase):
    def test_qt_composition_root_is_outside_application_package(self):
        self.assertTrue((ROOT / "kira" / "ui" / "bootstrap.py").is_file())
        self.assertFalse((ROOT / "kira" / "app" / "bootstrap.py").exists())

    def test_window_composition_requires_bootstrap_owned_dependencies(self):
        module = parse("kira/ui/main_window_composition.py")
        function = next(
            node for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "initialize_main_window"
        )
        required = next(
            node.value for node in ast.walk(function)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "required" for target in node.targets)
        )
        keys = {key.value for key in required.keys if isinstance(key, ast.Constant)}
        self.assertTrue({
            "memory_service", "mood_service", "character_service",
            "chat_event_publisher", "chat_application_service_factory",
            "session_manager", "session_application_service_factory",
            "web_search_service", "voice_application_service_factory",
            "game_mode_application_service", "settings", "tool_agent",
            "provider_application_service", "coding_agent_application_service",
            "vision_application_service", "runtime_settings_application_service",
            "shared_skills_application_service",
            "conversation_organization_application_service",
            "chat_search_application_service",
            "chat_transfer_application_service",
            "initiative_application_service_factory",
        }.issubset(keys))

    def test_organization_search_and_transfer_are_registered_and_injected(self):
        modules = parse("kira/app/feature_modules.py")
        bootstrap = parse("kira/ui/bootstrap.py")
        composition = parse("kira/ui/main_window_composition.py")

        registered_strings = {
            node.value for node in ast.walk(modules)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertTrue({
            "conversation_organization",
            "chat_search",
            "chat_transfer",
            "conversation_organization_application_service",
            "chat_search_application_service",
            "chat_transfer_application_service",
        }.issubset(registered_strings))

        bootstrap_keywords = {
            node.arg for node in ast.walk(bootstrap) if isinstance(node, ast.keyword)
        }
        composition_args = {
            node.arg for node in ast.walk(composition) if isinstance(node, ast.arg)
        }
        composition_required = next(
            node.value for node in ast.walk(composition)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "required" for target in node.targets)
        )
        composition_required_keys = {
            key.value for key in composition_required.keys if isinstance(key, ast.Constant)
        }
        keys = {
            "conversation_organization_application_service",
            "chat_search_application_service",
            "chat_transfer_application_service",
        }
        self.assertTrue(keys.issubset(bootstrap_keywords))
        self.assertTrue(keys.issubset(composition_args))
        self.assertTrue(keys.issubset(composition_required_keys))

    def test_music_watcher_timer_is_declared_presentation_state(self):
        context = parse("kira/ui/window_presentation_context.py")
        composition = parse("kira/ui/main_window_composition.py")
        state_fields = next(
            node.value for node in context.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "STATE_FIELDS" for target in node.targets)
        )
        declared = {item.value for item in state_fields.elts if isinstance(item, ast.Constant)}
        timer_assignments = [
            node for node in ast.walk(composition)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and target.attr == "_music_watcher_timer"
                for target in node.targets
            )
        ]
        self.assertIn("_music_watcher_timer", declared)
        self.assertTrue(timer_assignments)

    def test_provider_catalog_refresh_flag_is_declared_presentation_state(self):
        context = parse("kira/ui/window_presentation_context.py")
        composition = parse("kira/ui/main_window_composition.py")
        state_fields = next(
            node.value for node in context.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "STATE_FIELDS" for target in node.targets)
        )
        declared = {item.value for item in state_fields.elts if isinstance(item, ast.Constant)}
        assignments = [
            node for node in ast.walk(composition)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and target.attr == "_provider_catalog_auto_refresh_started"
                for target in node.targets
            )
        ]
        self.assertIn("_provider_catalog_auto_refresh_started", declared)
        self.assertTrue(assignments)

    def test_ui_composition_does_not_construct_application_services(self):
        module = parse("kira/ui/main_window_composition.py")
        forbidden_imports = []
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and node.module and (
                node.module.startswith("..app.") or node.module.startswith("..services.")
            ):
                forbidden_imports.append(node.module)
        self.assertEqual(forbidden_imports, [])

        forbidden_calls = {
            "PersonaMemoryService", "MoodStateService", "CharacterProfileService",
            "SqliteChatHistoryService", "WebSearchApplicationService",
            "GameModeApplicationService", "ProviderApplicationService",
            "CodingAgentApplicationService", "VisionApplicationService", "ToolAgent",
            "SessionManager", "ChatSession",
        }
        constructed = {
            node.func.id for node in ast.walk(module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(forbidden_calls & constructed)

    def test_bootstrap_owns_runtime_tool_agent_and_injects_it(self):
        module = parse("kira/ui/bootstrap.py")
        calls = [
            node for node in ast.walk(module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        self.assertIn("ToolAgent", {node.func.id for node in calls})
        main_window_calls = [
            node for node in calls if node.func.id == "MainWindow"
        ]
        self.assertEqual(len(main_window_calls), 1)
        self.assertEqual(main_window_calls[0].args, [])
        self.assertEqual(main_window_calls[0].keywords, [])

        initialize_calls = [
            node for node in calls if node.func.id == "initialize_main_window"
        ]
        self.assertEqual(len(initialize_calls), 1)
        keywords = {item.arg for item in initialize_calls[0].keywords}
        self.assertIn("tool_agent", keywords)
        self.assertIn("session_manager", keywords)

    def test_bootstrap_exposes_transfer_file_adapter_injection(self):
        bootstrap = parse("kira/ui/bootstrap.py")
        run_application = next(
            node for node in bootstrap.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_application"
        )
        self.assertIn(
            "transfer_file_port",
            {argument.arg for argument in run_application.args.kwonlyargs},
        )
        registration_calls = [
            node for node in ast.walk(run_application)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "register_application_modules"
        ]
        self.assertEqual(len(registration_calls), 1)
        self.assertIn(
            "transfer_file_port",
            {item.arg for item in registration_calls[0].keywords},
        )
        self.assertIn(
            "LocalChatTransferFileAdapter",
            {
                node.func.id for node in ast.walk(run_application)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            },
            "Bootstrap must supply a concrete filesystem adapter by default",
        )

    def test_shared_skills_is_registered_and_injected_from_bootstrap(self):
        modules = parse("kira/app/feature_modules.py")
        bootstrap = parse("kira/ui/bootstrap.py")
        composition = parse("kira/ui/main_window_composition.py")
        strings = {
            node.value for node in ast.walk(modules)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("shared_skills_application_service", strings)
        self.assertIn(
            "shared_skills_application_service",
            {node.arg for node in ast.walk(bootstrap) if isinstance(node, ast.keyword)},
        )
        self.assertIn(
            "shared_skills_application_service",
            {node.arg for node in ast.walk(composition) if isinstance(node, ast.arg)},
        )


class AttachmentControllerOwnershipTests(unittest.TestCase):
    def test_vision_controller_does_not_import_attachment_ui_support(self):
        source = (ROOT / "kira" / "ui" / "main_window_attachments_vision.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        imports = {
            node.module for node in ast.walk(module)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertNotIn("main_window_attachments_vision_support", imports)
        self.assertNotIn("QFileDialog", source)
        self.assertNotIn("AttachmentTile", source)

    def test_drag_drop_and_attachment_ui_are_owned_by_lazy_attachment_controller(self):
        main_window = parse("kira/ui/main_window.py")
        vision = parse("kira/ui/main_window_attachments_vision.py")
        attachments = parse("kira/ui/main_window_attachments.py")
        registrations = {
            node.value for node in ast.walk(main_window)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("attachments", registrations)
        self.assertIn("attachments", (ROOT / "kira" / "ui" / "main_window.py").read_text(encoding="utf-8"))
        self.assertIn("pick_attachments", {node.name for node in ast.walk(attachments) if isinstance(node, ast.FunctionDef)})
        self.assertIn("on_upload_event", {node.name for node in ast.walk(attachments) if isinstance(node, ast.FunctionDef)})
        self.assertIn("self.feature_controller(\"attachments\")", (ROOT / "kira" / "ui" / "main_window_attachments_vision.py").read_text(encoding="utf-8"))
        self.assertNotIn("def pick_attachments", {node.name for node in ast.walk(vision) if isinstance(node, ast.FunctionDef)})


class GameAudioControllerOwnershipTests(unittest.TestCase):
    def test_game_audio_lifecycle_is_owned_outside_vision_controller(self):
        main_window = (ROOT / "kira" / "ui" / "main_window.py").read_text(encoding="utf-8")
        vision = (ROOT / "kira" / "ui" / "main_window_attachments_vision.py").read_text(encoding="utf-8")
        game_audio = parse("kira/ui/main_window_game_audio.py")
        self.assertIn('"game_audio": controller_factory', main_window)
        self.assertIn('self.feature_controller("game_audio")', vision)
        names = {node.name for node in ast.walk(game_audio) if isinstance(node, ast.FunctionDef)}
        self.assertTrue({
            "_start_game_audio_listener",
            "_stop_game_audio_listener",
            "_on_game_audio_listener_finished",
            "on_game_audio_error",
            "on_game_audio_transcript",
        }.issubset(names))
        self.assertNotIn("def _start_game_audio_listener", {
            node.name for node in ast.walk(parse("kira/ui/main_window_attachments_vision.py"))
            if isinstance(node, ast.FunctionDef)
        })


class BrainReflectionCompositionTests(unittest.TestCase):
    def test_brain_and_reflection_services_are_required_and_injected(self):
        bootstrap = parse("kira/ui/bootstrap.py")
        composition = parse("kira/ui/main_window_composition.py")
        context = parse("kira/ui/window_presentation_context.py")
        bootstrap_keywords = {node.arg for node in ast.walk(bootstrap) if isinstance(node, ast.keyword)}
        composition_args = {node.arg for node in ast.walk(composition) if isinstance(node, ast.arg)}
        service_fields = {
            node.value for node in ast.walk(context)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertTrue({"brain_application_service", "reflection_application_service"}.issubset(bootstrap_keywords))
        self.assertTrue({"brain_application_service", "reflection_application_service"}.issubset(composition_args))
        self.assertTrue({"brain_application_service", "reflection_application_service"}.issubset(service_fields))



    def test_lazy_settings_tabs_block_reentrant_selection_changes_during_build(self):
        path = ROOT / "kira" / "ui" / "main_window_composition.py"
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source, filename=str(path))
        builder = next(
            node for node in ast.walk(module)
            if isinstance(node, ast.FunctionDef) and node.name == "_ensure_settings_tab"
        )
        body = ast.get_source_segment(source, builder)
        self.assertIn("tabs.blockSignals(True)", body)
        self.assertIn("tabs.currentWidget()", body)
        self.assertIn("tabs.setCurrentWidget(target_widget)", body)
        self.assertIn("len(new_pages) != 1", body)
        self.assertIn("tabs.blockSignals(previous_signals_blocked)", body)

if __name__ == "__main__":
    unittest.main()
