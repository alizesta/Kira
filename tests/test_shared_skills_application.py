from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from kira.app.shared_skills_application import SharedSkillsApplicationService


class SharedSkillsApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = {}
        self.saved = []
        self.service = SharedSkillsApplicationService(
            self.root / "library",
            self.settings,
            persist_settings=lambda settings: self.saved.append(json.loads(json.dumps(settings))),
        )
        self.source = self.root / "skill"
        self.source.mkdir()
        (self.source / "manifest.json").write_text(
            json.dumps({
                "id": "research-helper",
                "name": "Research Helper",
                "version": "1.0.0",
                "description": "Research workflow",
            }),
            encoding="utf-8",
        )
        (self.source / "SKILL.md").write_text(
            "Use a structured research workflow.", encoding="utf-8"
        )

    def tearDown(self):
        self.service.dispose()
        self.temp.cleanup()

    def test_lifecycle_and_use_cases(self):
        self.service.start()
        manifest = self.service.install(self.source)
        self.assertEqual(manifest.skill_id, "research-helper")
        self.assertFalse(self.service.is_globally_enabled("research-helper"))

        self.service.set_enabled("research-helper", True)
        self.assertTrue(self.service.is_globally_enabled("research-helper"))
        self.assertTrue(self.service.is_enabled("research-helper", "kira"))
        self.assertIn("structured research workflow", self.service.prompt_for("ren"))
        self.assertTrue(self.saved)

        self.service.set_enabled(
            "research-helper", False, character_id="ren"
        )
        self.assertFalse(self.service.is_enabled("research-helper", "ren"))
        self.assertTrue(self.service.is_enabled("research-helper", "mika"))

        self.assertTrue(self.service.uninstall("research-helper"))
        self.assertFalse(self.service.is_enabled("research-helper", "mika"))

    def test_disposed_service_rejects_use(self):
        self.service.dispose()
        with self.assertRaises(RuntimeError):
            self.service.list_installed()


if __name__ == "__main__":
    unittest.main()
