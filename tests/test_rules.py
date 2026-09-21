import unittest
from datetime import date
from unittest import mock

import numpy as np
import pandas as pd

import config
from alerts import dashboard
from alerts.email_alert import _build_digest_message
from core import indicators, risk
from core.signal_engine import (
    benchmark_rolling_return,
    delisting_advice,
    entry_failures,
    market_status,
    snapshot,
)
from fetchers.purification import parse_pdf_text, purification_amount


def _frame(close, volume=None, low=None, high=None):
    n = len(close)
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": close,
        "high": close + 1 if high is None else high,
        "low": close - 1 if low is None else low,
        "close": close,
        "volume": np.full(n, 500_000) if volume is None else volume,
        "is_anomaly": False,
    })


class TestATR(unittest.TestCase):
    def test_constant_range_gives_that_range(self):
        close = pd.Series([100.0] * 30)
        result = indicators.atr(close + 2, close - 2, close, period=14)
        self.assertAlmostEqual(result.iloc[-1], 4.0, places=6)

    def test_gap_uses_previous_close(self):
        # Day 2 gaps up: high-low is 1 but |high - prev close| is 11.
        high = pd.Series([101.0, 111.0])
        low = pd.Series([99.0, 110.0])
        close = pd.Series([100.0, 110.5])
        result = indicators.atr(high, low, close, period=1)
        self.assertAlmostEqual(result.iloc[-1], 11.0, places=6)


class TestRisk(unittest.TestCase):
    def test_atr_levels_keep_one_to_two(self):
        stop, target = risk.calculate_risk_levels(200.0, 10.0)
        self.assertEqual((stop, target), (185.0, 230.0))

    def test_size_risks_exactly_the_budget(self):
        # Risk per share = 1.5 x ATR = Rs. 15; budget = 1.5% of 1,000,000 = Rs. 15,000.
        with mock.patch.object(config, "TRADING_CAPITAL", 1_000_000):
            shares = risk.position_size(200.0, atr_value=10.0)
        self.assertEqual(shares, 1000)
        self.assertAlmostEqual(shares * 15.0, 1_000_000 * config.RISK_PER_TRADE_PCT)

    def test_tight_stop_is_capped_by_cash_not_risk(self):
        # Risk per share = Rs. 0.15 would ask for 100,000 shares = Rs. 20m of stock.
        with mock.patch.object(config, "TRADING_CAPITAL", 1_000_000):
            shares = risk.position_size(200.0, atr_value=0.1)
        self.assertEqual(shares, int(1_000_000 * config.MAX_POSITION_PCT / 200.0))

    def test_falls_back_to_flat_percent_without_atr(self):
        with mock.patch.object(config, "TRADING_CAPITAL", 1_000_000):
            self.assertEqual(risk.position_size(263.02), 380)

    def test_position_size_absent_without_capital(self):
        with mock.patch.object(config, "TRADING_CAPITAL", None):
            self.assertIsNone(risk.position_size(263.02, 10.0))


class TestEntryRules(unittest.TestCase):
    def _pullback_frame(self, last_volume):
        n = 115
        close = np.concatenate([np.linspace(100, 160, n - 8), np.linspace(159, 152, 8)])
        volume = np.full(n, 500_000.0)
        volume[-1] = last_volume
        return _frame(close, volume=volume)

    def test_volume_spike_required_when_strict(self):
        snap = snapshot(self._pullback_frame(last_volume=500_000))
        with mock.patch.object(config, "STRICT_ENTRY", True):
            self.assertIn("No volume spike", entry_failures(snap))

    def test_spike_and_support_are_informational_when_relaxed(self):
        snap = snapshot(self._pullback_frame(last_volume=500_000))
        with mock.patch.object(config, "STRICT_ENTRY", False):
            failures = entry_failures(snap)
        self.assertNotIn("No volume spike", failures)
        self.assertNotIn("Not near support", failures)
        # The measurement is still reported, it just does not block the signal.
        self.assertAlmostEqual(snap["volume_ratio"], 1.0, places=6)

    def test_spike_detected(self):
        snap = snapshot(self._pullback_frame(last_volume=900_000))
        self.assertAlmostEqual(snap["volume_ratio"], 1.8, places=6)
        with mock.patch.object(config, "STRICT_ENTRY", True):
            self.assertNotIn("No volume spike", entry_failures(snap))

    def test_close_just_above_recent_low_is_near_support(self):
        # Flat at 100 (lows 99), then closes at 101: 2% above the 20-day low.
        snap = snapshot(_frame([100.0] * 129 + [101.0]))
        self.assertEqual(snap["support_low"], 99.0)
        self.assertTrue(snap["near_support"])

    def test_far_above_support_fails_when_strict(self):
        # Steady strong uptrend: price far above both the EMA and the 20-day low.
        snap = snapshot(_frame(np.linspace(100, 300, 120)))
        self.assertFalse(snap["near_support"])
        with mock.patch.object(config, "STRICT_ENTRY", True):
            self.assertIn("Not near support", entry_failures(snap))


class TestQuantFilters(unittest.TestCase):
    """The four filters added in the quant upgrade."""

    def _snap(self, **overrides):
        base = {"close": 100.0, "ema_50": 95.0, "ema_100": 90.0, "ema_slope": 0.5, "adx": 25.0,
                "rsi": 40.0, "avg_volume": 500_000.0, "volume_ratio": 2.0, "atr": 3.0,
                "atr_pct": 0.03, "support_low": 98.0, "near_support": True,
                "return_20d": 0.08, "benchmark_return_20d": 0.02, "relative_strength": 0.06}
        return {**base, **overrides}

    def test_clean_setup_has_no_failures(self):
        self.assertEqual(entry_failures(self._snap()), [])

    def test_below_macro_ema_rejected(self):
        self.assertIn("Below 100-day EMA", entry_failures(self._snap(ema_100=105.0)))

    def test_flat_ema_with_low_adx_rejected(self):
        failures = entry_failures(self._snap(ema_slope=-0.1, adx=15.0))
        self.assertIn("Flat trend (EMA not rising, ADX low)", failures)

    def test_flat_ema_survives_on_strong_adx(self):
        self.assertEqual(entry_failures(self._snap(ema_slope=-0.1, adx=30.0)), [])

    def test_missing_adx_falls_back_to_slope(self):
        self.assertEqual(entry_failures(self._snap(adx=None)), [])
        self.assertIn("Flat trend (EMA not rising, ADX low)",
                      entry_failures(self._snap(adx=None, ema_slope=-0.2)))

    def test_too_quiet_rejected(self):
        self.assertIn("Too quiet (ATR below 2% of price)", entry_failures(self._snap(atr_pct=0.015)))

    def test_lagging_the_index_rejected(self):
        failures = entry_failures(self._snap(relative_strength=-0.01))
        self.assertIn(f"Lagging the {config.MARKET_INDEX} index", failures)

    def test_no_benchmark_skips_relative_strength(self):
        self.assertEqual(entry_failures(self._snap(relative_strength=None)), [])


class TestBenchmarkReturn(unittest.TestCase):
    def test_matches_manual_rolling_return(self):
        df = _frame([100.0] * 30 + [110.0])
        self.assertAlmostEqual(benchmark_rolling_return(df), 0.10, places=6)

    def test_short_history_returns_none(self):
        self.assertIsNone(benchmark_rolling_return(_frame([100.0] * 5)))


class TestADX(unittest.TestCase):
    def test_steady_uptrend_is_strong(self):
        close = pd.Series(range(100, 160), dtype=float)
        result = indicators.adx(close + 1, close - 1, close, period=14)
        self.assertGreater(result.iloc[-1], config.ADX_MIN)

    def test_choppy_market_is_weak(self):
        close = pd.Series([100.0 + (1 if i % 2 else -1) for i in range(60)])
        result = indicators.adx(close + 1, close - 1, close, period=14)
        self.assertLess(result.iloc[-1], config.ADX_MIN)


class TestMarketFilter(unittest.TestCase):
    def test_rising_index_is_uptrend(self):
        self.assertTrue(market_status(_frame(np.linspace(1000, 2000, 80)))["uptrend"])

    def test_falling_index_blocks(self):
        self.assertFalse(market_status(_frame(np.linspace(2000, 1000, 80)))["uptrend"])

    def test_duplicate_dates_are_ignored(self):
        df = _frame(np.linspace(1000, 2000, 80))
        df = pd.concat([df, df.tail(2)])
        self.assertIsNotNone(market_status(df))


class TestDelistingAdvice(unittest.TestCase):
    POSITION = pd.Series({"symbol": "XYZ", "date": date(2026, 9, 1), "close_price": 100.0})

    def _snap(self, close, ema, rsi, on=date(2026, 9, 5)):
        return {"date": on, "close": close, "ema_50": ema, "rsi": rsi}

    def test_below_ema_says_sell(self):
        self.assertEqual(delisting_advice(self.POSITION, self._snap(105, 110, 50))["recommendation"], "SELL")

    def test_in_loss_says_sell(self):
        self.assertEqual(delisting_advice(self.POSITION, self._snap(95, 90, 50))["recommendation"], "SELL")

    def test_overbought_says_sell(self):
        self.assertEqual(delisting_advice(self.POSITION, self._snap(120, 110, 75))["recommendation"], "SELL")

    def test_healthy_trend_says_hold(self):
        self.assertEqual(delisting_advice(self.POSITION, self._snap(108, 104, 55))["recommendation"], "HOLD")

    def test_settlement_note_before_min_hold(self):
        advice = delisting_advice(self.POSITION, self._snap(108, 104, 55, on=date(2026, 9, 2)))
        self.assertIn("settlement", advice["reason"])


class TestPurification(unittest.TestCase):
    SAMPLE = (
        "No. Ticker Company Name Income Ratio\n"
        "14 AIRLINK Air Link Communication Limited * 0.38% Compliant\n"
        "124 HALEON Haleon Pakistan Limited (Glaxo SmithKline Consumer \n"
        "Healthcare) 1.57% Compliant\n"
        "319 BIPL BankIslami Pakistan Ltd ** N/A Compliant\n"
        "340 ABL Allied Bank Ltd N/A NC by Nature\n"
    )

    def test_parses_normal_wrapped_and_islamic_rows(self):
        df = parse_pdf_text(self.SAMPLE).set_index("symbol")
        self.assertEqual(df.loc["AIRLINK", "non_compliant_income_pct"], 0.38)
        self.assertEqual(df.loc["HALEON", "non_compliant_income_pct"], 1.57)
        self.assertEqual(df.loc["BIPL", "non_compliant_income_pct"], 0.0)
        self.assertNotIn("ABL", df.index)

    def test_amount_only_on_profit(self):
        self.assertEqual(purification_amount(10_000, 1.3), 130.0)
        self.assertEqual(purification_amount(-5_000, 1.3), 0.0)


class TestOutputs(unittest.TestCase):
    RESULT = {
        "market": {"index": "KMI30", "date": date(2026, 9, 18), "close": 250000.0, "ema_50": 240000.0, "uptrend": True},
        "signals": [{
            "symbol": "HUBC", "signal_type": "SELL", "close_price": 220.0, "entry_price": 200.0,
            "stop_loss": 185.0, "take_profit": 218.0, "exit_reason": "TAKE_PROFIT", "days_held": 6,
            "shares": 500, "pnl_per_share": 20.0, "pnl_total": 10_000.0, "purification_pct": 7.16,
            "purification_on_profit": 716.0, "purification_source": "Al-Meezan",
            "timestamp": pd.Timestamp("2026-09-18 17:45", tz="Asia/Karachi"),
        }],
        "rows": [{"symbol": "HUBC", "date": date(2026, 9, 18), "status": "SELL", "reasons": ["TAKE_PROFIT"]}],
        "warnings": [],
        "watchlist": [{"symbol": "PSO", "missing": "Below 50-day EMA", "close": 345.6, "rsi": 42.9,
                       "ema_50": 354.3, "volume_ratio": 1.1}],
    }

    def test_email_shows_rupees_purification_and_watchlist(self):
        body = _build_digest_message(self.RESULT).get_content()
        self.assertIn("Rs. 10,000.00 on 500 shares", body)
        self.assertIn("Purify from this profit: Rs. 716.00", body)
        self.assertIn("special PSX Shariah exception", body)
        self.assertIn("PSO: missing Below 50-day EMA", body)

    def test_dashboard_never_publishes_position_size(self):
        log = pd.DataFrame([{"date": date(2026, 9, 12), "symbol": "HUBC", "signal_type": "BUY",
                             "close_price": 200.0, "stop_loss": 185.0, "take_profit": 218.0,
                             "exit_reason": "", "shares": 500}])
        payload = dashboard.build_payload(self.RESULT, log)
        text = str(payload)
        for secret in ("shares", "pnl_total", "purification_on_profit", "10000.0", "716.0", "500}"):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
