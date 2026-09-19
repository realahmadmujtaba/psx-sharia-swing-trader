import time
from datetime import date

import pandas as pd
import psxdata
from psxdata.exceptions import PSXDataError

OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume", "is_anomaly"]
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2


def fetch_ohlcv(symbol: str, start: date, end: date) -> pd.DataFrame:
    last_error: Exception | None = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            df = psxdata.stocks(symbol, start=start, end=end, cache=attempt == 0)
            return df.sort_values("date").reset_index(drop=True)
        except PSXDataError as error:
            last_error = error
        except Exception as error:  # network timeout, DNS failure, etc.
            last_error = error

        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(BACKOFF_SECONDS * (2**attempt))

    print(f"[psx_fetcher] {symbol}: giving up after {MAX_ATTEMPTS} attempts ({last_error})")
    return pd.DataFrame(columns=OHLCV_COLUMNS)
