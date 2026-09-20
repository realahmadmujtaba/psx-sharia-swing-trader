import argparse
import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import config
from core import indicators
from fetchers.psx_fetcher import fetch_ohlcv
from fetchers.universe import get_universe

RESULT_PATH = config.DOCS_DIR / "backtest.json"
VARIANTS = ("strict", "relaxed")


def _prepare(df: pd.DataFrame) -> pd.DataFrame | None:
    df = df.sort_values("date")
    df = df[~df["is_anomaly"]].drop_duplicates("date", keep="last").reset_index(drop=True)
    if len(df) < config.EMA_PERIOD + config.SUPPORT_LOOKBACK:
        return None

    volume = df["volume"].astype(float)
    df["ema_50"] = indicators.ema(df["close"], config.EMA_PERIOD)
    df["rsi"] = indicators.rsi(df["close"], config.RSI_PERIOD)
    df["atr"] = indicators.atr(df["high"], df["low"], df["close"], config.ATR_PERIOD)
    df["avg_volume"] = indicators.avg_volume(volume, config.VOLUME_LOOKBACK)
    df["volume_ratio"] = volume / volume.shift(1).rolling(config.VOLUME_LOOKBACK).mean()
    df["support_low"] = df["low"].shift(1).rolling(config.SUPPORT_LOOKBACK).min()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.set_index("date")


def _qualifies(row: pd.Series, variant: str) -> bool:
    if row[["ema_50", "rsi", "atr", "avg_volume", "volume_ratio", "support_low"]].isna().any():
        return False
    if not (row["close"] > row["ema_50"]):
        return False
    if not (config.RSI_LOWER <= row["rsi"] <= config.RSI_UPPER):
        return False
    if not (row["avg_volume"] > config.MIN_AVG_VOLUME):
        return False
    if variant == "relaxed":
        return True
    near_support = (row["close"] / row["ema_50"] - 1 <= config.SUPPORT_PROXIMITY_PCT
                    or row["close"] / row["support_low"] - 1 <= config.SUPPORT_PROXIMITY_PCT)
    return row["volume_ratio"] >= config.VOLUME_SPIKE_MULT and near_support


def _metrics(trades: list[dict], equity_curve: list[dict], start_equity: float, years: float) -> dict:
    if not trades:
        return {"trades": 0, "trades_per_year": 0.0, "win_rate": None, "total_return_pct": 0.0,
                "avg_return_pct": None, "avg_win_pct": None, "avg_loss_pct": None,
                "profit_factor": None, "max_drawdown_pct": 0.0, "avg_days_held": None}

    returns = np.array([t["return_pct"] for t in trades])
    wins, losses = returns[returns > 0], returns[returns <= 0]
    equity = np.array([point["equity"] for point in equity_curve])
    drawdown = (equity - np.maximum.accumulate(equity)) / np.maximum.accumulate(equity)
    gross_win = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = -sum(t["pnl"] for t in trades if t["pnl"] <= 0)

    return {
        "trades": len(trades),
        "trades_per_year": round(len(trades) / years, 1),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "total_return_pct": round((equity[-1] / start_equity - 1) * 100, 2),
        "avg_return_pct": round(float(returns.mean()), 2),
        "avg_win_pct": round(float(wins.mean()), 2) if len(wins) else None,
        "avg_loss_pct": round(float(losses.mean()), 2) if len(losses) else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "max_drawdown_pct": round(float(drawdown.min()) * 100, 2),
        "avg_days_held": round(float(np.mean([t["days_held"] for t in trades])), 1),
    }


def run(history: dict[str, pd.DataFrame], market: pd.DataFrame, variant: str,
        start_equity: float = 1_000_000.0) -> dict:
    dates = sorted({d for df in history.values() for d in df.index})
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []
    equity = start_equity
    equity_curve = [{"date": str(dates[0]), "equity": equity}] if dates else []

    for today in dates:
        for symbol in list(open_positions):
            position = open_positions[symbol]
            row = history[symbol].loc[today] if today in history[symbol].index else None
            if row is None:
                continue
            days_held = (today - position["entry_date"]).days
            if days_held < config.MIN_HOLDING_DAYS:
                continue

            close = float(row["close"])
            if close <= position["stop_loss"]:
                reason = "STOP_LOSS"
            elif close >= position["take_profit"]:
                reason = "TAKE_PROFIT"
            elif days_held >= config.MAX_HOLDING_DAYS:
                reason = "MAX_HOLD"
            else:
                continue

            cost = position["shares"] * position["entry_price"]
            proceeds = position["shares"] * close
            fees = (cost + proceeds) * config.COMMISSION_PCT
            pnl = proceeds - cost - fees
            equity += pnl
            trades.append({
                "symbol": symbol, "entry_date": str(position["entry_date"]), "exit_date": str(today),
                "entry_price": round(position["entry_price"], 2), "exit_price": round(close, 2),
                "days_held": days_held, "exit_reason": reason, "pnl": round(pnl, 2),
                "return_pct": round(pnl / cost * 100, 2),
            })
            equity_curve.append({"date": str(today), "equity": round(equity, 2)})
            del open_positions[symbol]

        if today not in market.index or not bool(market.loc[today, "uptrend"]):
            continue

        free_slots = config.MAX_OPEN_POSITIONS - len(open_positions)
        if free_slots <= 0:
            continue

        candidates = []
        for symbol, df in history.items():
            if symbol in open_positions or today not in df.index:
                continue
            row = df.loc[today]
            if _qualifies(row, variant):
                candidates.append((float(row["volume_ratio"]), symbol, row))

        candidates.sort(key=lambda item: item[0], reverse=True)
        for _, symbol, row in candidates[:free_slots]:
            close, atr_value = float(row["close"]), float(row["atr"])
            shares = int(equity * config.POSITION_PCT // close)
            if shares <= 0:
                continue
            open_positions[symbol] = {
                "entry_date": today,
                "entry_price": close,
                "shares": shares,
                "stop_loss": close - config.ATR_STOP_MULT * atr_value,
                "take_profit": close + config.ATR_TARGET_MULT * atr_value,
            }

    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9) if dates else 1
    return {
        "variant": variant,
        "from": str(dates[0]) if dates else None,
        "to": str(dates[-1]) if dates else None,
        "metrics": _metrics(trades, equity_curve, start_equity, years),
        "equity_curve": equity_curve,
        "trades": trades,
    }


def load_history(years: int) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    end = datetime.now(config.TIMEZONE).date()
    start = end - timedelta(days=round(years * 365.25) + config.EMA_PERIOD * 2)

    market = _prepare(fetch_ohlcv(config.MARKET_INDEX, start, end))
    if market is None:
        raise RuntimeError(f"No usable history for the {config.MARKET_INDEX} index")
    market["uptrend"] = market["close"] > market["ema_50"]

    history = {}
    for symbol in get_universe():
        prepared = _prepare(fetch_ohlcv(symbol, start, end))
        if prepared is not None:
            history[symbol] = prepared
    return history, market


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the swing rules over past PSX data")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--save", action="store_true", help="Write docs/backtest.json for the dashboard")
    args = parser.parse_args()

    history, market = load_history(args.years)
    results = {variant: run(history, market, variant) for variant in VARIANTS}

    for variant, result in results.items():
        m = result["metrics"]
        print(f"\n=== {variant.upper()}  {result['from']} to {result['to']} ===")
        print(f"  trades {m['trades']} ({m['trades_per_year']}/yr)   win rate {m['win_rate']}%   "
              f"avg {m['avg_return_pct']}%   held {m['avg_days_held']}d")
        print(f"  total return {m['total_return_pct']}%   max drawdown {m['max_drawdown_pct']}%   "
              f"profit factor {m['profit_factor']}")

    if args.save:
        strict = results["strict"]["metrics"]["trades_per_year"]
        payload = {
            "generated_at": datetime.now(config.TIMEZONE).isoformat(timespec="minutes"),
            "years": args.years,
            "universe": config.UNIVERSE_INDEX,
            "commission_pct": config.COMMISSION_PCT,
            "start_equity": 1_000_000.0,
            "active_variant": "relaxed" if strict < config.MIN_TRADES_PER_YEAR else "strict",
            "results": results,
            "caveats": [
                "Uses today's KMI-30 members over the whole period (survivorship bias).",
                f"Assumes {config.COMMISSION_PCT * 100:.2f}% brokerage per side, no slippage or taxes.",
                "Entries and exits use closing prices; a real fill may differ.",
                "Past results do not guarantee future results.",
            ],
        }
        RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {RESULT_PATH}")


if __name__ == "__main__":
    main()
