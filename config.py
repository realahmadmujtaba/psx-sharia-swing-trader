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

UNIVERSE_INDEX = "KMI30"

EMA_PERIOD = 50
RSI_PERIOD = 14
RSI_LOWER = 30
RSI_UPPER = 45
VOLUME_LOOKBACK = 20
MIN_AVG_VOLUME = 100_000

STOP_LOSS_PCT = 0.04
TAKE_PROFIT_PCT = 0.08

# Shares must settle into the account before they can be sold, so no SELL alert
# (not even stop-loss/take-profit) fires until this many days after entry.
MIN_HOLDING_DAYS = 3

# Longest end of the 3-15 day swing window; an open position is force-exited
# (SELL) if neither the stop-loss nor take-profit has been hit by this many
# days after entry.
MAX_HOLDING_DAYS = 15

EOD_CRON_HOUR = 17
EOD_CRON_MINUTE = 45
