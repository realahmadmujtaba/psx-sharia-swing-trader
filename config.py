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
SMTP_EMAIL = os.getenv("SMTP_EMAIL", EMAIL_SENDER)
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", EMAIL_PASSWORD)
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", EMAIL_RECIPIENT)
# Extra subscribers, comma-separated; they are BCC'd so addresses stay private.
EMAIL_SUBSCRIBERS = [a.strip() for a in os.getenv("EMAIL_SUBSCRIBERS", "").split(",") if a.strip()]

# Private: only used for the share count in emails, never published to the dashboard.
TRADING_CAPITAL = float(os.getenv("TRADING_CAPITAL", "0")) or None
# Risk-based sizing: shares = (equity * RISK_PER_TRADE_PCT) / (ATR stop distance).
RISK_PER_TRADE_PCT = 0.015
# A tight stop would otherwise demand more cash than the account holds.
MAX_POSITION_PCT = 0.20
POSITION_PCT = 0.10  # fallback sizing when ATR is unavailable
MAX_OPEN_POSITIONS = 8
PORTFOLIO_SIZE = 10
VALUE_WEIGHT = 0.4
INCOME_WEIGHT = 0.4
MOMENTUM_WEIGHT = 0.2

# Optional webhook for Telegram or Discord; empty disables it.
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

UNIVERSE_INDEX = "KMIALLSHR"
# Benchmark for relative strength and for return comparisons (the tradable Sharia index).
MARKET_INDEX = "KMI30"
# Regime gate: the broad Sharia market. No new BUY unless it closes above its own
# 100-day EMA.
REGIME_INDEX = "KMIALLSHR"
REGIME_EMA_PERIOD = 100
# Cheap pre-filter from the one-shot screener table, so ~300 symbols are not all fetched.
# Deliberately looser than MIN_AVG_VOLUME; the exact 20-day SMA still decides.
PREFILTER_AVG_VOLUME = 300_000

EMA_PERIOD = 50
RSI_PERIOD = 14
RSI_LOWER = 30
RSI_UPPER = 45
VOLUME_LOOKBACK = 20
# Baseline liquidity for mean-reversion candidates.
MIN_AVG_VOLUME = 200_000
MIN_PRICE = 10.0
VALUE_MAX_PE = 12.0
VALUE_MIN_DIVIDEND_YIELD = 0.04
WEEKLY_EMA_PERIOD = 20
WEEKLY_RSI_MIN = 45.0

VOLUME_SPIKE_MULT = 1.5
BB_PERIOD = 20
BB_DEVIATIONS = 2.0
BB_SQUEEZE_LOOKBACK = 30
BB_SQUEEZE_PERCENTILE = 0.30
SUPPORT_PROXIMITY_PCT = 0.04
MEAN_REVERSION_RSI_MAX = 38.0
MEAN_REVERSION_SUPPORT_PERIODS = (50, 200)

ATR_PERIOD = 14
ATR_STOP_MULT = 2.0
ATR_TARGET_MULT = 2.5

ADX_PERIOD = 14
ADX_MIN = 20.0
# Relative strength: the stock's N-day return must beat the index's over the same window.
RS_LOOKBACK = 20
# Macro trend: close must also be above this longer EMA.
MACRO_EMA_PERIOD = 100

# Shares must settle into the account (T+2) before they can be sold, so no SELL
# alert (not even stop-loss/take-profit) fires until this many days after entry.
MIN_HOLDING_DAYS = 2

TRAIL_EMA_PERIOD = 20

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
