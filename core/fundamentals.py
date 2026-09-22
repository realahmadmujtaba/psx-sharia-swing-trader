"""Cached fundamental data for PSX symbols.

Yahoo Finance is used only for company metadata; PSX OHLCV remains sourced by
the existing psxdata fetcher.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from pathlib import Path

import config

CACHE_PATH = config.DATA_DIR / "fundamentals.json"
DEFAULT_TTL_DAYS = 7
CACHE_LOCK = Lock()


def _load() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read fundamentals cache: {CACHE_PATH}") from exc


def _save(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def fetch(symbol: str, ttl_days: int = DEFAULT_TTL_DAYS) -> dict:
    """Fetch trailing P/E and dividend yield, using a bounded local cache."""
    cache = _load()
    cached = cache.get(symbol)
    if cached:
        try:
            fetched_at = datetime.fromisoformat(cached["fetched_at"])
            if datetime.now() - fetched_at < timedelta(days=ttl_days):
                return {key: cached.get(key) for key in ("pe", "dividend_yield")}
        except (KeyError, TypeError, ValueError):
            pass

    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required for live PSX fundamentals") from exc

    info = yf.Ticker(f"{symbol}.KA").get_info()
    pe = info.get("trailingPE")
    dividend_yield = info.get("dividendYield")
    result = {
        "pe": float(pe) if pe is not None else None,
        "dividend_yield": float(dividend_yield) if dividend_yield is not None else None,
    }
    with CACHE_LOCK:
        cache = _load()
        cache[symbol] = {**result, "fetched_at": datetime.now().isoformat(timespec="seconds")}
        _save(cache)
    return result


def fetch_many(symbols: list[str]) -> dict[str, dict]:
    """Fetch symbols independently; one provider failure does not hide others."""
    results = {}
    failures = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        pending = {executor.submit(fetch, symbol): symbol for symbol in symbols}
        for future in as_completed(pending):
            symbol = pending[future]
            try:
                results[symbol] = future.result()
            except (RuntimeError, OSError, ValueError) as exc:
                failures.append(f"{symbol}: {exc}")
                results[symbol] = {"pe": None, "dividend_yield": None}
    if failures:
        print("[fundamentals] unavailable: " + "; ".join(failures[:5]))
    return results
