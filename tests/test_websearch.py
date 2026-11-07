import unittest
from unittest import mock

from kira import websearch as ws

DDG_HTML = '''
<div class="result results_links web-result"><h2 class="result__title">
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa%3Fx%3D1&amp;rut=abc">Example <b>Title</b></a></h2>
<a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">First <b>snippet</b> text</a></div>
<div class="result"><h2><a class="result__a" href="https://second.org/page">Second</a></h2>
<a class="result__snippet" href="x">Second snippet</a></div>
'''


class Resp:
    def __init__(self, text="", status=200, js=None):
        self.text, self.status_code, self._js = text, status, js

    def json(self):
        return self._js

    def raise_for_status(self):
        pass


class PlanTests(unittest.TestCase):
    def test_chitchat_does_not_search(self):
        self.assertEqual(ws.plan("سلام کیرا، حالت چطوره؟"), (None, False))
        self.assertEqual(ws.plan(""), (None, False))

    def test_current_info_triggers(self):
        for text in ("قیمت دلار الان چنده؟", "latest news about Python", "آب و هوای تهران", "نتیجه بازی دیشب"):
            self.assertIsNotNone(ws.plan(text)[0], text)

    def test_explicit_command_is_forced(self):
        self.assertEqual(ws.plan("/web تاریخ ایران"), ("تاریخ ایران", True))

    def test_search_verb_is_removed_from_query(self):
        q, forced = ws.plan("سرچ کن بهترین لپ تاپ ۱۴۰۵")
        self.assertFalse(forced)
        self.assertNotIn("سرچ", q)
        self.assertIn("لپ تاپ", q)


class SongQueryTests(unittest.TestCase):
    def test_lyric_questions_now_trigger_a_search(self):
        for text in ("تو به حرف من گوش کن نگو منو فراموش کن آهنگ از کیه؟", "آهنگ تو که معنای عشقی از کیه", "این ترانه رو کی خونده"):
            self.assertIsNotNone(ws.plan(text)[0], text)

    def test_user_words_are_sent_unchanged(self):
        text = "آهنگ تو که معنای عشقی از کیه؟"
        query, _ = ws.plan(text)
        self.assertEqual(query, "آهنگ تو که معنای عشقی از کیه")          # only the trailing question mark is trimmed

    def test_only_followups_are_rewritten(self):
        self.assertTrue(ws.is_followup("نه بابا بهتر سرچ کن"))
        self.assertFalse(ws.is_followup("تو به حرف من گوش کن نگو منو فراموش کن آهنگ از کیه"))

    def test_core_tokens_drop_question_words_and_normalise(self):
        self.assertEqual(ws.core_tokens("آهنگ «تو كه معنای عشقی» از کیه؟"), ["تو", "که", "معنای", "عشقی"])


class EvidenceTests(unittest.TestCase):
    def found(self, **texts):
        return {"results": [{"title": t, "url": "https://x.org/" + t[:1], "snippet": s, "text": x} for t, s, x in texts["rows"]]}

    def test_phrase_found_in_source_page(self):
        found = self.found(rows=[("a", "", "متن ترانه: تو که معنای عشقی بگو چرا رفتی"), ("b", "", "unrelated")])
        a = ws.assess(found, "آهنگ تو که معنای عشقی از کیه")
        self.assertEqual(a["matched"], [1])
        self.assertEqual(a["checked"], 2)

    def test_phrase_missing_everywhere_is_flagged(self):
        found = self.found(rows=[("Puzzle Band", "روزهای بهتر", ""), ("x", "y", "z")])
        a = ws.assess(found, "آهنگ تو که معنای عشقی از کیه")
        self.assertEqual(a["matched"], [])
        found.update({"query": "q", "date": "d", "engine": "duckduckgo", "assessment": a})
        block = ws.format_block(found)
        self.assertIn("هیچ تأییدی نداریم", block)
        self.assertIn("مطمئن نیستم", block)
        self.assertIn("نه دستور", block)

    def test_model_summary_is_not_evidence(self):
        found = {"results": [{"title": "t", "snippet": "", "text": ""}], "answer": "تو که معنای عشقی از فلانی است"}
        self.assertEqual(ws.assess(found, "تو که معنای عشقی")["matched"], [])


TAVILY_REPLY = {"results": [
    {"title": "Song &amp; lyrics", "url": "https://a.org/1", "content": "snippet one", "raw_content": "متن ترانه: تو که معنای عشقی بگو چرا رفتی"},
    {"title": "Other", "url": "https://b.org/2", "content": "snippet two", "raw_content": None},
    {"title": "bad", "url": "javascript:alert(1)", "content": "x"}]}


class TavilyTests(unittest.TestCase):
    def post(self, status=200, js=None):
        return mock.patch("kira.websearch.requests.post", return_value=Resp(status=status, js=js if js is not None else TAVILY_REPLY))

    def test_request_shape_and_parsing(self):
        with self.post() as post:
            found = ws.research("آهنگ تو که معنای عشقی", " tvly-KEY ", "advanced")
        kw = post.call_args.kwargs
        self.assertEqual(post.call_args.args[0], "https://api.tavily.com/search")
        self.assertEqual(kw["headers"]["Authorization"], "Bearer tvly-KEY")
        self.assertEqual(kw["json"]["search_depth"], "advanced")
        self.assertEqual(kw["json"]["include_raw_content"], "text")
        self.assertEqual([r["url"] for r in found["results"]], ["https://a.org/1", "https://b.org/2"])   # non-http dropped
        self.assertEqual(found["results"][0]["title"], "Song & lyrics")
        self.assertEqual(found["engine"], "tavily")
        self.assertEqual(found["assessment"]["matched"], [1])

    def test_missing_key_never_calls_the_network(self):
        with mock.patch("kira.websearch.requests.post") as post:
            with self.assertRaises(ws.SearchError):
                ws.research("x", "  ", fallback=False)
            post.assert_not_called()

    def test_http_errors_have_persian_messages(self):
        for status, word in ((401, "نامعتبر"), (432, "سهمیه"), (429, "زیاد")):
            with self.post(status=status, js={"detail": {"error": "boom"}}):
                with self.assertRaises(ws.SearchError) as cm:
                    ws.research("x", "k")
            self.assertIn(word, str(cm.exception))

    def test_network_failure_and_empty_results(self):
        import requests as rq
        with mock.patch("kira.websearch.requests.post", side_effect=rq.ConnectionError()):
            with self.assertRaises(ws.SearchError) as cm:
                ws.research("x", "k")
        self.assertIn("فیلترشکن", str(cm.exception))
        with self.post(js={"results": []}):
            with self.assertRaises(ws.SearchError):
                ws.research("x", "k")

    def test_diagnose_reports_every_engine(self):
        with self.post():
            rep = ws.diagnose("k", "basic", "آهنگ تو که معنای عشقی")
        self.assertTrue(rep["engines"]["tavily"]["ok"])
        self.assertEqual(rep["engines"]["tavily"]["sources"], 2)
        self.assertFalse(rep["engines"]["google"]["ok"])            # no Gemini key given
        self.assertEqual(rep["assessment"]["matched"], [1])
        with self.post(status=401, js={}):
            rep = ws.diagnose("bad", "basic", "q")
        self.assertFalse(rep["engines"]["tavily"]["ok"])
        self.assertIn("نامعتبر", rep["engines"]["tavily"]["error"])


class LinkRenderTests(unittest.TestCase):
    def test_bare_urls_become_short_clickable_links(self):
        from kira.chat_render import message_html
        out = message_html("assistant", "Kira", "ببین https://www.youtube.com/watch?v=abc123&t=5. خوب بود")
        self.assertIn('<a href="https://www.youtube.com/watch?v=abc123&amp;t=5"', out)
        self.assertIn(">youtube.com/watch?v=abc123&amp;t=5</a>.", out)       # trailing dot stays outside the link

    def test_persian_percent_encoded_url_is_shown_decoded_and_short(self):
        from kira.chat_render import short_url
        url = "https://gandommusic.ir/music/%D8%A7%D9%87%D9%86%DA%AF-%D8%A8%D8%B3%D8%AA%DB%8C-%D8%B2%D9%88%D8%AF-%D8%A8%D8%A7%D8%B1%D8%AA%D9%88"
        label = short_url(url)
        self.assertTrue(label.startswith("gandommusic.ir/music/اهنگ"))
        self.assertLessEqual(len(label), 56)

    def test_sources_bubble_links_the_title(self):
        from kira.chat_render import message_html, sources_html
        html = sources_html([{"title": "Page", "url": "https://a.org/x"}, {"title": "bad", "url": "javascript:alert(1)"}])
        self.assertIn('<a href="https://a.org/x"', html)
        self.assertNotIn("javascript", html)
        bubble = message_html("system", "", "", "rtl", html)
        self.assertNotIn("&nbsp;</p></td>", bubble)


class FailureReplyTests(unittest.TestCase):
    def test_failure_says_unknown_and_never_guesses(self):
        from kira import websearch
        for reason in ("Tavily نتیجه‌ای پیدا نکرد.", "مهلت پاسخ Tavily تمام شد."):
            text = websearch.failure_reply(reason)
            self.assertIn("نمی‌دونم", text)
            self.assertIn(reason, text)
        self.assertIn("هیچ نتیجه‌ای", websearch.failure_reply("Tavily نتیجه‌ای پیدا نکرد."))
        self.assertIn("نتونستم سرچ کنم", websearch.failure_reply("مهلت پاسخ Tavily تمام شد."))


class RetryTests(unittest.TestCase):
    def test_alternate_queries_are_bare_phrase_variants(self):
        alts = ws.alternate_queries("آهنگ حالا که عشقه تو خورده در دیوار دورت شده پر تفریحات از کیه؟")
        self.assertTrue(alts[0].startswith('"') and "آهنگ" not in alts[0] and "کیه" not in alts[0])
        self.assertTrue(any("متن آهنگ" in a for a in alts))
        self.assertEqual(ws.alternate_queries("سلام"), [])

    def test_retry_finds_matching_source_and_puts_it_first(self):
        calls = []

        def fake(query, key, depth="basic", timeout=25, mode="fact"):
            calls.append(query)
            if query.startswith('"'):
                return {"query": query, "date": "d", "results": [{"title": "متن آهنگ", "url": "http://x/1", "snippet": "حالا که عشقه تو خورده در دیوار", "text": ""}]}
            return {"query": query, "date": "d", "results": [{"title": "نامربوط", "url": "http://x/0", "snippet": "چیز دیگر", "text": ""}]}
        with mock.patch.object(ws, "tavily_search", fake):
            found = ws.research("q", "k", "basic", "آهنگ حالا که عشقه تو خورده در دیوار از کیه")
        self.assertTrue(found["assessment"]["matched"])
        self.assertEqual(found["results"][0]["url"], "http://x/1")
        self.assertGreater(len(calls), 1)


DDG_PAGE = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa%3Fx%3D1&amp;rut=z">Title <b>A</b></a>'
            '<a class="result__snippet" href="x">Snippet <b>one</b></a>'
            '<a rel="nofollow" class="result__a" href="https://duckduckgo.com/y.js?ad=1">Ad</a>'
            '<a rel="nofollow" class="result__a" href="https://b.org/2">B</a><a class="result__snippet" href="x">two</a>')


class FallbackTests(unittest.TestCase):
    def test_ddg_parse_unwraps_redirect_and_skips_ads(self):
        res = ws.parse_ddg(DDG_PAGE)
        self.assertEqual([r["url"] for r in res], ["https://example.org/a?x=1", "https://b.org/2"])
        self.assertEqual(res[0]["title"], "Title A")
        self.assertEqual(res[0]["snippet"], "Snippet one")

    def test_grounding_uses_sources_not_gemini_answer(self):
        data = {"candidates": [{"content": {"parts": [{"text": "MODEL ANSWER"}]}, "groundingMetadata": {
            "groundingChunks": [{"web": {"uri": "https://a.org", "title": "a.org"}}],
            "groundingSupports": [{"segment": {"text": "the supported sentence"}, "groundingChunkIndices": [0]}]}}]}
        found = ws.parse_grounding(data, "q")
        self.assertEqual(found["engine"], "google")
        self.assertEqual(found["results"][0]["snippet"], "the supported sentence")
        self.assertNotIn("MODEL ANSWER", str(found))

    def test_order_tavily_then_google_then_ddg(self):
        calls = []
        ok = lambda eng: {"query": "q", "date": "d", "engine": eng, "results": [{"title": "t", "url": "http://x/1", "snippet": "s", "text": ""}]}

        def tav(*a, **k):
            calls.append("tavily"); raise ws.SearchError("سهمیه‌ی Tavily تمام شد")

        def goo(*a, **k):
            calls.append("google"); raise ws.SearchError("google down")

        def ddg(*a, **k):
            calls.append("ddg"); return ok("ddg")
        with mock.patch.object(ws, "tavily_search", tav), mock.patch.object(ws, "gemini_search", goo), mock.patch.object(ws, "ddg_search", ddg):
            found = ws.research("قیمت دلار", "k", gemini=("gk", "m"))
        self.assertEqual(calls, ["tavily", "google", "ddg"])
        self.assertEqual(found["engine"], "ddg")
        self.assertIn("Tavily کار نکرد", found["note"])

    def test_tavily_success_skips_fallbacks(self):
        calls = []
        good = {"query": "q", "date": "d", "engine": "tavily", "results": [{"title": "t", "url": "http://x/1", "snippet": "s", "text": ""}]}
        with mock.patch.object(ws, "tavily_search", lambda *a, **k: dict(good)), \
                mock.patch.object(ws, "ddg_search", lambda *a, **k: calls.append("ddg")):
            found = ws.research("قیمت دلار", "k")
        self.assertEqual(found["engine"], "tavily")
        self.assertEqual(calls, [])

    def test_all_engines_fail_raises_combined_error(self):
        boom = lambda *a, **k: (_ for _ in ()).throw(ws.SearchError("x-fail"))
        with mock.patch.object(ws, "tavily_search", boom), mock.patch.object(ws, "ddg_search", boom):
            with self.assertRaises(ws.SearchError) as cm:
                ws.research("q", "k")
        self.assertIn("x-fail", str(cm.exception))


class SavingsTests(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(ws.mode_for("آهنگ حالا که عشقه تو خورده در دیوار از کیه"), "phrase")
        self.assertEqual(ws.mode_for("اخبار امروز"), "news")
        self.assertEqual(ws.mode_for("پایتخت استرالیا"), "fact")

    def test_plain_fact_requests_no_page_text(self):
        seen = {}

        class R:
            status_code = 200
            def json(self): return {"results": [{"title": "t", "url": "http://a/1", "content": "c"}]}

        def post(url, json=None, **k):
            seen.update(json); return R()
        ws._CACHE.clear()
        with mock.patch("kira.websearch.requests.post", post):
            ws.tavily_search("پایتخت استرالیا", "k", mode="fact")
        self.assertNotIn("include_raw_content", seen)

    def test_focus_keeps_the_relevant_window_and_block_is_capped(self):
        long = "x " * 3000 + "حالا که عشقه تو خورده در دیوار" + " y" * 3000
        out = ws.focus_text(long, ws.core_tokens("حالا که عشقه تو خورده"), 300)
        self.assertIn("عشقه تو خورده", out)
        self.assertLessEqual(len(out), 300)
        found = {"query": "q", "date": "d", "engine": "tavily",
                 "results": [{"title": "t", "url": "http://a/%d" % i, "snippet": "s" * 400, "text": "z" * 900} for i in range(30)]}
        self.assertLess(len(ws.format_block(found)), ws.BLOCK_CHARS + len(ws.RULES) + 100)

    def test_cache_avoids_second_request(self):
        n = []

        class R:
            status_code = 200
            def json(self): return {"results": [{"title": "t", "url": "http://a/1", "content": "c"}]}
        ws._CACHE.clear()
        with mock.patch("kira.websearch.requests.post", lambda *a, **k: n.append(1) or R()):
            ws.tavily_search("same query here", "k"); ws.tavily_search("same query here", "k")
        self.assertEqual(len(n), 1)
