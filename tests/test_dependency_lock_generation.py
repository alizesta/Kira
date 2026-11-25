"""Regression tests for reproducible dependency lock generation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess

from scripts import generate_dependency_locks as generator


class DependencyLockGenerationTests(unittest.TestCase):
    def make_root(self, root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        for group in generator.GROUPS:
            (root / group.requirements).write_text("demo>=1\n", encoding="utf-8")
            for constraint in group.constraints:
                (root / constraint).write_text("demo<3\n", encoding="utf-8")
        return root

    def test_compile_command_covers_target_constraints_hashes_and_no_deps(self):
        root = Path("/repo")
        engine = next(g for g in generator.GROUPS if g.name == "voice-kitten-engine")
        command = generator.build_compile_command(
            "uv", root, engine, "3.11", generator.DEFAULT_PLATFORM, Path("out.txt")
        )

        self.assertEqual(command[:3], ["uv", "pip", "compile"])
        self.assertIn("--python-version", command)
        self.assertEqual(command[command.index("--python-version") + 1], "3.11")
        self.assertIn("--python-platform", command)
        self.assertIn("--generate-hashes", command)
        self.assertIn("--no-deps", command)
        self.assertEqual(command.count("--constraint"), 1)

    def test_success_publishes_all_groups_for_both_supported_python_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_root(Path(temp) / "repo")
            output = root / "dependency-locks" / "windows-x86_64"
            calls = []

            def runner(command, **kwargs):
                calls.append(command)
                lock_path = Path(command[command.index("--output-file") + 1])
                lock_path.write_text(
                    "demo==1.2.3 --hash=sha256:0123456789abcdef\n",
                    encoding="utf-8",
                )
                return CompletedProcess(command, 0)

            result = generator.generate_locks(
                root=root,
                output_dir=output,
                uv_executable="uv",
                runner=runner,
                out=lambda _message: None,
            )

            self.assertEqual(result, 0)
            self.assertEqual(len(calls), len(generator.GROUPS) * 2)
            self.assertEqual(
                len(list(output.glob("python*/*.txt"))), len(generator.GROUPS) * 2
            )
            self.assertTrue((output / "python311" / "core.txt").is_file())
            self.assertTrue((output / "python312" / "voice-kitten-engine.txt").is_file())

    def test_resolution_failure_preserves_previous_lock_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_root(Path(temp) / "repo")
            output = root / "dependency-locks" / "windows-x86_64"
            previous = output / "python311" / "core.txt"
            previous.parent.mkdir(parents=True)
            previous.write_text("old-lock\n", encoding="utf-8")
            calls = 0

            def runner(command, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    return CompletedProcess(command, 1)
                lock_path = Path(command[command.index("--output-file") + 1])
                lock_path.write_text(
                    "demo==1.2.3 --hash=sha256:0123456789abcdef\n",
                    encoding="utf-8",
                )
                return CompletedProcess(command, 0)

            result = generator.generate_locks(
                root=root,
                output_dir=output,
                uv_executable="uv",
                runner=runner,
                out=lambda _message: None,
            )

            self.assertEqual(result, 1)
            self.assertEqual(previous.read_text(encoding="utf-8"), "old-lock\n")
            self.assertEqual(len(list(output.glob("**/*.txt"))), 1)

    def test_hashless_resolver_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.txt"
            path.write_text("demo==1.2.3\n", encoding="utf-8")
            with self.assertRaises(generator.LockGenerationError):
                generator._validate_lock(path)

    def test_supported_python_version_parser_rejects_other_versions(self):
        self.assertEqual(generator._parse_versions("3.12,3.11"), ("3.12", "3.11"))
        with self.assertRaises(Exception):
            generator._parse_versions("3.10")


if __name__ == "__main__":
    unittest.main()
