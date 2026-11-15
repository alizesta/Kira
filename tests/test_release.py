import hashlib
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from tests import helpers
from tests.helpers import ROOT, CANARY
import install_deps
from kira import memory, config

KEY_PATTERNS = [r"gsk_[A-Za-z0-9]{20,}", r"sk-or-v1-[A-Za-z0-9]{20,}", r"AIza[0-9A-Za-z_\-]{30,}",
                r"sk-[A-Za-z0-9]{32,}", r"Bearer\s+[A-Za-z0-9_\-]{30,}", re.escape(CANARY)]
SKIP_DIRS = {".venv", "__pycache__", "data", ".git", ".uvboot"}


def project_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS):
            yield p


class ReleaseTests(unittest.TestCase):
    # 4) no secrets in the shipped tree (the release script runs the same scan on the final ZIP)
    def test_04_no_api_keys_in_sources(self):
        hits = []
        for p in project_files():
            if p.suffix.lower() in (".png", ".pyc") or p.name.startswith("test_release"):
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            in_tests = p.relative_to(ROOT).parts[0] == "tests"
            for pat in KEY_PATTERNS:
                if in_tests and pat == re.escape(CANARY):
                    continue                      # the canary constant legitimately lives in the tests themselves
                if re.search(pat, text):
                    hits.append((str(p.relative_to(ROOT)), pat))
        self.assertEqual(hits, [])

    def test_04b_no_user_data_shipped(self):
        for forbidden in ("data/settings.json", "data/kira_memory.sqlite3", ".venv"):
            self.assertFalse((ROOT / forbidden).exists() and not (ROOT / "data").samefile(config.DATA_DIR), forbidden)

    def test_version(self):
        self.assertEqual(config.VERSION, "1.1")

    # 15) real SQLite history is provider-neutral and ordered
    def test_15_memory_context_is_ordered_and_bounded(self):
        memory.init_db()
        memory.clear_memory()
        for i in range(30):
            memory.add_message("user" if i % 2 == 0 else "assistant", f"m{i}")
        ctx = memory.conversation_context(limit=12)
        self.assertEqual([m["content"] for m in ctx], [f"m{i}" for i in range(18, 30)])
        memory.clear_memory()
        memory.add_message("user", "x" * 9000)
        memory.add_message("assistant", "y" * 9000)
        self.assertLessEqual(sum(len(m["content"]) for m in memory.conversation_context(12, max_chars=12000)), 12000)

    # dependency installer: names the failing package, never reports success on failure
    def test_install_deps_reports_failed_package_and_dns_hint(self):
        req = config.DATA_DIR / "req_test.txt"
        req.write_text("# comment\nPySide6>=6.7,<7\nrequests>=2.31,<3\nnumpy>=1.26\n", encoding="utf-8")
        log = []

        def runner(args):
            joined = " ".join(args)
            if args[0] == "-r":
                return 1, "ERROR: bulk failed"
            if "numpy" in joined:
                return 1, "NameResolutionError: Failed to resolve 'files.pythonhosted.org'"
            return 0, "ok"
        code = install_deps.install(str(req), runner=runner, out=log.append)
        text = "\n".join(log)
        self.assertEqual(code, 1)
        self.assertIn("FAILED PACKAGES: numpy>=1.26", text)
        self.assertIn("DNS", text)
        self.assertNotIn("PySide6", text.split("FAILED PACKAGES:")[1].splitlines()[0])

    def test_install_deps_success_and_empty(self):
        req = config.DATA_DIR / "req_ok.txt"
        req.write_text("requests>=2.31,<3\n", encoding="utf-8")
        self.assertEqual(install_deps.install(str(req), runner=lambda a: (0, "ok"), out=lambda s: None), 0)
        empty = config.DATA_DIR / "req_empty.txt"
        empty.write_text("# nothing\n", encoding="utf-8")
        self.assertEqual(install_deps.install(str(empty), runner=lambda a: (0, "ok"), out=lambda s: None), 1)

    def test_requirements_contain_no_unneeded_packages(self):
        names = {re.split(r"[<>=]", l)[0].strip().lower() for l in (ROOT / "requirements.txt").read_text().splitlines() if l.strip()}
        self.assertEqual(names, {"pyside6", "requests", "numpy", "psutil", "ruff"})
        self.assertIn("optional", (ROOT / "requirements.txt").read_text(encoding="utf-8").lower())

    def test_bat_files_keep_crlf_and_call_installer(self):
        for name in ("install.bat", "download_model.bat", "start_kira.bat", "run_tests.bat"):
            raw = (ROOT / name).read_bytes()
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)
            self.assertTrue(all(b < 128 for b in raw), name + " must stay ASCII for CMD")
        installer = (ROOT / "install.bat").read_bytes()
        self.assertIn(b"install_deps.py", installer)
        self.assertIn(b"Install Python 3.12", installer)
        self.assertNotIn(b"Continuing with your own Python", installer)
        self.assertIn(b"qwen3.5:4b", (ROOT / "download_model.bat").read_bytes())

    def test_release_batch_normalizer_forces_crlf_even_from_lf_sources(self):
        from scripts.build_release import release_file_bytes
        source = ROOT / "run_tests.bat"
        normalized = release_file_bytes(source, Path("run_tests.bat"))
        self.assertEqual(normalized.count(b"\n"), normalized.count(b"\r\n"))
        mixed = ROOT / "data" / "mixed_test.bat"
        mixed.parent.mkdir(parents=True, exist_ok=True)
        mixed.write_bytes(b"@echo off\nlabel\r\ngoto label\n")
        try:
            fixed = release_file_bytes(mixed, Path("mixed_test.bat"))
            self.assertEqual(fixed.count(b"\n"), fixed.count(b"\r\n"))
            self.assertIn(b"goto label\r\n", fixed)
        finally:
            mixed.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
