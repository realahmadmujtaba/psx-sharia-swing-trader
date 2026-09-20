from datetime import datetime

import pandas as pd

import config
from core import indicators, risk

MIN_HISTORY_ROWS = config.EMA_PERIOD + 1
OVERBOUGHT_RSI = 70


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date")
    df = df[~df["is_anomaly"]].drop_duplicates("date", keep="last")
    return df.reset_index(drop=True)


def snapshot(df: pd.DataFrame) -> dict | None:
    df = _clean(df)
    if len(df) < max(MIN_HISTORY_ROWS, config.SUPPORT_LOOKBACK + 1):
        return None

    close = df["close"]
    volume = df["volume"].astype(float)
    ema_50 = indicators.ema(close, config.EMA_PERIOD).iloc[-1]
    rsi_14 = indicators.rsi(close, config.RSI_PERIOD).iloc[-1]
    avg_vol_20 = indicators.avg_volume(volume, config.VOLUME_LOOKBACK).iloc[-1]
    atr_14 = indicators.atr(df["high"], df["low"], close, config.ATR_PERIOD).iloc[-1]
    if pd.isna(ema_50) or pd.isna(rsi_14) or pd.isna(avg_vol_20) or pd.isna(atr_14):
        return None

    last_close = float(close.iloc[-1])
    prior_avg_volume = volume.iloc[-config.VOLUME_LOOKBACK - 1 : -1].mean()
    support_low = float(df["low"].iloc[-config.SUPPORT_LOOKBACK - 1 : -1].min())
    near_ema = last_close / ema_50 - 1 <= config.SUPPORT_PROXIMITY_PCT
    near_low = last_close / support_low - 1 <= config.SUPPORT_PROXIMITY_PCT

    return {
        "date": pd.Timestamp(df["date"].iloc[-1]).date(),
        "close": last_close,
        "ema_50": float(ema_50),
        "rsi": float(rsi_14),
        "avg_volume": float(avg_vol_20),
        "volume_ratio": float(volume.iloc[-1] / prior_avg_volume) if prior_avg_volume else 0.0,
        "atr": float(atr_14),
        "support_low": support_low,
        "near_support": bool(near_ema or near_low),
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
    if config.STRICT_ENTRY:
        if snap["volume_ratio"] < config.VOLUME_SPIKE_MULT:
            failures.append("No volume spike")
        if not snap["near_support"]:
            failures.append("Not near support")
    return failures


def market_status(index_df: pd.DataFrame) -> dict | None:
    df = _clean(index_df)
    if len(df) < MIN_HISTORY_ROWS:
        return None
    ema_50 = float(indicators.ema(df["close"], config.EMA_PERIOD).iloc[-1])
    close = float(df["close"].iloc[-1])
    return {
        "index": config.MARKET_INDEX,
        "date": pd.Timestamp(df["date"].iloc[-1]).date(),
        "close": close,
        "ema_50": ema_50,
        "uptrend": close > ema_50,
    }


def evaluate_symbol(symbol: str, df: pd.DataFrame) -> dict | None:
    snap = snapshot(df)
    if snap is None or entry_failures(snap):
        return None

    stop_loss, take_profit = risk.calculate_risk_levels(snap["close"], snap["atr"])
    shares = risk.position_size(snap["close"])

    return {
        "symbol": symbol,
        "signal_type": "BUY",
        "close_price": snap["close"],
        "rsi": snap["rsi"],
        "ema_50": snap["ema_50"],
        "avg_volume": snap["avg_volume"],
        "volume_ratio": snap["volume_ratio"],
        "support_low": snap["support_low"],
        "atr": snap["atr"],
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "shares": shares,
        "timestamp": datetime.now(config.TIMEZONE),
    }


def evaluate_exit(position: pd.Series, df: pd.DataFrame) -> dict | None:
    df = _clean(df)
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

    entry_price = float(position["close_price"])
    # Recomputed rather than stored, so the public signal log never reveals capital.
    shares = risk.position_size(entry_price)

    return {
        "symbol": position["symbol"],
        "signal_type": "SELL",
        "close_price": latest_close,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "exit_reason": exit_reason,
        "days_held": days_held,
        "shares": shares,
        "pnl_per_share": latest_close - entry_price,
        "timestamp": datetime.now(config.TIMEZONE),
    }


def delisting_advice(position: pd.Series, snap: dict) -> dict:
    entry_price = float(position["close_price"])
    days_held = (snap["date"] - position["date"]).days

    if snap["close"] < snap["ema_50"]:
        recommendation, reason = "SELL", "Trend is broken: price is below its 50-day EMA."
    elif snap["close"] < entry_price:
        recommendation, reason = "SELL", "Position is in loss and the stock is no longer Sharia-screened."
    elif snap["rsi"] > OVERBOUGHT_RSI:
        recommendation, reason = "SELL", f"Overbought (RSI above {OVERBOUGHT_RSI}): a good point to lock in profit."
    else:
        recommendation, reason = "HOLD", (
            "Trend is still up and the position is in profit; holding a few more days until "
            "stop-loss, take-profit or the max holding period is reasonable."
        )

    if days_held < config.MIN_HOLDING_DAYS:
        reason += f" Shares cannot be sold before day {config.MIN_HOLDING_DAYS} (settlement)."

    return {
        "symbol": position["symbol"],
        "recommendation": recommendation,
        "reason": reason,
        "close_price": snap["close"],
        "entry_price": entry_price,
        "days_held": days_held,
    }
