# PSX Sharia Swing Scanner

End-of-day swing trading engine for the Pakistan Stock Exchange's KMI-30 Sharia index.
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
| Signals | `core/indicators.py` | EMA, RSI, ATR, ADX, slope, rolling return (Wilder smoothing) |
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

**Baseline — every candidate must clear:** KMI-30 index above its 50-day EMA (market filter);
close above the 100-day EMA; 20-day average volume above 500,000 shares; price above Rs. 10.

**Entry (breakout):** ADX(14) above 20, a 20-day return beating the KMI-30, and volume at least
1.5× its 20-day average.

A pullback setup (RSI < 45 near the 50-day EMA, with mean-reversion exits) was built and then
**removed**: out-of-sample profit factor 0.60 against a 1.20 keep threshold. `core/backtest.py`
still tags pullbacks so that decision can be re-checked.

Exits: stop-loss at 1.5 × ATR, take-profit at 3 × ATR, or a trailing exit when price closes below
its 20-day EMA. There is no time-based exit — winners are allowed to run. Nothing sells before
day 2 (T+2 settlement, so the shares are actually possessed before being sold).

## Position sizing

`shares = (equity × 1.5%) / (1.5 × ATR)`, capped at 20% of equity in any one stock. A stop-out
therefore costs about 1.5% of the account. Set `TRADING_CAPITAL` in `.env`; share counts appear
only in the private email, never on the public dashboard.

## Running it

**In the cloud (default).** `.github/workflows/daily-scan.yml` runs the scan weekdays at 12:45 UTC
(17:45 PKT) and pushes the refreshed dashboard; `weekly-backtest.yml` refreshes the backtest every
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
the held-back 30% (out-of-sample) separately, each against buy-and-hold. Latest run:

| Period | Trades | Win rate | Profit factor | Return | Index | Sharpe | Beta |
|---|---|---|---|---|---|---|---|
| Full 2023-03 → 2026-09 | 407 | 40.3% | 1.24 | +133.9% | +243.6% | 0.50 | 0.47 |
| In-sample 2023-03 → 2025-09 | 287 | 43.2% | 1.45 | +148.3% | +203.6% | 0.99 | 0.47 |
| **Out-of-sample 2025-09 → 2026-09** | **131** | **30.5%** | **0.88** | **−12.1%** | **+12.5%** | **−0.96** | **0.27** |

The strategy underperforms simply holding the KMI-30 in every window, and loses money on the
held-back period. Beta near 0.5 says roughly half the movement is just the market. Nothing here
demonstrates an edge. The landing page publishes this table as-is; treat the alerts as a screening
shortlist, not investment advice.
