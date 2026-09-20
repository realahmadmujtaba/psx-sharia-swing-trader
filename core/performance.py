import pandas as pd


def closed_trades(log_df: pd.DataFrame) -> list[dict]:
    if log_df.empty:
        return []

    trades = []
    for symbol, rows in log_df.sort_values("date").groupby("symbol", sort=False):
        entry = None
        for _, row in rows.iterrows():
            if row["signal_type"] == "BUY":
                entry = row
            elif entry is not None:
                trades.append({
                    "symbol": symbol,
                    "entry_date": str(entry["date"]),
                    "exit_date": str(row["date"]),
                    "entry_price": float(entry["close_price"]),
                    "exit_price": float(row["close_price"]),
                    "exit_reason": row["exit_reason"],
                    "days_held": (row["date"] - entry["date"]).days,
                    "return_pct": round((float(row["close_price"]) / float(entry["close_price"]) - 1) * 100, 2),
                })
                entry = None
    return sorted(trades, key=lambda t: t["exit_date"], reverse=True)


def summarise(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0, "win_rate": None, "avg_return_pct": None, "best_pct": None,
                "worst_pct": None, "cumulative_pct": None}

    returns = [t["return_pct"] for t in trades]
    compounded = 1.0
    for r in returns:
        compounded *= 1 + r / 100
    return {
        "trades": len(trades),
        "win_rate": round(sum(r > 0 for r in returns) / len(returns) * 100, 1),
        "avg_return_pct": round(sum(returns) / len(returns), 2),
        "best_pct": max(returns),
        "worst_pct": min(returns),
        "cumulative_pct": round((compounded - 1) * 100, 2),
    }
