# PSX Sharia Swing Scanner

Weekly multi-factor portfolio engine for the Pakistan Stock Exchange's KMI All-Share Sharia universe.
Each trading day at 17:45 PKT it scans every KMI-30 constituent, applies a fixed rule set to the
closing data, and sends BUY/SELL alerts by email (optionally to a Telegram or Discord webhook),
then publishes a public dashboard.

- Landing page: https://realahmadmujtaba.github.io/psx-sharia-swing-trader/
- Live dashboard: https://realahmadmujtaba.github.io/psx-sharia-swing-trader/dashboard.html

## Architecture

| Layer | Module | Responsibility |
|---|---|---|
| Data | `fetchers/psx_fetcher.py` | `psxdata` OHLCV with retry + backoff |
| Data | `fetchers/universe.py` | live KMI-30 constituents, cached fallback |
| Data | `fetchers/purification.py` | Al-Meezan non-compliant income ratios |
| Signals | `core/indicators.py` | EMA, RSI, ATR, ADX, Bollinger width, rolling return (Wilder smoothing) |
| Signals | `core/signal_engine.py` | entry/exit rules over **any** dataframe — no I/O |
| Risk | `core/risk.py` | ATR stops and risk-based position sizing |
| State | `core/db.py` | SQLite: signal history + open positions (hold-time across runs) |
| Analysis | `core/backtest.py` | replays the rules over years of history |
| Output | `alerts/email_alert.py`, `alerts/webhook.py`, `alerts/dashboard.py` | email digest, webhook push, published JSON |

Signal generation is deliberately separate from data fetching: `signal_engine.snapshot()` and
`evaluate_symbol()` take a dataframe, so the backtest feeds them history and the live scan feeds
them today's data through the same code path.

## Entry rules

The universe is the PSX **KMI All-Share** Sharia index (~313 names), pre-filtered by one screener
call to the liquid ones (~85 scanned per run).

**Weekly trend gate:** the stock close must be above its 100-day EMA and the KMI All-Share
close must be above its own 100-day EMA. **Support/liquidity gate:** price must be within 4%
of its 50-day or 200-day EMA, 20-day average volume must exceed 200,000 shares, and price
must be above Rs. 10.

**Market regime gate (checked before any stock):** no new BUY unless the KMI All-Share index
closes above its own 100-day EMA. Open positions still exit normally when this is false —
only new entries pause.

**Entry (mean reversion):** daily RSI(14) below 38 **or** the close touches/crosses below the
lower 20-day Bollinger Band.

Exits: mean reversion when close rises above the 20-day EMA, volatility target at +2.5 × ATR,
or structure stop when close falls more than 3% below the 50-day EMA. There is no time-based
exit. Nothing sells before day 2 (T+2 settlement, so the shares are actually possessed before
being sold).

## Position sizing

`shares = (equity × 1.5%) / (distance to the 50-day EMA stop)`, capped at 20% of equity in any one stock. A stop-out
therefore costs about 1.5% of the account. Set `TRADING_CAPITAL` in `.env`; share counts appear
only in the private email, never on the public dashboard.

## Running it

**In the cloud (default).** `.github/workflows/daily-scan.yml` runs the scan daily at 15:00 UTC
(20:00 PKT) and pushes the refreshed dashboard; `weekly-backtest.yml` refreshes the backtest every
Saturday. Configuration lives in repo secrets: `SMTP_HOST`, `SMTP_PORT`, `EMAIL_SENDER`,
`EMAIL_PASSWORD`, `EMAIL_RECIPIENT`, `EMAIL_SUBSCRIBERS`, `TRADING_CAPITAL`, and optionally
`WEBHOOK_URL` / `TELEGRAM_CHAT_ID`.

```bash
gh workflow run "Daily EOD scan"     # run it now
gh run watch                          # follow it
```

**Locally.**

```bash
pip install -r requirements.txt
cp .env.example .env                  # then fill in the values
python main.py --once                 # one scan and exit (cron / Task Scheduler)
python main.py                        # stay running; fires at 17:45 PKT via APScheduler
python -m core.backtest --years 3 --save
python -m core.db                     # create or inspect the database
python -m unittest discover tests
```

## Notes on dependencies

`pandas_ta` and TA-Lib are deliberately not used: `pandas_ta` breaks on NumPy 2.x and TA-Lib needs
a compiled C library, which would complicate the GitHub Actions run. The indicators are implemented
directly in `core/indicators.py` with Wilder smoothing and unit-tested against known values.

## Results, honestly

`python -m core.backtest --years 3 --save` reports the full period, the first 70% (in-sample) and
the held-back 30% (out-of-sample) separately, each against buy-and-hold. Latest run, with weekly
20-period trend confirmation and the fundamental value gate active:

| Period | Trades | Win rate | PF | Return | Index | Exposure | Max DD | DD days | Sharpe | Beta |
|---|---|---|---|---|---|---|---|---|---|---|
| In-sample 2023-03 → 2025-09 | 462 | 57.8% | 1.17 | +18.11% | +205.35% | 54.4% | −18.80% | — | −0.47 | 0.33 |
| **Out-of-sample 2025-09 → 2026-09** | **188** | **45.7%** | **0.88** | **−5.59%** | **+11.43%** | **62.0%** | **−16.44%** | **151** | **−1.48** | **0.16** |

The active architecture now ranks the universe cross-sectionally each week: Value (40%), Income
(40%), and 12-week Momentum (20%), then holds the top 10 at equal weights when the KMI All-Share
index is above its 100-day EMA. This replaces binary setup signals and individual stop-losses.

Nothing here demonstrates an edge. The landing page publishes this table as-is; treat the alerts
as a screening shortlist, not investment advice.
