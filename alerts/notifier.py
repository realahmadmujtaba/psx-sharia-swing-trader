"""Daily two-stock AI signal notification."""

import argparse
import asyncio
from email.message import EmailMessage
from datetime import datetime

import aiosmtplib

import config


def build_portfolio_message(
    portfolio: list[dict],
    market: dict | None,
    intelligence: dict | None = None,
) -> EmailMessage:
    message = EmailMessage()
    sender = config.SMTP_EMAIL or config.EMAIL_SENDER
    recipient = config.RECIPIENT_EMAIL or config.EMAIL_RECIPIENT
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = f"PSX Daily AI Signals ({datetime.now(config.TIMEZONE).date()})"
    rows = "".join(
        f"<tr><td>{item['symbol']}</td><td>{item.get('pe', 'N/A')}</td>"
        f"<td>{item.get('dividend_yield', 'N/A')}</td>"
        f"<td>{item.get('momentum_score', 0):.2f}</td>"
        f"<td>{item.get('qualitative_flag', '—')}</td>"
        f"<td>{item.get('composite_score', 0):.2f}</td></tr>"
        for item in portfolio
    )
    regime = "BULLISH" if market and market.get("uptrend") else "CASH / NOT BULLISH"
    html = (
        f"<h2>PSX Daily AI Signals</h2><p>Market regime: <b>{regime}</b></p>"
        "<table border='1' cellpadding='6'><tr><th>Ticker</th><th>P/E</th>"
        "<th>Dividend Yield</th><th>Momentum Score</th><th>Total Score</th><th>News Flag</th></tr>"
        f"{rows}</table>"
    )
    intelligence = intelligence or {}
    daily_signals = intelligence.get("daily_signals", [])
    signal_rows = "".join(
        f"<tr><td>{item.get('symbol')}</td><td>{item.get('action', 'WATCH')}</td>"
        f"<td>{float(item.get('score', 0)):.2f}</td><td>{item.get('reason', '')}</td>"
        f"<td>{item.get('risk', '')}</td></tr>"
        for item in daily_signals[:2]
    )
    evidence_items = []
    for item in daily_signals[:2]:
        for source in item.get("news_evidence", [])[:3]:
            if isinstance(source, dict):
                evidence_items.append(
                    f"{item.get('symbol')}: {source.get('source', 'Source')} - "
                    f"{source.get('title', '')} ({source.get('url', '')})"
                )
            else:
                evidence_items.append(f"{item.get('symbol')}: {source}")
    evidence = "".join(f"<li>{item}</li>" for item in evidence_items)
    html += (
        "<h2>Two-stock update from news, blogs, and market data</h2>"
        "<table border='1' cellpadding='6'><tr><th>Ticker</th><th>Action</th>"
        "<th>AI score</th><th>Reason</th><th>Risk</th></tr>"
        f"{signal_rows}</table>"
        + (f"<p><b>News evidence</b></p><ul>{evidence}</ul>" if evidence else "")
    )
    takeaways = intelligence.get("takeaways", ["No sentiment report available."])
    bullets = "".join(f"<li>{item}</li>" for item in takeaways[:4])
    html += (
        "<h2>Daily Market &amp; News Intelligence</h2>"
        f"<p>Sentiment: <b>{intelligence.get('market_sentiment', 'Unavailable')}</b> "
        f"(confidence {intelligence.get('confidence', 0):.0%})</p>"
        f"<ul>{bullets}</ul>"
        "<h2>Buy/Sell Improvement Insights</h2><ul>"
        + "".join(f"<li>{item}</li>" for item in intelligence.get("divergence_insights", []))
        + "</ul>"
    )
    briefings = intelligence.get("urdu_briefings") or []
    if briefings:
        cards = []
        for record in briefings[:5]:
            briefing = record.get("briefing", {})
            cards.append(
                "<div><h3>{symbol}</h3><p><b>Final AI Score:</b> {score}</p>"
                + "".join(f"<p><b>{k}</b>: {v}</p>" for k, v in briefing.items())
                + "</div>"
            )
        html += "<h2>اردو مارکیٹ بریفنگ</h2>" + "".join(cards)
    message.set_content(
        f"Market regime: {regime}\nDaily signals: "
        + ", ".join(f"{item.get('symbol')} ({item.get('action', 'WATCH')})" for item in daily_signals[:2])
    )
    message.add_alternative(html, subtype="html")
    return message


async def send_portfolio_alert(result: dict, intelligence: dict | None = None) -> None:
    sender = config.SMTP_EMAIL or config.EMAIL_SENDER
    password = config.SMTP_PASSWORD or config.EMAIL_PASSWORD
    recipient = config.RECIPIENT_EMAIL or config.EMAIL_RECIPIENT
    if not (sender and password and recipient):
        raise RuntimeError("SMTP_EMAIL/SMTP_PASSWORD/RECIPIENT_EMAIL must be set.")
    flags = {
        item.get("symbol"): item.get("sentiment", "Neutral")
        for item in (intelligence or {}).get("stock_flags", [])
    }
    enriched = [
        {**item, "qualitative_flag": flags.get(item.get("symbol"), "—")}
        for item in result.get("portfolio", [])
    ]
    await aiosmtplib.send(
        build_portfolio_message(enriched, result.get("market"), intelligence),
        hostname=config.SMTP_HOST,
        port=config.SMTP_PORT,
        username=sender,
        password=password,
        start_tls=True,
    )


async def _test() -> int:
    try:
        await send_portfolio_alert({
            "market": {"uptrend": True},
            "portfolio": [{
                "symbol": "TEST",
                "pe": 10.0,
                "dividend_yield": 0.05,
                "momentum_score": 50.0,
                "composite_score": 50.0,
            }],
        })
    except RuntimeError as exc:
        print(f"Notifier test not sent: {exc}")
        return 2
    except (OSError, aiosmtplib.SMTPException) as exc:
        print(f"Notifier SMTP test failed: {exc}")
        return 1
    print("Notifier test email sent.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the PSX Top 10 email notification.")
    parser.add_argument("--test", action="store_true", help="Send a test Top 10 digest.")
    args = parser.parse_args()
    if not args.test:
        parser.error("use --test to send a connectivity test")
    raise SystemExit(asyncio.run(_test()))


if __name__ == "__main__":
    main()
