"""Safe shadow learning for the PSX agent.

This module records what happened, compares tested variants, and produces
recommendations. It never creates or overrides live BUY/SELL signals.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import config
from core import performance

RESULT_PATH = config.DOCS_DIR / "backtest.json"
LEARNING_PATH = config.DOCS_DIR / "learning.json"


def experience_from_trade(trade: dict) -> dict:
    """Convert a completed trade into a replayable reward record."""
    reward = float(trade.get("pnl", trade.get("return_pct", 0.0)))
    return {
        "symbol": trade.get("symbol"),
        "setup": trade.get("setup", "UNKNOWN"),
        "entry_date": trade.get("entry_date"),
        "exit_date": trade.get("exit_date"),
        "action": "BUY_HOLD_SELL",
        "reward": round(reward, 4),
        "return_pct": float(trade.get("return_pct", 0.0)),
        "days_held": int(trade.get("days_held", 0)),
        "exit_reason": trade.get("exit_reason"),
    }


def replay_experiences(trades: list[dict]) -> list[dict]:
    """Build deterministic experience records without look-ahead or live effects."""
    return [experience_from_trade(trade) for trade in trades]


def summarize_experiences(experiences: list[dict]) -> dict:
    """Summarize rewards for monitoring and future model training."""
    if not experiences:
        return {"count": 0, "win_rate": None, "average_reward": None}
    rewards = [float(item["reward"]) for item in experiences]
    return {
        "count": len(rewards),
        "win_rate": round(sum(reward > 0 for reward in rewards) / len(rewards) * 100, 1),
        "average_reward": round(sum(rewards) / len(rewards), 4),
    }


def _metric(metrics: dict, key: str, default: float = 0.0) -> float:
    value = metrics.get(key)
    return default if value is None else float(value)


def promotion_gate(baseline: dict, candidate: dict) -> dict:
    """Require OOS return improvement with no worse drawdown or exposure."""
    baseline_metrics = baseline.get("out_of_sample", {}).get("metrics", {})
    candidate_metrics = candidate.get("out_of_sample", {}).get("metrics", {})
    checks = {
        "return_improved": _metric(candidate_metrics, "total_return_pct")
        > _metric(baseline_metrics, "total_return_pct"),
        "drawdown_not_worse": _metric(candidate_metrics, "max_drawdown_pct")
        >= _metric(baseline_metrics, "max_drawdown_pct"),
        "exposure_not_worse": _metric(candidate_metrics, "exposure_pct")
        <= _metric(baseline_metrics, "exposure_pct"),
    }
    return {
        "eligible": all(checks.values()),
        "checks": checks,
        "baseline_oos": baseline_metrics,
        "candidate_oos": candidate_metrics,
    }


def build_report(backtest: dict) -> dict:
    """Create the weekly learning report and keep the live variant unchanged."""
    baseline = backtest.get("multi_factor", {})
    candidate = backtest.get("ai_conviction", {})
    gate = promotion_gate(baseline, candidate)
    experiences = replay_experiences(baseline.get("full", {}).get("trades", []))
    return {
        "updated_at": datetime.now(config.TIMEZONE).isoformat(timespec="seconds"),
        "mode": "shadow_learning",
        "live_authority": "fixed_psx_sharia_risk_rules",
        "promotion_gate": "oos_return_up_and_drawdown_exposure_not_worse",
        "candidate_variant": "ai_conviction",
        "recommendation": (
            "candidate_ready_for_human_review" if gate["eligible"]
            else "keep_current_strategy"
        ),
        "promotion": gate,
        "experience_summary": summarize_experiences(experiences),
        "experiences": experiences[-200:],
        "note": (
            "This report is advisory. It does not modify live signals automatically."
        ),
    }


def save_report(
    backtest_path: Path = RESULT_PATH,
    output_path: Path = LEARNING_PATH,
) -> dict:
    if not backtest_path.exists():
        raise FileNotFoundError(f"Backtest result not found: {backtest_path}")
    payload = json.loads(backtest_path.read_text(encoding="utf-8"))
    report = build_report(payload.get("results", payload))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the PSX shadow-learning report")
    parser.add_argument("--save", action="store_true", help="Write docs/learning.json")
    args = parser.parse_args()
    if not args.save:
        parser.error("use --save to write the learning report")
    report = save_report()
    print(f"Learning recommendation: {report['recommendation']}")


if __name__ == "__main__":
    main()
