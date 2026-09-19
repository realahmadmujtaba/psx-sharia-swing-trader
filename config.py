import os

import pytz
from dotenv import load_dotenv

load_dotenv()

TIMEZONE = pytz.timezone('Asia/Karachi')

# Kept out of source control; set in the environment before running the agent.
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT")

# Private: only used for the share count in emails, never published to the dashboard.
TRADING_CAPITAL = float(os.getenv("TRADING_CAPITAL", "0")) or None
POSITION_PCT = 0.10
MAX_OPEN_POSITIONS = 5

UNIVERSE_INDEX = "KMI30"
# No new BUY while this index closes below its own EMA_PERIOD-day EMA.
MARKET_INDEX = "KMI30"

EMA_PERIOD = 50
RSI_PERIOD = 14
RSI_LOWER = 30
RSI_UPPER = 45
VOLUME_LOOKBACK = 20
MIN_AVG_VOLUME = 100_000

VOLUME_SPIKE_MULT = 1.5
# Support = the 50-day EMA or the lowest low of the prior SUPPORT_LOOKBACK sessions;
# "near" = close no more than SUPPORT_PROXIMITY_PCT above it.
SUPPORT_LOOKBACK = 20
SUPPORT_PROXIMITY_PCT = 0.03

ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
ATR_TARGET_MULT = 3.0

# Shares must settle into the account (T+2) before they can be sold, so no SELL
# alert (not even stop-loss/take-profit) fires until this many days after entry.
MIN_HOLDING_DAYS = 2

# Longest end of the swing window; an open position is force-exited (SELL) if
# neither the stop-loss nor take-profit has been hit by this many days after entry.
MAX_HOLDING_DAYS = 15

# Above this, a company is only compliant under a special PSX Shariah exception.
PURIFICATION_WARN_PCT = 5.0

EOD_CRON_HOUR = 17
EOD_CRON_MINUTE = 45
