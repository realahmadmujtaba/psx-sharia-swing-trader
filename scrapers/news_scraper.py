"""RSS and article-snippet ingestion for Pakistani financial media."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import unescape

import feedparser
from bs4 import BeautifulSoup
import requests

FEEDS = {
    "Business Recorder": "https://www.brecorder.com/feeds/latest-news",
    "Profit": "https://profit.pakistantoday.com.pk/feed/",
    "Dawn Business": "https://www.dawn.com/feeds/business",
    "Mettis Global": "https://mettisglobal.news/feed/",
}


def _text(value: str) -> str:
    return BeautifulSoup(unescape(value or ""), "html.parser").get_text(" ", strip=True)


def fetch_feed(name: str, url: str, timeout: int = 15) -> list[dict]:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "PSX-ResearchBot/1.0"})
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    articles = []
    for entry in parsed.entries:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            timestamp = datetime(*published[:6], tzinfo=timezone.utc)
            if timestamp < cutoff:
                continue
        title = _text(entry.get("title", ""))
        summary = _text(entry.get("summary", entry.get("description", "")))
        if title:
            articles.append({
                "source": name,
                "title": title,
                "summary": summary[:1000],
                "url": entry.get("link", ""),
            })
    return articles


def collect( tickers: list[str], feeds: dict[str, str] | None = None) -> list[dict]:
    """Collect recent articles and keep PSX/ticker-relevant items."""
    terms = {"psx", "kse", "kmi", "karachi stock", "shares", "market"}
    terms.update(ticker.upper() for ticker in tickers)
    articles = []
    for name, url in (feeds or FEEDS).items():
        try:
            articles.extend(fetch_feed(name, url))
        except (OSError, requests.RequestException, ValueError):
            continue
    return [
        article for article in articles
        if any(term.lower() in f"{article['title']} {article['summary']}".lower() for term in terms)
    ]
