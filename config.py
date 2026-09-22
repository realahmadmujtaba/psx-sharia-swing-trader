import os
from pathlib import Path

import pytz
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
DOCS_DIR = PROJECT_ROOT / "docs"
DATA_DIR = PROJECT_ROOT / "data"

TIMEZONE = pytz.timezone('Asia/Karachi')

# Kept out of source control; set in the environment before running the agent.
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT")
# Extra subscribers, comma-separated; they are BCC'd so addresses stay private.
EMAIL_SUBSCRIBERS = [a.strip() for a in os.getenv("EMAIL_SUBSCRIBERS", "").split(",") if a.strip()]

# Private: only used for the share count in emails, never published to the dashboard.
TRADING_CAPITAL = float(os.getenv("TRADING_CAPITAL", "0")) or None
# Risk-based sizing: shares = (equity * RISK_PER_TRADE_PCT) / (ATR_STOP_MULT * ATR).
RISK_PER_TRADE_PCT = 0.015
# A tight stop would otherwise demand more cash than the account holds.
MAX_POSITION_PCT = 0.20
POSITION_PCT = 0.10  # fallback sizing when ATR is unavailable
MAX_OPEN_POSITIONS = 8

# Optional webhook for Telegram or Discord; empty disables it.
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

UNIVERSE_INDEX = "KMIALLSHR"
# Benchmark for relative strength and for return comparisons (the tradable Sharia index).
MARKET_INDEX = "KMI30"
# Regime gate: the broad Sharia market. No new BUY unless it closes above its own
# REGIME_EMA_PERIOD EMA *and* that EMA is higher than it was REGIME_SLOPE_LOOKBACK days ago,
# so the engine sits in cash through sideways markets instead of being chopped up.
REGIME_INDEX = "KMIALLSHR"
REGIME_EMA_PERIOD = 100
REGIME_SLOPE_LOOKBACK = 5
# Cheap pre-filter from the one-shot screener table, so ~300 symbols are not all fetched.
# Deliberately looser than MIN_AVG_VOLUME; the exact 20-day SMA still decides.
PREFILTER_AVG_VOLUME = 300_000

EMA_PERIOD = 50
RSI_PERIOD = 14
RSI_LOWER = 30
RSI_UPPER = 45
VOLUME_LOOKBACK = 20
# Baseline liquidity for the wider universe: 20-day SMA of volume, and a price floor
# that keeps out penny stocks whose tick size swamps a 1.5 x ATR stop.
MIN_AVG_VOLUME = 500_000
MIN_PRICE = 10.0

VOLUME_SPIKE_MULT = 1.5
# Setup B support test: close no more than this far above the 50-day EMA.
SUPPORT_PROXIMITY_PCT = 0.03

ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
ATR_TARGET_MULT = 3.0

# Trend strength: the 50-day EMA must be rising over EMA_SLOPE_LOOKBACK days, OR ADX above the floor.
EMA_SLOPE_LOOKBACK = 5
ADX_PERIOD = 14
ADX_MIN = 20.0
# Relative strength: the stock's N-day return must beat the index's over the same window.
RS_LOOKBACK = 20
# Macro trend: close must also be above this longer EMA.
MACRO_EMA_PERIOD = 100

# Shares must settle into the account (T+2) before they can be sold, so no SELL
# alert (not even stop-loss/take-profit) fires until this many days after entry.
MIN_HOLDING_DAYS = 2

# Exits are per setup. Breakouts trail a rising EMA; pullbacks take profit when price
# reverts to that same EMA, because a pullback entry starts below it by construction.
TRAIL_EMA_PERIOD = 20
# Setup B hard stop: support is broken when price closes this far below the 50-day EMA.
PULLBACK_STOP_BELOW_EMA_PCT = 0.02

# Annualised risk-free rate used for the Sharpe ratio (Pakistan T-bill territory).
RISK_FREE_RATE = 0.15
# Out-of-sample split: the first share of history is train, the remainder is test.
TRAIN_FRACTION = 0.70
# A setup must clear this profit factor out-of-sample to stay in the engine.
MIN_OOS_PROFIT_FACTOR = 1.20

# Above this, a company is only compliant under a special PSX Shariah exception.
PURIFICATION_WARN_PCT = 5.0

# PSX brokerage per side, applied in the backtest so results are not flattering.
COMMISSION_PCT = 0.0015
EOD_CRON_HOUR = 17
EOD_CRON_MINUTE = 45
