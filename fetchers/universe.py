import re

import pandas as pd
import psxdata

import config

CACHE_PATH = config.DATA_DIR / "universe_cache.csv"

# PSX's live board lists ex-dividend/bonus/right stocks as e.g. LUCKXD, which has no price history.
_EX_SUFFIX = re.compile(r"(XD|XB|XR)$")


def normalize_symbol(symbol: str) -> str:
    return _EX_SUFFIX.sub("", symbol)


def _prefilter(symbols: list[str]) -> list[str]:
    """Drop obviously illiquid or penny names using one screener call.

    Saves ~200 per-symbol history fetches per run. The exact 20-day SMA and price
    rules are still enforced later against real OHLCV data.
    """
    try:
        screener = psxdata.screener(cache=False)
    except Exception as error:
        print(f"[universe] screener unavailable ({error}); keeping the full index list")
        return symbols

    if screener.empty:
        return symbols

    liquid = screener[
        (screener["price"] > config.MIN_PRICE)
        & (screener["volume_avg_30d"] > config.PREFILTER_AVG_VOLUME)
    ]
    keep = set(liquid["symbol"])
    return [s for s in symbols if s in keep]


def get_universe() -> list[str]:
    try:
        symbols = psxdata.tickers(index=config.UNIVERSE_INDEX, cache=False)
        if symbols:
            normalized = sorted({normalize_symbol(symbol) for symbol in symbols})
            selected = _prefilter(normalized)
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            pd.Series(selected, name="symbol").to_csv(CACHE_PATH, index=False)
            return selected
    except Exception as error:
        print(f"[universe] live {config.UNIVERSE_INDEX} fetch failed ({error}); trying cache")

    if CACHE_PATH.exists():
        return pd.read_csv(CACHE_PATH)["symbol"].tolist()

    raise RuntimeError(
        f"Could not load the {config.UNIVERSE_INDEX} constituent list from PSX or from cache; "
        "refusing to scan an unverified symbol list."
    )
