# PSX AI Swing Trading Agent - Behavioral Contract & Project Rules

## 1. Project Context & Objectives
You are acting as a Quantitative Trading Architect assisting in building an End-of-Day (EOD) Swing Trading AI Agent tailored strictly for the Pakistan Stock Exchange (PSX). The primary goal is to fetch historical OHLCV data autonomously, apply quantitative technical indicators (RSI, EMA, Volume Breakout), and dispatch "Buy/Sell" swing trading alerts via asynchronous Email.

## 2. Technical Stack & Environment
* **Language:** Python 3.11+
* **Data Source:** `psxdata` library (for all PSX scraping and historical data). `yfinance` has no
  Pakistan Stock Exchange coverage under any ticker suffix (verified live — `.KH`/`.KA`/`.KAR` and
  bare symbols all return empty, and `yf.Search()` finds nothing for PSX names), so it is not used.
  Resilience instead comes from retrying `psxdata.stocks()` up to 3 times with exponential backoff,
  bypassing the disk cache on retries, before giving up on a symbol for that run.
* **Data Manipulation:** `pandas`, `numpy`.
* **Alert System:** `aiosmtplib` (Asynchronous SMTP Email).
* **Task Scheduling:** `APScheduler` (or standard Linux cron).
* **Timezone Enforced:** `Asia/Karachi` (PKT - Pakistan Standard Time).

## 3. Hard Architectural Rules (IMPORTANT)
* **Timezone Strictness:** All datetime operations, scheduling, and logging MUST use `pytz.timezone('Asia/Karachi')`. The market EOD analysis cron runs exactly at 17:45 PKT.
* **Data Ingestion Hierarchy:** Fetch historical prices using `psxdata.stocks(symbol, start, end)`. Wrap this in a try-except block; on exception or network timeout, retry up to 3 times with exponential backoff (`cache=False` on retries to force a fresh fetch instead of re-reading a possibly-stale cache). If all attempts fail, skip that symbol for the current run rather than emitting a signal on missing data.
* **Trading Logic Parameters:**
  * **Swing Trade Duration:** Assumed 3 to 15 days holding period.
  * **Trend Filter:** Close Price > 50-day EMA.
  * **Pullback/Momentum Filter:** 14-day RSI between 30 and 45.
  * **Liquidity Filter:** 20-day Average Daily Volume > 100,000 shares (vital for PSX to avoid illiquid traps).
* **Risk Management Implementation:** Every generated signal must auto-calculate a strict 4% Stop-Loss and an 8% Take-Profit (1:2 Risk-to-Reward ratio) based on the current closing price.
* **SELL Signal = Exit Alert:** PSX retail swing trading is long-only (no shorting), so SELL is not an independent scan — it is the exit for a position a prior BUY alert opened. Once a symbol's BUY alert fires, treat it as an open position (the last logged signal for that symbol) until a SELL closes it. Each EOD run, for any open position, fire SELL when the closing price crosses the entry's Stop-Loss or Take-Profit, OR when `MAX_HOLDING_DAYS` (15) has elapsed since entry — whichever comes first. Do not scan a symbol for a new BUY setup while it already has an open position.
* **Minimum Holding Lock:** Shares must settle into the account before they can be sold (Sharia possession requirement, plus PSX T+2 settlement). No SELL alert of any kind — including Stop-Loss or Take-Profit — may fire until `MIN_HOLDING_DAYS` (3) have elapsed since the BUY alert.
* **Scan Universe:** Sharia-compliant stocks only. The scan universe is the live constituent list of the PSX KMI-30 index (`psxdata.tickers(index="KMI30")`), refreshed each run with a cached fallback in `data/universe_cache.csv`. Ex-dividend/bonus/right suffixes (`XD`/`XB`/`XR`) are stripped from symbols. If neither live nor cached list is available, abort the run rather than scan an unverified list. Never hardcode or guess compliance status.
* **Alert Wording:** Alerts state that a stock matches the swing-entry criteria; they never claim a price is guaranteed to rise.
* **Async Execution:** The email alert module must be purely asynchronous using `asyncio` and `aiosmtplib`. Do not use `smtplib` synchronously or blocking SMTP calls, to prevent I/O blocking.

## 4. Workflow Preferences
* When writing Python code, favor modular functional design over deep OOP hierarchies unless state management strictly demands classes.
* Do not explain standard Python library functions. Output raw, deployable code blocks primarily.
* Make rules testable; any logic for indicators must be verified against standard mathematical definitions.

## 5. Out of Scope
* Intraday scraping (minute-by-minute data) is entirely out of scope. Do not write code for live WebSocket feeds or order matching execution (no broker API integrations yet).
* Do not enforce standard PEP8 linting rules in our chats; assume a pre-commit hook handles all formatting.