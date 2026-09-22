"""Gemini-powered structured PSX market intelligence."""

from __future__ import annotations

import json
import os

SYSTEM_INSTRUCTION = """
You are a Pakistan Stock Exchange market intelligence analyst. Return only valid JSON:
{"market_sentiment":"Bullish|Neutral|Bearish","confidence":0.0,
"macro_drivers":["..."],"takeaways":["..."],
"stock_flags":[{"symbol":"...","sentiment":"Bullish|Neutral|Bearish","reason":"..."}],
"divergence_insights":["..."]}
Do not invent facts or tickers. Use only the supplied material.
"""


def analyze(articles: list[dict], videos: list[dict], tickers: list[str]) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for sentiment analysis")
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("google-genai is required for sentiment analysis") from exc

    payload = {
        "tickers": tickers,
        "articles": articles,
        "videos": videos,
    }
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=SYSTEM_INSTRUCTION + "\nINPUT:\n" + json.dumps(payload, default=str),
        config={"response_mime_type": "application/json"},
    )
    text = response.text.strip()
    result = json.loads(text)
    required = {"market_sentiment", "confidence", "macro_drivers", "takeaways", "stock_flags"}
    if not required.issubset(result):
        raise ValueError("Gemini response omitted required sentiment fields")
    return result


def daily_report(tickers: list[str], video_ids: list[str] | None = None) -> dict:
    """Collect current media and analyze it; provider errors remain explicit."""
    from scrapers.news_scraper import collect as collect_news
    from scrapers.video_scraper import collect as collect_videos

    articles = collect_news(tickers)
    videos = collect_videos(video_ids or [])
    return analyze(articles, videos, tickers)
