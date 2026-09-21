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

UNIVERSE_INDEX = "KMI30"
# No new BUY while this index closes below its own EMA_PERIOD-day EMA.
MARKET_INDEX = "KMI30"

EMA_PERIOD = 50
RSI_PERIOD = 14
RSI_LOWER = 30
RSI_UPPER = 45
VOLUME_LOOKBACK = 20
MIN_AVG_VOLUME = 100_000

# Requiring both a volume spike and near-support left only 3.7 trades a year in the
# 3-year backtest, so they are reported with every signal but do not block one.
STRICT_ENTRY = False
VOLUME_SPIKE_MULT = 1.5
# Support = the 50-day EMA or the lowest low of the prior SUPPORT_LOOKBACK sessions;
# "near" = close no more than SUPPORT_PROXIMITY_PCT above it.
SUPPORT_LOOKBACK = 20
SUPPORT_PROXIMITY_PCT = 0.03

ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
ATR_TARGET_MULT = 3.0

# Trend strength: the 50-day EMA must be rising over EMA_SLOPE_LOOKBACK days, OR ADX above the floor.
EMA_SLOPE_LOOKBACK = 5
ADX_PERIOD = 14
ADX_MIN = 20.0
# Volatility gate: the stock must move enough to reach a 3x ATR target inside the holding window.
MIN_ATR_PCT = 0.02
# Relative strength: the stock's N-day return must beat the index's over the same window.
RS_LOOKBACK = 20
# Macro trend: close must also be above this longer EMA.
MACRO_EMA_PERIOD = 100

# Shares must settle into the account (T+2) before they can be sold, so no SELL
# alert (not even stop-loss/take-profit) fires until this many days after entry.
MIN_HOLDING_DAYS = 2

# Longest end of the swing window; an open position is force-exited (SELL) if
# neither the stop-loss nor take-profit has been hit by this many days after entry.
MAX_HOLDING_DAYS = 15

# Above this, a company is only compliant under a special PSX Shariah exception.
PURIFICATION_WARN_PCT = 5.0

# PSX brokerage per side, applied in the backtest so results are not flattering.
COMMISSION_PCT = 0.0015
# Below this many trades a year, the strict rules are too tight to be usable.
MIN_TRADES_PER_YEAR = 10

EOD_CRON_HOUR = 17
EOD_CRON_MINUTE = 45
