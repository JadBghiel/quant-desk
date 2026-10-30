"""r1 RAG over the news: articles -> chunks -> embeddings in sqlite -> the closest chunks to a question

get_news picks 10 articles by sentiment and date, this finds the ones that talk about what is asked
ollama cloud refuses /api/embed -> a local ollama w/ nomic-embed-text, same http api, no key
massive gives a title, a summary and a reason per article, no full text -> that is what gets indexed
embedded when a search covers it: get_news stays fast, a 90s call doesnt have to hold 700
articles if the dates are given, and whats saved stays saved for the next search
"""

import os
import re
import sqlite3
import time
from datetime import date, timedelta

import numpy as np

from sensai.data import DataError, news, now as _now, sub_dir
from sensai.ollama import OllamaClient, OllamaError

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "nomic-embed-text"
CHUNK = 500  # chars, a summary + its reason gives 1 to 3 chunks
BATCH = 64
DEADLINE = 60  # secs of embedding per search, the hub gives up on a tool call after 90
MAX_LIMIT = 20
DEFAULT_DAYS = 30
# the news is fetched by window then cut to the dates, 1 window per date range would be 1 massive call each (5 / min)
WINDOWS = (30, 60, 90, 180, 365)
SENTENCE = re.compile(r"(?<=[.!?])\s+")
# nomic was trained w/ these, w/o them the search gets worse
DOC, QUERY = "search_document: ", "search_query: "
SCHEMA = """CREATE TABLE IF NOT EXISTS chunks (model TEXT, ticker TEXT, url TEXT, n INTEGER, time TEXT, title TEXT,
source TEXT, sentiment TEXT, text TEXT, vec BLOB, PRIMARY KEY (model, ticker, url, n))"""


def host():
    return os.environ.get("SENSAI_EMBED_HOST") or DEFAULT_HOST


def model():
    return os.environ.get("SENSAI_EMBED_MODEL") or DEFAULT_MODEL


def unavailable():
    """why the search cant run, None when it can, read by the server at start"""
    try:
        names = OllamaClient(host(), timeout=5).list_models()
    except OllamaError as e:
        return f"no ollama at {host()}: {e}"
    if not any(n == model() or n.split(":")[0] == model() for n in names):
        return f"{model()} isnt on the ollama at {host()}, run: ollama pull {model()}"
    return None


def _embed(texts):
    try:
        return OllamaClient(host(), timeout=60).embed(model(), texts)
    except OllamaError as e:
        raise DataError(f"embedding failed on the local ollama: {e}. get_news still works") from None


def chunks(article):
    """-> the chunks of 1 article, cut between sentences w/ 1 sentence of overlap, the title on each
    -> a chunk still says what its about on its own"""
    title = " ".join((article.get("title") or "").split())
    body = " ".join(f"{article.get('summary') or ''} {article.get('reason') or ''}".split())
    sentences = [s for s in SENTENCE.split(body) if s]
    if not sentences:
        return [title] if title else []
    out, current = [], []
    for s in sentences:
        if current and sum(map(len, current)) + len(s) > CHUNK:
            out.append(current)
            current = current[-1:]
        current.append(s)
    out.append(current)
    return [f"{title}. {' '.join(group)}" if title else " ".join(group) for group in out]


def _db():
    db = sqlite3.connect(sub_dir("rag") / "news.sqlite")
    db.execute(SCHEMA)
    return db


def ingest(db, ticker, articles, clock=time.monotonic):
    """embeds the chunks not stored yet, saved per batch -> a stop loses 1 batch at most, -> nb still missing"""
    m = model()
    stored = {tuple(r) for r in db.execute("SELECT url, n FROM chunks WHERE model = ? AND ticker = ?", (m, ticker))}
    todo = []
    for a in articles:
        url = a.get("url") or a.get("title") or ""
        for n, text in enumerate(chunks(a)):
            if (url, n) not in stored:
                todo.append((url, n, a, text))
    start = clock()
    for i in range(0, len(todo), BATCH):
        if clock() - start > DEADLINE:
            return len(todo) - i
        batch = todo[i:i + BATCH]
        vectors = _embed([DOC + text for _, _, _, text in batch])
        db.executemany("INSERT OR REPLACE INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (m, ticker, url, n, a.get("time", ""), a.get("title", ""), a.get("source", ""), a.get("sentiment"), text,
             np.asarray(v, dtype=np.float32).tobytes()) for (url, n, a, text), v in zip(batch, vectors)])
        db.commit()
    return 0


def _unit(vectors):
    norm = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(norm == 0, 1, norm)


def _day(value, name):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise DataError(f"{name} must be a date like 2026-10-22, got {value!r}") from None


def search_news(query, ticker, start=None, end=None, limit=5, now=None):
    """the articles closest to the query between 2 days, best chunk of each, best 1st"""
    query = " ".join((query or "").split())
    ticker = (ticker or "").strip().upper()
    if not query:
        raise DataError("query is empty")
    if not ticker:
        raise DataError("ticker is empty")
    if not 1 <= limit <= MAX_LIMIT:
        raise DataError(f"limit must be between 1 and {MAX_LIMIT}")
    now = now or _now()
    last = _day(end, "end") if end else now.date()
    first = _day(start, "start") if start else last - timedelta(days=DEFAULT_DAYS - 1)
    if first > last:
        raise DataError(f"start {first} is after end {last}")
    days = (now.date() - first).days + 1
    if days > 365:
        raise DataError("news goes back 365 days at most in 1 search, use a later start")
    if days < 1:
        raise DataError(f"start {first} is in the future, today is {now.date()}")
    window = next(w for w in WINDOWS if w >= days)
    articles, meta, _, coverage = news._articles(ticker, window, now)
    # by day -> the whole start day counts, whatever the time now
    articles = [a for a in articles if first.isoformat() <= a["time"][:10] <= last.isoformat()]
    db = _db()
    try:
        missing = ingest(db, ticker, articles)
        q = _unit(np.asarray(_embed([QUERY + query])[0], dtype=np.float32))
        rows = db.execute("SELECT url, time, title, source, sentiment, text, vec FROM chunks WHERE model = ? AND "
                          "ticker = ? AND substr(time, 1, 10) BETWEEN ? AND ?",
                          (model(), ticker, first.isoformat(), last.isoformat())).fetchall()
    finally:
        db.close()
    best = {}
    if rows:
        scores = _unit(np.stack([np.frombuffer(r[6], dtype=np.float32) for r in rows])) @ q
        for r, s in zip(rows, scores.tolist()):
            if r[0] not in best or s > best[r[0]][0]:
                best[r[0]] = (s, r)
    hits = sorted(best.values(), key=lambda h: h[0], reverse=True)[:limit]
    out = {
        "query": query, "ticker": ticker, "start": first.isoformat(), "end": last.isoformat(),
        "articles_searched": len(best),
        # 2 decimals: a score written 0.7134 would source a made up 71.3% in the number check
        "hits": [{"title": r[2], "url": r[0], "time": r[1], "source": r[3], "sentiment": r[4], "text": r[5],
                  "score": round(s, 2)} for s, r in hits],
        "note": "These are summaries of articles, written by others. News near a price move doesn't prove what caused "
                "it: say what the articles report, cite the url of each article you use, and say so if none explains it.",
        "source": "massive, searched with local embeddings",
    }
    # the window can be cut w/o touching the days asked for
    cut = coverage.get("warning") and (coverage.get("covered_from") or "") > first.isoformat()
    warnings = [f"massive caps a call at 1000 articles, this search only covers {coverage['covered_from']} onwards"] if cut else []
    if missing:
        warnings.append(f"{missing} chunks not indexed yet in this window, search again to continue or narrow the dates")
    if not articles:
        warnings.append(f"no article for {ticker} between {first} and {last} in the data")
    if warnings:
        out["warning"] = " ".join(warnings)
    return {**out, **meta}
