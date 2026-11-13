"""Version metadata rule (PROJECT_CONTEXT.md): About fields, automatic developer attribution, release gate."""
import ast
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests import helpers  # noqa: F401  (redirects the data folder)
from tests.helpers import ROOT

from kira import about, build_rules, config
from scripts import build_metadata as bm
from scripts import build_release


def constants(path):
    """Read simple string constants without importing (and running) the module."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return values


class DeveloperDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "kira").mkdir()
        self.addCleanup(self.tmp.cleanup)

    def detect(self, env):
        # never reach a real repository from a temporary folder: the git fallback is tested separately
        with mock.patch.object(bm, "git_identities", return_value=[]):
            return bm.detect_developer(self.root, env)

    def test_only_the_four_approved_tools_are_accepted(self):
        self.assertEqual(build_rules.DEVELOPERS, ("Codex", "OpenCode", "Claude Code", "ChatGPT"))
        for name in ("Codex", "OpenCode", "Claude Code", "ChatGPT"):
            self.assertIsNone(build_rules.developer_error(name))
        self.assertIsNotNone(build_rules.developer_error("Somebody Else"))

    def test_tool_names_are_normalised(self):
        for raw, expected in (("opencode", "OpenCode"), ("Open Code", "OpenCode"), ("OPEN-CODE", "OpenCode"),
                              ("claude", "Claude Code"), ("claude-code", "Claude Code"), ("claudecode", "Claude Code"),
                              ("codex", "Codex"), ("OpenAI Codex", "Codex"), ("chatgpt", "ChatGPT")):
            self.assertEqual(build_rules.normalize_developer(raw), expected, raw)
        self.assertIsNone(build_rules.normalize_developer("alizesta"))

    def test_explicit_override_wins_and_an_unknown_value_stops_the_build(self):
        self.assertEqual(self.detect({"KIRA_DEVELOPER": "Codex", "OPENCODE": "1"}), "Codex")
        with self.assertRaises(bm.MetadataError):
            self.detect({"KIRA_DEVELOPER": "NotATool"})

    def test_build_host_markers_are_detected(self):
        self.assertEqual(self.detect({"OPENCODE": "1"}), "OpenCode")
        self.assertEqual(self.detect({"CLAUDECODE": "1"}), "Claude Code")
        self.assertEqual(self.detect({"CODEX_SANDBOX": "seatbelt"}), "Codex")
        self.assertEqual(self.detect({"AI_AGENT": "chatgpt"}), "ChatGPT")

    def test_recorded_stamp_is_used_when_the_build_host_is_unknown(self):
        (self.root / "kira" / "build_info.py").write_text(
            'BUILD_DATE = "2026-11-13"\nBUILD_TIME = "08:05"\nDEVELOPER = "Claude Code"\n', encoding="utf-8")
        self.assertEqual(self.detect({}), "Claude Code")

    def test_git_author_is_the_last_automatic_fallback(self):
        with mock.patch.object(bm, "git_identities", return_value=["alizesta", "OpenCode"]):
            self.assertEqual(bm.detect_developer(self.root, {}), "OpenCode")

    def test_missing_metadata_stops_the_build(self):
        with self.assertRaises(bm.MetadataError) as ctx:
            self.detect({})
        self.assertIn("KIRA_DEVELOPER", str(ctx.exception))


class BuildStampTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "kira").mkdir()
        self.addCleanup(self.tmp.cleanup)

    def write_metadata(self, version="1 stable", build_date="2026-11-13", build_time="22:06",
                       developer="OpenCode", changelog=None):
        (self.root / "kira" / "config.py").write_text(f'VERSION = "{version}"\n', encoding="utf-8")
        (self.root / "kira" / "build_info.py").write_text(
            f'BUILD_DATE = "{build_date}"\nBUILD_TIME = "{build_time}"\nDEVELOPER = "{developer}"\n', encoding="utf-8")
        if changelog is None:
            changelog = f"# Changelog\n\n## Version\n\n- Current version: `{version}`\n"
        (self.root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")

    def test_stamp_writes_the_documented_formats(self):
        (self.root / "kira" / "config.py").write_text('VERSION = "1 stable"\n', encoding="utf-8")
        now = datetime(2026, 11, 13, 10, 54, tzinfo=timezone.utc)          # 14:24 in Asia/Tehran
        data = bm.stamp(self.root, now=now, developer="Claude Code")
        values = constants(self.root / "kira" / "build_info.py")
        self.assertEqual(values, {"BUILD_DATE": "2026-11-13", "BUILD_TIME": "14:24", "DEVELOPER": "Claude Code"})
        self.assertEqual(data, {"version": "1 stable", "build_date": "2026-11-13",
                                "build_time": "14:24", "developer": "Claude Code"})
        self.assertRegex(values["BUILD_DATE"], build_rules.DATE_RE)
        self.assertRegex(values["BUILD_TIME"], build_rules.TIME_RE)

    def test_stamp_uses_the_automatically_detected_developer(self):
        (self.root / "kira" / "config.py").write_text('VERSION = "1 stable"\n', encoding="utf-8")
        with mock.patch.dict(os.environ, {"KIRA_DEVELOPER": "Codex"}, clear=False):
            data = bm.stamp(self.root)
        self.assertEqual(data["developer"], "Codex")
        self.assertEqual(constants(self.root / "kira" / "build_info.py")["DEVELOPER"], "Codex")

    def test_the_repository_metadata_is_complete(self):
        data = bm.validate()
        self.assertEqual(data["version"], config.VERSION)
        self.assertRegex(data["build_date"], build_rules.DATE_RE)
        self.assertRegex(data["build_time"], build_rules.TIME_RE)
        self.assertIn(data["developer"], build_rules.DEVELOPERS)

    def test_each_incomplete_or_malformed_field_stops_the_release(self):
        cases = (
            ({"build_date": "13/11/2026"}, "BUILD_DATE"),
            ({"build_date": "2026-02-30"}, "BUILD_DATE"),
            ({"build_time": "9:5"}, "BUILD_TIME"),
            ({"build_time": "24:00"}, "BUILD_TIME"),
            ({"developer": "Somebody"}, "DEVELOPER"),
            ({"version": ""}, "VERSION"),
            ({"changelog": "# Changelog\n\n- something else entirely\n"}, "CHANGELOG"),
        )
        for overrides, needle in cases:
            with self.subTest(overrides=overrides):
                self.write_metadata(**overrides)
                with self.assertRaises(bm.MetadataError) as ctx:
                    bm.validate(self.root)
                self.assertIn(needle, str(ctx.exception))

    def test_missing_generated_stamp_stops_the_release(self):
        self.write_metadata()
        (self.root / "kira" / "build_info.py").unlink()
        with self.assertRaises(bm.MetadataError) as ctx:
            bm.validate(self.root)
        self.assertIn("build_info.py", str(ctx.exception))

    def test_release_metadata_refreshes_the_stamp_then_validates(self):
        self.write_metadata(build_date="2020-01-01", build_time="00:00", developer="ChatGPT")
        with mock.patch.object(bm, "detect_developer", return_value="OpenCode"):
            data = bm.ensure_release_metadata(self.root)
        self.assertEqual(data["developer"], "OpenCode")
        self.assertNotEqual(data["build_date"], "2020-01-01")


class ReleaseGateTests(unittest.TestCase):
    def test_build_release_refuses_to_package_incomplete_metadata(self):
        error = build_release.build_metadata.MetadataError("DEVELOPER 'Somebody' must be one of: Codex, OpenCode")
        with mock.patch.object(build_release.build_metadata, "ensure_release_metadata", side_effect=error):
            with self.assertRaises(SystemExit) as ctx:
                build_release.main()
        self.assertIn("Release stopped", str(ctx.exception))
        self.assertIn("DEVELOPER", str(ctx.exception))

    def test_ci_validates_metadata_and_runs_this_rule_suite(self):
        workflow = (ROOT / ".github" / "workflows" / "kira-release.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/build_metadata.py --check", workflow)
        self.assertIn("tests.test_build_metadata", workflow)


class AboutTests(unittest.TestCase):
    def test_about_rows_are_the_four_mandatory_fields_in_order(self):
        rows = about.about_rows("1 stable")
        self.assertEqual([key for key, _ in rows], list(about.ROW_KEYS))
        self.assertEqual([key for key, _ in rows],
                         ["about_version", "about_build_date", "about_build_time", "about_developer"])
        values = dict(rows)
        self.assertEqual(values["about_version"], "1 stable")
        self.assertRegex(values["about_build_date"], build_rules.DATE_RE)
        self.assertRegex(values["about_build_time"], build_rules.TIME_RE)
        self.assertIn(values["about_developer"], build_rules.DEVELOPERS)

    def test_a_missing_generated_stamp_shows_unknown_instead_of_crashing(self):
        import kira
        # hide both the module entry and the package attribute another test may already have imported
        with mock.patch.dict(sys.modules, {"kira.build_info": None}), \
                mock.patch.object(kira, "build_info", None, create=True):
            self.assertEqual(about.build_stamp()["developer"], about.FALLBACK)
            self.assertEqual(dict(about.about_rows("1 stable"))["about_build_date"], about.FALLBACK)

    def test_the_ui_labelled_the_about_rows_in_both_languages(self):
        from kira.strings import STR
        for lang in ("fa", "en"):
            for key in ("g_about", *about.ROW_KEYS):
                self.assertIn(key, STR[lang], f"{lang}:{key}")


if __name__ == "__main__":
    unittest.main()
