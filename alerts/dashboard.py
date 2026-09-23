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
    rows = result.get("portfolio", result["rows"])
    history = log_df.drop(columns=["shares"], errors="ignore").sort_values("date", ascending=False).head(HISTORY_LIMIT)
    price_dates = [row["date"] for row in rows if row.get("date")]

    return {
        "updated_at": datetime.now(config.TIMEZONE).isoformat(timespec="minutes"),
        "price_date": max(price_dates) if price_dates else None,
        "universe": config.UNIVERSE_INDEX,
        "market": result.get("market"),
        "rules": {
            "value_weight": config.VALUE_WEIGHT,
            "income_weight": config.INCOME_WEIGHT,
            "momentum_weight": config.MOMENTUM_WEIGHT,
            "portfolio_size": config.PORTFOLIO_SIZE,
            "regime_index": config.REGIME_INDEX,
            "regime_ema_period": config.REGIME_EMA_PERIOD,
            "value_max_pe": config.VALUE_MAX_PE,
            "value_min_dividend_yield": config.VALUE_MIN_DIVIDEND_YIELD,
            "smtp_weekly_alert_day": "Friday",
            "market_index": config.UNIVERSE_INDEX,
            "min_holding_days": config.MIN_HOLDING_DAYS,
        },
        "stocks": rows,
        "portfolio": rows,
        "signals_today": [],
        "warnings": result.get("warnings", []),
        "watchlist": [],
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
    for generated in ("docs/dashboard.html", "docs/tearsheet.html"):
        if (PROJECT_ROOT / generated).exists():
            paths.append(generated)
    blog_posts = sorted((PROJECT_ROOT / "docs" / "blog_posts").glob("*.md"))
    if blog_posts:
        paths.append(str(blog_posts[-1].relative_to(PROJECT_ROOT)))
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
