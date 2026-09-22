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
* **Market Regime Filter (gates ALL new BUYs, checked before any stock):** no new signal unless the KMI All-Share index (`REGIME_INDEX`, ~313 names — broader than the KMI-30 traded benchmark) both closes above its own 100-day EMA (`REGIME_EMA_PERIOD`) AND that EMA is higher than it was 5 sessions ago (`REGIME_SLOPE_LOOKBACK`). Fails either test → 0 new signals; open positions still exit normally. Measured effect: closed only 22% of the out-of-sample window (2025-09 to 2026-09) — a 100-day EMA is too slow to detect chop after the prior rally pushed it up for over a year, so this did not fix Setup A's OOS underperformance (PF 0.83, still < 1). Documented as a real limit, not tuned away.
* **Entry — Breakout Only (`core/signal_engine.SETUPS`):** the signal records which setup fired (`setup`); the dashboard and email show it.
  * **Baseline:** 20-day SMA of volume > 500,000 shares; Close > Rs. 10; Close > 100-day EMA.
  * **Setup A — Breakout:** 14-day ADX > 20, the stock's 20-day return beats the KMI-30's, and today's volume ≥ 1.5× the prior 20-session average.
  * **Setup B — Pullback (RETIRED):** removed after out-of-sample testing — profit factor 0.60 (re-checked with the regime filter active: 0.71), both below the 1.20 keep threshold (`MIN_OOS_PROFIT_FACTOR`). `core/backtest.py` still tags pullbacks so the decision stays reproducible; do not re-add it to the live engine without OOS evidence.
* **Risk Management Implementation:** Every BUY auto-calculates an ATR-based Stop-Loss (close − 1.5 × ATR(14), Wilder smoothing) and Take-Profit (close + 3 × ATR(14)), keeping a 1:2 risk-to-reward ratio, all stated in rupees.
* **Position Sizing:** Risk-based — `shares = (equity × RISK_PER_TRADE_PCT) / (ATR_STOP_MULT × ATR)`, so a stop-out costs ~1.5% of equity, capped at `MAX_POSITION_PCT` (20%) of equity in one stock because a tight stop would otherwise demand more cash than the account holds. Falls back to a flat 10% when ATR is unavailable. `MAX_OPEN_POSITIONS` (8) remains a safety limit; when more stocks qualify than free slots, the largest volume spikes win. Share counts and rupee totals appear only in the private email, never on the public dashboard.
* **State Persistence:** SQLite (`data/signals.db`, schema in `core/db.py`) is the source of truth — a `signals` history table plus a `positions` table whose `status` carries the 15-day hold across separate runs. `core/state.py` is the adapter; `data/signals_log.csv` is a committed human-readable export. Both files are committed so cloud runs remember open positions.
* **Webhook Alerts:** When `WEBHOOK_URL` is set, `alerts/webhook.py` posts a one-line-per-signal summary to Telegram (with `TELEGRAM_CHAT_ID`) or Discord after the email. Delivery failures are logged, never raised — email stays the primary channel.
* **Backtest Separation:** `core/signal_engine` takes dataframes and performs no I/O, so `core/backtest.py` replays the identical rules over history with brokerage costs and a cash constraint (a position is skipped when the cash is not there).
* **Out-of-Sample Discipline (IMPORTANT):** every rule change must be judged on `run_split()`, which reports the full period, the first `TRAIN_FRACTION` (70%) as in-sample, and the held-back 30% as out-of-sample, each starting from the same equity. Report Profit Factor, Win Rate, Total Return, Exposure % (`exposure_pct`: share of trading days with ≥1 open position), Max Drawdown, Drawdown Duration (`drawdown_duration_days`), Sharpe (vs `RISK_FREE_RATE`, 15%) and Beta, always beside the buy-and-hold benchmark for the same window. An in-sample improvement alone is not evidence. `docs/backtest.json` feeds the public landing page, which must keep showing the out-of-sample row and losing periods.
* **SELL Signal = Exit Alert:** PSX retail swing trading is long-only (no shorting), so SELL is not an independent scan — it is the exit for a position a prior BUY alert opened. Once a symbol's BUY alert fires, treat it as an open position until a SELL closes it. Each EOD run, for any open position, fire SELL when the closing price crosses the entry's Stop-Loss or Take-Profit, or when it closes below the `TRAIL_EMA_PERIOD` (20) EMA — a trailing exit that lets winners run instead of cutting them on a fixed calendar day. There is no time-based exit. Exits are stored per position (`positions.setup`) because they are setup-specific. Do not scan a symbol for a new BUY while it already has an open position.
* **Minimum Holding Lock:** Shares must settle into the account before they can be sold (Sharia possession requirement, plus PSX T+2 settlement). No SELL alert of any kind — including Stop-Loss or Take-Profit — may fire until `MIN_HOLDING_DAYS` (2) have elapsed since the BUY alert.
* **Purification:** Each company's non-compliant income ratio comes from Al-Meezan's "complete ratios" KMI-30 recomposition PDF, parsed into `data/purification_ratios.csv` by `python -m fetchers.purification <pdf> --as-of <date> --source <label>` (refresh after each May/November recomposition). SELL alerts state the ratio, the purification amount on any profit, and a reminder to purify dividends by the same ratio. Ratios above 5% are flagged as compliant only under a special PSX Shariah exception.
* **Left the Sharia Index:** If a held stock drops out of KMI-30, keep evaluating its exit rules and email a warning with a hold-or-sell suggestion (SELL if below the 50-day EMA, in loss, or RSI > 70; otherwise HOLD a few days). The decision stays with the investor.
* **Watchlist:** Every email lists stocks exactly one condition short of a BUY (including stocks blocked only by the market filter or the position cap).
* **Scan Universe:** Sharia-compliant stocks only — the live PSX **KMI All-Share** index (`psxdata.tickers(index="KMIALLSHR")`, ~313 names), pre-filtered with one `psxdata.screener()` call to those above Rs. 10 and 300,000 average volume so ~300 per-symbol fetches become ~85. The exact 20-day SMA and price rules are still enforced on real OHLCV. Refreshed each run with a cached fallback in `data/universe_cache.csv`. Ex-dividend/bonus/right suffixes (`XD`/`XB`/`XR`) are stripped from symbols. If neither live nor cached list is available, abort the run rather than scan an unverified list. Never hardcode or guess compliance status.
* **Alert Wording:** Alerts state that a stock matches the swing-entry criteria; they never claim a price is guaranteed to rise.
* **Async Execution:** The email alert module must be purely asynchronous using `asyncio` and `aiosmtplib`. Do not use `smtplib` synchronously or blocking SMTP calls, to prevent I/O blocking.

## 4. Workflow Preferences
* When writing Python code, favor modular functional design over deep OOP hierarchies unless state management strictly demands classes.
* Do not explain standard Python library functions. Output raw, deployable code blocks primarily.
* Make rules testable; any logic for indicators must be verified against standard mathematical definitions.

## 5. Out of Scope
* Intraday scraping (minute-by-minute data) is entirely out of scope. Do not write code for live WebSocket feeds or order matching execution (no broker API integrations yet).
* Do not enforce standard PEP8 linting rules in our chats; assume a pre-commit hook handles all formatting.