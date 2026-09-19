import argparse
import asyncio
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from alerts import dashboard
from alerts.email_alert import send_digest
from core import state
from core.signal_engine import entry_failures, evaluate_exit, evaluate_symbol, snapshot
from fetchers.psx_fetcher import fetch_ohlcv
from fetchers.universe import get_universe

HISTORY_DAYS = 400
# Weekend plus a public holiday; anything older means PSX stopped reporting the symbol.
STALE_AFTER_DAYS = 4


def run_scan() -> tuple[list[dict], list[dict]]:
    end = datetime.now(config.TIMEZONE).date()
    start = end - timedelta(days=HISTORY_DAYS)

    log_df = state.load_log()
    signals = []
    rows = []

    for symbol in get_universe():
        df = fetch_ohlcv(symbol, start, end)
        snap = snapshot(df) if not df.empty else None
        if snap is None:
            rows.append({"symbol": symbol, "status": "NO DATA", "reasons": ["No usable price history from PSX"]})
            continue

        row = {"symbol": symbol, **snap, "stale": (end - snap["date"]).days > STALE_AFTER_DAYS}

        open_position = state.get_open_position(log_df, symbol)
        if open_position is not None:
            exit_signal = evaluate_exit(open_position, df)
            row.update(
                entry_price=float(open_position["close_price"]),
                stop_loss=float(open_position["stop_loss"]),
                take_profit=float(open_position["take_profit"]),
                days_held=(snap["date"] - open_position["date"]).days,
            )
            if exit_signal is not None:
                signals.append(exit_signal)
                state.append_signal(exit_signal)
                row.update(status="SELL", reasons=[exit_signal["exit_reason"]])
            else:
                row.update(status="HOLDING", reasons=[])
            rows.append(row)
            continue

        entry_signal = evaluate_symbol(symbol, df)
        if entry_signal is not None:
            signals.append(entry_signal)
            state.append_signal(entry_signal)
            row.update(
                status="BUY",
                reasons=[],
                stop_loss=entry_signal["stop_loss"],
                take_profit=entry_signal["take_profit"],
            )
        else:
            row.update(status="NO SIGNAL", reasons=entry_failures(snap))
        rows.append(row)

    return signals, rows


def run_once() -> None:
    signals, rows = run_scan()
    dashboard.publish(dashboard.build_payload(rows, signals, state.load_log()))
    asyncio.run(send_digest(signals))


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
