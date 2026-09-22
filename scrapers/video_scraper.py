"""Recent YouTube transcript ingestion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def fetch_transcript(video_id: str) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise RuntimeError("youtube-transcript-api is required for video ingestion") from exc
    transcript = YouTubeTranscriptApi().fetch(video_id)
    return " ".join(item.text for item in transcript)


def collect(video_ids: list[str], published_at: dict[str, datetime] | None = None) -> list[dict]:
    """Fetch transcripts for videos published within the last 24 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    results = []
    for video_id in video_ids:
        timestamp = (published_at or {}).get(video_id)
        if timestamp is not None and timestamp < cutoff:
            continue
        try:
            results.append({"video_id": video_id, "transcript": fetch_transcript(video_id)})
        except (RuntimeError, OSError, ValueError):
            continue
    return results
