import unittest
from pathlib import Path
from unittest import mock

from alerts.notifier import build_portfolio_message
from core import fundamentals
from core.scoring import rank_snapshots


class TestFundamentals(unittest.TestCase):
    def test_fetch_reads_and_writes_cached_metrics(self):
        with mock.patch.object(fundamentals, "CACHE_PATH", Path("tests") / "tmp-fundamentals.json"):
            fundamentals.CACHE_PATH.unlink(missing_ok=True)
            ticker = mock.Mock()
            ticker.get_info.return_value = {"trailingPE": 8.5, "dividendYield": 0.06}
            with mock.patch.dict("sys.modules", {"yfinance": mock.Mock(Ticker=mock.Mock(return_value=ticker))}):
                self.assertEqual(fundamentals.fetch("ABC"), {"pe": 8.5, "dividend_yield": 0.06})
                self.assertEqual(fundamentals.fetch("ABC"), {"pe": 8.5, "dividend_yield": 0.06})
            fundamentals.CACHE_PATH.unlink(missing_ok=True)


class TestNotifier(unittest.TestCase):
    def test_message_contains_ranked_portfolio_columns(self):
        message = build_portfolio_message(
            [{"symbol": "ABC", "pe": 8.5, "dividend_yield": 0.06,
              "momentum_score": 80.0, "composite_score": 76.0}],
            {"uptrend": True},
        )
        body = message.get_body("html").get_content()
        for value in ("ABC", "P/E", "Dividend Yield", "Momentum Score", "Total Score"):
            self.assertIn(value, body)


class TestSectorCaps(unittest.TestCase):
    def test_selects_next_sector_when_two_are_already_selected(self):
        rows = [
            {"symbol": "PRL", "pe": 5, "dividend_yield": .05, "roc_12w": 1},
            {"symbol": "CNERGY", "pe": 6, "dividend_yield": .05, "roc_12w": 1},
            {"symbol": "NRL", "pe": 7, "dividend_yield": .05, "roc_12w": 1},
            {"symbol": "SYS", "pe": 8, "dividend_yield": .05, "roc_12w": 1},
        ]
        selected = rank_snapshots(rows, limit=3)
        self.assertEqual([row["symbol"] for row in selected], ["PRL", "CNERGY", "SYS"])
        self.assertEqual(sum(row["sector"] == "Refinery" for row in selected), 2)
