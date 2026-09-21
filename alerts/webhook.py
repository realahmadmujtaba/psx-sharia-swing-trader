"""Push a short summary to Telegram or Discord when a scan produces signals.

Set WEBHOOK_URL (and TELEGRAM_CHAT_ID for Telegram) to enable it; otherwise this
is a no-op. Failures never interrupt the scan — email stays the primary channel.
"""
import requests

import config

TIMEOUT_SECONDS = 15


def build_summary(result: dict) -> str | None:
    signals = result.get("signals", [])
    warnings = result.get("warnings", [])
    if not signals and not warnings:
        return None

    lines = []
    for signal in signals:
        if signal["signal_type"] == "BUY":
            lines.append(
                f"BUY {signal['symbol']} @ Rs. {signal['close_price']:.2f} | "
                f"SL {signal['stop_loss']:.2f} | TP {signal['take_profit']:.2f}"
            )
        else:
            lines.append(
                f"SELL {signal['symbol']} @ Rs. {signal['close_price']:.2f} | "
                f"{signal['exit_reason']} | {signal['pnl_per_share'] / signal['entry_price'] * 100:+.1f}%"
            )
    for warning in warnings:
        lines.append(f"WARNING {warning['symbol']} left {config.UNIVERSE_INDEX} - "
                     f"suggestion: {warning['recommendation']}")

    market = result.get("market")
    if market:
        lines.append(f"Market: {config.MARKET_INDEX} {'up' if market['uptrend'] else 'down'} vs 50-day EMA")
    return "PSX Sharia Swing Scanner\n" + "\n".join(lines)


def _payload(text: str) -> dict:
    if config.TELEGRAM_CHAT_ID:
        return {"chat_id": config.TELEGRAM_CHAT_ID, "text": text}
    return {"content": text}


def notify(result: dict) -> None:
    if not config.WEBHOOK_URL:
        return

    text = build_summary(result)
    if text is None:
        return

    try:
        response = requests.post(config.WEBHOOK_URL, json=_payload(text), timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"[webhook] not delivered: {error}")
