import unittest

import pandas as pd

from core import indicators


class TestEMA(unittest.TestCase):
    def test_constant_series_equals_constant(self):
        series = pd.Series([50.0] * 10)
        result = indicators.ema(series, period=5)
        self.assertTrue((result == 50.0).all())

    def test_matches_hand_computed_values(self):
        # span=2 -> alpha = 2/(2+1) = 2/3
        series = pd.Series([1.0, 2.0, 3.0])
        result = indicators.ema(series, period=2)
        self.assertAlmostEqual(result.iloc[0], 1.0, places=6)
        self.assertAlmostEqual(result.iloc[1], 5 / 3, places=6)
        self.assertAlmostEqual(result.iloc[2], 23 / 9, places=6)


class TestRSI(unittest.TestCase):
    def test_strictly_increasing_series_approaches_100(self):
        series = pd.Series(range(1, 31), dtype=float)
        result = indicators.rsi(series, period=14)
        self.assertAlmostEqual(result.iloc[-1], 100.0, places=6)

    def test_strictly_decreasing_series_approaches_0(self):
        series = pd.Series(range(30, 0, -1), dtype=float)
        result = indicators.rsi(series, period=14)
        self.assertAlmostEqual(result.iloc[-1], 0.0, places=6)

    def test_warmup_period_is_nan(self):
        series = pd.Series(range(1, 10), dtype=float)
        result = indicators.rsi(series, period=14)
        self.assertTrue(result.isna().all())


class TestAvgVolume(unittest.TestCase):
    def test_rolling_mean_matches_manual_computation(self):
        series = pd.Series([10, 20, 30, 40])
        result = indicators.avg_volume(series, period=3)
        self.assertTrue(pd.isna(result.iloc[0]))
        self.assertTrue(pd.isna(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 20.0, places=6)
        self.assertAlmostEqual(result.iloc[3], 30.0, places=6)


if __name__ == "__main__":
    unittest.main()
