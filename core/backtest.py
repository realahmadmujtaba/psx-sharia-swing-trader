import argparse
import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import config
from core import indicators, risk
from fetchers.psx_fetcher import fetch_ohlcv
from fetchers.universe import get_universe

RESULT_PATH = config.DOCS_DIR / "backtest.json"
CACHE_DIR = config.DATA_DIR / "history_cache"
# "both" is what runs live; the single-setup runs show which half carries the result.
VARIANTS = {
    "both": ("BREAKOUT", "PULLBACK"),
    "breakout": ("BREAKOUT",),
    "pullback": ("PULLBACK",),
}


def _prepare(df: pd.DataFrame, benchmark_return: pd.Series | None) -> pd.DataFrame | None:
    df = df.sort_values("date")
    df = df[~df["is_anomaly"]].drop_duplicates("date", keep="last").reset_index(drop=True)
    if len(df) < config.MACRO_EMA_PERIOD + config.RS_LOOKBACK:
        return None

    close, volume = df["close"], df["volume"].astype(float)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["ema_50"] = indicators.ema(close, config.EMA_PERIOD)
    df["ema_100"] = indicators.ema(close, config.MACRO_EMA_PERIOD)
    df["ema_trail"] = indicators.ema(close, config.TRAIL_EMA_PERIOD)
    df["adx"] = indicators.adx(df["high"], df["low"], close, config.ADX_PERIOD)
    df["rsi"] = indicators.rsi(close, config.RSI_PERIOD)
    df["atr"] = indicators.atr(df["high"], df["low"], close, config.ATR_PERIOD)
    df["return_20d"] = indicators.rolling_return(close, config.RS_LOOKBACK)
    df["avg_volume"] = indicators.avg_volume(volume, config.VOLUME_LOOKBACK)
    df["volume_ratio"] = volume / volume.shift(1).rolling(config.VOLUME_LOOKBACK).mean()
    df = df.set_index("date")

    gap = df["close"] / df["ema_50"] - 1
    baseline = ((df["avg_volume"] > config.MIN_AVG_VOLUME)
                & (df["close"] > config.MIN_PRICE)
                & (df["close"] > df["ema_100"]))

    breakout = baseline & (df["adx"] > config.ADX_MIN) & (df["volume_ratio"] >= config.VOLUME_SPIKE_MULT)
    if benchmark_return is not None:
        aligned = benchmark_return.reindex(df.index)
        breakout &= df["return_20d"] > aligned

    pullback = (baseline & (df["rsi"] < config.RSI_UPPER)
                & (gap >= 0) & (gap <= config.SUPPORT_PROXIMITY_PCT))

    df["setup"] = np.where(breakout.fillna(False), "BREAKOUT",
                           np.where(pullback.fillna(False), "PULLBACK", None))
    return df


def _metrics(trades: list[dict], equity_curve: list[dict], start_equity: float, years: float) -> dict:
    if not trades:
        return {"trades": 0, "trades_per_year": 0.0, "win_rate": None, "total_return_pct": 0.0,
                "avg_return_pct": None, "avg_win_pct": None, "avg_loss_pct": None,
                "profit_factor": None, "max_drawdown_pct": 0.0, "avg_days_held": None}

    returns = np.array([t["return_pct"] for t in trades])
    wins, losses = returns[returns > 0], returns[returns <= 0]
    equity = np.array([point["equity"] for point in equity_curve])
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
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
    allowed = VARIANTS[variant]
    # Pre-index everything the day loop needs, so it never touches pandas lookups.
    bars = {s: {d: (row.close, row.ema_trail) for d, row in df[["close", "ema_trail"]].iterrows()}
            for s, df in history.items()}
    entries: dict[date, list[tuple]] = {}
    for symbol, df in history.items():
        hits = df[df["setup"].isin(allowed)]
        for entry_date, row in hits[["close", "atr", "volume_ratio", "setup"]].iterrows():
            if not np.isnan(row.atr):
                entries.setdefault(entry_date, []).append(
                    (row.volume_ratio, symbol, row.close, row.atr, row.setup))

    dates = sorted({d for df in history.values() for d in df.index})
    uptrend = market["uptrend"].to_dict()
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []
    equity = start_equity
    equity_curve = [{"date": str(dates[0]), "equity": equity}] if dates else []

    for today in dates:
        for symbol in list(open_positions):
            position = open_positions[symbol]
            bar = bars[symbol].get(today)
            if bar is None:
                continue
            close, ema_trail = bar
            days_held = (today - position["entry_date"]).days
            if days_held < config.MIN_HOLDING_DAYS:
                continue

            if close <= position["stop_loss"]:
                reason = "STOP_LOSS"
            elif close >= position["take_profit"]:
                reason = "TAKE_PROFIT"
            elif not np.isnan(ema_trail) and close < ema_trail:
                reason = "TRAIL_EMA"
            else:
                continue

            cost = position["shares"] * position["entry_price"]
            proceeds = position["shares"] * close
            fees = (cost + proceeds) * config.COMMISSION_PCT
            pnl = proceeds - cost - fees
            equity += pnl
            trades.append({
                "symbol": symbol, "setup": position["setup"],
                "entry_date": str(position["entry_date"]), "exit_date": str(today),
                "entry_price": round(position["entry_price"], 2), "exit_price": round(close, 2),
                "days_held": days_held, "exit_reason": reason, "pnl": round(pnl, 2),
                "return_pct": round(pnl / cost * 100, 2),
            })
            equity_curve.append({"date": str(today), "equity": round(equity, 2)})
            del open_positions[symbol]

        if not uptrend.get(today, False):
            continue

        free_slots = config.MAX_OPEN_POSITIONS - len(open_positions)
        if free_slots <= 0:
            continue

        candidates = sorted((c for c in entries.get(today, []) if c[1] not in open_positions),
                            key=lambda item: item[0], reverse=True)
        for _, symbol, close, atr_value, setup in candidates[:free_slots]:
            shares = risk.position_size(float(close), float(atr_value), equity) or 0
            if shares <= 0:
                continue
            open_positions[symbol] = {
                "entry_date": today, "entry_price": float(close), "shares": shares, "setup": setup,
                "stop_loss": close - config.ATR_STOP_MULT * atr_value,
                "take_profit": close + config.ATR_TARGET_MULT * atr_value,
            }

    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9) if dates else 1
    by_setup = {}
    for name in ("BREAKOUT", "PULLBACK"):
        picked = [t for t in trades if t["setup"] == name]
        if picked:
            by_setup[name] = {
                "trades": len(picked),
                "win_rate": round(sum(t["return_pct"] > 0 for t in picked) / len(picked) * 100, 1),
                "avg_return_pct": round(float(np.mean([t["return_pct"] for t in picked])), 2),
            }

    return {
        "variant": variant,
        "from": str(dates[0]) if dates else None,
        "to": str(dates[-1]) if dates else None,
        "metrics": _metrics(trades, equity_curve, start_equity, years),
        "by_setup": by_setup,
        "equity_curve": equity_curve,
        "trades": trades[-200:],
    }


def _cached_fetch(symbol: str, start: date, end: date, refresh: bool) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{symbol}.csv"
    if path.exists() and not refresh:
        cached = pd.read_csv(path, parse_dates=["date"])
        if not cached.empty and cached["date"].max().date() >= end - timedelta(days=5):
            return cached

    df = fetch_ohlcv(symbol, start, end)
    if not df.empty:
        df.to_csv(path, index=False)
    return df


def load_history(years: int, refresh: bool = False) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    end = datetime.now(config.TIMEZONE).date()
    start = end - timedelta(days=round(years * 365.25) + config.MACRO_EMA_PERIOD * 2)

    market_raw = _cached_fetch(config.MARKET_INDEX, start, end, refresh)
    market = _prepare(market_raw, None)
    if market is None:
        raise RuntimeError(f"No usable history for the {config.MARKET_INDEX} index")
    market["uptrend"] = market["close"] > market["ema_50"]

    history = {}
    for symbol in get_universe():
        prepared = _prepare(_cached_fetch(symbol, start, end, refresh), market["return_20d"])
        if prepared is not None:
            history[symbol] = prepared
    return history, market


def benchmark_buy_and_hold(market: pd.DataFrame, start: str, end: str) -> dict:
    """What simply holding the index over the same window would have returned."""
    window = market.loc[date.fromisoformat(start):date.fromisoformat(end), "close"]
    drawdown = (window / window.cummax() - 1).min()
    return {
        "index": config.MARKET_INDEX,
        "total_return_pct": round((window.iloc[-1] / window.iloc[0] - 1) * 100, 2),
        "max_drawdown_pct": round(float(drawdown) * 100, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the swing rules over past PSX data")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--refresh", action="store_true", help="Ignore the local history cache")
    parser.add_argument("--save", action="store_true", help="Write docs/backtest.json for the dashboard")
    args = parser.parse_args()

    history, market = load_history(args.years, args.refresh)
    print(f"Universe: {len(history)} symbols with usable history")
    results = {variant: run(history, market, variant) for variant in VARIANTS}

    for variant, result in results.items():
        m = result["metrics"]
        print(f"\n=== {variant.upper()}  {result['from']} to {result['to']} ===")
        print(f"  trades {m['trades']} ({m['trades_per_year']}/yr)   win rate {m['win_rate']}%   "
              f"avg {m['avg_return_pct']}%   held {m['avg_days_held']}d")
        print(f"  total return {m['total_return_pct']}%   max drawdown {m['max_drawdown_pct']}%   "
              f"profit factor {m['profit_factor']}")
        for setup, stats in result["by_setup"].items():
            print(f"    {setup:9} {stats['trades']:>4} trades  win {stats['win_rate']}%  "
                  f"avg {stats['avg_return_pct']}%")

    active = results["both"]
    benchmark = benchmark_buy_and_hold(market, active["from"], active["to"])
    print(f"\nBenchmark: holding {benchmark['index']} over the same window returned "
          f"{benchmark['total_return_pct']}% with a {benchmark['max_drawdown_pct']}% drawdown.")

    if args.save:
        payload = {
            "generated_at": datetime.now(config.TIMEZONE).isoformat(timespec="minutes"),
            "years": args.years,
            "universe": config.UNIVERSE_INDEX,
            "universe_size": len(history),
            "commission_pct": config.COMMISSION_PCT,
            "start_equity": 1_000_000.0,
            "active_variant": "both",
            "benchmark": benchmark,
            "results": results,
            "caveats": [
                "Uses today's index members, already filtered by today's price and liquidity, "
                "over the whole period — so it is biased towards stocks that survived and did well.",
                "Compare the return against the benchmark above, not against zero: most of it is "
                "the market itself, which rose sharply over this window.",
                f"Assumes {config.COMMISSION_PCT * 100:.2f}% brokerage per side, no slippage or taxes.",
                "Entries and exits use closing prices; a real fill may differ.",
                "Past results do not guarantee future results.",
            ],
        }
        RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {RESULT_PATH}")


if __name__ == "__main__":
    main()
