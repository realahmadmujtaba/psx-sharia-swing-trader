"""Generate a dated Markdown market-intelligence article from scan outputs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import config


def _bullet_lines(values: list[str] | None, fallback: str) -> str:
    items = [str(value).strip() for value in (values or []) if str(value).strip()]
    return "\n".join(f"- {value}" for value in items) or f"- {fallback}"


def build_blog_post(
    intelligence: dict,
    portfolio: list[dict],
    date: datetime | None = None,
) -> str:
    """Render a deterministic Markdown post using Gemini output and rankings."""
    current = date or datetime.now(config.TIMEZONE)
    title = f"PSX Daily Intelligence & Value Radar - {current.date().isoformat()}"
    sentiment = intelligence.get("market_sentiment", "Unavailable")
    confidence = intelligence.get("confidence", 0)
    picks = portfolio[:10]
    pick_lines = "\n".join(
        f"- **{item.get('symbol', 'Unknown')}** — composite score "
        f"{item.get('composite_score', '—')}, value {item.get('value_score', '—')}, "
        f"income {item.get('income_score', '—')}, momentum {item.get('momentum_score', '—')}."
        for item in picks
    ) or "- No ranked stocks were available for this report."

    return f"""# {title}

## Market Overview

**Market sentiment:** {sentiment} (confidence: {confidence})

{_bullet_lines(intelligence.get("macro_drivers"), "No macro drivers were reported today.")}

## Top Value & Dividend Picks

The quantitative radar ranks stocks cross-sectionally using value, dividend income,
and 12-week momentum. These are watchlist candidates, not guaranteed returns.

{pick_lines}

## Risk & Sentiment Warnings

{_bullet_lines(intelligence.get("divergence_insights"), "No quantitative/qualitative divergences were reported.")}

### Media Takeaways

{_bullet_lines(intelligence.get("takeaways"), "No media takeaways were available.")}

*Generated {current.isoformat(timespec="minutes")} PKT by PSX Sharia Swing Trader.*
"""


def save_blog_post(
    intelligence: dict,
    portfolio: list[dict],
    output_dir: Path | None = None,
    date: datetime | None = None,
) -> Path:
    """Write the dated article beneath the public docs directory."""
    current = date or datetime.now(config.TIMEZONE)
    directory = output_dir or (config.DOCS_DIR / "blog_posts")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{current.date().isoformat()}_psx_analysis.md"
    path.write_text(build_blog_post(intelligence, portfolio, current), encoding="utf-8")
    return path
