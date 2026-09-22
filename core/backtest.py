import argparse
import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import config
from core import indicators, risk
from core import scoring
from core.signal_engine import snapshot
from fetchers.psx_fetcher import fetch_ohlcv
from fetchers.universe import get_universe

RESULT_PATH = config.DOCS_DIR / "backtest.json"
CACHE_DIR = config.DATA_DIR / "history_cache"
# "both" is what runs live; the single-setup runs show which half carries the result.
VARIANTS = {"multi_factor": ()}


def _prepare(df: pd.DataFrame, benchmark_return: pd.Series | None) -> pd.DataFrame | None:
    df = df.sort_values("date")
    df = df[~df["is_anomaly"]].drop_duplicates("date", keep="last").reset_index(drop=True)
    if len(df) < 100:
        return None

    close, volume = df["close"], df["volume"].astype(float)
    dates = pd.to_datetime(df["date"])
    df["date"] = dates.dt.date
    df["ema_20"] = indicators.ema(close, config.TRAIL_EMA_PERIOD)
    df["ema_50"] = indicators.ema(close, config.EMA_PERIOD)
    df["ema_200"] = indicators.ema(close, 200)
    df["ema_100"] = indicators.ema(close, config.MACRO_EMA_PERIOD)
    weekly = (
        df.assign(date=dates)
        .set_index("date")
        .resample("W-FRI")
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
             close=("close", "last"), volume=("volume", "sum"))
        .dropna()
    )
    weekly_ema = indicators.ema(weekly["close"], config.WEEKLY_EMA_PERIOD)
    weekly_rsi = indicators.rsi(weekly["close"], config.RSI_PERIOD)
    weekly_features = pd.DataFrame({"weekly_ema": weekly_ema, "weekly_rsi": weekly_rsi})
    weekly_features.index = weekly_features.index.date
    df["weekly_ema"] = df["date"].map(weekly_features["weekly_ema"])
    df["weekly_rsi"] = df["date"].map(weekly_features["weekly_rsi"])
    df["rsi"] = indicators.rsi(close, config.RSI_PERIOD)
    df["atr"] = indicators.atr(df["high"], df["low"], close, config.ATR_PERIOD)
    df["avg_volume"] = indicators.avg_volume(volume, config.VOLUME_LOOKBACK)
    df = df.set_index("date")

    baseline = ((df["avg_volume"] > config.MIN_AVG_VOLUME)
                & (df["close"] > config.MIN_PRICE)
                & (df["weekly_ema"].notna())
                & (df["close"] > df["weekly_ema"])
                & (df["weekly_rsi"] > config.WEEKLY_RSI_MIN))
    df["setup"] = pd.Series(
        ["MEAN_REVERSION" if value else None for value in baseline.fillna(False)],
        index=df.index,
        dtype=object,
    )
    return df


TRADING_DAYS = 252


def profit_factor(trades: list[dict]) -> float | None:
    gross_win = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = -sum(t["pnl"] for t in trades if t["pnl"] <= 0)
    return round(gross_win / gross_loss, 2) if gross_loss else None


def _risk_metrics(daily_equity: pd.Series, benchmark: pd.Series) -> dict:
    """Sharpe against the risk-free rate, and beta against the benchmark."""
    if len(daily_equity) < 3:
        return {"sharpe": None, "beta": None, "annual_return_pct": None, "annual_vol_pct": None}

    returns = daily_equity.pct_change().dropna()
    if returns.empty or returns.std() == 0:
        return {"sharpe": None, "beta": None, "annual_return_pct": None, "annual_vol_pct": None}

    annual_return = returns.mean() * TRADING_DAYS
    annual_vol = returns.std() * np.sqrt(TRADING_DAYS)
    sharpe = (annual_return - config.RISK_FREE_RATE) / annual_vol

    beta = None
    bench_returns = benchmark.reindex(returns.index).pct_change().dropna()
    paired = pd.concat([returns, bench_returns], axis=1).dropna()
    if len(paired) > 2 and paired.iloc[:, 1].var() > 0:
        beta = paired.iloc[:, 0].cov(paired.iloc[:, 1]) / paired.iloc[:, 1].var()

    return {
        "sharpe": round(float(sharpe), 2),
        "beta": None if beta is None else round(float(beta), 2),
        "annual_return_pct": round(float(annual_return) * 100, 2),
        "annual_vol_pct": round(float(annual_vol) * 100, 2),
    }


def drawdown_duration_days(daily_equity: pd.Series) -> int:
    """Longest run of days spent below the previous all-time high."""
    if daily_equity.empty:
        return 0
    underwater = daily_equity < daily_equity.cummax()
    longest = run = 0
    for below in underwater:
        run = run + 1 if below else 0
        longest = max(longest, run)
    return int(longest)


def _metrics(trades: list[dict], daily_equity: pd.Series, benchmark: pd.Series,
             start_equity: float, years: float, exposure_days: int = 0) -> dict:
    base = {"trades": 0, "trades_per_year": 0.0, "win_rate": None, "total_return_pct": 0.0,
            "avg_return_pct": None, "avg_win_pct": None, "avg_loss_pct": None,
            "profit_factor": None, "max_drawdown_pct": 0.0, "avg_days_held": None,
            "sharpe": None, "beta": None, "annual_return_pct": None, "annual_vol_pct": None,
            "exposure_pct": 0.0, "drawdown_duration_days": 0, "trading_days": len(daily_equity)}
    if not trades or daily_equity.empty:
        return base

    returns = np.array([t["return_pct"] for t in trades])
    wins, losses = returns[returns > 0], returns[returns <= 0]
    drawdown = (daily_equity / daily_equity.cummax() - 1)

    return {
        **base,
        **_risk_metrics(daily_equity, benchmark),
        "exposure_pct": round(exposure_days / len(daily_equity) * 100, 1),
        "drawdown_duration_days": drawdown_duration_days(daily_equity),
        "trades": len(trades),
        "trades_per_year": round(len(trades) / years, 1),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "total_return_pct": round((daily_equity.iloc[-1] / start_equity - 1) * 100, 2),
        "avg_return_pct": round(float(returns.mean()), 2),
        "avg_win_pct": round(float(wins.mean()), 2) if len(wins) else None,
        "avg_loss_pct": round(float(losses.mean()), 2) if len(losses) else None,
        "profit_factor": profit_factor(trades),
        "max_drawdown_pct": round(float(drawdown.min()) * 100, 2),
        "avg_days_held": round(float(np.mean([t["days_held"] for t in trades])), 1),
    }


def _exit_reason(position: dict, close: float, ema_20: float) -> str | None:
    """Mirror of signal_engine.evaluate_exit for mean reversion."""
    if close < position["stop_loss"]:
        return "STOP_LOSS"
    if close >= position["take_profit"]:
        return "ATR_TARGET"
    if not np.isnan(ema_20) and close > ema_20:
        return "MEAN_REVERT"
    return None


def run(history: dict[str, pd.DataFrame], market: pd.DataFrame, variant: str,
        start_equity: float = 1_000_000.0, period: tuple[date, date] | None = None) -> dict:
    allowed = VARIANTS[variant]
    # Pre-index everything the day loop needs, so it never touches pandas lookups.
    bars = {s: {d: (r.close, r.ema_20)
                for d, r in df[["close", "ema_20"]].iterrows()}
            for s, df in history.items()}
    entries: dict[date, list[tuple]] = {}
    for symbol, df in history.items():
        hits = df[df["setup"].isin(allowed)]
        for entry_date, row in hits[["close", "atr", "setup"]].iterrows():
            if not np.isnan(row.atr):
                entries.setdefault(entry_date, []).append(
                    (1.0, symbol, row.close, row.atr, row.setup))

    dates = sorted({d for df in history.values() for d in df.index})
    if period:
        dates = [d for d in dates if period[0] <= d <= period[1]]
    uptrend = market["uptrend"].to_dict()

    open_positions: dict[str, dict] = {}
    trades: list[dict] = []
    cash = start_equity
    last_price: dict[str, float] = {}
    daily_equity: dict[date, float] = {}
    exposure_days = 0

    for today in dates:
        for symbol in list(open_positions):
            position = open_positions[symbol]
            bar = bars[symbol].get(today)
            if bar is None:
                continue
            close, ema_20 = bar
            last_price[symbol] = close
            if (today - position["entry_date"]).days < config.MIN_HOLDING_DAYS:
                continue

            reason = _exit_reason(position, close, ema_20)
            if reason is None:
                continue

            cost = position["shares"] * position["entry_price"]
            proceeds = position["shares"] * close
            pnl = proceeds - cost - (cost + proceeds) * config.COMMISSION_PCT
            cash += proceeds - proceeds * config.COMMISSION_PCT
            trades.append({
                "symbol": symbol, "setup": position["setup"],
                "entry_date": str(position["entry_date"]), "exit_date": str(today),
                "entry_price": round(position["entry_price"], 2), "exit_price": round(close, 2),
                "days_held": (today - position["entry_date"]).days, "exit_reason": reason,
                "pnl": round(pnl, 2), "return_pct": round(pnl / cost * 100, 2),
            })
            del open_positions[symbol]

        equity_now = cash + sum(p["shares"] * last_price.get(s, p["entry_price"])
                                for s, p in open_positions.items())

        if uptrend.get(today, False):
            free_slots = config.MAX_OPEN_POSITIONS - len(open_positions)
            candidates = sorted((c for c in entries.get(today, []) if c[1] not in open_positions),
                                key=lambda item: item[0], reverse=True)
            for _, symbol, close, atr_value, setup in candidates[:max(free_slots, 0)]:
                stop_loss, take_profit = risk.calculate_risk_levels(
                    float(close), float(atr_value), setup)
                shares = risk.position_size(float(close), float(atr_value), equity_now,
                                            stop_loss=stop_loss) or 0
                spend = shares * close * (1 + config.COMMISSION_PCT)
                if shares <= 0 or spend > cash:
                    continue
                cash -= spend
                last_price[symbol] = close
                open_positions[symbol] = {
                    "entry_date": today, "entry_price": float(close), "shares": shares,
                    "setup": setup, "stop_loss": stop_loss, "take_profit": take_profit,
                }

        daily_equity[today] = cash + sum(p["shares"] * last_price.get(s, p["entry_price"])
                                         for s, p in open_positions.items())
        if open_positions:
            exposure_days += 1

    equity_series = pd.Series(daily_equity).sort_index()
    benchmark = market["close"].reindex(equity_series.index).ffill()
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9) if dates else 1

    by_setup = {}
    for name in ("MEAN_REVERSION",):
        picked = [t for t in trades if t["setup"] == name]
        if picked:
            by_setup[name] = {
                "trades": len(picked),
                "win_rate": round(sum(t["return_pct"] > 0 for t in picked) / len(picked) * 100, 1),
                "avg_return_pct": round(float(np.mean([t["return_pct"] for t in picked])), 2),
                "profit_factor": profit_factor(picked),
                "avg_days_held": round(float(np.mean([t["days_held"] for t in picked])), 1),
            }

    return {
        "variant": variant,
        "from": str(dates[0]) if dates else None,
        "to": str(dates[-1]) if dates else None,
        "metrics": _metrics(trades, equity_series, benchmark, start_equity, years, exposure_days),
        "by_setup": by_setup,
        "equity_curve": [{"date": str(d), "equity": round(v, 2)}
                         for d, v in equity_series.items()],
        "trades": trades[-200:],
    }


def _weekly_rebalance_run(
    history: dict[str, pd.DataFrame],
    market: pd.DataFrame,
    start_equity: float,
    period: tuple[date, date] | None,
) -> dict:
    dates = sorted({d for df in history.values() for d in df.index})
    if period:
        dates = [d for d in dates if period[0] <= d <= period[1]]
    if not dates:
        return {"variant": "multi_factor", "from": None, "to": None,
                "metrics": _metrics([], pd.Series(dtype=float), pd.Series(dtype=float),
                                    start_equity, 1), "by_setup": {}, "equity_curve": [], "trades": []}

    market_ok = market["uptrend"].reindex(dates).ffill().fillna(False)
    prices = {symbol: df["close"].reindex(dates).ffill() for symbol, df in history.items()}
    weekly_data = {}
    for symbol, prepared in history.items():
        source = prepared.reset_index()
        source["date"] = pd.to_datetime(source["date"])
        weekly = source.set_index("date").resample("W-FRI").agg(
            open=("open", "first"), high=("high", "max"), low=("low", "min"),
            close=("close", "last"), volume=("volume", "sum"),
        ).dropna(subset=["close"])
        weekly["ema_20"] = indicators.ema(weekly["close"], config.WEEKLY_EMA_PERIOD)
        weekly["rsi"] = indicators.rsi(weekly["close"], config.RSI_PERIOD)
        weekly["roc_12w"] = indicators.rolling_return(weekly["close"], 12)
        weekly_data[symbol] = weekly
    rebalance_dates = [d for d in dates if pd.Timestamp(d).weekday() == 4]
    if dates[-1] not in rebalance_dates:
        rebalance_dates.append(dates[-1])
    holdings: list[str] = []
    weights: dict[str, float] = {}
    equity = start_equity
    daily_equity: dict[date, float] = {}
    trades: list[dict] = []
    exposure_days = 0

    for today in dates:
        if today in rebalance_dates:
            snapshots = []
            for symbol, weekly in weekly_data.items():
                available = weekly.loc[:pd.Timestamp(today)]
                if available.empty:
                    continue
                latest = available.iloc[-1]
                if any(pd.isna(latest[field]) for field in ("ema_20", "rsi", "roc_12w")):
                    continue
                snapshots.append({
                    "symbol": symbol,
                    "close": float(latest["close"]),
                    "avg_volume": float(latest["volume"]),
                    "pe": None,
                    "dividend_yield": None,
                    "roc_12w": float(latest["roc_12w"]),
                })
            target = scoring.rank_snapshots(snapshots, config.PORTFOLIO_SIZE) if market_ok.loc[today] else []
            new_holdings = [row["symbol"] for row in target]
            turnover = len(set(holdings) ^ set(new_holdings)) / max(config.PORTFOLIO_SIZE, 1)
            if holdings and turnover:
                equity *= 1 - turnover * config.COMMISSION_PCT
            holdings = new_holdings
            weights = {symbol: 1 / len(holdings) for symbol in holdings} if holdings else {}
            if holdings:
                trades.append({"return_pct": 0.0, "pnl": 0.0, "days_held": 7})

        previous = daily_equity.get(dates[dates.index(today) - 1], equity) if dates.index(today) else equity
        if holdings:
            daily_returns = []
            for symbol in holdings:
                series = prices[symbol]
                if today in series.index and series.index.get_loc(today) > 0:
                    prior = series.iloc[series.index.get_loc(today) - 1]
                    current = series.loc[today]
                    if prior:
                        daily_returns.append(current / prior - 1)
            if daily_returns:
                equity *= 1 + float(np.mean(daily_returns))
            exposure_days += 1
        daily_equity[today] = equity

    equity_series = pd.Series(daily_equity).sort_index()
    benchmark = market["close"].reindex(equity_series.index).ffill()
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    return {
        "variant": "multi_factor",
        "from": str(dates[0]),
        "to": str(dates[-1]),
        "metrics": _metrics(trades, equity_series, benchmark, start_equity, years, exposure_days),
        "by_setup": {},
        "equity_curve": [{"date": str(d), "equity": round(v, 2)} for d, v in equity_series.items()],
        "trades": trades[-200:],
    }


def run(history: dict[str, pd.DataFrame], market: pd.DataFrame, variant: str,
        start_equity: float = 1_000_000.0, period: tuple[date, date] | None = None) -> dict:
    """Run the weekly equal-weight Top 10 multi-factor portfolio."""
    return _weekly_rebalance_run(history, market, start_equity, period)


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

    market = _prepare(_cached_fetch(config.MARKET_INDEX, start, end, refresh), None)
    if market is None:
        raise RuntimeError(f"No usable history for the {config.MARKET_INDEX} index")

    # Regime gate runs on the broad index: close above its 100-day EMA.
    regime = _prepare(_cached_fetch(config.REGIME_INDEX, start, end, refresh), None)
    if regime is None:
        raise RuntimeError(f"No usable history for the {config.REGIME_INDEX} index")
    regime_ema = indicators.ema(regime["close"], config.REGIME_EMA_PERIOD)
    regime_ok = regime["close"] > regime_ema
    market["uptrend"] = regime_ok.reindex(market.index).fillna(False)

    history = {}
    for symbol in get_universe():
        prepared = _prepare(_cached_fetch(symbol, start, end, refresh), None)
        if prepared is not None:
            history[symbol] = prepared
    return history, market


def benchmark_buy_and_hold(market: pd.DataFrame, start: str, end: str) -> dict:
    """What simply holding the index over the same window would have returned."""
    window = market.loc[date.fromisoformat(start):date.fromisoformat(end), "close"]
    drawdown = (window / window.cummax() - 1).min()
    returns = window.pct_change().dropna()
    annual_vol = float(returns.std() * np.sqrt(TRADING_DAYS)) if len(returns) > 2 else None
    annual_return = float(returns.mean() * TRADING_DAYS) if len(returns) > 2 else None
    sharpe = None
    if annual_vol:
        sharpe = round((annual_return - config.RISK_FREE_RATE) / annual_vol, 2)
    return {
        "index": config.MARKET_INDEX,
        "total_return_pct": round((window.iloc[-1] / window.iloc[0] - 1) * 100, 2),
        "max_drawdown_pct": round(float(drawdown) * 100, 2),
        "sharpe": sharpe,
    }


def generate_tearsheet(result: dict, market: pd.DataFrame, output: str | None = None) -> str | None:
    """Write a QuantStats HTML tear sheet for the supplied portfolio run."""
    try:
        import quantstats as qs
    except ImportError:
        print("QuantStats is not installed; skipping tear sheet generation.")
        return None
    equity = pd.Series(
        {pd.Timestamp(row["date"]): row["equity"] for row in result["equity_curve"]}
    ).sort_index()
    benchmark = market["close"].reindex(equity.index).ffill()
    returns = equity.pct_change().dropna()
    benchmark_returns = benchmark.pct_change().dropna()
    target = output or str(config.DOCS_DIR / "tearsheet.html")
    qs.reports.html(returns, benchmark=benchmark_returns, output=target,
                    title="PSX Multi-Factor Weekly Portfolio")
    return target


def split_dates(history: dict[str, pd.DataFrame]) -> tuple[date, date, date, date]:
    """(train_start, train_end, test_start, test_end) at TRAIN_FRACTION of the timeline."""
    dates = sorted({d for df in history.values() for d in df.index})
    cut = int(len(dates) * config.TRAIN_FRACTION)
    return dates[0], dates[cut - 1], dates[cut], dates[-1]


def run_split(history: dict[str, pd.DataFrame], market: pd.DataFrame, variant: str) -> dict:
    """One continuous run, plus independent in-sample and out-of-sample runs.

    The OOS run restarts from the same equity, so its return is not inflated by
    compounding through the bull market that came before it.
    """
    train_start, train_end, test_start, test_end = split_dates(history)
    return {
        "full": run(history, market, variant),
        "in_sample": run(history, market, variant, period=(train_start, train_end)),
        "out_of_sample": run(history, market, variant, period=(test_start, test_end)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the swing rules over past PSX data")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--refresh", action="store_true", help="Ignore the local history cache")
    parser.add_argument("--save", action="store_true", help="Write docs/backtest.json for the dashboard")
    args = parser.parse_args()

    history, market = load_history(args.years, args.refresh)
    print(f"Universe: {len(history)} symbols with usable history")
    results = {variant: run_split(history, market, variant) for variant in VARIANTS}

    def line(label: str, result: dict) -> None:
        m = result["metrics"]
        bm = benchmark_buy_and_hold(market, result["from"], result["to"])
        print(f"  {label:14} {result['from']} to {result['to']}")
        print(f"    trades {m['trades']:>4} ({m['trades_per_year']}/yr)  win {m['win_rate']}%  "
              f"PF {m['profit_factor']}  held {m['avg_days_held']}d")
        print(f"    return {m['total_return_pct']}%  (index {bm['total_return_pct']}%)  "
              f"drawdown {m['max_drawdown_pct']}%  Sharpe {m['sharpe']} (index {bm['sharpe']})  "
              f"beta {m['beta']}")
        for setup, stats in result["by_setup"].items():
            print(f"      {setup:9} {stats['trades']:>4} trades  win {stats['win_rate']}%  "
                  f"PF {stats['profit_factor']}  avg {stats['avg_return_pct']}%  "
                  f"held {stats['avg_days_held']}d")

    for variant, split in results.items():
        print(f"\n=== {variant.upper()} ===")
        line("FULL", split["full"])
        line("IN-SAMPLE", split["in_sample"])
        line("OUT-OF-SAMPLE", split["out_of_sample"])

    oos_metrics = results["multi_factor"]["out_of_sample"]["metrics"]
    print(f"\nMulti-factor OOS return = {oos_metrics['total_return_pct']}%  "
          f"drawdown = {oos_metrics['max_drawdown_pct']}%  Sharpe = {oos_metrics['sharpe']}")

    active = results["multi_factor"]["full"]
    benchmark = benchmark_buy_and_hold(market, active["from"], active["to"])

    if args.save:
        payload = {
            "generated_at": datetime.now(config.TIMEZONE).isoformat(timespec="minutes"),
            "years": args.years,
            "universe": config.UNIVERSE_INDEX,
            "universe_size": len(history),
            "commission_pct": config.COMMISSION_PCT,
            "start_equity": 1_000_000.0,
            "active_variant": "multi_factor",
            "retired_setups": {},
            "benchmark": benchmark,
            "train_fraction": config.TRAIN_FRACTION,
            "risk_free_rate": config.RISK_FREE_RATE,
            "benchmark_in_sample": benchmark_buy_and_hold(
                market, results["multi_factor"]["in_sample"]["from"],
                results["multi_factor"]["in_sample"]["to"]),
            "benchmark_out_of_sample": benchmark_buy_and_hold(
                market, results["multi_factor"]["out_of_sample"]["from"],
                results["multi_factor"]["out_of_sample"]["to"]),
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
        generate_tearsheet(active, market)
        print(f"\nWrote {RESULT_PATH}")


if __name__ == "__main__":
    main()
