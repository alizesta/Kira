"""Regression tests for deterministic, isolated dependency lock generation."""
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

    @staticmethod
    def write_valid_lock(path: Path) -> None:
        path.write_text(
            "demo==1.2.3 --hash=sha256:" + "a" * 64 + "\n",
            encoding="utf-8",
        )

    def test_compile_command_is_deterministic_and_ignores_machine_local_config(self):
        root = Path("/repo")
        engine = next(g for g in generator.GROUPS if g.name == "voice-kitten-engine")
        args = ("uv", root, engine, "3.11", generator.DEFAULT_PLATFORM, Path("out.txt"))
        self.assertEqual(
            generator.build_compile_command(*args),
            generator.build_compile_command(*args),
        )
        command = generator.build_compile_command(*args)
        for flag in (
            "--generate-hashes", "--no-header", "--no-annotate",
            "--no-emit-index-url", "--no-emit-find-links", "--no-sources",
            "--no-config", "--resolution", "--exclude-newer",
        ):
            self.assertIn(flag, command)
        self.assertIn("--no-deps", command)
        self.assertEqual(command.count("--constraint"), 1)

    def test_lock_fingerprint_changes_when_package_index_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_root(Path(temp) / "repo")
            default = generator._input_fingerprint(
                root, ("3.11",), generator.DEFAULT_PLATFORM,
                generator.DEFAULT_SNAPSHOT_CUTOFF,
            )
            mirror = generator._input_fingerprint(
                root, ("3.11",), generator.DEFAULT_PLATFORM,
                generator.DEFAULT_SNAPSHOT_CUTOFF, "https://mirror.example/simple",
            )
            self.assertNotEqual(default, mirror)

    def test_core_hash_lock_is_converted_to_plain_constraints(self):
        with tempfile.TemporaryDirectory() as temp:
            core_lock = Path(temp) / "core.txt"
            constraints = Path(temp) / "core-constraints.txt"
            core_lock.write_text(
                "PySide6==6.12.0 --hash=sha256:" + "a" * 64 + "\n"
                "requests==2.32.5 --hash=sha256:" + "b" * 64 + "\n",
                encoding="utf-8",
            )
            generator._write_core_constraints(core_lock, constraints)
            self.assertEqual(
                constraints.read_text(encoding="utf-8"),
                "pyside6==6.12.0\nrequests==2.32.5\n",
            )

    def test_optional_groups_are_constrained_by_the_generated_core_lock(self):
        root = Path("/repo")
        group = next(g for g in generator.GROUPS if g.name == "ocr")
        core_lock = Path("/tmp/core.txt")
        command = generator.build_compile_command(
            "uv", root, group, "3.11", generator.DEFAULT_PLATFORM, Path("ocr.txt"),
            extra_constraints=(core_lock,),
        )
        self.assertIn(str(core_lock), command)
        self.assertEqual(command.count("--constraint"), 2)

    def test_success_publishes_all_groups_for_both_python_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_root(Path(temp) / "repo")
            output = root / "dependency-locks" / "windows-x86_64"
            calls = []

            def runner(command, **kwargs):
                calls.append(command)
                self.write_valid_lock(Path(command[command.index("--output-file") + 1]))
                return CompletedProcess(command, 0)

            result = generator.generate_locks(
                root=root, output_dir=output, uv_executable="uv",
                runner=runner, out=lambda _message: None,
            )
            self.assertEqual(result, 0)
            self.assertEqual(len(calls), len(generator.GROUPS) * 2)
            self.assertTrue((output / "python311" / "core.txt").is_file())
            self.assertTrue((output / "python312" / "voice-kitten-engine.txt").is_file())
            self.assertEqual(
                (output / "python311" / "core-constraints.txt").read_text(encoding="utf-8"),
                "demo==1.2.3\n",
            )
            call_count = len(calls)
            reused = generator.generate_locks(
                root=root, output_dir=output, uv_executable="uv",
                runner=runner, out=lambda _message: None,
            )
            self.assertEqual(reused, 0)
            self.assertEqual(len(calls), call_count)

    def test_optional_resolution_failure_does_not_block_core_or_other_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_root(Path(temp) / "repo")
            output = root / "dependency-locks" / "windows-x86_64"
            failed_group = "audio"
            messages = []

            def runner(command, **kwargs):
                if Path(command[3]).name == "requirements-audio.txt":
                    return CompletedProcess(command, 1)
                self.write_valid_lock(Path(command[command.index("--output-file") + 1]))
                return CompletedProcess(command, 0)

            result = generator.generate_locks(
                root=root, output_dir=output, uv_executable="uv",
                python_versions=("3.11",), runner=runner, out=messages.append,
            )
            self.assertEqual(result, 0)
            self.assertTrue((output / "python311" / "core.txt").is_file())
            self.assertTrue((output / "python311" / "ocr.txt").is_file())
            self.assertFalse((output / "python311" / f"{failed_group}.txt").exists())
            self.assertTrue(any("optional dependency locks" in line for line in messages))
            reused = generator.generate_locks(
                root=root, output_dir=output, uv_executable="uv",
                python_versions=("3.11",), runner=runner, out=lambda _message: None,
            )
            self.assertEqual(reused, 0)

    def test_core_resolution_failure_preserves_previous_lock_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_root(Path(temp) / "repo")
            output = root / "dependency-locks" / "windows-x86_64"
            previous = output / "python311" / "core.txt"
            previous.parent.mkdir(parents=True)
            previous.write_text("old-lock\n", encoding="utf-8")

            def runner(command, **kwargs):
                return CompletedProcess(command, 1)

            result = generator.generate_locks(
                root=root, output_dir=output, uv_executable="uv",
                python_versions=("3.11",), runner=runner, out=lambda _message: None,
            )
            self.assertEqual(result, 1)
            self.assertEqual(previous.read_text(encoding="utf-8"), "old-lock\n")

    def test_every_package_stanza_requires_a_hash_and_duplicate_pins_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.txt"
            path.write_text(
                "demo==1.2.3 --hash=sha256:" + "a" * 64 + "\n"
                "other==2.0.0\n",
                encoding="utf-8",
            )
            with self.assertRaises(generator.LockGenerationError):
                generator._validate_lock(path)
            path.write_text(
                "Demo_Pkg==1.0.0 --hash=sha256:" + "a" * 64 + "\n"
                "demo-pkg==2.0.0 --hash=sha256:" + "b" * 64 + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(generator.LockGenerationError):
                generator._validate_lock(path)

    def test_supported_python_version_parser_rejects_other_versions(self):
        self.assertEqual(generator._parse_versions("3.12,3.11"), ("3.12", "3.11"))
        with self.assertRaises(Exception):
            generator._parse_versions("3.10")


if __name__ == "__main__":
    unittest.main()
