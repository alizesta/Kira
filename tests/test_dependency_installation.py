"""Regression tests for the dependency resolver and install lifecycle."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import install_deps


class DependencyInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.requirements = self.root / "requirements-test.txt"
        self.requirements.write_text("alpha>=1\nbeta<3\n", encoding="utf-8")
        self.constraints = self.root / "constraints-test.txt"
        self.constraints.write_text("alpha==1.2\n", encoding="utf-8")
        self.site_packages = self.root / "site-packages"
        self.scripts = self.root / "Scripts"
        self.site_packages.mkdir()
        self.scripts.mkdir()
        (self.site_packages / "existing.dist-info").mkdir()
        (self.site_packages / "existing.dist-info" / "METADATA").write_text(
            "Name: existing\nVersion: 1.0\n", encoding="utf-8"
        )
        (self.scripts / "existing.exe").write_bytes(b"old-script")

    def patched_environment(self):
        return mock.patch(
            "install_deps._environment_paths",
            return_value=[self.site_packages, self.scripts],
        )

    def make_runner(self, results=None):
        calls = []
        outcomes = list(results or [(0, "ok"), (0, "installed"), (0, "No broken requirements found.")])

        def runner(command):
            calls.append(list(command))
            return outcomes.pop(0)

        return calls, runner

    def test_preflight_install_and_pip_check_share_the_same_constraints(self):
        calls, runner = self.make_runner()
        output = []
        with self.patched_environment():
            result = install_deps.install(
                self.requirements,
                runner=runner,
                out=output.append,
                constraints=[self.constraints],
            )

        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 3)
        self.assertIn("--dry-run", calls[0])
        self.assertIn("--report", calls[0])
        self.assertIn("-r", calls[0])
        self.assertIn(str(self.requirements), calls[0])
        self.assertIn("--constraint", calls[0])
        self.assertIn(str(self.constraints), calls[0])
        self.assertNotIn("--upgrade", calls[0])
        self.assertNotIn("--upgrade", calls[1])
        self.assertEqual(calls[2][-1], "check")
        self.assertTrue(any("installed and verified" in line for line in output))

    def test_resolution_failure_stops_before_mutating_the_environment(self):
        calls, runner = self.make_runner([(1, "ResolutionImpossible: conflicting dependencies")])
        output = []
        with self.patched_environment():
            result = install_deps.install(
                self.requirements, runner=runner, out=output.append,
                constraints=[self.constraints],
            )
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("--dry-run", calls[0])
        self.assertTrue(any("No package installation was attempted" in line for line in output))

    def test_upgrade_is_opt_in_and_applies_to_preflight_and_install(self):
        calls, runner = self.make_runner()
        with self.patched_environment():
            result = install_deps.install(
                self.requirements, runner=runner, out=lambda _message: None,
                constraints=[self.constraints], upgrade=True,
            )
        self.assertEqual(result, 0)
        self.assertIn("--upgrade", calls[0])
        self.assertIn("--upgrade", calls[1])

    def test_missing_constraint_stops_before_pip_is_invoked(self):
        calls, runner = self.make_runner()
        output = []
        missing = self.root / "missing-constraints.txt"
        with self.patched_environment():
            result = install_deps.install(
                self.requirements, runner=runner, out=output.append,
                constraints=[missing],
            )
        self.assertEqual(result, 1)
        self.assertEqual(calls, [])
        self.assertTrue(any("Constraint file does not exist" in line for line in output))

    def test_post_install_pip_check_failure_is_not_reported_as_success(self):
        calls, runner = self.make_runner([
            (0, "resolved"), (0, "installed"),
            (1, "alpha 1.2 has requirement beta<2, but beta 2.5 is installed"),
        ])
        output = []
        with self.patched_environment():
            result = install_deps.install(
                self.requirements, runner=runner, out=output.append,
                constraints=[self.constraints],
            )
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 3)
        self.assertTrue(any("pip check found" in line for line in output))
        self.assertFalse(any("installed and verified" in line for line in output))

    def test_mid_install_failure_restores_packages_and_scripts(self):
        calls = []
        output = []

        def runner(command):
            calls.append(list(command))
            if "--dry-run" in command:
                return 0, "resolved"
            if "install" in command:
                (self.site_packages / "partially-installed.dist-info").mkdir()
                (self.scripts / "new-command.exe").write_bytes(b"partial")
                (self.site_packages / "existing.dist-info" / "METADATA").write_text(
                    "corrupted", encoding="utf-8"
                )
                return 1, "wheel installation failed halfway"
            return 0, "not expected"

        with self.patched_environment():
            result = install_deps.install(
                self.requirements, runner=runner, out=output.append,
                constraints=[self.constraints],
            )

        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse((self.site_packages / "partially-installed.dist-info").exists())
        self.assertFalse((self.scripts / "new-command.exe").exists())
        self.assertEqual(
            (self.site_packages / "existing.dist-info" / "METADATA").read_text(encoding="utf-8"),
            "Name: existing\nVersion: 1.0\n",
        )
        self.assertEqual((self.scripts / "existing.exe").read_bytes(), b"old-script")
        self.assertTrue(any("Rollback completed" in line for line in output))

    def test_snapshot_failure_prevents_the_mutating_install(self):
        calls, runner = self.make_runner()
        output = []
        with self.patched_environment(), mock.patch(
            "install_deps.shutil.copytree", side_effect=OSError("disk full")
        ):
            result = install_deps.install(
                self.requirements, runner=runner, out=output.append,
                constraints=[self.constraints],
            )
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("--dry-run", calls[0])
        self.assertTrue(any("installation was not attempted" in line for line in output))


if __name__ == "__main__":
    unittest.main()
