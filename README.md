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

A BUY requires all of:

1. KMI-30 index above its 50-day EMA (market filter)
2. Close above the 50-day EMA **and** above the 100-day EMA (macro trend)
3. 50-day EMA rising over 5 days **or** ADX(14) above 20 (trend strength)
4. RSI(14) between 30 and 45 (pullback)
5. ATR(14) at least 2% of price (volatility gate)
6. 20-day return above the KMI-30's 20-day return (relative strength)
7. 20-day average volume above 100,000 shares (liquidity)

Volume spike (≥1.5× average) and proximity to support are reported with every signal but do not
block one; set `STRICT_ENTRY = True` in `config.py` to require them.

Exits: stop-loss at 1.5 × ATR, take-profit at 3 × ATR, or 15 days — whichever comes first, and
never before day 2 (T+2 settlement, so the shares are actually possessed before being sold).

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

`docs/backtest.json` holds the latest replay, published on the landing page including the periods
where the rules lost money. A train/test grid over stop and target multiples found no setting that
was profitable in both halves of the sample, so the parameters are not tuned to the past. The
current filters produce roughly 4 trades a year — too few to claim a proven edge. Treat the alerts
as a screening shortlist, not investment advice.
