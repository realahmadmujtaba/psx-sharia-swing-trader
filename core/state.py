from pathlib import Path

import pandas as pd

LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "signals_log.csv"
LOG_COLUMNS = ["date", "symbol", "signal_type", "close_price", "stop_loss", "take_profit", "exit_reason"]


def load_log() -> pd.DataFrame:
    if not LOG_PATH.exists():
        return pd.DataFrame(columns=LOG_COLUMNS)
    log_df = pd.read_csv(LOG_PATH, parse_dates=["date"])
    log_df["date"] = log_df["date"].dt.date
    log_df["exit_reason"] = log_df["exit_reason"].fillna("")
    return log_df


def get_open_position(log_df: pd.DataFrame, symbol: str) -> pd.Series | None:
    if log_df.empty:
        return None

    symbol_log = log_df[log_df["symbol"] == symbol].sort_values("date")
    if symbol_log.empty:
        return None

    last_row = symbol_log.iloc[-1]
    return last_row if last_row["signal_type"] == "BUY" else None


def append_signal(signal: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame(
        [
            {
                "date": signal["timestamp"].date(),
                "symbol": signal["symbol"],
                "signal_type": signal["signal_type"],
                "close_price": signal["close_price"],
                "stop_loss": signal["stop_loss"],
                "take_profit": signal["take_profit"],
                "exit_reason": signal.get("exit_reason", ""),
            }
        ]
    )
    header = not LOG_PATH.exists()
    row.to_csv(LOG_PATH, mode="a", header=header, index=False)
