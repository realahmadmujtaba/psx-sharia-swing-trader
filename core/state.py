"""Position and signal state, backed by SQLite (see core/db.py).

Positions are exposed in the shape the signal engine expects: `date` is the entry
date and `close_price` the entry price.
"""
import pandas as pd

from core import db

POSITION_COLUMNS = ["symbol", "date", "close_price", "stop_loss", "take_profit", "setup"]


def _as_position(row: dict) -> pd.Series:
    return pd.Series({
        "symbol": row["symbol"],
        "date": row["entry_date"],
        "close_price": float(row["entry_price"]),
        "stop_loss": float(row["stop_loss"]),
        "take_profit": float(row["take_profit"]),
        "setup": row.get("setup") or "MEAN_REVERSION",
    })


def load_log() -> pd.DataFrame:
    db.init_db()
    return db.history()


def open_positions() -> pd.DataFrame:
    db.init_db()
    rows = db.open_positions()
    if rows.empty:
        return pd.DataFrame(columns=POSITION_COLUMNS)
    return pd.DataFrame([_as_position(row) for _, row in rows.iterrows()])


def get_open_position(symbol: str) -> pd.Series | None:
    db.init_db()
    row = db.open_position(symbol)
    return None if row is None else _as_position(row)


def append_signal(signal: dict) -> None:
    db.init_db()
    db.record_signal(signal)
    db.export_csv()
