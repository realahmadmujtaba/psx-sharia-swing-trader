import argparse
import asyncio
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from alerts import dashboard, notifier, webhook
from alerts.email_alert import send_digest
from core import state
from core import scoring
from core.fundamentals import fetch_many
from core.signal_engine import benchmark_rolling_return, market_status, snapshot
from fetchers.psx_fetcher import fetch_ohlcv
from fetchers.purification import load_ratios, purification_amount
from fetchers.universe import get_universe

HISTORY_DAYS = 400
# Weekend plus a public holiday; anything older means PSX stopped reporting the symbol.
STALE_AFTER_DAYS = 4


def _attach_purification(signal: dict, ratios: dict) -> None:
    ratio = ratios.get(signal["symbol"])
    signal["purification_pct"] = float(ratio["non_compliant_income_pct"]) if ratio else None
    signal["purification_source"] = ratio["source"] if ratio else None
    if signal["signal_type"] == "SELL" and signal.get("shares"):
        signal["pnl_total"] = round(signal["pnl_per_share"] * signal["shares"], 2)
        if signal["purification_pct"] is not None:
            signal["purification_on_profit"] = purification_amount(signal["pnl_total"], signal["purification_pct"])


def _watch(row: dict, missing: str) -> dict:
    return {"symbol": row["symbol"], "missing": missing, "close": row["close"], "rsi": row["rsi"],
            "ema_50": row["ema_50"], "volume_ratio": row["volume_ratio"]}


def run_scan() -> dict:
    end = datetime.now(config.TIMEZONE).date()
    start = end - timedelta(days=HISTORY_DAYS)

    log_df = state.load_log()
    ratios = load_ratios()
    universe = get_universe()
    fundamentals = fetch_many(universe)
    positions = state.open_positions()
    held_outside = [s for s in positions["symbol"] if s not in universe]
    open_count = len(positions)

    # Regime gate runs on the broad index; relative strength still measures against KMI-30.
    market = market_status(fetch_ohlcv(config.REGIME_INDEX, start, end))
    benchmark_return = benchmark_rolling_return(fetch_ohlcv(config.MARKET_INDEX, start, end))

    rows, warnings, snapshots = [], [], []

    for symbol in [*universe, *held_outside]:
        df = fetch_ohlcv(symbol, start, end)
        snap = snapshot(
            df,
            benchmark_return,
            fundamentals.get(symbol),
        ) if not df.empty else None
        if snap is None:
            rows.append({"symbol": symbol, "status": "NO DATA", "reasons": ["No usable price history from PSX"]})
            continue

        row = {"symbol": symbol, **snap, "stale": (end - snap["date"]).days > STALE_AFTER_DAYS}

        row.update(status="RANKED", reasons=[])
        snapshots.append({"symbol": symbol, **snap})
        rows.append(row)

    ranked = scoring.rank_snapshots(snapshots, config.PORTFOLIO_SIZE)
    ranked_symbols = {row["symbol"] for row in ranked}
    bullish = bool(market and market["uptrend"])
    # The ranking remains visible in bearish regimes as a watchlist. The regime
    # gate controls new BUY execution, not visibility of the strongest stocks.
    portfolio = ranked
    for row in rows:
        scored = next((item for item in ranked if item["symbol"] == row["symbol"]), None)
        if scored:
            row.update({key: scored[key] for key in (
                "value_score", "income_score", "momentum_score", "composite_score"
            )})
        row["status"] = "TOP 10" if bullish and row["symbol"] in ranked_symbols else "RANKED"

    return {
        "signals": [],
        "rows": portfolio,
        "all_rows": rows,
        "market": market,
        "warnings": warnings,
        "watchlist": [],
        "portfolio": portfolio,
    }


def run_once() -> None:
    result = run_scan()
    dashboard.publish(dashboard.build_payload(result, state.load_log()))
    asyncio.run(send_digest(result))
    if datetime.now(config.TIMEZONE).weekday() == 4:
        asyncio.run(notifier.send_portfolio_alert(result))
    webhook.notify(result)


def run_scheduled() -> None:
    scheduler = BlockingScheduler(timezone=config.TIMEZONE)
    scheduler.add_job(
        run_once,
        CronTrigger(
            hour=config.EOD_CRON_HOUR,
            minute=config.EOD_CRON_MINUTE,
            timezone=config.TIMEZONE,
        ),
    )
    scheduler.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="PSX EOD swing trading scanner")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan immediately and exit (for Windows Task Scheduler)",
    )
    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        run_scheduled()


if __name__ == "__main__":
    main()
