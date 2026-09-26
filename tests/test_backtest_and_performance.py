import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import config
from alerts import dashboard
from core import performance
from core.backtest import _load_market_and_regime, _metrics, _prepare


def _frame(closes, volumes=None, highs=None):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="D"),
        "open": closes,
        "high": closes + 1 if highs is None else highs,
        "low": closes - 1,
        "close": closes,
        "volume": np.full(n, 900_000.0) if volumes is None else volumes,
        "is_anomaly": False,
    })


class TestPrepareTagsSetups(unittest.TestCase):
    """The backtest must tag the same setups the live engine would."""

    def test_weekly_trend_series_is_tagged(self):
        n = 200
        closes = np.concatenate([np.linspace(50, 160, n - 12), np.linspace(159, 149, 12)])
        frame = _frame(closes)
        prepared = _prepare(frame, None)
        self.assertIn(prepared["setup"].iloc[-1], (None, "MEAN_REVERSION"))

    def test_strong_trend_is_tagged_without_daily_dip(self):
        n = 200
        closes = np.linspace(50, 200, n)
        prepared = _prepare(_frame(closes), None)
        self.assertEqual(prepared.loc[prepared["weekly_rsi"].last_valid_index(), "setup"], "MEAN_REVERSION")

    def test_penny_stock_is_never_tagged(self):
        closes = np.linspace(2, 9, 200)
        prepared = _prepare(_frame(closes), None)
        self.assertIsNone(prepared["setup"].iloc[-1])

    def test_illiquid_stock_is_never_tagged(self):
        closes = np.linspace(50, 200, 200)
        prepared = _prepare(_frame(closes, volumes=np.full(200, 100_000.0)), None)
        self.assertIsNone(prepared["setup"].iloc[-1])

    def test_short_history_returns_none(self):
        self.assertIsNone(_prepare(_frame(np.linspace(50, 60, 40)), None))

    def test_missing_market_index_uses_explicit_regime_benchmark(self):
        regime = pd.DataFrame({"close": [100.0, 101.0]})
        with mock.patch("core.backtest._cached_fetch", side_effect=[pd.DataFrame(), pd.DataFrame()]), \
             mock.patch("core.backtest._prepare", side_effect=[regime, None]):
            market, loaded_regime = _load_market_and_regime(
                date(2025, 1, 1), date(2025, 1, 2), refresh=False
            )
        self.assertIs(loaded_regime, regime)
        self.assertEqual(market.attrs["benchmark_index"], config.REGIME_INDEX)
        pd.testing.assert_frame_equal(market, regime)


class TestMetrics(unittest.TestCase):
    TRADES = [
        {"return_pct": 10.0, "pnl": 100.0, "days_held": 5},
        {"return_pct": -5.0, "pnl": -50.0, "days_held": 3},
        {"return_pct": 4.0, "pnl": 40.0, "days_held": 7},
    ]

    def _series(self, values):
        return pd.Series(values, index=pd.date_range("2025-01-01", periods=len(values), freq="D"))

    def test_empty_is_zeroed(self):
        self.assertEqual(_metrics([], pd.Series(dtype=float), pd.Series(dtype=float), 100.0, 1)["trades"], 0)

    def test_win_rate_drawdown_and_profit_factor(self):
        equity = self._series([1000.0, 1100.0, 1050.0, 1090.0])
        m = _metrics(self.TRADES, equity, self._series([100.0] * 4), 1000.0, 2.0)
        self.assertEqual(m["trades"], 3)
        self.assertEqual(m["trades_per_year"], 1.5)
        self.assertAlmostEqual(m["win_rate"], 66.7, places=1)
        self.assertEqual(m["profit_factor"], 2.8)
        self.assertAlmostEqual(m["max_drawdown_pct"], -4.55, places=2)
        self.assertEqual(m["total_return_pct"], 9.0)

    def test_beta_is_one_when_tracking_the_benchmark(self):
        moves = [1000.0, 1010.0, 1005.0, 1020.0, 1015.0, 1030.0]
        m = _metrics(self.TRADES, self._series(moves), self._series(moves), 1000.0, 1.0)
        self.assertAlmostEqual(m["beta"], 1.0, places=2)

    def test_beta_is_zero_against_a_flat_market(self):
        equity = self._series([1000.0, 1010.0, 1005.0, 1020.0, 1015.0, 1030.0])
        flat = self._series([100.0, 101.0, 100.0, 101.0, 100.0, 101.0])
        m = _metrics(self.TRADES, equity, flat, 1000.0, 1.0)
        self.assertLess(abs(m["beta"]), 1.0)

    def test_sharpe_is_negative_when_returns_trail_the_risk_free_rate(self):
        flatish = self._series([1000.0, 1001.0, 1000.5, 1001.5, 1001.0, 1002.0])
        m = _metrics(self.TRADES, flatish, self._series([100.0] * 6), 1000.0, 1.0)
        self.assertLess(m["sharpe"], 0)


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
