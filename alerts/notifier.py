"""Friday Top 10 portfolio notification."""

from email.message import EmailMessage
from datetime import datetime

import aiosmtplib

import config


def build_portfolio_message(portfolio: list[dict], market: dict | None) -> EmailMessage:
    message = EmailMessage()
    sender = config.SMTP_EMAIL or config.EMAIL_SENDER
    recipient = config.RECIPIENT_EMAIL or config.EMAIL_RECIPIENT
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = f"PSX Top 10 Multi-Factor Portfolio ({datetime.now(config.TIMEZONE).date()})"
    rows = "".join(
        f"<tr><td>{item['symbol']}</td><td>{item.get('pe', 'N/A')}</td>"
        f"<td>{item.get('dividend_yield', 'N/A')}</td>"
        f"<td>{item.get('momentum_score', 0):.2f}</td>"
        f"<td>{item.get('composite_score', 0):.2f}</td></tr>"
        for item in portfolio
    )
    regime = "BULLISH" if market and market.get("uptrend") else "CASH / NOT BULLISH"
    html = (
        f"<h2>PSX Top 10 Multi-Factor Portfolio</h2><p>Market regime: <b>{regime}</b></p>"
        "<table border='1' cellpadding='6'><tr><th>Ticker</th><th>P/E</th>"
        "<th>Dividend Yield</th><th>Momentum Score</th><th>Total Score</th></tr>"
        f"{rows}</table>"
    )
    message.set_content(f"Market regime: {regime}\nTop 10: " + ", ".join(i["symbol"] for i in portfolio))
    message.add_alternative(html, subtype="html")
    return message


async def send_portfolio_alert(result: dict) -> None:
    sender = config.SMTP_EMAIL or config.EMAIL_SENDER
    password = config.SMTP_PASSWORD or config.EMAIL_PASSWORD
    recipient = config.RECIPIENT_EMAIL or config.EMAIL_RECIPIENT
    if not (sender and password and recipient):
        raise RuntimeError("SMTP_EMAIL/SMTP_PASSWORD/RECIPIENT_EMAIL must be set.")
    await aiosmtplib.send(
        build_portfolio_message(result.get("portfolio", []), result.get("market")),
        hostname=config.SMTP_HOST,
        port=config.SMTP_PORT,
        username=sender,
        password=password,
        start_tls=True,
    )
