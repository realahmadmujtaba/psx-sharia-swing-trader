import sqlite3
from contextlib import contextmanager
from datetime import date

import pandas as pd

import config

DB_PATH = config.DATA_DIR / "signals.db"
CSV_EXPORT_PATH = config.DATA_DIR / "signals_log.csv"

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL,
    symbol       TEXT    NOT NULL,
    signal_type  TEXT    NOT NULL CHECK (signal_type IN ('BUY', 'SELL')),
    close_price  REAL    NOT NULL,
    stop_loss    REAL,
    take_profit  REAL,
    exit_reason  TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS signals_symbol_date ON signals (symbol, date);

-- One row per position; `status` is what makes the 15-day hold survive across runs.
CREATE TABLE IF NOT EXISTS positions (
    symbol       TEXT    NOT NULL,
    entry_date   TEXT    NOT NULL,
    entry_price  REAL    NOT NULL,
    stop_loss    REAL    NOT NULL,
    take_profit  REAL    NOT NULL,
    -- Which setup opened it: the exit rules differ per setup.
    setup        TEXT    NOT NULL DEFAULT 'MEAN_REVERSION',
    status       TEXT    NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    exit_date    TEXT,
    exit_price   REAL,
    exit_reason  TEXT,
    PRIMARY KEY (symbol, entry_date)
);
CREATE INDEX IF NOT EXISTS positions_status ON positions (status);
"""


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(positions)")}
        if "setup" not in columns:
            conn.execute("ALTER TABLE positions ADD COLUMN setup TEXT NOT NULL DEFAULT 'MEAN_REVERSION'")
        if not conn.execute("SELECT 1 FROM signals LIMIT 1").fetchone():
            _import_legacy_csv(conn)


def _import_legacy_csv(conn: sqlite3.Connection) -> None:
    """Carry over the pre-SQLite CSV log the first time the database is built."""
    if not CSV_EXPORT_PATH.exists():
        return
    legacy = pd.read_csv(CSV_EXPORT_PATH)
    for _, row in legacy.iterrows():
        record_signal({
            "date": pd.Timestamp(row["date"]).date(),
            "symbol": row["symbol"],
            "signal_type": row["signal_type"],
            "close_price": float(row["close_price"]),
            "stop_loss": float(row["stop_loss"]),
            "take_profit": float(row["take_profit"]),
            "exit_reason": row.get("exit_reason") or "",
        }, conn=conn)


def record_signal(signal: dict, conn: sqlite3.Connection | None = None) -> None:
    """Append to history and open or close the matching position."""
    if conn is None:
        with connect() as owned:
            return record_signal(signal, conn=owned)

    signal_date = str(signal["date"] if "date" in signal else signal["timestamp"].date())
    conn.execute(
        "INSERT INTO signals (date, symbol, signal_type, close_price, stop_loss, take_profit, exit_reason)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (signal_date, signal["symbol"], signal["signal_type"], signal["close_price"],
         signal.get("stop_loss"), signal.get("take_profit"), signal.get("exit_reason") or ""),
    )

    if signal["signal_type"] == "BUY":
        conn.execute(
            "INSERT OR REPLACE INTO positions"
            " (symbol, entry_date, entry_price, stop_loss, take_profit, setup, status)"
            " VALUES (?, ?, ?, ?, ?, ?, 'OPEN')",
            (signal["symbol"], signal_date, signal["close_price"],
             signal["stop_loss"], signal["take_profit"], signal.get("setup", "MEAN_REVERSION")),
        )
    else:
        conn.execute(
            "UPDATE positions SET status = 'CLOSED', exit_date = ?, exit_price = ?, exit_reason = ?"
            " WHERE symbol = ? AND status = 'OPEN'",
            (signal_date, signal["close_price"], signal.get("exit_reason") or "", signal["symbol"]),
        )


def open_positions() -> pd.DataFrame:
    with connect() as conn:
        rows = conn.execute(
            "SELECT symbol, entry_date, entry_price, stop_loss, take_profit, setup FROM positions"
            " WHERE status = 'OPEN' ORDER BY entry_date"
        ).fetchall()
    df = pd.DataFrame([dict(row) for row in rows])
    if df.empty:
        return pd.DataFrame(columns=["symbol", "entry_date", "entry_price", "stop_loss",
                                     "take_profit", "setup"])
    df["entry_date"] = pd.to_datetime(df["entry_date"]).dt.date
    return df


def open_position(symbol: str) -> dict | None:
    df = open_positions()
    match = df[df["symbol"] == symbol] if not df.empty else df
    return None if match.empty else match.iloc[-1].to_dict()


def history() -> pd.DataFrame:
    with connect() as conn:
        rows = conn.execute(
            "SELECT date, symbol, signal_type, close_price, stop_loss, take_profit, exit_reason"
            " FROM signals ORDER BY date, id"
        ).fetchall()
    df = pd.DataFrame([dict(row) for row in rows])
    if df.empty:
        return pd.DataFrame(columns=["date", "symbol", "signal_type", "close_price",
                                     "stop_loss", "take_profit", "exit_reason"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def export_csv() -> None:
    """Human-readable mirror of the history, committed alongside the database."""
    df = history()
    if not df.empty:
        df.to_csv(CSV_EXPORT_PATH, index=False)


if __name__ == "__main__":
    init_db()
    print(f"Initialised {DB_PATH}: {len(history())} signals, {len(open_positions())} open positions")
