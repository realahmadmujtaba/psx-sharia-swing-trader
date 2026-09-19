import re
from pathlib import Path

import pandas as pd
import psxdata

import config

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "universe_cache.csv"

# PSX's live board lists ex-dividend/bonus/right stocks as e.g. LUCKXD, which has no price history.
_EX_SUFFIX = re.compile(r"(XD|XB|XR)$")


def normalize_symbol(symbol: str) -> str:
    return _EX_SUFFIX.sub("", symbol)


def get_universe() -> list[str]:
    try:
        symbols = psxdata.tickers(index=config.UNIVERSE_INDEX, cache=False)
        if symbols:
            normalized = sorted({normalize_symbol(symbol) for symbol in symbols})
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            pd.Series(normalized, name="symbol").to_csv(CACHE_PATH, index=False)
            return normalized
    except Exception as error:
        print(f"[universe] live {config.UNIVERSE_INDEX} fetch failed ({error}); trying cache")

    if CACHE_PATH.exists():
        return pd.read_csv(CACHE_PATH)["symbol"].tolist()

    raise RuntimeError(
        f"Could not load the {config.UNIVERSE_INDEX} constituent list from PSX or from cache; "
        "refusing to scan an unverified symbol list."
    )
