from datetime import datetime

import pandas as pd

import config
from core import indicators, risk

MIN_HISTORY_ROWS = config.MACRO_EMA_PERIOD + 1
OVERBOUGHT_RSI = 70


def _weekly(df: pd.DataFrame) -> pd.DataFrame:
    indexed = df.copy()
    indexed["date"] = pd.to_datetime(indexed["date"])
    indexed = indexed.set_index("date").sort_index()
    weekly = indexed.resample("W-FRI").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        is_anomaly=("is_anomaly", "all"),
    ).dropna(subset=["close"])
    weekly["date"] = weekly.index
    return weekly.reset_index(drop=True)


def _fundamental_status(fundamentals: dict | None, avg_volume: float, close: float) -> dict:
    if fundamentals is None:
        return {
            "pe": None,
            "dividend_yield": None,
            "fundamental_status": "PROXY",
            "value_pass": avg_volume > config.MIN_AVG_VOLUME and close > config.MIN_PRICE,
        }
    pe = fundamentals.get("pe")
    dividend_yield = fundamentals.get("dividend_yield")
    value_pass = (
        pe is not None and dividend_yield is not None
        and float(pe) < config.VALUE_MAX_PE
        and float(dividend_yield) > config.VALUE_MIN_DIVIDEND_YIELD
    )
    return {
        "pe": None if pe is None else float(pe),
        "dividend_yield": None if dividend_yield is None else float(dividend_yield),
        "fundamental_status": "LIVE",
        "value_pass": value_pass,
    }


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date")
    df = df[~df["is_anomaly"]].drop_duplicates("date", keep="last")
    return df.reset_index(drop=True)


def snapshot(
    df: pd.DataFrame,
    benchmark_return: float | None = None,
    fundamentals: dict | None = None,
) -> dict | None:
    df = _clean(df)
    weekly = _weekly(df)
    if len(weekly) < config.RSI_PERIOD + 1:
        return None

    close, high, low = weekly["close"], weekly["high"], weekly["low"]
    volume = df["volume"].astype(float)
    daily_close = df["close"]
    daily_ema_50 = indicators.ema(daily_close, config.EMA_PERIOD).iloc[-1]
    daily_ema_200 = indicators.ema(daily_close, 200).iloc[-1]
    open_price = weekly["open"]
    ema_20 = indicators.ema(close, config.WEEKLY_EMA_PERIOD)
    rsi_14 = indicators.rsi(close, config.RSI_PERIOD)
    atr_14 = indicators.atr(high, low, close, config.ATR_PERIOD)
    avg_vol_20 = indicators.avg_volume(volume, config.VOLUME_LOOKBACK)
    ema_100 = indicators.ema(close, config.MACRO_EMA_PERIOD)
    last_close = float(close.iloc[-1])
    roc_12w = indicators.rolling_return(close, 12).iloc[-1]
    value = _fundamental_status(fundamentals, float(avg_vol_20.iloc[-1]), last_close)
    prior_volume = volume.iloc[-config.VOLUME_LOOKBACK - 1:-1].mean()
    daily_ema_9 = indicators.ema(daily_close, 9)
    daily_ema_20 = indicators.ema(daily_close, config.TRAIL_EMA_PERIOD)
    daily_rsi = indicators.rsi(daily_close, config.RSI_PERIOD)
    ema_cross = bool(
        len(daily_close) > 1
        and daily_ema_9.iloc[-2] <= daily_ema_20.iloc[-2]
        and daily_ema_9.iloc[-1] > daily_ema_20.iloc[-1]
    )
    rsi_breakout = bool(
        len(daily_rsi) > 1
        and daily_rsi.iloc[-1] > 50
        and daily_rsi.iloc[-2] <= 50
        and daily_rsi.iloc[-6:-1].between(40, 55).all()
    )
    technical_score = 50.0 + (30.0 if ema_cross else 0.0) + (20.0 if rsi_breakout else 0.0)
    latest_high = float(df["high"].iloc[-1])
    latest_low = float(df["low"].iloc[-1])
    range_size = latest_high - latest_low
    retail_trap = bool(
        prior_volume > 0
        and float(volume.iloc[-1]) > prior_volume * 3
        and range_size > 0
        and (last_close - latest_low) / range_size <= 0.25
    )
    required = [ema_20.iloc[-1], rsi_14.iloc[-1], atr_14.iloc[-1], avg_vol_20.iloc[-1], roc_12w]
    if any(pd.isna(value) for value in required):
        return None

    return {
        "date": pd.Timestamp(weekly["date"].iloc[-1]).date(),
        "close": last_close,
        "open": float(open_price.iloc[-1]),
        "bullish": bool(last_close > float(open_price.iloc[-1])),
        "ema_20": float(ema_20.iloc[-1]),
        "ema_50": float(daily_ema_50),
        "ema_200": float(daily_ema_200),
        "ema_100": float(ema_100.iloc[-1]),
        "rsi": float(rsi_14.iloc[-1]),
        "avg_volume": float(avg_vol_20.iloc[-1]),
        "volume": float(volume.iloc[-1]),
        "volume_ratio": float(volume.iloc[-1] / prior_volume) if prior_volume else 0.0,
        "near_support": bool(
            min(abs(last_close / daily_ema_50 - 1), abs(last_close / daily_ema_200 - 1))
            <= config.SUPPORT_PROXIMITY_PCT
        ),
        "atr": float(atr_14.iloc[-1]),
        "atr_pct": float(atr_14.iloc[-1]) / last_close,
        "weekly_trend": bool(last_close > ema_20.iloc[-1] and rsi_14.iloc[-1] > config.WEEKLY_RSI_MIN),
        "roc_12w": float(roc_12w),
        "benchmark_return_20d": benchmark_return,
        "ema_9": float(daily_ema_9.iloc[-1]),
        "daily_ema_20": float(daily_ema_20.iloc[-1]),
        "daily_rsi": float(daily_rsi.iloc[-1]),
        "ema_9_20_cross": ema_cross,
        "rsi_breakout": rsi_breakout,
        "technical_score": technical_score,
        "retail_trap": retail_trap,
        "conviction_score": technical_score * (0.5 if retail_trap else 1.0),
        **value,
    }


def benchmark_rolling_return(index_df: pd.DataFrame) -> float | None:
    df = _clean(index_df)
    if len(df) <= config.RS_LOOKBACK:
        return None
    value = indicators.rolling_return(df["close"], config.RS_LOOKBACK).iloc[-1]
    return None if pd.isna(value) else float(value)


def market_status(index_df: pd.DataFrame) -> dict | None:
    """Regime gate: is the broad market trending up enough to take new entries?"""
    df = _clean(index_df)
    if len(df) < config.REGIME_EMA_PERIOD + 1:
        return None

    ema = indicators.ema(df["close"], config.REGIME_EMA_PERIOD)
    ema_now = float(ema.iloc[-1])
    close = float(df["close"].iloc[-1])
    above_ema = close > ema_now

    return {
        "index": config.REGIME_INDEX,
        "date": pd.Timestamp(df["date"].iloc[-1]).date(),
        "close": close,
        "ema_100": ema_now,
        "above_ema": above_ema,
        "uptrend": above_ema,
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

    setup = position.get("setup") or "MEAN_REVERSION"
    close = df["close"]
    ema_20 = indicators.ema(close, config.TRAIL_EMA_PERIOD).iloc[-1]
    stop_loss = float(position["stop_loss"])
    take_profit = float(position["take_profit"])

    if latest_close < stop_loss:
        exit_reason = "STOP_LOSS"
    elif latest_close >= take_profit:
        exit_reason = "ATR_TARGET"
    elif not pd.isna(ema_20) and latest_close > float(ema_20):
        exit_reason = "MEAN_REVERT"
    else:
        return None

    entry_price = float(position["close_price"])
    # Recomputed rather than stored, so the public signal log never reveals capital.
    shares = risk.position_size(entry_price)

    return {
        "symbol": position["symbol"],
        "signal_type": "SELL",
        "setup": setup,
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
