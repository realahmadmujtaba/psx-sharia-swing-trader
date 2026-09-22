import json
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd

import config
from core import performance

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "docs" / "data.json"
HISTORY_LIMIT = 50
# The dashboard is public: anything that reveals position size (and so capital) stays in the email only.
PRIVATE_FIELDS = {"timestamp", "shares", "pnl_total", "purification_on_profit"}


def build_payload(result: dict, log_df: pd.DataFrame) -> dict:
    rows = result["rows"]
    history = log_df.drop(columns=["shares"], errors="ignore").sort_values("date", ascending=False).head(HISTORY_LIMIT)
    price_dates = [row["date"] for row in rows if row.get("date")]

    return {
        "updated_at": datetime.now(config.TIMEZONE).isoformat(timespec="minutes"),
        "price_date": max(price_dates) if price_dates else None,
        "universe": config.UNIVERSE_INDEX,
        "market": result.get("market"),
        "rules": {
            "ema_period": config.EMA_PERIOD,
            "rsi_period": config.RSI_PERIOD,
            "rsi_lower": config.RSI_LOWER,
            "rsi_upper": config.RSI_UPPER,
            "volume_lookback": config.VOLUME_LOOKBACK,
            "min_avg_volume": config.MIN_AVG_VOLUME,
            "volume_spike_mult": config.VOLUME_SPIKE_MULT,
            "min_price": config.MIN_PRICE,
            "support_proximity_pct": config.SUPPORT_PROXIMITY_PCT,
            "atr_period": config.ATR_PERIOD,
            "atr_stop_mult": config.ATR_STOP_MULT,
            "atr_target_mult": config.ATR_TARGET_MULT,
            "macro_ema_period": config.MACRO_EMA_PERIOD,
            "adx_period": config.ADX_PERIOD,
            "adx_min": config.ADX_MIN,
            "ema_slope_lookback": config.EMA_SLOPE_LOOKBACK,
            "rs_lookback": config.RS_LOOKBACK,
            "regime_index": config.REGIME_INDEX,
            "regime_ema_period": config.REGIME_EMA_PERIOD,
            "regime_slope_lookback": config.REGIME_SLOPE_LOOKBACK,
            "risk_per_trade_pct": config.RISK_PER_TRADE_PCT,
            "trail_ema_period": config.TRAIL_EMA_PERIOD,
            "min_holding_days": config.MIN_HOLDING_DAYS,
            "max_open_positions": config.MAX_OPEN_POSITIONS,
            "market_index": config.MARKET_INDEX,
        },
        "stocks": rows,
        "signals_today": [
            {key: value for key, value in signal.items() if key not in PRIVATE_FIELDS}
            for signal in result["signals"]
        ],
        "warnings": result.get("warnings", []),
        "watchlist": result.get("watchlist", []),
        "performance": performance.summarise(performance.closed_trades(log_df)),
        "history": history.to_dict(orient="records"),
    }


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True)


def publish(payload: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    # The signal log is state: it must travel with the repo so cloud runs remember open positions.
    # It only exists once a signal has fired, and git add fails the whole call on a missing path.
    paths = [str(DATA_PATH.relative_to(PROJECT_ROOT))]
    for state_file in ("data/signals.db", "data/signals_log.csv"):
        if (PROJECT_ROOT / state_file).exists():
            paths.append(state_file)
    _git("add", *paths)
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return

    commit = _git("commit", "-m", f"Update dashboard for {payload['price_date']}")
    push = _git("push") if commit.returncode == 0 else commit
    if push.returncode != 0:
        print(f"[dashboard] publish failed: {push.stderr.strip() or push.stdout.strip()}")
