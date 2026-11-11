import copy
import datetime as dt
import json
import urllib.error
import urllib.parse
import unittest
from unittest.mock import patch
from test_collect import collector, NOW


def news(title="World leaders meet for peace talks"):
    return {"BBC World": {"items": [{"title": title, "link": "https://example.com/article", "pubDate": "date"}], "stale": False}}


def response(text="Líderes mundiais se reúnem para negociações de paz"):
    return json.dumps({"responseStatus": 200, "quotaFinished": False,
                       "responseData": {"translatedText": text, "match": 0.85}}).encode()


class TranslationTests(unittest.TestCase):
    def test_translates_title_preserves_source_and_reuses_cache(self):
        items = news()
        original = copy.deepcopy(items["BBC World"]["items"][0])
        with patch.object(collector, "translation_fetch", return_value=response()) as request:
            state = collector.translate_headlines(items, None, NOW)
            translated = items["BBC World"]["items"][0]
            self.assertEqual(translated["title"], original["title"])
            self.assertEqual(translated["title_original"], original["title"])
            self.assertEqual(translated["link"], original["link"])
            self.assertEqual(translated["translation_status"], "translated")
            self.assertIn("Líderes", translated["title_pt"])
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.call_args.args[0]).query)
            self.assertEqual(query["langpair"], ["en|pt-BR"])
            self.assertNotIn("de", query)
            self.assertNotIn("key", query)
            collector.translate_headlines(news(), state, NOW + dt.timedelta(minutes=15))
            self.assertEqual(request.call_count, 1)

    def test_changed_headline_is_not_given_previous_translation(self):
        with patch.object(collector, "translation_fetch", return_value=response()) as request:
            state = collector.translate_headlines(news(), None, NOW)
            collector.translate_headlines(news("A different headline"), state, NOW)
            self.assertEqual(request.call_count, 2)

    def test_service_failure_uses_original_and_backs_off(self):
        items = news()
        with patch.object(collector, "translation_fetch", side_effect=urllib.error.URLError("offline")) as request:
            state = collector.translate_headlines(items, None, NOW)
            self.assertNotIn("title_pt", items["BBC World"]["items"][0])
            collector.translate_headlines(news(), state, NOW + dt.timedelta(minutes=15))
            self.assertEqual(request.call_count, 1)

    def test_rolling_budget_stops_requests_without_spending_money(self):
        state = {"usage": [{"at": NOW.isoformat(), "chars": 500}] * 9}
        items = news()
        with patch.object(collector, "translation_fetch") as request:
            collector.translate_headlines(items, state, NOW)
            request.assert_not_called()
        self.assertEqual(items["BBC World"]["items"][0]["translation_status"], "limited")

    def test_provider_quota_stops_rest_of_run_and_following_runs(self):
        items = news()
        items["BBC World"]["items"].append({"title": "Second headline"})
        with patch.object(collector, "translation_fetch", return_value=b'{"responseStatus":200,"quotaFinished":true}') as request:
            state = collector.translate_headlines(items, None, NOW)
            collector.translate_headlines(news("New headline"), state, NOW + dt.timedelta(hours=1))
            self.assertEqual(request.call_count, 1)
        self.assertEqual(state["blocked_until"], (NOW + dt.timedelta(hours=24)).isoformat())

    def test_provider_errors_and_weak_matches_are_not_displayed(self):
        responses = [b'{"responseStatus":403,"responseData":{"translatedText":"ERROR"}}',
                     b'{"responseStatus":200,"responseData":{"translatedText":"Unrelated","match":0.3}}',
                     b'{"responseStatus":200,"responseData":{"translatedText":"MYMEMORY WARNING: LIMIT","match":1}}']
        for raw in responses:
            items = news()
            with self.subTest(raw=raw), patch.object(collector, "translation_fetch", return_value=raw):
                collector.translate_headlines(items, None, NOW)
                self.assertNotIn("title_pt", items["BBC World"]["items"][0])

    def test_long_titles_and_unknown_language_are_not_sent(self):
        for items in (news("ç" * 251), {"Unknown": {"items": [{"title": "Hello"}]}}):
            with patch.object(collector, "translation_fetch") as request:
                collector.translate_headlines(items, None, NOW)
                request.assert_not_called()

    def test_stale_news_does_not_request_new_translation(self):
        items = news()
        items["BBC World"]["stale"] = True
        with patch.object(collector, "translation_fetch") as request:
            collector.translate_headlines(items, None, NOW)
            request.assert_not_called()

    def test_html_entities_are_decoded_as_text(self):
        items = news()
        with patch.object(collector, "translation_fetch", return_value=response("Paz &amp; cooperação")):
            collector.translate_headlines(items, None, NOW)
        self.assertEqual(items["BBC World"]["items"][0]["title_pt"], "Paz & cooperação")


if __name__ == "__main__":
    unittest.main()
