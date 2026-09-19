from datetime import datetime
from email.message import EmailMessage

import aiosmtplib

import config


def _format_signal(signal: dict) -> str:
    if signal["signal_type"] == "BUY":
        return (
            f"{signal['symbol']} — BUY\n"
            f"  Close: {signal['close_price']:.2f}\n"
            f"  RSI (14): {signal['rsi']:.2f}\n"
            f"  EMA (50): {signal['ema_50']:.2f}\n"
            f"  Avg Volume (20d): {signal['avg_volume']:.0f}\n"
            f"  Stop Loss (4%): {signal['stop_loss']:.2f}\n"
            f"  Take Profit (8%): {signal['take_profit']:.2f}\n"
        )

    return (
        f"{signal['symbol']} — SELL ({signal['exit_reason']})\n"
        f"  Exit Close: {signal['close_price']:.2f}\n"
        f"  Entry Close: {signal['entry_price']:.2f}\n"
        f"  Stop Loss: {signal['stop_loss']:.2f}\n"
        f"  Take Profit: {signal['take_profit']:.2f}\n"
        f"  Days Held: {signal['days_held']}\n"
    )


def _build_digest_message(signals: list[dict]) -> EmailMessage:
    run_time = datetime.now(config.TIMEZONE)
    date_str = run_time.strftime("%Y-%m-%d")

    message = EmailMessage()
    message["From"] = config.EMAIL_SENDER
    message["To"] = config.EMAIL_RECIPIENT

    if not signals:
        message["Subject"] = f"PSX Swing Scan — No Signals — {date_str}"
        body = "No symbols met the entry or exit criteria today.\n"
    else:
        buy_count = sum(1 for signal in signals if signal["signal_type"] == "BUY")
        sell_count = len(signals) - buy_count
        message["Subject"] = f"PSX Swing Alerts — {buy_count} BUY / {sell_count} SELL — {date_str}"
        body = "\n".join(_format_signal(signal) for signal in signals)

    body += f"\nRun at: {run_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
    message.set_content(body)
    return message


async def send_digest(signals: list[dict]) -> None:
    if not (config.EMAIL_SENDER and config.EMAIL_PASSWORD and config.EMAIL_RECIPIENT):
        raise RuntimeError(
            "SMTP_HOST/EMAIL_SENDER/EMAIL_PASSWORD/EMAIL_RECIPIENT must be set in the environment."
        )

    message = _build_digest_message(signals)
    await aiosmtplib.send(
        message,
        hostname=config.SMTP_HOST,
        port=config.SMTP_PORT,
        username=config.EMAIL_SENDER,
        password=config.EMAIL_PASSWORD,
        start_tls=True,
    )
