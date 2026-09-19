import unittest
from datetime import date

import pandas as pd

from core.signal_engine import evaluate_exit
from fetchers.universe import normalize_symbol

POSITION = pd.Series(
    {
        "symbol": "ENGRO",
        "date": date(2026, 9, 1),
        "close_price": 150.0,
        "stop_loss": 144.0,
        "take_profit": 162.0,
    }
)


def _df(close: float, as_of: date) -> pd.DataFrame:
    return pd.DataFrame({"date": [pd.Timestamp(as_of)], "close": [close], "is_anomaly": [False]})


class TestMinHoldingLock(unittest.TestCase):
    def test_take_profit_before_min_hold_is_suppressed(self):
        self.assertIsNone(evaluate_exit(POSITION, _df(170.0, date(2026, 9, 2))))

    def test_stop_loss_before_min_hold_is_suppressed(self):
        self.assertIsNone(evaluate_exit(POSITION, _df(130.0, date(2026, 9, 2))))

    def test_take_profit_on_min_hold_day_fires(self):
        signal = evaluate_exit(POSITION, _df(170.0, date(2026, 9, 3)))
        self.assertEqual(signal["exit_reason"], "TAKE_PROFIT")
        self.assertEqual(signal["days_held"], 2)
        self.assertAlmostEqual(signal["pnl_per_share"], 20.0)

    def test_stop_loss_after_min_hold_fires(self):
        signal = evaluate_exit(POSITION, _df(140.0, date(2026, 9, 6)))
        self.assertEqual(signal["exit_reason"], "STOP_LOSS")

    def test_max_hold_still_forces_exit(self):
        signal = evaluate_exit(POSITION, _df(155.0, date(2026, 9, 16)))
        self.assertEqual(signal["exit_reason"], "MAX_HOLD")


class TestNormalizeSymbol(unittest.TestCase):
    def test_strips_ex_dividend_suffix(self):
        self.assertEqual(normalize_symbol("LUCKXD"), "LUCK")
        self.assertEqual(normalize_symbol("SAZEWXD"), "SAZEW")

    def test_leaves_normal_symbols_alone(self):
        self.assertEqual(normalize_symbol("ENGROH"), "ENGROH")
        self.assertEqual(normalize_symbol("HUBC"), "HUBC")


if __name__ == "__main__":
    unittest.main()
