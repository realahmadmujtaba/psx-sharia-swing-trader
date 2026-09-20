from datetime import datetime, timedelta
from email.message import EmailMessage

import aiosmtplib

import config

EXIT_REASONS = {
    "STOP_LOSS": "Stop-loss hit",
    "TAKE_PROFIT": "Take-profit hit",
    "MAX_HOLD": f"Max holding period ({config.MAX_HOLDING_DAYS} days) reached",
}


def rs(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}Rs. {abs(value):,.2f}"


def _purification_line(signal: dict) -> str:
    pct = signal.get("purification_pct")
    if pct is None:
        return "  Purification ratio: not in the Al-Meezan list - check before trading\n"
    line = f"  Purification ratio: {pct:.2f}% of income (Al-Meezan)\n"
    if pct > config.PURIFICATION_WARN_PCT:
        line += (f"  Note: above the normal {config.PURIFICATION_WARN_PCT:.0f}% limit; "
                 "compliant only under a special PSX Shariah exception\n")
    return line


def _format_buy(signal: dict) -> str:
    close = signal["close_price"]
    earliest_sell = signal["timestamp"].date() + timedelta(days=config.MIN_HOLDING_DAYS)
    text = (
        f"{signal['symbol']} - BUY (matches all swing-entry rules)\n"
        f"  Close: {rs(close)}\n"
        f"  Stop-loss: {rs(signal['stop_loss'])}  ({config.ATR_STOP_MULT:g} x ATR below; risk {rs(close - signal['stop_loss'])}/share)\n"
        f"  Take-profit: {rs(signal['take_profit'])}  ({config.ATR_TARGET_MULT:g} x ATR above; reward {rs(signal['take_profit'] - close)}/share)\n"
        f"  ATR (14): {rs(signal['atr'])}\n"
    )
    if signal.get("shares"):
        text += (f"  Suggested size: {signal['shares']:,} shares = {rs(signal['shares'] * close)} "
                 f"({config.POSITION_PCT:.0%} of capital)\n")
    text += (
        f"  RSI (14): {signal['rsi']:.1f}   50-day EMA: {rs(signal['ema_50'])}\n"
        f"  Volume today: {signal['volume_ratio']:.1f} x the 20-day average\n"
        f"  Support: 50-day EMA {rs(signal['ema_50'])} / 20-day low {rs(signal['support_low'])}\n"
        f"{_purification_line(signal)}"
        f"  Earliest sell alert: {earliest_sell} (after settlement)\n"
    )
    return text


def _format_sell(signal: dict) -> str:
    pnl = signal["pnl_per_share"]
    pct = pnl / signal["entry_price"] * 100
    text = (
        f"{signal['symbol']} - SELL ({EXIT_REASONS.get(signal['exit_reason'], signal['exit_reason'])})\n"
        f"  Exit close: {rs(signal['close_price'])}   Entry: {rs(signal['entry_price'])}   Days held: {signal['days_held']}\n"
        f"  Profit/loss: {rs(pnl)} per share ({pct:+.1f}%)\n"
    )
    if signal.get("pnl_total") is not None:
        text += f"  Total profit/loss: {rs(signal['pnl_total'])} on {signal['shares']:,} shares\n"
    text += _purification_line(signal)
    if signal.get("purification_on_profit"):
        text += f"  Purify from this profit: {rs(signal['purification_on_profit'])}\n"
    if signal.get("purification_pct") is not None:
        text += f"  Also purify {signal['purification_pct']:.2f}% of any dividend received while holding.\n"
    return text


def _format_warning(warning: dict) -> str:
    return (
        f"{warning['symbol']} - LEFT {config.UNIVERSE_INDEX} (no longer Sharia-screened)\n"
        f"  Suggestion: {'SELL now' if warning['recommendation'] == 'SELL' else 'Can HOLD a few days'}\n"
        f"  Why: {warning['reason']}\n"
        f"  Close: {rs(warning['close_price'])}   Entry: {rs(warning['entry_price'])}   Days held: {warning['days_held']}\n"
        f"  The decision is yours.\n"
    )


def _format_market(market: dict | None) -> str:
    if market is None:
        return f"Market: {config.MARKET_INDEX} data unavailable - new BUY signals paused today.\n"
    trend = "UP (BUY signals allowed)" if market["uptrend"] else "DOWN (new BUY signals paused)"
    return (f"Market: {config.MARKET_INDEX} {market['close']:,.0f} vs 50-day EMA "
            f"{market['ema_50']:,.0f} - trend {trend}\n")


def _build_digest_message(result: dict) -> EmailMessage:
    run_time = datetime.now(config.TIMEZONE)
    date_str = run_time.strftime("%Y-%m-%d")
    signals = result["signals"]
    buys = [s for s in signals if s["signal_type"] == "BUY"]
    sells = [s for s in signals if s["signal_type"] == "SELL"]
    warnings = result.get("warnings", [])
    watchlist = result.get("watchlist", [])

    message = EmailMessage()
    message["From"] = config.EMAIL_SENDER
    message["To"] = config.EMAIL_RECIPIENT
    if config.EMAIL_SUBSCRIBERS:
        message["Bcc"] = ", ".join(config.EMAIL_SUBSCRIBERS)

    headline = f"{len(buys)} BUY / {len(sells)} SELL" if signals else "No Signals"
    if warnings:
        headline += f" / {len(warnings)} WARNING"
    message["Subject"] = f"PSX Swing - {headline} - {date_str}"

    parts = [_format_market(result.get("market"))]
    if warnings:
        parts.append("=== WARNINGS ===\n" + "\n".join(_format_warning(w) for w in warnings))
    if sells:
        parts.append("=== SELL ===\n" + "\n".join(_format_sell(s) for s in sells))
    if buys:
        parts.append("=== BUY ===\n" + "\n".join(_format_buy(s) for s in buys))
    if not signals:
        parts.append("No stock met the entry or exit rules today.\n")
    if watchlist:
        lines = [f"  {w['symbol']}: missing {w['missing']} (close {rs(w['close'])}, RSI {w['rsi']:.1f})"
                 for w in watchlist]
        parts.append("=== WATCHLIST (one condition short) ===\n" + "\n".join(lines) + "\n")

    parts.append(
        "Signals mean a stock matched fixed rules on end-of-day data. They are not a guarantee the price will rise.\n"
        f"Run at: {run_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
    )
    message.set_content("\n".join(parts))
    return message


async def send_digest(result: dict) -> None:
    if not (config.EMAIL_SENDER and config.EMAIL_PASSWORD and config.EMAIL_RECIPIENT):
        raise RuntimeError(
            "SMTP_HOST/EMAIL_SENDER/EMAIL_PASSWORD/EMAIL_RECIPIENT must be set in the environment."
        )

    message = _build_digest_message(result)
    await aiosmtplib.send(
        message,
        hostname=config.SMTP_HOST,
        port=config.SMTP_PORT,
        username=config.EMAIL_SENDER,
        password=config.EMAIL_PASSWORD,
        start_tls=True,
    )
