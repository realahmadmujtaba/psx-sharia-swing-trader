"""Gemini-powered structured PSX market intelligence."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

import config

SYSTEM_INSTRUCTION = """
You are a Pakistan Stock Exchange market intelligence analyst. Return only valid JSON.
Schema:
{"market_sentiment":"Bullish|Neutral|Bearish","confidence":0.0,
"macro_drivers":["..."],"takeaways":["..."],
"stock_flags":[{"symbol":"...","sentiment":"Bullish|Neutral|Bearish","reason":"..."}],
"divergence_insights":["..."],
"urdu_briefings":[
  {"symbol":"...","final_ai_score":0.0,
   "briefing":{
     "ٹارگٹ اور ٹائم فریم":"...",
     "بنیادی مضبوطی اور تحفظ":"...",
     "تکنیکی بریک آؤٹ":"...",
     "حقیقی بائنگ بمقابلہ فیک بائنگ":"...",
     "ملکی و عالمی معاشی محرکات":"..."
   }
  }
]}
Do not invent facts or tickers. Use only the supplied material. Write in natural Urdu, include words like بریک آؤٹ and والیوم, and keep the response concise and actionable.
"""


def _briefing_record(row: dict) -> dict:
    symbol = str(row.get("symbol", "UNKNOWN"))
    score = float(row.get("final_ai_score", row.get("composite_score", 0.0)))
    sector = row.get("sector") or "General"
    return {
        "symbol": symbol,
        "ticker": symbol,
        "price": row.get("close"),
        "final_ai_score": round(score, 2),
        "sector": sector,
        "briefing": {
            "ٹارگت اور ٹائم فریم": f"{symbol} کو 2–20 دن کے Swing ٹائم فریم میں Buy Zone اور ٹارگٹ پر غور کریں۔",
            "بنیادی مضبوطی اور تحفظ": "اگر Swing ناکام ہو تو کمپنی کی بنیادی مضبوطی، مناسب نقد بہاؤ اور معقول قیمت کے ساتھ محفوظ لانگ پوزیشن کی بنیاد بن سکتی ہے۔",
            "تکنیکی بریک آؤٹ": "روزانہ اور ہفتہ واری چارٹ پر بریک آؤٹ کی ساخت واضح ہو تو زبردست خریداری کے امکانات بنتے ہیں۔",
            "حقیقی بائنگ بمقابلہ فیک بائنگ": "والیوم کو پورے رینج کے مقابلے میں جانچیں تاکہ حقیقی خریداری اور فیک بائنگ کا فرق واضح ہو۔",
            "ملکی و عالمی معاشی محرکات": "مذکورہ سیکٹر کو مارکیٹ رجحان، اوسط قیمت، اور عالمی خام تیل/ڈالر کے ردعمل سے جوڑ کر دیکھیں۔",
        },
    }


def build_urdu_briefing_payload(rows: list[dict], limit: int = 5) -> dict:
    """Prepare a top-N Urdu UI payload that can be written to docs/urdu_briefing.json."""
    ranked = [dict(row) for row in rows if isinstance(row, dict)]
    ranked.sort(key=lambda item: float(item.get("final_ai_score", item.get("composite_score", 0.0))), reverse=True)
    briefings = [_briefing_record(row) for row in ranked[:limit]]
    return {"briefings": briefings}


def write_urdu_briefing(rows: list[dict], output_path: str | Path | None = None, limit: int = 5) -> dict:
    payload = build_urdu_briefing_payload(rows, limit=limit)
    target = Path(output_path) if output_path is not None else config.DOCS_DIR / "urdu_briefing.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


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
    result.setdefault("urdu_briefings", [])
    return result


def daily_report(tickers: list[str], video_ids: list[str] | None = None) -> dict:
    """Collect current media and analyze it; provider errors remain explicit."""
    from scrapers.news_scraper import collect as collect_news
    from scrapers.video_scraper import collect as collect_videos

    articles = collect_news(tickers)
    videos = collect_videos(video_ids or [])
    return analyze(articles, videos, tickers)
