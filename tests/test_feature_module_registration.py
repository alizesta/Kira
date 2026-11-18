"""Integration tests for lifecycle-managed Chat application service registration."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from kira.app.dependency_container import DependencyContainer
from kira.app.event_bus import EventBus
from kira.app.feature_modules import (
    APPLICATION_FEATURE_DEPENDENCIES,
    register_application_modules,
)
from kira.app.module_manager import ModuleManager, ModuleState
from kira.app.organization_application import ChatOrganizationService
from kira.app.chat_search_application import ChatSearchService
from kira.app.chat_transfer_application import ChatTransfer


class MemoryChatHistory:
    """One persistence test double implementing the shared Chat History capabilities."""

    def __init__(self):
        self.records = {
            "conversation-1": {
                "id": "conversation-1",
                "character_id": "kira",
                "title": "First conversation",
                "metadata": {},
                "status": "active",
                "created_at": "2026-11-18T10:00:00Z",
                "updated_at": "2026-11-18T10:00:00Z",
            }
        }
        self.messages = [
            {
                "id": 1,
                "role": "user",
                "content": "hello search",
                "created_at": "2026-11-18T10:01:00Z",
                "character_id": "kira",
                "conversation_id": "conversation-1",
                "metadata": {"session_id": "session-1"},
                "status": "complete",
            }
        ]
        self.lifecycle = []

    def start(self):
        self.lifecycle.append("start")

    def stop(self):
        self.lifecycle.append("stop")

    def get_conversation(self, conversation_id):
        return self.records.get(conversation_id)

    def list_conversations(self, character_id=None):
        rows = list(self.records.values())
        return [
            dict(row)
            for row in rows
            if character_id is None or row["character_id"] == character_id
        ]

    def mutate_conversations(self, mutations):
        updated = {}
        for conversation_id, mutation in mutations:
            record = self.records[conversation_id]
            updated[conversation_id] = mutation(record)
        return updated

    def mutate_all_conversations(self, character_id, mutator):
        updated = {}
        for conversation_id, record in self.records.items():
            if character_id is None or record["character_id"] == character_id:
                updated[conversation_id] = mutator(record)
        return updated

    def messages_after(self, after_id=0, limit=500):
        return [row for row in self.messages if row["id"] > after_id][:limit]

    def get_transfer_messages(
        self, conversation_id, character_id, after_created_at="", after_id=0, limit=1000
    ):
        rows = [
            row for row in self.messages
            if row["conversation_id"] == conversation_id
            and row["character_id"] == character_id
            and (row["created_at"], row["id"]) > (after_created_at, after_id)
        ]
        return rows[:limit]

    def import_transfer_records(self, conversations, messages):
        return {
            "imported_conversations": len(conversations),
            "imported_messages": len(messages),
            "skipped_duplicates": 0,
            "remapped_conversations": 0,
            "remapped_messages": 0,
            "conversation_id_map": {
                item["id"]: item["id"] for item in conversations
            },
        }


class EventPublisher:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **kwargs):
        self.events.append((event_type, kwargs))


class MemoryTransferFilePort:
    def __init__(self):
        self.files = {}

    def read_bytes(self, source: Path, *, max_bytes: int):
        content = self.files[Path(source)]
        if len(content) > max_bytes:
            raise ValueError("file exceeds configured import size")
        return content

    def write_bytes_atomically(self, directory: Path, filename: str, content: bytes):
        path = Path(directory) / filename
        self.files[path] = bytes(content)
        return path


class FeatureModuleRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.container = DependencyContainer()
        self.event_bus = EventBus()
        self.manager = ModuleManager(self.container, self.event_bus)
        self.repository = MemoryChatHistory()
        self.publisher = EventPublisher()
        self.file_port = MemoryTransferFilePort()

        self.module_ids = register_application_modules(
            self.manager,
            self.container,
            settings={},
            event_publisher=self.publisher,
            service_factories={
                "chat_history_service": lambda: self.repository,
            },
            transfer_file_port=self.file_port,
        )

    def tearDown(self):
        self.manager.shutdown()
        self.event_bus.close()

    def test_new_use_cases_are_registered_with_chat_history_dependencies(self):
        expected = {
            "conversation_organization",
            "chat_search",
            "chat_transfer",
        }
        self.assertTrue(expected.issubset(set(self.module_ids)))
        for module_id in expected:
            self.assertEqual(
                APPLICATION_FEATURE_DEPENDENCIES[module_id],
                ("chat_history",),
            )

    def test_each_use_case_resolves_the_same_lifecycle_managed_repository(self):
        self.manager.start("conversation_organization")
        self.manager.start("chat_search")
        self.manager.start("chat_transfer")

        organization = self.container.resolve(
            "conversation_organization_application_service"
        )
        search = self.container.resolve("chat_search_application_service")
        transfer = self.container.resolve("chat_transfer_application_service")

        self.assertIsInstance(organization, ChatOrganizationService)
        self.assertIsInstance(search, ChatSearchService)
        self.assertIsInstance(transfer, ChatTransfer)
        self.assertIs(organization._repository, self.repository)
        self.assertIs(search._repository, self.repository)
        self.assertIs(search._conversation_reader, self.repository)
        self.assertIs(transfer._repository, self.repository)
        self.assertIs(transfer._file_port, self.file_port)
        self.assertEqual(self.repository.lifecycle, ["start"])

    def test_registered_services_execute_against_the_shared_history_adapter(self):
        self.manager.start("conversation_organization")
        self.manager.start("chat_search")
        self.manager.start("chat_transfer")

        organization = self.container.resolve(
            "conversation_organization_application_service"
        )
        search = self.container.resolve("chat_search_application_service")
        transfer = self.container.resolve("chat_transfer_application_service")

        changed = organization.add_tag("conversation-1", "work")
        self.assertTrue(changed.success)
        self.assertEqual(
            self.repository.records["conversation-1"]["metadata"]["organization"]["tags"],
            ["work"],
        )
        self.assertTrue(
            any(
                name == "conversation_metadata_updated"
                for name, _ in self.publisher.events
            )
        )

        results = search.search("hello")
        self.assertEqual([item.message_id for item in results.results], [1])

        destination = transfer.write_export(
            Path("memory-export"), filename="conversation.json"
        )
        self.assertIn(destination, self.file_port.files)
        preview = transfer.preview_import(destination)
        self.assertTrue(preview.valid, preview.errors)
        self.assertEqual(preview.conversation_count, 1)

    def test_starting_a_dependent_service_starts_persistence_first(self):
        self.manager.start("chat_transfer")
        self.assertEqual(self.repository.lifecycle, ["start"])
        self.assertEqual(self.manager.state("chat_history"), ModuleState.STARTED)
        self.assertEqual(self.manager.state("chat_transfer"), ModuleState.STARTED)

    def test_shutdown_stops_the_shared_persistence_module_after_dependents(self):
        self.manager.start("conversation_organization")
        self.manager.start("chat_search")
        self.manager.start("chat_transfer")

        errors = self.manager.shutdown()

        self.assertEqual(errors, {})
        self.assertEqual(self.repository.lifecycle, ["start", "stop"])
        self.assertEqual(self.manager.state("chat_history"), ModuleState.DISPOSED)
        self.assertEqual(self.manager.state("chat_transfer"), ModuleState.DISPOSED)

    def test_failed_persistence_dependency_prevents_dependent_service_creation(self):
        class BrokenHistory:
            def start(self):
                raise RuntimeError("database unavailable")

        manager = ModuleManager(DependencyContainer(), EventBus())
        container = manager.container
        publisher = EventPublisher()
        register_application_modules(
            manager,
            container,
            settings={},
            event_publisher=publisher,
            service_factories={"chat_history_service": BrokenHistory},
        )
        try:
            with self.assertRaises(Exception):
                manager.start("chat_search")
            self.assertEqual(manager.state("chat_history"), ModuleState.FAILED)
            self.assertEqual(manager.state("chat_search"), ModuleState.FAILED)
            with self.assertRaises(KeyError):
                container.resolve("chat_search_application_service")
        finally:
            manager.shutdown()
            manager.event_bus.close()


if __name__ == "__main__":
    unittest.main()
