"""Integration checks for the production application feature lifecycle graph."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kira.app.dependency_container import DependencyContainer
from kira.app.event_bus import EventBus
from kira.app.feature_modules import (
    APPLICATION_FEATURE_DEPENDENCIES,
    register_application_modules,
)
from kira.app.module_manager import ModuleManager, ModuleState
from kira.chat.persistence import ChatPersistence, SqliteChatRepository
from kira.services.chat_history_service import SqliteChatHistoryService


class ApplicationFeatureLifecycleTests(unittest.TestCase):
    def test_all_application_features_start_and_shutdown_in_dependency_order(self):
        with tempfile.TemporaryDirectory(prefix="kira-feature-lifecycle-") as directory:
            container = DependencyContainer()
            event_bus = EventBus()
            manager = ModuleManager(container, event_bus)
            database = Path(directory) / "chat.sqlite3"

            module_ids = register_application_modules(
                manager,
                container,
                settings={"vision_mode": "economic"},
                event_publisher=event_bus,
                service_factories={
                    "chat_history_service": lambda: SqliteChatHistoryService(
                        ChatPersistence(SqliteChatRepository(database))
                    )
                },
            )

            self.assertEqual(set(module_ids), set(APPLICATION_FEATURE_DEPENDENCIES))
            states = manager.start_all()
            self.assertEqual(set(states), set(module_ids))
            self.assertTrue(all(state == ModuleState.STARTED for state in states.values()))

            expected_services = (
                "memory_service",
                "mood_service",
                "character_service",
                "chat_history_service",
                "conversation_lifecycle_service",
                "conversation_organization_application_service",
                "chat_search_application_service",
                "chat_transfer_application_service",
                "web_search_service",
                "game_mode_application_service",
                "provider_application_service",
                "coding_agent_application_service",
                "runtime_settings_application_service",
                "vision_application_service",
                "chat_application_service_factory",
                "session_application_service_factory",
                "voice_application_service_factory",
            )
            for key in expected_services:
                self.assertIsNotNone(container.resolve(key), key)

            errors = manager.shutdown()
            self.assertEqual(errors, {})
            self.assertTrue(
                all(manager.state(module_id) == ModuleState.DISPOSED for module_id in module_ids)
            )
            for key in expected_services:
                with self.assertRaises(KeyError):
                    container.resolve(key)
            event_bus.close()

    def test_feature_graph_declares_real_runtime_dependencies(self):
        self.assertEqual(APPLICATION_FEATURE_DEPENDENCIES["vision"], ("game_mode",))
        self.assertEqual(APPLICATION_FEATURE_DEPENDENCIES["conversation_lifecycle"], ("chat_history",))
        self.assertEqual(APPLICATION_FEATURE_DEPENDENCIES["conversation_organization"], ("chat_history",))
        self.assertEqual(APPLICATION_FEATURE_DEPENDENCIES["chat_search"], ("chat_history",))
        self.assertEqual(APPLICATION_FEATURE_DEPENDENCIES["chat_transfer"], ("chat_history",))
        self.assertEqual(
            APPLICATION_FEATURE_DEPENDENCIES["chat_application"],
            ("chat_history", "conversation_lifecycle"),
        )
        self.assertEqual(APPLICATION_FEATURE_DEPENDENCIES["session_application"], ("chat_application",))


if __name__ == "__main__":
    unittest.main()
