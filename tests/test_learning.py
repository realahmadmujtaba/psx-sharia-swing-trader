import unittest

from core.learning import experience_from_trade, promotion_gate, summarize_experiences


class TestLearning(unittest.TestCase):
    def test_trade_becomes_replayable_experience(self):
        experience = experience_from_trade({
            "symbol": "HUBC",
            "setup": "MEAN_REVERSION",
            "pnl": 125.5,
            "return_pct": 2.5,
            "days_held": 4,
        })
        self.assertEqual(experience["action"], "BUY_HOLD_SELL")
        self.assertEqual(experience["reward"], 125.5)

    def test_promotion_requires_all_oos_checks(self):
        baseline = {"out_of_sample": {"metrics": {
            "total_return_pct": 1.0, "max_drawdown_pct": -10.0, "exposure_pct": 40.0,
        }}}
        candidate = {"out_of_sample": {"metrics": {
            "total_return_pct": 2.0, "max_drawdown_pct": -10.0, "exposure_pct": 40.0,
        }}}
        self.assertTrue(promotion_gate(baseline, candidate)["eligible"])

    def test_worse_drawdown_is_rejected(self):
        baseline = {"out_of_sample": {"metrics": {
            "total_return_pct": 1.0, "max_drawdown_pct": -10.0, "exposure_pct": 40.0,
        }}}
        candidate = {"out_of_sample": {"metrics": {
            "total_return_pct": 2.0, "max_drawdown_pct": -12.0, "exposure_pct": 40.0,
        }}}
        self.assertFalse(promotion_gate(baseline, candidate)["eligible"])

    def test_experience_summary_tracks_rewards(self):
        summary = summarize_experiences([
            {"reward": 10}, {"reward": -4}, {"reward": 2},
        ])
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["win_rate"], 66.7)
        self.assertEqual(summary["average_reward"], 2.6667)


if __name__ == "__main__":
    unittest.main()
