import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from alerts.blog_generator import build_blog_post, save_blog_post


class TestBlogGenerator(unittest.TestCase):
    def test_builds_structured_post(self):
        post = build_blog_post(
            {
                "market_sentiment": "Neutral",
                "confidence": 0.8,
                "macro_drivers": ["IMF review"],
                "takeaways": ["PSX breadth was mixed"],
                "divergence_insights": ["News is weaker than the ranking"],
            },
            [{"symbol": "CNERGY", "composite_score": 82, "value_score": 90,
              "income_score": 80, "momentum_score": 70}],
            datetime(2026, 9, 23, 8, 0),
        )
        self.assertIn("# PSX Daily Intelligence & Value Radar - 2026-09-23", post)
        self.assertIn("CNERGY", post)
        self.assertIn("IMF review", post)
        self.assertIn("Risk & Sentiment Warnings", post)

    def test_saves_dated_post(self):
        with TemporaryDirectory() as directory:
            path = save_blog_post(
                {"takeaways": []},
                [],
                Path(directory),
                datetime(2026, 9, 23, 8, 0),
            )
            self.assertEqual(path.name, "2026-09-23_psx_analysis.md")
            self.assertTrue(path.exists())
