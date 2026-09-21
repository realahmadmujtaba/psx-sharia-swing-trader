import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd

import config
from core.signal_engine import evaluate_exit
from fetchers.universe import normalize_symbol

POSITION = pd.Series({
    "symbol": "ENGRO",
    "date": date(2026, 9, 1),
    "close_price": 150.0,
    "stop_loss": 144.0,
    "take_profit": 162.0,
})


def _history(closes: list[float], as_of: date) -> pd.DataFrame:
    """Frame ending on `as_of`, long enough for a 20-day EMA."""
    dates = [as_of - timedelta(days=len(closes) - 1 - i) for i in range(len(closes))]
    close = np.array(closes, dtype=float)
    return pd.DataFrame({"date": pd.to_datetime(dates), "open": close, "high": close + 1,
                         "low": close - 1, "close": close, "volume": 500_000, "is_anomaly": False})


def _flat_then(last: float, as_of: date, level: float = 150.0) -> pd.DataFrame:
    return _history([level] * 40 + [last], as_of)


class TestMinHoldingLock(unittest.TestCase):
    def test_take_profit_before_min_hold_is_suppressed(self):
        self.assertIsNone(evaluate_exit(POSITION, _flat_then(170.0, date(2026, 9, 2))))

    def test_stop_loss_before_min_hold_is_suppressed(self):
        self.assertIsNone(evaluate_exit(POSITION, _flat_then(130.0, date(2026, 9, 2))))

    def test_take_profit_on_min_hold_day_fires(self):
        signal = evaluate_exit(POSITION, _flat_then(170.0, date(2026, 9, 3)))
        self.assertEqual(signal["exit_reason"], "TAKE_PROFIT")
        self.assertEqual(signal["days_held"], 2)
        self.assertAlmostEqual(signal["pnl_per_share"], 20.0)

    def test_stop_loss_after_min_hold_fires(self):
        signal = evaluate_exit(POSITION, _flat_then(140.0, date(2026, 9, 6)))
        self.assertEqual(signal["exit_reason"], "STOP_LOSS")


class TestTrailingExit(unittest.TestCase):
    def test_close_below_trailing_ema_exits(self):
        # Rising to 170, then a drop that is still above the 4% stop but below the 20-day EMA.
        rising = list(np.linspace(150, 170, 40))
        df = _history(rising + [158.0], date(2026, 9, 20))
        signal = evaluate_exit(POSITION, df)
        self.assertEqual(signal["exit_reason"], "TRAIL_EMA")
        self.assertGreater(signal["close_price"], POSITION["stop_loss"])

    def test_holding_above_the_trailing_ema_does_not_exit(self):
        # Stays under the 162 take-profit and above its own 20-day EMA: no exit.
        rising = list(np.linspace(150, 160, 40))
        signal = evaluate_exit(POSITION, _history(rising + [159.0], date(2026, 9, 20)))
        self.assertIsNone(signal)

    def test_no_time_based_exit_remains(self):
        # 60 days held, price flat and above its EMA: the old MAX_HOLD rule would have exited.
        df = _flat_then(150.0, date(2026, 10, 31))
        self.assertIsNone(evaluate_exit(POSITION, df))
        self.assertFalse(hasattr(config, "MAX_HOLDING_DAYS"))


class TestNormalizeSymbol(unittest.TestCase):
    def test_strips_ex_dividend_suffix(self):
        self.assertEqual(normalize_symbol("LUCKXD"), "LUCK")
        self.assertEqual(normalize_symbol("SAZEWXD"), "SAZEW")

    def test_leaves_normal_symbols_alone(self):
        self.assertEqual(normalize_symbol("ENGROH"), "ENGROH")
        self.assertEqual(normalize_symbol("HUBC"), "HUBC")


if __name__ == "__main__":
    unittest.main()
