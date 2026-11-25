"""Regression coverage for the allowlisted, secret-scanned release package."""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from scripts import build_release, release_manifest


def make_runtime_tree(root: Path) -> dict[str, bytes]:
    """Create the smallest complete installable tree required by the package contract."""
    files = {}
    for relative in release_manifest.REQUIRED_RELEASE_FILES:
        if relative.endswith(".py"):
            content = b"VALUE = 1\n"
        elif relative.endswith(".bat"):
            content = b"@echo off\necho Kira\n"
        elif relative.endswith(".vbs"):
            content = b"Option Explicit\n"
        elif relative.endswith((".png", ".ico")):
            content = b"test-binary\n"
        elif relative.endswith(".json"):
            content = b"{}\n"
        else:
            content = b"# runtime resource\n"
        files[relative] = content

    files["requirements.txt"] = b"PySide6>=6.7,<7\nrequests>=2.31,<3\n"
    files["requirements-voice-local.txt"] = b"piper-tts>=1.3.0,<2\n"
    files["constraints-voice.txt"] = b"Pillow>=8,<13\n"
    files.update({
        "README.md": b"Kira\n",
        "README.fa.md": "کیرا\n".encode("utf-8"),
        "CHANGELOG.md": b"1.2.6\n",
        "assets/icons/chat.svg": b"<svg/>\n",
        "emotion_library/emotions.json": b"{}\n",
    })
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return files


class ReleasePackageTests(unittest.TestCase):
    def test_timestamp_uses_project_zip_format(self):
        now = datetime(2026, 11, 11, 3, 7, tzinfo=ZoneInfo("Asia/Tehran"))
        self.assertEqual(build_release.release_stamp(now), "261111_0307")

    def test_known_local_artifacts_are_rejected(self):
        for name in (
            ".venv/Lib/site-packages/package.py", "kira/__pycache__/main.pyc",
            "logs/kira.log", "data/kira_memory.sqlite3", "settings.json",
            "ProjectKira_261111_0059.zip",
        ):
            with self.subTest(name=name):
                self.assertTrue(build_release.should_skip(Path(name)))
        self.assertFalse(build_release.should_skip(Path(".env.example")))

    def test_allowlist_accepts_reviewed_files_and_rejects_unknown_paths(self):
        self.assertTrue(release_manifest.is_release_path_allowed("kira/vision_pipeline.py"))
        self.assertTrue(release_manifest.is_release_path_allowed("scripts/setup_local_voice.py"))
        self.assertTrue(release_manifest.is_release_path_allowed("emotion_library/emotions.json"))
        for name in (
            "tests/test_release_package.py", "docs/internal.md", "scripts/build_release.py",
            "new_root_secret.txt", ".env.example", "kira/../secrets.json",
            "C:\\private\\settings.json", "kira/new_module_added_later.py",
        ):
            with self.subTest(name=name):
                self.assertFalse(release_manifest.is_release_path_allowed(name))

    def test_unlisted_files_added_to_runtime_directories_stay_out(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            allowed = {"kira/__init__.py", "kira/main.py", "install.bat"}
            for name in allowed | {"kira/new_runtime_module.py", "scripts/new_tool.py", "tests/test_new.py"}:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("VALUE = 1\n", encoding="utf-8")
            with mock.patch.object(release_manifest, "ALLOWED_FILES", frozenset(allowed)):
                actual = {path.as_posix() for _, path in build_release.source_files(root)}
            self.assertEqual(actual, allowed)

    def test_symlinked_runtime_file_is_never_packaged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "kira"
            package.mkdir()
            outside = root / "outside.py"
            outside.write_text("VALUE = 1\n", encoding="utf-8")
            try:
                (package / "linked.py").symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symbolic links are unavailable in this environment")
            with mock.patch.object(release_manifest, "ALLOWED_FILES", frozenset({"kira/linked.py"})):
                self.assertNotIn("kira/linked.py", {p.as_posix() for _, p in build_release.source_files(root)})

    def test_secret_scanner_detects_provider_tokens_and_private_keys(self):
        cases = (
            (b'api = "AIza0123456789abcdefghijABCDEFGHIJKL"', "google_api_key"),
            (b'api = "gsk_012345678901234567890123"', "groq_api_key"),
            (b'api = "sk-or-v1-012345678901234567890123"', "openrouter_api_key"),
            (b'api = "sk-01234567890123456789012345678901"', "openai_api_key"),
            (b'token = "github_pat_012345678901234567890123456789"', "github_pat"),
            (b'token = "ghp_012345678901234567890123456789"', "github_token"),
            (b'key = "AKIA0123456789ABCDEF"', "aws_access_key_id"),
            (b'token = "xoxb-1234567890-abcdefghijkl"', "slack_token"),
            (b"Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789", "bearer_token"),
            (b"-----BEGIN PRIVATE KEY-----", "private_key"),
        )
        for content, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(expected, build_release.scan_release_content("kira/main.py", content))

    def test_secret_scan_never_echoes_the_secret_value(self):
        secret = b"gsk_012345678901234567890123"
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "main.py"
            source.write_bytes(b"TOKEN = b'" + secret + b"'\n")
            with self.assertRaises(build_release.ReleaseSecurityError) as ctx:
                build_release._scan_release_files([(source, Path("kira/main.py"))])
            self.assertIn("groq_api_key", str(ctx.exception))
            self.assertNotIn(secret.decode(), str(ctx.exception))

    def test_package_builder_emits_exact_allowlist_manifest_and_install_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "checkout"
            dist = root / "dist"
            files = make_runtime_tree(root)
            (root / "tests").mkdir()
            (root / "tests" / "test_private.py").write_text("pass\n", encoding="utf-8")
            (root / "PROJECT_CONTEXT.md").write_text("internal\n", encoding="utf-8")

            with mock.patch.object(release_manifest, "ALLOWED_FILES", frozenset(files)), \
                    mock.patch.object(build_release, "ROOT", root), \
                    mock.patch.object(build_release, "DIST", dist), \
                    mock.patch.object(build_release, "release_stamp", return_value="261125_1000"), \
                    mock.patch.object(build_release.build_metadata, "ensure_release_metadata", return_value={
                        "version": "1.2.6", "build_date": "2026-11-25",
                        "build_time": "10:00", "developer": "ChatGPT"
                    }):
                archive = build_release.main()

            expected = set(files)
            build_release.validate_archive(archive, expected)
            with zipfile.ZipFile(archive) as package:
                names = set(package.namelist())
                self.assertEqual(names, expected | {release_manifest.PACKAGE_MANIFEST_NAME})
                manifest = json.loads(package.read(release_manifest.PACKAGE_MANIFEST_NAME))
                self.assertEqual(set(manifest["files"]), expected)
                self.assertEqual(manifest["runtime_dependencies"], list(release_manifest.RUNTIME_DEPENDENCY_FILES))
                self.assertEqual(manifest["runtime_setup"], sorted(release_manifest.RUNTIME_SCRIPT_FILES))
                self.assertNotIn("tests/test_private.py", names)
                self.assertNotIn("PROJECT_CONTEXT.md", names)
                self.assertEqual(
                    package.read("install.bat").count(b"\n"),
                    package.read("install.bat").count(b"\r\n"),
                )

            # Changing the dependency inventory without changing the payload invalidates the ZIP.
            tampered = root / "tampered.zip"
            with zipfile.ZipFile(archive, "r") as source, zipfile.ZipFile(tampered, "w") as target:
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename == release_manifest.PACKAGE_MANIFEST_NAME:
                        broken = json.loads(data)
                        broken["runtime_dependencies"] = ["requirements-dev.txt"]
                        data = json.dumps(broken).encode("utf-8")
                    target.writestr(info, data)
            with self.assertRaisesRegex(RuntimeError, "incorrect runtime dependency"):
                build_release.validate_archive(tampered, expected)

    def test_missing_allowlisted_file_stops_the_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = [(root / "requirements.txt", Path("requirements.txt"))]
            with mock.patch.object(release_manifest, "ALLOWED_FILES", frozenset({"requirements.txt", "kira/main.py"})), \
                    mock.patch.object(release_manifest, "REQUIRED_RELEASE_FILES", frozenset()):
                with self.assertRaisesRegex(RuntimeError, "allowlist references files missing"):
                    build_release._validate_release_inputs(root, files)

    def test_required_installer_or_dependency_file_stops_the_build(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "missing required runtime files"):
                build_release._validate_release_inputs(Path(temp), [])

    def test_empty_runtime_dependency_declaration_stops_the_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = []
            for required in release_manifest.REQUIRED_RELEASE_FILES:
                path = root / required
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("VALUE = 1\n", encoding="utf-8")
                files.append((path, Path(required)))
            for dependency in release_manifest.RUNTIME_DEPENDENCY_FILES:
                path = root / dependency
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# no requirements\n", encoding="utf-8")
                files.append((path, Path(dependency)))
            with mock.patch.object(release_manifest, "ALLOWED_FILES", frozenset(p.as_posix() for _, p in files)):
                with self.assertRaisesRegex(RuntimeError, "dependency declaration is empty"):
                    build_release._validate_release_inputs(root, files)

    def test_secret_failure_preserves_previous_release_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = make_runtime_tree(root)
            (root / "kira" / "main.py").write_text("TOKEN = 'gsk_012345678901234567890123'\n", encoding="utf-8")
            dist = root / "dist"
            dist.mkdir()
            archive = dist / "ProjectKira_261125_1000.zip"
            archive.write_bytes(b"previous release remains intact")
            with mock.patch.object(release_manifest, "ALLOWED_FILES", frozenset(files)), \
                    mock.patch.object(build_release, "ROOT", root), \
                    mock.patch.object(build_release, "DIST", dist), \
                    mock.patch.object(build_release, "release_stamp", return_value="261125_1000"), \
                    mock.patch.object(build_release.build_metadata, "ensure_release_metadata", return_value={
                        "version": "1.2.6", "build_date": "2026-11-25",
                        "build_time": "10:00", "developer": "ChatGPT"
                    }):
                with self.assertRaises(build_release.ReleaseSecurityError):
                    build_release.main()
            self.assertEqual(archive.read_bytes(), b"previous release remains intact")


if __name__ == "__main__":
    unittest.main()
