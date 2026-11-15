"""Ai1 Code inside Kira's chat: Qt-free logic (parsing, file resolution, safety gates, patch apply, rendering)."""
import tempfile
import unittest
from pathlib import Path

from kira import chat_code as cc
from kira.code_agent import PATCH_START, PATCH_END


class _Router:
    def __init__(self, text):
        self.text, self.calls = text, []

    def chat_stream(self, messages, system, temperature=0.7, on_chunk=None, **kw):
        self.calls.append((messages, system))
        if on_chunk:
            on_chunk(self.text)
        return {"text": self.text}


class ParseTests(unittest.TestCase):
    def test_edit_request_with_mention_is_a_patch(self):
        r = cc.parse_request("@kira/main.py تابع save را درست کن")
        self.assertEqual(r.kind, "patch")
        self.assertEqual(r.mentions, ["kira/main.py"])

    def test_question_stays_an_ask_even_with_edit_words(self):
        self.assertEqual(cc.parse_request("چرا این fix کار نمی‌کند؟ app.py").kind, "ask")
        self.assertEqual(cc.parse_request("سلام").kind, "ask")

    def test_slash_commands(self):
        self.assertEqual(cc.parse_request("/files").kind, "files")
        self.assertEqual(cc.parse_request("/apply").kind, "apply")
        run = cc.parse_request("/run pytest -q")
        self.assertEqual((run.kind, run.command), ("run", "pytest -q"))
        self.assertEqual(cc.parse_request("/patch x.py add logging").kind, "patch")
        self.assertEqual(cc.parse_request("/ask fix x.py").kind, "ask")


class IntentTests(unittest.TestCase):
    VOCAB = frozenset({"vrm", "avatar", "routes", "ollama"})

    def intent(self, text):
        return cc.classify_intent(text, self.VOCAB)

    def test_missions_are_recognised_without_file_names_or_commands(self):
        for text in ("مدل دوبعدی کیرا رو حذف کن و فقط VRM بماند", "این قابلیت رو اضافه کن", "فایل kira/main.py رو چک کن",
                     "باگ لود آواتار را پیدا کن و درست کن", "fix the crash in my project", "پروژه رو بررسی کن و تست‌ها رو بزن"):
            self.assertEqual(self.intent(text), ("task", True), text)

    def test_project_questions_are_read_only_questions(self):
        for text in ("چرا آواتار دوبعدی قبل از VRM لود میشه؟", "کدوم فایل مسئول routes هست؟",
                     "Traceback (most recent call last):\n  File \"a.py\", line 3\nValueError: x"):
            self.assertEqual(self.intent(text), ("question", True), text)

    def test_normal_talk_and_general_programming_stay_in_the_normal_chat(self):
        for text in ("سلام کیرا حالت چطوره؟", "مرسی", "تفاوت list و tuple چیه؟", "امروز خیلی خسته‌ام",
                     "ببین این کد چرا کار نمی‌کنه؟\n```py\nx = 1\n```"):
            self.assertEqual(self.intent(text), ("chat", True), text)

    def test_ambiguous_wording_is_left_to_the_model(self):
        self.assertEqual(self.intent("این تابع رو درست کن")[1], False)

    def test_colloquial_ui_complaints_are_project_tasks_without_code_terms(self):
        for text in (
            "رنگ آیکون‌های نئونی به هم ریخته، درستش کن",
            "ایموجی ساده رو پاک کن",
            "کادر چت داره می‌لرزه",
            "وقتی ضربدر ضمیمه رو می‌زنم کار نمی‌کنه",
            "فایل زیپ بزرگ‌تر از ده مگ رو نمی‌ذاره ضمیمه کنم",
            "دکمه ارسال غیرفعاله",
            "می‌خوام اندازه دکمه‌ها کوچیک‌تر بشه",
            "وقتی پوشه رو باز می‌کنم برنامه بسته می‌شه",
            "the chat window is too big, make it smaller",
        ):
            self.assertEqual(self.intent(text), ("task", True), text)

    def test_general_programming_questions_are_not_project_tasks(self):
        for text in ("پایتون چیه؟", "تفاوت جاوا و پایتون چیه؟", "چطور حلقه for کار می‌کنه؟"):
            self.assertEqual(self.intent(text), ("chat", True), text)

    def test_classifier_answers_are_parsed_safely(self):
        self.assertEqual(cc.parse_classification("TASK"), "task")
        self.assertEqual(cc.parse_classification("  question."), "question")
        self.assertEqual(cc.parse_classification("CHAT"), "chat")
        self.assertEqual(cc.parse_classification("I think maybe"), "chat")                  # unsure -> never starts work
        self.assertEqual(cc.parse_classification(None), "chat")

    def test_changing_the_project_folder_in_words(self):
        self.assertEqual(cc.parse_request("پوشه پروژه رو عوض کن").kind, "project")
        self.assertNotEqual(cc.parse_request("این پروژه رو عوض کن").kind, "project")

    def test_zwnj_and_natural_folder_requests_are_recognised(self):
        for text in ("پوشه‌ی پروژه را عوض کن", "پوشه‌ی پروژه رو عوض کن", "پوشه‌ی پروژه را انتخاب کن",
                     "مسیر پروژه را تغییر بده", "change the project folder"):
            self.assertTrue(cc.wants_project_change(text), text)
            self.assertEqual(cc.parse_request(text).kind, "project", text)
        # replacing the project's content is a mission, not a project-folder switch
        for text in ("این پروژه رو عوض کن", "پروژه رو بررسی کن و تست‌ها رو بزن"):
            self.assertFalse(cc.wants_project_change(text), text)

    def test_project_location_questions_are_distinguished_from_folder_changes(self):
        for text in ("پوشه پروژه کجاست؟", "مسیر پوشه پروژه چیه؟", "آدرس پروژه کجاست؟",
                     "پوشه کاری کیرا کجا ذخیره شده؟", "where is the project folder?"):
            self.assertTrue(cc.wants_project_location(text), text)
        for text in ("پوشه پروژه رو عوض کن", "پوشه پروژه را انتخاب کن", "سلام"):
            self.assertFalse(cc.wants_project_location(text), text)

    def test_vocabulary_comes_from_the_projects_own_names(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "vrm_loader.py").write_text("", encoding="utf-8")
            (Path(d) / "main.py").write_text("", encoding="utf-8")
            vocab = cc.project_vocabulary(d)
        self.assertIn("vrm", vocab)
        self.assertIn("loader", vocab)
        self.assertNotIn("main", vocab)


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "b.py").write_text("y = 2\n", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=abc", encoding="utf-8")
        (self.root / "other").mkdir()
        (self.root / "pkg" / "twin.py").write_text("", encoding="utf-8")
        (self.root / "other" / "twin.py").write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_relative_path_and_unique_basename(self):
        files, problems = cc.resolve_files(self.root, ["pkg/a.py", "b.py"])
        self.assertEqual([f.name for f in files], ["a.py", "b.py"])
        self.assertEqual(problems, [])
        files, _ = cc.resolve_files(self.root, ["a.py"])
        self.assertEqual(files[0].name, "a.py")                      # found by name alone

    def test_secret_and_escaping_paths_are_refused(self):
        files, problems = cc.resolve_files(self.root, [".env"], explicit=[".env"])
        self.assertEqual(files, [])
        self.assertTrue(problems)
        files, problems = cc.resolve_files(self.root, ["../outside.py"], explicit=["../outside.py"])
        self.assertEqual(files, [])

    def test_ambiguous_name_and_missing_explicit_file(self):
        files, problems = cc.resolve_files(self.root, ["twin.py"])      # two files with this name, none at the project root
        self.assertEqual(files, [])
        self.assertTrue(any("twin.py" in p for p in problems))
        _, problems = cc.resolve_files(self.root, ["nope.py"], explicit=["nope.py"])
        self.assertTrue(problems)
        _, problems = cc.resolve_files(self.root, ["v1.2"])           # a bare word that only looks like a file: silent
        self.assertEqual(problems, [])

    def test_patch_blocked_for_huge_or_secret_files(self):
        big = self.root / "big.py"
        big.write_text("a = 1\n" * 10000, encoding="utf-8")
        self.assertIn("بزرگ", cc.patch_blocker(self.root, big))
        secret = self.root / "cfg.py"
        secret.write_text('api_key = "sk-real"\n', encoding="utf-8")
        self.assertTrue(cc.patch_blocker(self.root, secret))
        self.assertEqual(cc.patch_blocker(self.root, self.root / "b.py"), "")

    def test_multi_context_redacts_and_lists_files(self):
        (self.root / "cfg.py").write_text('password = "hunter2"\nok = 1\n', encoding="utf-8")
        ctx = cc.build_multi_context(self.root, [self.root / "b.py", self.root / "cfg.py"])
        self.assertIn("FILE: b.py", ctx)
        self.assertIn("FILE: cfg.py", ctx)
        self.assertNotIn("hunter2", ctx)


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.file = self.root / "app.py"
        self.file.write_text("print('old')\n", encoding="utf-8")
        self.base = self.file.read_bytes()

    def tearDown(self):
        self.tmp.cleanup()

    def test_apply_writes_backup_and_new_content(self):
        patch = cc.PatchStore().add("app.py", "print('new')\n", self.base)
        backup = cc.apply_patch(self.root, patch)
        self.assertEqual(self.file.read_text(encoding="utf-8"), "print('new')\n")
        self.assertEqual(backup.read_bytes(), self.base)
        self.assertFalse((self.root / "app.py.ai1code.tmp").exists())

    def test_backup_is_kept_from_the_first_apply(self):
        store = cc.PatchStore()
        cc.apply_patch(self.root, store.add("app.py", "print(1)\n", self.base))
        cc.apply_patch(self.root, store.add("app.py", "print(2)\n", self.file.read_bytes()))
        self.assertEqual((self.root / "app.py.ai1code.bak").read_bytes(), self.base)

    def test_stale_proposal_is_rejected(self):
        patch = cc.PatchStore().add("app.py", "print('new')\n", self.base)
        self.file.write_text("print('edited elsewhere')\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            cc.apply_patch(self.root, patch)
        self.assertEqual(self.file.read_text(encoding="utf-8"), "print('edited elsewhere')\n")

    def test_store_is_bounded_and_last_works(self):
        store = cc.PatchStore()
        ids = [store.add("a.py", "x", b"x").pid for _ in range(cc.MAX_PENDING_PATCHES + 3)]
        self.assertEqual(len(store), cc.MAX_PENDING_PATCHES)
        self.assertIsNone(store.get(ids[0]))
        self.assertEqual(store.last().pid, ids[-1])

    def test_crlf_files_keep_their_line_endings(self):
        self.assertEqual(cc.match_newlines("a\r\nb\r\n", "a\nc\n"), "a\r\nc\r\n")
        self.assertEqual(cc.match_newlines("a\nb\n", "a\nc\n"), "a\nc\n")

    def test_final_line_break_follows_the_original_file(self):
        self.assertEqual(cc.match_newlines("a\nb\n", "a\nc"), "a\nc\n")              # the marker parser drops the last \n
        self.assertEqual(cc.match_newlines("a\r\nb\r\n", "a\nc"), "a\r\nc\r\n")
        self.assertEqual(cc.match_newlines("a\nb", "a\nc"), "a\nc")                  # the original had none: keep none

    def test_diff_and_card_html(self):
        diff = cc.make_diff("app.py", "a\nb\n", "a\nc\n")
        card = cc.patch_card_html(cc.PendingPatch("7", "app.py", "a\nc\n", b""), diff)
        self.assertIn("kira-code://apply/7", card)
        self.assertIn("kira-code://reject/7", card)
        self.assertIn("+1", card)
        self.assertEqual(cc.make_diff("x", "same\n", "same\n"), "")


class EngineTests(unittest.TestCase):
    def test_ask_uses_kira_prompt_and_history_in_alternating_roles(self):
        router = _Router("جواب")
        history = [{"role": "assistant", "content": "x"}, {"role": "user", "content": "q1"},
                   {"role": "assistant", "content": "a1"}, {"role": "assistant", "content": "a2"}]
        out = cc.KiraCodeEngine(router).ask("q2", "CTX", history=history)
        self.assertEqual(out, "جواب")
        messages, system = router.calls[0]
        self.assertIn("You are Kira", system)
        self.assertIn("NO tools", system)
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])
        self.assertIn("q2", messages[-1]["content"])

    def test_patch_proposal_parsed_and_redacted_context_blocked(self):
        router = _Router(f"{PATCH_START}\nprint('x')\n{PATCH_END}")
        self.assertEqual(cc.KiraCodeEngine(router).propose_replacement("do", "CTX"), "print('x')")
        with self.assertRaises(ValueError):
            cc.KiraCodeEngine(_Router("")).propose_replacement("do", "key [REDACTED]")


class RenderTests(unittest.TestCase):
    def test_code_fences_become_ltr_code_blocks_and_html_is_escaped(self):
        html_out = cc.answer_html("سلام <b>\n```python\nif a < b:\n    pass\n```\nتمام")
        self.assertIn("&lt;b&gt;", html_out)
        self.assertIn("if a &lt; b:", html_out)
        self.assertIn('dir="ltr"', html_out)
        self.assertNotIn("```", html_out)

    def test_inline_code_is_styled_not_shown_with_backticks(self):
        out = cc.answer_html("از `with open()` استفاده کن")
        self.assertNotIn("`", out)
        self.assertIn("with open()", out)

    def test_unclosed_fence_still_renders(self):
        self.assertIn("print(1)", cc.answer_html("```py\nprint(1)"))


if __name__ == "__main__":
    unittest.main()
