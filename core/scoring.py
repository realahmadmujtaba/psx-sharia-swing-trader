"""Cross-sectional multi-factor ranking for the weekly portfolio."""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
from core.fundamentals import toxic_asset_filter

# A small maintained map for symbols whose sector is not supplied by the data
# provider. Unknown symbols remain independent sectors rather than being
# incorrectly grouped together.
SECTOR_MAP = {
    "LUCK": "Cement",
    "DGKC": "Cement",
    "MLCF": "Cement",
    "FCCL": "Cement",
    "LOTCHEM": "Fertilizer",
    "ENGRO": "Fertilizer",
    "EFERT": "Fertilizer",
    "FFC": "Fertilizer",
    "FFBL": "Fertilizer",
    "POL": "E&P",
    "PPL": "E&P",
    "OGDC": "E&P",
    "MARI": "E&P",
    "SNGPL": "Gas Utilities",
    "SSGC": "Gas Utilities",
    "HUBC": "Power",
    "KEL": "Power",
    "PSO": "Oil Marketing",
    "SHEL": "Oil Marketing",
    "ATRL": "Refinery",
    "NRL": "Refinery",
    "PRL": "Refinery",
    "CNERGY": "Refinery",
    "SYS": "Technology",
    "TRG": "Technology",
    "NETSOL": "Technology",
    "MEBL": "Commercial Banks",
    "HBL": "Commercial Banks",
    "UBL": "Commercial Banks",
    "MCB": "Commercial Banks",
    "BAHL": "Commercial Banks",
    "FFC": "Fertilizer",
}


def sector_for(symbol: str, sector: str | None = None) -> str:
    """Return the provider sector, known PSX mapping, or symbol fallback."""
    if sector is not None and not pd.isna(sector) and str(sector).strip():
        return str(sector).strip()
    normalized = str(symbol).strip().upper()
    return SECTOR_MAP.get(normalized, f"Unknown:{normalized}")


def _percentile(values: pd.Series, higher_is_better: bool) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() <= 1:
        return pd.Series(50.0, index=values.index)
    rank = numeric.rank(method="average", pct=True, ascending=higher_is_better)
    return (rank * 100).fillna(0.0).round(2)


def _proxy_values(rows: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Use transparent price/liquidity proxies when fundamentals are unavailable."""
    price_proxy = pd.to_numeric(rows.get("close", pd.Series(1.0, index=rows.index)), errors="coerce")
    avg_volume = pd.to_numeric(
        rows.get("avg_volume", pd.Series(1.0, index=rows.index)),
        errors="coerce",
    )
    income_proxy = avg_volume / price_proxy.replace(0, np.nan)
    return price_proxy, income_proxy


def rank_snapshots(snapshots: list[dict], limit: int = 10, insider_selling: set[str] | None = None) -> list[dict]:
    """Return the highest-ranked candidates with 0-100 factor scores."""
    if not snapshots:
        return []
    frame = pd.DataFrame(snapshots).copy()
    if frame.empty:
        return []
    frame = frame.drop_duplicates("symbol", keep="last")
    proxy_pe, proxy_income = _proxy_values(frame)
    pe = pd.to_numeric(
        frame.get("pe", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    ).fillna(proxy_pe)
    income = pd.to_numeric(
        frame.get("dividend_yield", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    ).fillna(proxy_income)
    frame["pe"] = pe
    frame["dividend_yield"] = income
    momentum = pd.to_numeric(
        frame.get("roc_12w", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )
    frame["value_score"] = _percentile(pe, higher_is_better=False)
    frame["income_score"] = _percentile(income, higher_is_better=True)
    frame["momentum_score"] = _percentile(momentum, higher_is_better=True)

    risk_rows = frame.apply(
        lambda row: toxic_asset_filter(row.to_dict(), row.get("avg_volume")),
        axis=1,
        result_type="expand",
    )
    for column in risk_rows.columns:
        frame[column] = risk_rows[column]

    base = (
        frame["value_score"] * 0.4
        + frame["income_score"] * 0.4
        + frame["momentum_score"] * 0.2
    )
    conviction = pd.to_numeric(
        frame.get("conviction_score", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )
    conviction_multiplier = pd.to_numeric(
        frame.get("conviction_multiplier", pd.Series(1.0, index=frame.index)),
        errors="coerce",
    ).fillna(1.0)
    frame["conviction_multiplier"] = conviction_multiplier
    frame["conviction_score"] = (
        conviction.fillna(base) * conviction_multiplier
    ).clip(0, 100).round(2)
    frame["composite_score"] = (
        frame["conviction_score"] * frame["fundamental_multiplier"]
        + frame["toxic_penalty"]
    ).clip(0, 100).round(2)

    if insider_selling:
        mask = frame["symbol"].str.upper().isin({item.upper() for item in insider_selling})
        frame["insider_selling"] = mask.fillna(False)
        frame.loc[mask, "composite_score"] = (frame.loc[mask, "composite_score"] * 0.8).round(2)
    else:
        frame["insider_selling"] = False

    frame = frame.sort_values(["composite_score", "symbol"], ascending=[False, True])
    selected = []
    sector_counts: dict[str, int] = {}
    for row in frame.to_dict("records"):
        sector = sector_for(row["symbol"], row.get("sector"))
        if sector_counts.get(sector, 0) >= 2:
            continue
        row["sector"] = sector
        selected.append(row)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        # Keep legacy order when sector caps do not exclude a symbol.
        pass
    return pd.DataFrame(selected).where(pd.notna(pd.DataFrame(selected)), None).to_dict("records")


def score_snapshot(symbol: str, snapshot: dict) -> dict:
    """Add the twelve-week momentum field used by the cross-sectional ranker."""
    result = {"symbol": symbol, **snapshot}
    result["roc_12w"] = snapshot.get("roc_12w")
    return result
