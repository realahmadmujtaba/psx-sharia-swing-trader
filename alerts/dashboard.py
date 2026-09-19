import json
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd

import config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "docs" / "data.json"
HISTORY_LIMIT = 50


def build_payload(rows: list[dict], signals: list[dict], log_df: pd.DataFrame) -> dict:
    history = log_df.sort_values("date", ascending=False).head(HISTORY_LIMIT)
    price_dates = [row["date"] for row in rows if row.get("date")]

    return {
        "updated_at": datetime.now(config.TIMEZONE).isoformat(timespec="minutes"),
        "price_date": max(price_dates) if price_dates else None,
        "universe": config.UNIVERSE_INDEX,
        "rules": {
            "ema_period": config.EMA_PERIOD,
            "rsi_period": config.RSI_PERIOD,
            "rsi_lower": config.RSI_LOWER,
            "rsi_upper": config.RSI_UPPER,
            "volume_lookback": config.VOLUME_LOOKBACK,
            "min_avg_volume": config.MIN_AVG_VOLUME,
            "stop_loss_pct": config.STOP_LOSS_PCT,
            "take_profit_pct": config.TAKE_PROFIT_PCT,
            "min_holding_days": config.MIN_HOLDING_DAYS,
            "max_holding_days": config.MAX_HOLDING_DAYS,
        },
        "stocks": rows,
        "signals_today": [
            {key: value for key, value in signal.items() if key != "timestamp"} for signal in signals
        ],
        "history": history.to_dict(orient="records"),
    }


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True)


def publish(payload: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    _git("add", str(DATA_PATH.relative_to(PROJECT_ROOT)))
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return

    commit = _git("commit", "-m", f"Update dashboard for {payload['price_date']}")
    push = _git("push") if commit.returncode == 0 else commit
    if push.returncode != 0:
        print(f"[dashboard] publish failed: {push.stderr.strip() or push.stdout.strip()}")
