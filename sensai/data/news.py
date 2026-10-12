"""news + sentiment from alpha vantage NEWS_SENTIMENT

free tier = 25 calls/day. 1 call fetches a whole window (30 days min, 1000 articles max)
for a ticker and is cached 6h, get_news and get_sentiment both filter that same call
so 1 ticker = 1 call a day in practice
"""

import csv
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import requests

from sensai.data import DataError, sub_dir
from sensai.data.cache import cached

URL = "https://www.alphavantage.co/query"
MIN_WINDOW_DAYS = 30
def label_for(score):
    """alpha vantage's own thresholds for ticker_sentiment_score"""
    if score is None:
        return None
    if score <= -0.35:
        return "Bearish"
    if score <= -0.15:
        return "Somewhat-Bearish"
    if score < 0.15:
        return "Neutral"
    if score < 0.35:
        return "Somewhat-Bullish"
    return "Bullish"


def _key():
    key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    if not key:
        raise DataError("ALPHAVANTAGE_API_KEY is missing, get a free key at "
                        "https://www.alphavantage.co/support/#api-key and put it in .env")
    return key


def _parse_time(s):
    return datetime.strptime(s, "%Y%m%dT%H%M%S")


def _fetch(ticker, window, now):
    """1 alpha vantage call -> compact articles w/ this ticker's own sentiment, newest 1st"""
    params = {"function": "NEWS_SENTIMENT", "tickers": ticker, "sort": "LATEST", "limit": 1000,
              "time_from": (now - timedelta(days=window)).strftime("%Y%m%dT%H%M"), "apikey": _key()}
    try:
        r = requests.get(URL, params=params, timeout=(10, 30))
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise DataError(f"alpha vantage unreachable: {type(e).__name__}") from None
    except ValueError:
        raise DataError("alpha vantage sent something that isnt json") from None
    # limits and errors come back as a 200 w/ 1 text field
    msg = data.get("Information") or data.get("Note") or data.get("Error Message")
    if msg and "feed" not in data:
        if "rate limit" in msg.lower() or "requests per day" in msg.lower():
            raise DataError("alpha vantage daily limit (25 calls) reached, cached data only until tomorrow")
        if "no articles" in msg.lower():
            return []
        raise DataError(f"alpha vantage: {msg}")
    feed = data.get("feed", [])
    articles = []
    for item in feed:
        mine = next((t for t in item.get("ticker_sentiment", []) if t.get("ticker") == ticker), None)
        if mine is None:
            continue
        articles.append({
            "time": _parse_time(item["time_published"]).isoformat(),
            "title": item.get("title", ""),
            "source": item.get("source", ""),
            "url": item.get("url", ""),
            "summary": item.get("summary", ""),
            "score": round(float(mine["ticker_sentiment_score"]), 4),
            "label": mine.get("ticker_sentiment_label") or label_for(float(mine["ticker_sentiment_score"])),
            "relevance": round(float(mine["relevance_score"]), 4),
        })
    articles.sort(key=lambda a: a["time"], reverse=True)
    # sorted LATEST + 1000 cap: a full feed means the oldest days of the window were cut
    return {"articles": articles, "truncated": len(feed) >= 1000}


def _articles(ticker, days, now=None):
    """(articles in the last `days`, meta, window start, coverage). ticker already uppercased"""
    now = now or datetime.now()
    if not 1 <= days <= 365:
        raise DataError("days must be between 1 and 365")
    window = max(MIN_WINDOW_DAYS, days)
    # keyed on the day so the window moves forward, 6h so the same day gets fresh news
    # "v2": the cached value changed shape (articles + truncated flag)
    got, meta = cached("news", ["v2", ticker, window, now.date().isoformat()], 6 * 3600,
                       lambda: _fetch(ticker, window, now))
    since = (now - timedelta(days=days)).isoformat()
    articles = [a for a in got["articles"] if a["time"] >= since]
    covered_from = min((a["time"][:10] for a in articles), default=None)
    # truncated only matters if the cut reaches into the days asked for
    cut = got["truncated"] and covered_from is not None and covered_from > since[:10]
    coverage = {"covered_from": covered_from, "truncated": bool(cut)}
    if cut:
        coverage["warning"] = (f"alpha vantage caps a call at 1000 articles, so only {covered_from} onwards is "
                               f"covered, not the full {days} days. ask for fewer days for full coverage")
    return articles, meta, since[:10], coverage


def _norm(ticker):
    t = (ticker or "").strip().upper()
    if not t:
        raise DataError("ticker is empty")
    return t


def get_news(ticker, days=7, limit=10, now=None):
    ticker = _norm(ticker)
    if not 1 <= limit <= 50:
        raise DataError("limit must be between 1 and 50")
    now = now or datetime.now()
    articles, meta, since, coverage = _articles(ticker, days, now)
    path = sub_dir("news") / f"{ticker}_{since}_{now.date()}.json"
    path.write_text(json.dumps(articles, ensure_ascii=False, indent=1), encoding="utf-8")
    top = sorted(articles, key=lambda a: (a["relevance"], a["time"]), reverse=True)[:limit]
    return {
        "ticker": ticker,
        "days": days,
        "total_articles": len(articles),
        "articles": [{**a, "summary": a["summary"][:300] + ("..." if len(a["summary"]) > 300 else "")}
                     for a in top],
        "path": str(path),
        "source": "alphavantage",
        **coverage,
        **meta,
    }


def get_sentiment(ticker, days=30, now=None):
    ticker = _norm(ticker)
    now = now or datetime.now()
    articles, meta, since, coverage = _articles(ticker, days, now)

    # relevance weighted, an article that barely mentions the ticker counts less
    def weighted(items):
        total = sum(a["relevance"] for a in items)
        if total == 0:
            return round(sum(a["score"] for a in items) / len(items), 4)
        return round(sum(a["score"] * a["relevance"] for a in items) / total, 4)

    by_day = defaultdict(list)
    for a in articles:
        by_day[a["time"][:10]].append(a)
    path = sub_dir("sentiment") / f"{ticker}_{since}_{now.date()}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "n_articles", "mean_score"])
        for day in sorted(by_day):
            w.writerow([day, len(by_day[day]), weighted(by_day[day])])

    mean = weighted(articles) if articles else None
    return {
        "ticker": ticker,
        "days": days,
        "n_articles": len(articles),
        "mean_score": mean,
        "label": label_for(mean) if articles else "no news",
        "label_counts": dict(Counter(a["label"] for a in articles)),
        "days_with_news": len(by_day),
        "path": str(path),
        "columns": ["date", "n_articles", "mean_score"],
        "source": "alphavantage",
        **coverage,
        **meta,
    }
