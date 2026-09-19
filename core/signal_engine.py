from datetime import datetime

import pandas as pd

import config
from core import indicators, risk

MIN_HISTORY_ROWS = config.EMA_PERIOD + 1


def snapshot(df: pd.DataFrame) -> dict | None:
    df = df.sort_values("date").reset_index(drop=True)
    df = df[~df["is_anomaly"]].reset_index(drop=True)

    if len(df) < MIN_HISTORY_ROWS:
        return None

    ema_50 = indicators.ema(df["close"], config.EMA_PERIOD).iloc[-1]
    rsi_14 = indicators.rsi(df["close"], config.RSI_PERIOD).iloc[-1]
    avg_vol_20 = indicators.avg_volume(df["volume"].astype(float), config.VOLUME_LOOKBACK).iloc[-1]
    if pd.isna(ema_50) or pd.isna(rsi_14) or pd.isna(avg_vol_20):
        return None

    return {
        "date": pd.Timestamp(df["date"].iloc[-1]).date(),
        "close": float(df["close"].iloc[-1]),
        "ema_50": float(ema_50),
        "rsi": float(rsi_14),
        "avg_volume": float(avg_vol_20),
    }


def entry_failures(snap: dict) -> list[str]:
    failures = []
    if not snap["close"] > snap["ema_50"]:
        failures.append("Below 50-day EMA")
    if snap["rsi"] > config.RSI_UPPER:
        failures.append("RSI too high")
    elif snap["rsi"] < config.RSI_LOWER:
        failures.append("RSI too low")
    if not snap["avg_volume"] > config.MIN_AVG_VOLUME:
        failures.append("Low volume")
    return failures


def evaluate_symbol(symbol: str, df: pd.DataFrame) -> dict | None:
    snap = snapshot(df)
    if snap is None or entry_failures(snap):
        return None

    stop_loss, take_profit = risk.calculate_risk_levels(snap["close"])

    return {
        "symbol": symbol,
        "signal_type": "BUY",
        "close_price": snap["close"],
        "rsi": snap["rsi"],
        "ema_50": snap["ema_50"],
        "avg_volume": snap["avg_volume"],
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "timestamp": datetime.now(config.TIMEZONE),
    }


def evaluate_exit(position: pd.Series, df: pd.DataFrame) -> dict | None:
    df = df.sort_values("date").reset_index(drop=True)
    df = df[~df["is_anomaly"]].reset_index(drop=True)
    if df.empty:
        return None

    latest = df.iloc[-1]
    latest_close = float(latest["close"])
    latest_date = pd.Timestamp(latest["date"]).date()
    days_held = (latest_date - position["date"]).days
    if days_held < config.MIN_HOLDING_DAYS:
        return None

    stop_loss = float(position["stop_loss"])
    take_profit = float(position["take_profit"])

    if latest_close <= stop_loss:
        exit_reason = "STOP_LOSS"
    elif latest_close >= take_profit:
        exit_reason = "TAKE_PROFIT"
    elif days_held >= config.MAX_HOLDING_DAYS:
        exit_reason = "MAX_HOLD"
    else:
        return None

    return {
        "symbol": position["symbol"],
        "signal_type": "SELL",
        "close_price": latest_close,
        "entry_price": float(position["close_price"]),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "exit_reason": exit_reason,
        "days_held": days_held,
        "timestamp": datetime.now(config.TIMEZONE),
    }
