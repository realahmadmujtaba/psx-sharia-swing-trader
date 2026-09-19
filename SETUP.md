# Manual Setup — Things I Can't Do For You

Built and validated against the real `psxdata` package and the live Yahoo Finance API.
Everything below requires your login/credentials.

## Resolved since the first pass

**Fallback data source.** Confirmed live that neither `yfinance` (no `.KH`/`.KA`/`.KAR`/bare-symbol
PSX coverage at all) nor `investpy` (scraper broken by Cloudflare since ~2022) nor `stooq` (no PSX
support) can serve as a working second data source. `fetchers/psx_fetcher.py` now retries
`psxdata.stocks()` itself — up to 3 attempts with exponential backoff, bypassing the disk cache on
retries — instead of falling through to a vendor with zero real coverage. CLAUDE.md updated to match.

**SELL alerts.** Implemented as exit alerts for a position opened by a prior BUY (your choice —
matches long-only PSX swing trading). Once a symbol's BUY alert fires, it's tracked as "open" until
SELL closes it (`core/state.get_open_position`). Each run, an open position exits when price crosses
its stop-loss or take-profit, or when 15 days have elapsed since entry, whichever comes first
(`core/signal_engine.evaluate_exit`, `config.MAX_HOLDING_DAYS`). A symbol with an open position is
skipped for new BUY scanning. Digest emails now show `N BUY / M SELL` and break out exit reason,
entry price, and days held for each SELL. All boundary cases (SL hit, TP hit, day 14 vs. 15 vs. 16)
tested directly.

## 1. Email credentials (I cannot generate these — needs your Google login)

The alert system (`alerts/email_alert.py`) sends via SMTP using `aiosmtplib`. To make it work:

1. Copy `.env.example` to `.env` in the project root.
2. Get a Gmail **App Password** (regular password won't work with 2FA on):
   - Go to https://myaccount.google.com/apppasswords (needs 2-Step Verification enabled first)
   - Generate a 16-character app password for "Mail"
3. Fill in `.env`:
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   EMAIL_SENDER=your-gmail-address@gmail.com
   EMAIL_PASSWORD=<the 16-char app password, no spaces>
   EMAIL_RECIPIENT=where-you-want-alerts@example.com
   ```
   (Any SMTP provider works, not just Gmail — just change `SMTP_HOST`/`SMTP_PORT`.)

## 2. Schedule the daily 17:45 PKT run (Windows Task Scheduler)

I built `main.py` to support both a one-shot mode and a persistent scheduler — you chose
"both." For Windows, Task Scheduler + one-shot is the reliable option:

1. Confirm your Windows clock/timezone is set to Pakistan Standard Time (Task Scheduler fires
   on **local system time**, not PKT specifically — if your machine is in a different
   timezone, adjust the trigger time accordingly).
2. Open Task Scheduler → Create Task:
   - **Trigger:** Daily, 5:45 PM (17:45), "if system starts late, run as soon as possible"
   - **Action:** Start a program
     - Program/script: full path to `python.exe` (run `where python` to find it)
     - Add arguments: `"C:\Users\Abdul Rehman\OneDrive\Desktop\STOCK_AGENT\main.py" --once`
   - Or via command line (adjust the python.exe path from `where python`):
     ```
     schtasks /create /tn "PSX Swing EOD Scan" /tr "\"C:\Path\To\python.exe\" \"C:\Users\Abdul Rehman\OneDrive\Desktop\STOCK_AGENT\main.py\" --once" /sc daily /st 17:45
     ```

Alternative: run `python main.py` (no `--once`) in a terminal you leave open — it starts an
internal APScheduler loop and fires the same job at 17:45 PKT every day on its own.

## 3. Verify it end-to-end

```
cd "C:\Users\Abdul Rehman\OneDrive\Desktop\STOCK_AGENT"
pip install -r requirements.txt
python -m unittest discover tests          # indicator math checks — all passed in my testing
python main.py --once                      # real run: fetches, filters, emails the digest
```

If it errors on the email step, that confirms `.env` isn't filled in yet (step 2). Everything
before that — data fetch, indicator math, signal filtering, CSV logging/dedup — is already
validated against live PSX data and synthetic edge cases.

## 4. Live dashboard

https://realahmadmujtaba.github.io/psx-sharia-swing-trader/

After each scan, `alerts/dashboard.py` writes `docs/data.json` and commits and pushes it, and
GitHub Pages redeploys within a minute or two. The page shows every KMI-30 stock with its latest
close, distance from the 50-day EMA, RSI, volume, status and the reason it didn't qualify, plus the
signal history. The push uses your GitHub login on this PC. If that login expires, the email still
goes out, and the task output shows `[dashboard] publish failed`.

## 5. Ticker list

The agent scans only Sharia-compliant stocks: the live PSX **KMI-30** constituent list, fetched
fresh each run (`fetchers/universe.py`, `config.UNIVERSE_INDEX`). A copy is cached in
`data/universe_cache.csv` in case PSX is unreachable. No SELL alert fires until at least
3 days after the BUY (`config.MIN_HOLDING_DAYS`), so shares have time to settle into your account.
