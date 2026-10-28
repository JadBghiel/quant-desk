"""news + sentiment from massive (ex polygon.io) /v2/reference/news

free basic plan = 5 calls/min, 2 years of history, 1000 articles per call
1 call fetches a whole window (30 days min) for a ticker, cached 6h, get_news and get_sentiment
both filter that same call
each article has per ticker insights: sentiment (positive / neutral / negative) + a sentence
saying why, mapped to 1 / 0 / -1 for a mean
"""

import csv
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import requests

from sensai.data import DataError, now as _now, sub_dir
from sensai.data.cache import cached

URL = "https://api.massive.com/v2/reference/news"
MIN_WINDOW_DAYS = 30
MAX_ARTICLES = 1000
SCORES = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}


def label_for(score):
    """mean of the 1 / 0 / -1 scores -> a label, Neutral between -0.15 and 0.15"""
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
    key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not key:
        raise DataError("MASSIVE_API_KEY is missing, get a free key at https://massive.com "
                        "and put it in .env")
    return key


def _error(r):
    try:
        data = r.json()
        return data.get("error") or data.get("message") or r.reason
    except ValueError:
        return r.text.strip()[:200] or r.reason


def _fetch(ticker, window, now):
    """1 massive call -> compact articles w/ this ticker's own sentiment, newest 1st"""
    params = {"ticker": ticker, "published_utc.gte": (now - timedelta(days=window)).strftime("%Y-%m-%d"),
              "order": "desc", "sort": "published_utc", "limit": MAX_ARTICLES, "apiKey": _key()}
    try:
        r = requests.get(URL, params=params, timeout=(10, 30))
    except requests.RequestException as e:
        raise DataError(f"massive unreachable: {type(e).__name__}") from None
    if r.status_code in (401, 403):
        raise DataError(f"massive refused the key, check MASSIVE_API_KEY in .env ({_error(r)})")
    if r.status_code == 429:
        raise DataError("massive rate limit (5 calls/min on the free plan), retry in a minute")
    if not r.ok:
        raise DataError(f"massive error {r.status_code}: {_error(r)}")
    try:
        data = r.json()
    except ValueError:
        raise DataError("massive sent something that isnt json") from None
    items = data.get("results") or []
    articles = []
    for item in items:
        mine = next((i for i in item.get("insights") or [] if i.get("ticker") == ticker), None)
        sentiment = (mine or {}).get("sentiment")
        articles.append({
            # "2026-10-09T14:03:00Z" -> naive utc, same format as the rest of the data layer
            "time": item.get("published_utc", "").rstrip("Z")[:19],
            "title": item.get("title", ""),
            "source": (item.get("publisher") or {}).get("name", ""),
            "url": item.get("article_url", ""),
            "summary": item.get("description") or "",
            # no insight for this ticker -> the article mentions it but isnt scored
            "sentiment": sentiment,
            "score": SCORES.get(sentiment),
            "reason": (mine or {}).get("sentiment_reasoning") or "",
            "n_tickers": len(item.get("tickers") or []),
        })
    articles.sort(key=lambda a: a["time"], reverse=True)
    # newest 1st + 1000 cap: a next page means the oldest days of the window were cut
    return {"articles": articles, "truncated": bool(data.get("next_url")) or len(items) >= MAX_ARTICLES}


def _articles(ticker, days, now=None):
    """(articles in the last `days`, meta, window start, coverage), ticker already uppercased"""
    now = now or _now()
    if not 1 <= days <= 365:
        raise DataError("days must be between 1 and 365")
    window = max(MIN_WINDOW_DAYS, days)
    # keyed on the day -> the window moves forward, 6h -> fresh news within the same day
    # the fallback key doesnt have a date, if massive fails yesterday's news is served as stale
    day = now.date().isoformat()
    got, meta = cached("news", ["v3", ticker, window, day], 6 * 3600,
                       lambda: _fetch(ticker, window, now), fallback_key=["v3", ticker, window],
                       cover=lambda k: k[:2] == ["v3", ticker] and k[2] >= window and k[3] == day)
    since = (now - timedelta(days=days)).isoformat()
    articles = [a for a in got["articles"] if a["time"] >= since]
    covered_from = min((a["time"][:10] for a in articles), default=None)
    # truncated counts when the cut reaches into the days asked for
    cut = got["truncated"] and covered_from is not None and covered_from > since[:10]
    coverage = {"covered_from": covered_from, "truncated": bool(cut)}
    if cut:
        coverage["warning"] = (f"massive caps a call at {MAX_ARTICLES} articles, so only {covered_from} onwards "
                               f"is covered, not the full {days} days. ask for fewer days for full coverage")
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
    now = now or _now()
    articles, meta, since, coverage = _articles(ticker, days, now)
    path = sub_dir("news") / f"{ticker}_{since}_{now.date()}.json"
    path.write_text(json.dumps(articles, ensure_ascii=False, indent=1), encoding="utf-8")
    # scored for this ticker 1st, then the ones about fewer companies, then the newest
    top = sorted(articles, key=lambda a: (a["score"] is not None, -a["n_tickers"], a["time"]), reverse=True)[:limit]
    return {
        "ticker": ticker,
        "days": days,
        "total_articles": len(articles),
        "articles": [{k: v for k, v in a.items() if k != "n_tickers"}
                     | {"summary": a["summary"][:300] + ("..." if len(a["summary"]) > 300 else "")}
                     for a in top],
        "path": str(path),
        "source": "massive",
        **coverage,
        **meta,
    }


def get_sentiment(ticker, days=30, now=None):
    ticker = _norm(ticker)
    now = now or _now()
    articles, meta, since, coverage = _articles(ticker, days, now)
    scored = [a for a in articles if a["score"] is not None]

    def mean(items):
        return round(sum(a["score"] for a in items) / len(items), 4)

    by_day = defaultdict(list)
    for a in scored:
        by_day[a["time"][:10]].append(a)
    path = sub_dir("sentiment") / f"{ticker}_{since}_{now.date()}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "n_articles", "mean_score"])
        for day in sorted(by_day):
            w.writerow([day, len(by_day[day]), mean(by_day[day])])

    m = mean(scored) if scored else None
    return {
        "ticker": ticker,
        "days": days,
        "n_articles": len(articles),
        "n_scored": len(scored),
        "mean_score": m,
        "label": label_for(m) if scored else "no news",
        "sentiment_counts": dict(Counter(a["sentiment"] for a in scored)),
        "days_with_news": len(by_day),
        "path": str(path),
        "columns": ["date", "n_articles", "mean_score"],
        "method": "each article's sentiment towards the ticker (positive 1, neutral 0, negative -1), averaged",
        "source": "massive",
        **coverage,
        **meta,
    }
