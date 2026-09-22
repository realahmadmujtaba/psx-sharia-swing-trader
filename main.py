import argparse
import asyncio
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from alerts import dashboard, webhook
from alerts.email_alert import send_digest
from core import state
from core.signal_engine import (
    benchmark_rolling_return,
    delisting_advice,
    entry_failures,
    entry_setup,
    evaluate_exit,
    evaluate_symbol,
    market_status,
    snapshot,
)
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
    positions = state.open_positions()
    held_outside = [s for s in positions["symbol"] if s not in universe]
    open_count = len(positions)

    # Regime gate runs on the broad index; relative strength still measures against KMI-30.
    market = market_status(fetch_ohlcv(config.REGIME_INDEX, start, end))
    benchmark_return = benchmark_rolling_return(fetch_ohlcv(config.MARKET_INDEX, start, end))

    signals, rows, warnings, watchlist, candidates = [], [], [], [], []

    for symbol in [*universe, *held_outside]:
        df = fetch_ohlcv(symbol, start, end)
        snap = snapshot(df, benchmark_return) if not df.empty else None
        if snap is None:
            rows.append({"symbol": symbol, "status": "NO DATA", "reasons": ["No usable price history from PSX"]})
            continue

        row = {"symbol": symbol, **snap, "stale": (end - snap["date"]).days > STALE_AFTER_DAYS}

        open_position = state.get_open_position(symbol)
        if open_position is not None:
            exit_signal = evaluate_exit(open_position, df)
            row.update(
                entry_price=float(open_position["close_price"]),
                stop_loss=float(open_position["stop_loss"]),
                take_profit=float(open_position["take_profit"]),
                days_held=(snap["date"] - open_position["date"]).days,
            )
            if exit_signal is not None:
                _attach_purification(exit_signal, ratios)
                signals.append(exit_signal)
                state.append_signal(exit_signal)
                open_count -= 1
                row.update(status="SELL", reasons=[exit_signal["exit_reason"]])
            elif symbol in held_outside:
                warnings.append(delisting_advice(open_position, snap))
                row.update(status="HOLDING", reasons=[f"Left {config.UNIVERSE_INDEX}"])
            else:
                row.update(status="HOLDING", reasons=[])
            rows.append(row)
            continue

        if entry_setup(snap) is None:
            failures = entry_failures(snap)
            row.update(status="NO SIGNAL", reasons=failures)
            if len(failures) == 1:
                watchlist.append(_watch(row, failures[0]))
        else:
            candidates.append((row, df))
        rows.append(row)

    if market is None or not market["uptrend"]:
        if market is None:
            blocked = f"Market regime: {config.REGIME_INDEX} data unavailable"
        elif not market["above_ema"]:
            blocked = f"Market regime: {config.REGIME_INDEX} below its {config.REGIME_EMA_PERIOD}-day EMA"
        else:
            blocked = f"Market regime: {config.REGIME_INDEX} {config.REGIME_EMA_PERIOD}-day EMA not rising"
        for row, _ in candidates:
            row.update(status="NO SIGNAL", reasons=[blocked])
            watchlist.append(_watch(row, blocked))
    else:
        candidates.sort(key=lambda item: item[0]["volume_ratio"], reverse=True)
        free_slots = max(config.MAX_OPEN_POSITIONS - open_count, 0)
        for rank, (row, df) in enumerate(candidates):
            if rank >= free_slots:
                full = f"Max {config.MAX_OPEN_POSITIONS} open positions reached"
                row.update(status="NO SIGNAL", reasons=[full])
                watchlist.append(_watch(row, full))
                continue
            entry_signal = evaluate_symbol(row["symbol"], df, benchmark_return)
            _attach_purification(entry_signal, ratios)
            signals.append(entry_signal)
            state.append_signal(entry_signal)
            row.update(status="BUY", reasons=[], setup=entry_signal["setup"],
                       stop_loss=entry_signal["stop_loss"], take_profit=entry_signal["take_profit"])

    return {"signals": signals, "rows": rows, "market": market, "warnings": warnings, "watchlist": watchlist}


def run_once() -> None:
    result = run_scan()
    dashboard.publish(dashboard.build_payload(result, state.load_log()))
    asyncio.run(send_digest(result))
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
