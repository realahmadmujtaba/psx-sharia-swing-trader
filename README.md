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

**Market regime gate (checked before any stock):** no new BUY unless the KMI All-Share index
closes above its own 100-day EMA *and* that EMA is higher than 5 sessions ago. Open positions
still exit normally when this is false — only new entries pause.

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
the held-back 30% (out-of-sample) separately, each against buy-and-hold. Latest run, with the
market regime gate active:

| Period | Trades | Win rate | PF | Return | Index | Exposure | Max DD | DD days | Sharpe | Beta |
|---|---|---|---|---|---|---|---|---|---|---|
| In-sample 2023-03 → 2025-09 | 317 | 43.2% | 1.53 | +186.8% | +205.4% | 93.3% | −16.7% | 90 | 1.17 | 0.66 |
| **Out-of-sample 2025-09 → 2026-09** | **145** | **29.0%** | **0.83** | **−20.3%** | **+11.4%** | **82.9%** | **−27.7%** | **244** | **−1.26** | **0.26** |

**The regime gate did not fix it — and the reason is worth knowing.** It requires the KMI
All-Share to be above a *rising* 100-day EMA, but after the prior rally that EMA kept climbing on
its own inertia: it was only closed 22% of the out-of-sample window, so the strategy stayed almost
as exposed (83% of days) through the exact chop that hurt it. A 100-day EMA is too slow to detect
a market that goes sideways after a huge run-up. The drawdown also went underwater for 244 of 263
out-of-sample trading days — essentially the whole period.

Setup B (pullback), re-checked with the gate active: out-of-sample profit factor 0.71, still below
the 1.20 keep threshold, so it stays retired.

Nothing here demonstrates an edge. The landing page publishes this table as-is; treat the alerts
as a screening shortlist, not investment advice.
