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
"daily_signals":[
  {"symbol":"...","action":"BUY|WATCH|AVOID","score":0.0,
   "reason":"...","research_priority":"High|Medium|Low",
   "news_evidence":[{"source":"...","title":"...","url":"..."}],"risk":"...",
   "selection_checks":[
     {"question":"Is the price/volume move confirmed?","answer":"...","status":"confirmed|unverified|negative"},
     {"question":"Is there relevant fresh news or an event?","answer":"...","status":"confirmed|unverified|negative"},
     {"question":"Does the company have real business exposure?","answer":"...","status":"confirmed|unverified|negative"},
     {"question":"Are fundamentals, valuation, and cash flow acceptable?","answer":"...","status":"confirmed|unverified|negative"},
     {"question":"Is liquidity sufficient for a PSX swing trade?","answer":"...","status":"confirmed|unverified|negative"},
     {"question":"What is the strongest risk or counterargument?","answer":"...","status":"confirmed|unverified|negative"},
     {"question":"What evidence would invalidate this priority?","answer":"...","status":"confirmed|unverified|negative"}
   ]}
],
"urdu_briefings":[
  {"symbol":"...","final_ai_score":0.0,
   "briefing":{
     "ٹارگٹ اور ٹائم فریم":"...",
     "بنیادی مضبوطی اور تحفظ":"...",
     "تکنیکی بریک آؤٹ":"...",
     "حقیقی بائنگ بمقابلہ فیک بائنگ":"...",
     "ملکی و عالمی معاشی محرکات":"...",
     "سپلائی چین میں مقام اور اصل رکاوٹ":"...",
     "ثبوت اور اگلا چیک":"...",
     "مخالف دلیل اور فیصلہ بدلنے کی شرط":"..."
   },
   "evidence":{
     "volume_ratio":0.0,"volume_average_shares":0.0,"volume_today_shares":0.0,
     "stop_loss":0.0,"take_profit":0.0,"holding_days":"2-20",
     "sources":[{"title":"...","url":"...","type":"primary|media|lead"}]
   }
  }
]}
Do not invent facts, prices, ratios, or tickers. Use only the supplied material and quote numeric evidence.
Select exactly two daily_signals and exactly two urdu_briefings from the supplied candidates.
Apply only relevant parts of this research strategy before ranking them:
1. Verify the current PSX theme, company event, or market driver from the supplied fresh news
   and blogs. If no relevant theme exists, do not invent one.
2. Use supply-chain analysis only when the evidence concerns a product, customer, capacity,
   order, qualification, import input, or infrastructure constraint. Otherwise mark it
   "not applicable" rather than forcing a narrative onto a bank, refinery, or other stock.
3. Separate a media theme from disclosed company exposure, orders, production, revenue,
   margins, cash flow, valuation, financing, and governance. Never turn a rumor, partnership,
   sample, patent, or repeated article into a confirmed order or revenue claim.
4. Prefer official PSX/company disclosures and credible Pakistani financial media. Use blogs or
   social posts only as leads, label them unverified, and include source URLs.
5. Treat supplied psxdata OHLCV and fundamentals as the PSX market-data sources. Do not use
   China-only sources such as Eastmoney, Tencent, CNINFO, Baostock, or A-share ticker rules.
6. Check only available dimensions: price/volume trend, liquidity, market regime, relevant
   corporate/event news, fundamentals or valuation, and financing/governance risk. Mark missing
   dimensions "not verified"; never fill gaps with assumptions.
7. State the strongest counterargument and the specific next disclosure or event that would
   lower the research priority. Research priority is not a return forecast or a forced BUY.
8. Answer every selection_checks question for every selected stock. Select the top stocks only
   when their technical evidence and research evidence are stronger than the alternatives.
   A missing answer is "unverified", not a positive assumption. Do not rank a stock highly
   solely because it has an attractive story or a high technical score.
Prioritize candidates with fresh, symbol-specific evidence and confirm it against supplied
technical data. If evidence is weak, use WATCH rather than BUY. Never select a ticker outside
candidates. The two signals are research priorities, not guaranteed trade instructions.
The volume section MUST state: "Volume is N% above/below the 20-day average (today: X shares; average: Y shares)." Never say only "volume is good".
Use a decisive, professional Urdu tone with "اسٹاپ لاس", "ٹیک پرافٹ", "بریک آؤٹ", and "والیوم".
State the action, invalidation level, 2–20 day timeframe, evidence strength, supply-chain role,
counterargument, and next verification step. Do not invent a target price or company fact.
"""


def _briefing_record(row: dict) -> dict:
    symbol = str(row.get("symbol", "UNKNOWN"))
    score = float(row.get("final_ai_score", row.get("composite_score", 0.0)))
    sector = row.get("sector") or "General"
    today_volume = float(row.get("volume", row.get("latest_volume", 0)) or 0)
    average_volume = float(row.get("avg_volume", 0) or 0)
    ratio = float(row.get("volume_ratio", 0) or 0)
    volume_change = (ratio - 1) * 100 if ratio else 0.0
    direction = "above" if volume_change >= 0 else "below"
    stop_loss = row.get("stop_loss", row.get("close"))
    take_profit = row.get("take_profit", row.get("close"))
    return {
        "symbol": symbol,
        "ticker": symbol,
        "price": row.get("close"),
        "final_ai_score": round(score, 2),
        "sector": sector,
        "briefing": {
            "ٹارگت اور ٹائم فریم": f"{symbol} کو 2–20 دن کے Swing ٹائم فریم میں Buy Zone اور ٹارگٹ پر غور کریں۔",
            "بنیادی مضبوطی اور تحفظ": "بنیادیات، نقد بہاؤ، valuation اور governance کی تازہ تصدیق اس fallback میں دستیاب نہیں؛ اسے غیرمصدقہ سمجھیں۔",
            "تکنیکی بریک آؤٹ": "یہ صرف دستیاب تکنیکی اسکریننگ امیدوار ہے؛ بریک آؤٹ اور حقیقی طلب کی الگ تصدیق ضروری ہے۔",
            "حقیقی بائنگ بمقابلہ فیک بائنگ": f"Volume is {abs(volume_change):.1f}% {direction} the 20-day average (today: {today_volume:,.0f} shares; average: {average_volume:,.0f} shares). اسی والیوم پر حقیقی بائنگ یا فیک بائنگ کا فیصلہ کریں۔",
            "ملکی و عالمی معاشی محرکات": "متعلقہ تازہ خبر یا macro driver اس fallback میں verify نہیں ہوا۔",
            "سپلائی چین میں مقام اور اصل رکاوٹ": "اس کمپنی کے لیے supply-chain thesis لاگو ہے یا نہیں، تازہ evidence کے بغیر verify نہیں کیا جا سکتا۔",
            "ثبوت اور اگلا چیک": "تازہ کمپنی disclosure، PSX notice، مالیاتی رپورٹ اور متعلقہ خبر چیک کریں۔",
            "مخالف دلیل اور فیصلہ بدلنے کی شرط": "کمزور volume، منفی disclosure، liquidity issue یا thesis کی عدم تصدیق research priority کم کرے گی۔",
        },
        "evidence": {
            "volume_ratio": round(ratio, 4),
            "volume_average_shares": round(average_volume, 2),
            "volume_today_shares": round(today_volume, 2),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "holding_days": "2-20",
            "sources": [],
        },
        "selection_checks": [
            {"question": "Is the price/volume move confirmed?", "answer": "Technical screen only; independent confirmation is required.", "status": "unverified"},
            {"question": "Is there relevant fresh news or an event?", "answer": "Fresh AI/news evidence was unavailable in fallback mode.", "status": "unverified"},
            {"question": "Does the company have real business exposure?", "answer": "Not verified from fallback data.", "status": "unverified"},
            {"question": "Are fundamentals, valuation, and cash flow acceptable?", "answer": "Not verified from fallback data.", "status": "unverified"},
            {"question": "Is liquidity sufficient for a PSX swing trade?", "answer": "Liquidity is reflected only by the supplied volume metrics.", "status": "unverified"},
            {"question": "What is the strongest risk or counterargument?", "answer": "Weak volume or negative disclosure can invalidate the idea.", "status": "unverified"},
            {"question": "What evidence would invalidate this priority?", "answer": "A failed technical setup or contradictory company disclosure.", "status": "unverified"},
        ],
    }


def build_urdu_briefing_payload(rows: list[dict], limit: int = 5) -> dict:
    """Prepare a top-N fallback Urdu UI payload from technical candidates."""
    ranked = [dict(row) for row in rows if isinstance(row, dict)]
    ranked.sort(key=lambda item: float(item.get("final_ai_score", item.get("composite_score", 0.0))), reverse=True)
    briefings = [_briefing_record(row) for row in ranked[:limit]]
    return {"briefings": briefings}


def build_ai_urdu_briefing_payload(
    briefings: list[dict],
    candidates: list[dict],
    limit: int = 2,
) -> dict:
    """Keep only AI briefings for known candidates, with at most two daily picks."""
    allowed = {str(row.get("symbol", "")).upper() for row in candidates}
    valid = []
    seen = set()
    for record in briefings:
        if not isinstance(record, dict):
            continue
        symbol = str(record.get("symbol", record.get("ticker", ""))).upper()
        if symbol in allowed and symbol not in seen and isinstance(record.get("briefing"), dict):
            valid.append({**record, "symbol": symbol, "ticker": symbol})
            seen.add(symbol)
    return {"briefings": valid[:limit]}


def write_urdu_briefing(rows: list[dict], output_path: str | Path | None = None, limit: int = 5) -> dict:
    payload = build_urdu_briefing_payload(rows, limit=limit)
    target = Path(output_path) if output_path is not None else config.DOCS_DIR / "urdu_briefing.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def analyze(
    articles: list[dict],
    videos: list[dict],
    tickers: list[str],
    candidates: list[dict] | None = None,
) -> dict:
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
        "candidates": candidates or [],
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
    signals = result.get("daily_signals", [])
    allowed = {str(item.get("symbol", "")).upper() for item in candidates or []}
    valid_signals = []
    for signal in signals:
        symbol = str(signal.get("symbol", "")).upper()
        if symbol in allowed and symbol not in {item["symbol"] for item in valid_signals}:
            signal["symbol"] = symbol
            valid_signals.append(signal)
    result["daily_signals"] = valid_signals[:2]
    return result


def daily_report(
    tickers: list[str],
    video_ids: list[str] | None = None,
    candidates: list[dict] | None = None,
) -> dict:
    """Collect current media and analyze it; provider errors remain explicit."""
    from scrapers.news_scraper import collect as collect_news
    from scrapers.video_scraper import collect as collect_videos

    articles = collect_news(tickers)
    videos = collect_videos(video_ids or [])
    return analyze(articles, videos, tickers, candidates)
