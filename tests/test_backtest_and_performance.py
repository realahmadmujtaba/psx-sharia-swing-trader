import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

import config
from alerts import dashboard
from core import performance
from core.backtest import _metrics, _qualifies

ROW = pd.Series({
    "close": 100.0, "ema_50": 98.0, "rsi": 40.0, "atr": 3.0,
    "avg_volume": 500_000.0, "volume_ratio": 2.0, "support_low": 98.5,
})


class TestQualifies(unittest.TestCase):
    def test_all_conditions_pass(self):
        self.assertTrue(_qualifies(ROW, "strict"))

    def test_missing_indicator_rejects(self):
        self.assertFalse(_qualifies(pd.Series({**ROW, "atr": float("nan")}), "strict"))

    def test_strict_needs_volume_spike_but_relaxed_does_not(self):
        row = pd.Series({**ROW, "volume_ratio": 1.0})
        self.assertFalse(_qualifies(row, "strict"))
        self.assertTrue(_qualifies(row, "relaxed"))

    def test_strict_needs_support_but_relaxed_does_not(self):
        # Far above both the EMA and the 20-day low.
        row = pd.Series({**ROW, "close": 130.0})
        self.assertFalse(_qualifies(row, "strict"))
        self.assertTrue(_qualifies(row, "relaxed"))

    def test_rsi_outside_band_rejected_by_both(self):
        row = pd.Series({**ROW, "rsi": config.RSI_UPPER + 5})
        self.assertFalse(_qualifies(row, "strict"))
        self.assertFalse(_qualifies(row, "relaxed"))


class TestMetrics(unittest.TestCase):
    def test_empty_is_zeroed(self):
        self.assertEqual(_metrics([], [], 100.0, 1)["trades"], 0)

    def test_win_rate_drawdown_and_profit_factor(self):
        trades = [
            {"return_pct": 10.0, "pnl": 100.0, "days_held": 5},
            {"return_pct": -5.0, "pnl": -50.0, "days_held": 3},
            {"return_pct": 4.0, "pnl": 40.0, "days_held": 7},
        ]
        curve = [{"equity": 1000.0}, {"equity": 1100.0}, {"equity": 1050.0}, {"equity": 1090.0}]
        m = _metrics(trades, curve, 1000.0, 2.0)
        self.assertEqual(m["trades"], 3)
        self.assertEqual(m["trades_per_year"], 1.5)
        self.assertAlmostEqual(m["win_rate"], 66.7, places=1)
        self.assertEqual(m["profit_factor"], 2.8)
        self.assertAlmostEqual(m["max_drawdown_pct"], -4.55, places=2)
        self.assertEqual(m["total_return_pct"], 9.0)


class TestPerformance(unittest.TestCase):
    LOG = pd.DataFrame([
        {"date": date(2026, 9, 1), "symbol": "HUBC", "signal_type": "BUY", "close_price": 200.0,
         "stop_loss": 190.0, "take_profit": 220.0, "exit_reason": ""},
        {"date": date(2026, 9, 8), "symbol": "HUBC", "signal_type": "SELL", "close_price": 220.0,
         "stop_loss": 190.0, "take_profit": 220.0, "exit_reason": "TAKE_PROFIT"},
        {"date": date(2026, 9, 3), "symbol": "LUCK", "signal_type": "BUY", "close_price": 400.0,
         "stop_loss": 380.0, "take_profit": 440.0, "exit_reason": ""},
        {"date": date(2026, 9, 9), "symbol": "LUCK", "signal_type": "SELL", "close_price": 380.0,
         "stop_loss": 380.0, "take_profit": 440.0, "exit_reason": "STOP_LOSS"},
        {"date": date(2026, 9, 10), "symbol": "SYS", "signal_type": "BUY", "close_price": 120.0,
         "stop_loss": 114.0, "take_profit": 132.0, "exit_reason": ""},
    ])

    def test_pairs_buys_with_sells_and_ignores_open_position(self):
        trades = performance.closed_trades(self.LOG)
        self.assertEqual([t["symbol"] for t in trades], ["LUCK", "HUBC"])
        self.assertEqual(trades[1]["return_pct"], 10.0)
        self.assertEqual(trades[0]["return_pct"], -5.0)
        self.assertEqual(trades[1]["days_held"], 7)

    def test_summary_compounds(self):
        summary = performance.summarise(performance.closed_trades(self.LOG))
        self.assertEqual(summary["trades"], 2)
        self.assertEqual(summary["win_rate"], 50.0)
        self.assertEqual(summary["cumulative_pct"], 4.5)

    def test_empty_log(self):
        self.assertEqual(performance.summarise(performance.closed_trades(pd.DataFrame()))["trades"], 0)


class TestPublishStaging(unittest.TestCase):
    """A missing signal log must not stop the dashboard file from being staged."""

    def _staged_paths(self, log_exists: bool) -> tuple[str, ...]:
        calls = []

        def fake_git(*args):
            calls.append(args)
            return subprocess.CompletedProcess(args, 1 if args[0] == "diff" else 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            if log_exists:
                (root / "data" / "signals_log.csv").write_text("date,symbol\n", encoding="utf-8")
            with mock.patch.object(dashboard, "_git", fake_git), \
                 mock.patch.object(dashboard, "PROJECT_ROOT", root), \
                 mock.patch.object(dashboard, "DATA_PATH", root / "docs" / "data.json"):
                dashboard.publish({"price_date": "2026-09-18"})
        return [c for c in calls if c[0] == "add"][0][1:]

    def test_stages_dashboard_even_without_log(self):
        staged = self._staged_paths(log_exists=False)
        self.assertEqual(len(staged), 1)
        self.assertIn("data.json", staged[0])

    def test_stages_log_when_present(self):
        self.assertIn("data/signals_log.csv", self._staged_paths(log_exists=True))


if __name__ == "__main__":
    unittest.main()
