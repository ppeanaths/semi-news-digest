"""Semiconductor news digest: fetch news -> summarize with an LLM -> post to Discord."""
import os
import time
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # gemini (free tier) or claude (paid)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")


def load_config() -> dict:
    with open(ROOT / "config" / "watchlist.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; semi-news-digest/1.0)"}


def fetch_google_news(query: str, limit: int) -> list[dict]:
    """Google News RSS: free, no API key, works from GitHub Actions."""
    url = (
        "https://news.google.com/rss/search?q="
        f"{quote_plus(query + ' when:2d')}&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as e:  # never let one source break the whole digest
        print(f"Google News failed for '{query}': {e}")
        return []
    return [
        {"title": e.get("title", ""), "summary": "", "url": e.get("link", "")}
        for e in feed.entries[:limit]
    ]


def fetch_news(ticker: str, limit: int, name: str = "") -> list[dict]:
    """Return a list of {title, summary, url} for one ticker (deduplicated)."""
    query = f"{name} {ticker} stock".strip()
    items = fetch_google_news(query, limit)
    seen, unique = set(), []
    for i in items:
        key = i["title"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(i)
    print(f"{ticker}: {len(unique[:limit])} articles")
    return unique[:limit]


def build_prompt(news_by_ticker: dict, language: str) -> str:
    blocks = []
    for ticker, items in news_by_ticker.items():
        lines = [f"- {i['title']}" + (f": {i['summary'][:300]}" if i["summary"] else "") for i in items]
        blocks.append(f"## {ticker}\n" + ("\n".join(lines) if lines else "- (no news)"))
    return (
        f"You are a financial news assistant. Write a concise daily digest in {language}.\n"
        "For each ticker: 1-2 sentence summary, then Sentiment: Bullish / Neutral / Bearish.\n"
        "End with a 2-3 line overall takeaway for the semiconductor sector.\n"
        "Only use the news provided. Keep it under 1500 characters total. "
        "Do not give investment advice.\n\n" + "\n\n".join(blocks)
    )


def summarize(prompt: str) -> str:
    if PROVIDER == "claude":
        from anthropic import Anthropic  # pip install anthropic

        resp = Anthropic().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text

    # Default: Google Gemini API (free tier, key from Google AI Studio)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    key = os.environ["GEMINI_API_KEY"].strip()
    if not key.isascii():
        raise SystemExit("GEMINI_API_KEY has non-English characters. Re-create the secret by pasting the key.")
    for attempt in range(5):
        r = requests.post(
            url,
            headers={"x-goog-api-key": key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=60,
        )
        if r.status_code in (429, 500, 503, 504):  # temporary errors: wait and retry
            print(f"Gemini returned {r.status_code}, retrying ({attempt + 1}/5)...")
            time.sleep(5 * 2**attempt)  # 5, 10, 20, 40, 80 seconds
            continue
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    r.raise_for_status()


def send_discord(text: str) -> None:
    webhook = os.environ["DISCORD_WEBHOOK_URL"].strip()
    # Discord limit is 2000 chars per message
    for i in range(0, len(text), 1900):
        r = requests.post(webhook, json={"content": text[i : i + 1900]}, timeout=15)
        r.raise_for_status()


def main() -> None:
    cfg = load_config()
    names = cfg.get("names", {})
    news = {t: fetch_news(t, cfg["max_news_per_ticker"], names.get(t, "")) for t in cfg["tickers"]}
    digest = summarize(build_prompt(news, cfg.get("language", "English")))
    header = "📰 **Semiconductor Daily Digest**\n\n"
    footer = "\n\n_Not investment advice._"
    send_discord(header + digest + footer)
    print("Sent.")


if __name__ == "__main__":
    main()
