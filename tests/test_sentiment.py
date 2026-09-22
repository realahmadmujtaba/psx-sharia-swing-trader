import unittest
from unittest import mock

from core import sentiment
from scrapers import news_scraper
from alerts.notifier import build_portfolio_message


class TestNewsScraper(unittest.TestCase):
    def test_filters_irrelevant_feed_entries(self):
        parsed = mock.Mock(entries=[
            {"title": "PSX closes higher", "summary": "KMI index gained", "link": "x"},
            {"title": "Weather update", "summary": "Rain expected", "link": "y"},
        ])
        response = mock.Mock(content=b"feed")
        with mock.patch.object(news_scraper.requests, "get", return_value=response), \
             mock.patch.object(news_scraper.feedparser, "parse", return_value=parsed):
            result = news_scraper.fetch_feed("Test", "https://example.test")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["title"], "PSX closes higher")


class TestSentiment(unittest.TestCase):
    def test_parses_structured_gemini_json(self):
        response = mock.Mock(text='{"market_sentiment":"Bullish","confidence":0.8,'
                             '"macro_drivers":[],"takeaways":["Rates"],'
                             '"stock_flags":[],"divergence_insights":[]}')
        client = mock.Mock()
        client.models.generate_content.return_value = response
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}), \
             mock.patch("google.genai.Client", return_value=client):
            result = sentiment.analyze([], [], ["ABC"])
        self.assertEqual(result["market_sentiment"], "Bullish")


class TestNotifierIntelligence(unittest.TestCase):
    def test_message_includes_sentiment_sections(self):
        message = build_portfolio_message(
            [{"symbol": "ABC", "pe": 8, "dividend_yield": .05,
              "momentum_score": 80, "composite_score": 75,
              "qualitative_flag": "Bullish"}],
            {"uptrend": False},
            {"market_sentiment": "Neutral", "confidence": .7,
             "takeaways": ["Oil prices"], "divergence_insights": []},
        )
        html = message.get_body("html").get_content()
        self.assertIn("Daily Market", html)
        self.assertIn("Bullish", html)
