"""Cross-sectional multi-factor ranking for the weekly portfolio."""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


def _percentile(values: pd.Series, higher_is_better: bool) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() <= 1:
        return pd.Series(50.0, index=values.index)
    rank = numeric.rank(method="average", pct=True, ascending=higher_is_better)
    return (rank * 100).fillna(0.0).round(2)


def _proxy_values(rows: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Use transparent price/liquidity proxies when fundamentals are unavailable."""
    price_proxy = rows["close"]
    income_proxy = rows["avg_volume"] / rows["close"].replace(0, np.nan)
    return price_proxy, income_proxy


def rank_snapshots(snapshots: list[dict], limit: int = 10) -> list[dict]:
    """Return the highest-ranked candidates with 0-100 factor scores."""
    if not snapshots:
        return []
    frame = pd.DataFrame(snapshots).copy()
    frame = frame.drop_duplicates("symbol", keep="last")
    proxy_pe, proxy_income = _proxy_values(frame)
    pe = pd.to_numeric(frame.get("pe"), errors="coerce").fillna(proxy_pe)
    income = pd.to_numeric(frame.get("dividend_yield"), errors="coerce").fillna(proxy_income)
    frame["pe"] = pe
    frame["dividend_yield"] = income
    momentum = pd.to_numeric(frame.get("roc_12w"), errors="coerce")
    frame["value_score"] = _percentile(pe, higher_is_better=False)
    frame["income_score"] = _percentile(income, higher_is_better=True)
    frame["momentum_score"] = _percentile(momentum, higher_is_better=True)
    frame["composite_score"] = (
        frame["value_score"] * 0.4
        + frame["income_score"] * 0.4
        + frame["momentum_score"] * 0.2
    ).round(2)
    frame = frame.sort_values(["composite_score", "symbol"], ascending=[False, True])
    return frame.head(limit).where(pd.notna(frame.head(limit)), None).to_dict("records")


def score_snapshot(symbol: str, snapshot: dict) -> dict:
    """Add the twelve-week momentum field used by the cross-sectional ranker."""
    result = {"symbol": symbol, **snapshot}
    result["roc_12w"] = snapshot.get("roc_12w")
    return result
