"""web search through tavily /search

for what the market tools dont cover: fresh events, macro, other markets, a 2nd source when a
data api fails
free plan = 1000 searches a month, basic depth = 1 credit
include_answer stays off, its tavily's own LLM and every model call has to go through ollama ->
the model reads the sources and writes the answer itself
"""

import os
from datetime import date, timedelta

import requests

from sensai.data import DataError
from sensai.data.cache import cached

URL = "https://api.tavily.com/search"
TOPICS = ("general", "news", "finance")
MAX_SNIPPET = 500  # chars per result, 5 results stay under 3k chars


def _key():
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        raise DataError("TAVILY_API_KEY is missing, get a free key at https://tavily.com and put it in .env")
    return key


def _error(r):
    try:
        data = r.json()
        detail = data.get("detail")
        if isinstance(detail, dict):
            return detail.get("error") or str(detail)
        return data.get("error") or detail or r.reason
    except ValueError:
        return r.text.strip()[:200] or r.reason


def _fetch(query, topic, days, max_results, today):
    body = {"query": query, "topic": topic, "search_depth": "basic", "max_results": max_results,
            "include_answer": False, "include_published_date": True}
    if days:
        body["start_date"] = (today - timedelta(days=days)).isoformat()
    try:
        r = requests.post(URL, json=body, headers={"Authorization": f"Bearer {_key()}"}, timeout=(10, 30))
    except requests.RequestException as e:
        raise DataError(f"tavily unreachable: {type(e).__name__}") from None
    if r.status_code == 401:
        raise DataError("tavily refused the key, check TAVILY_API_KEY in .env")
    if r.status_code == 429:
        raise DataError("tavily rate limit, retry in a minute")
    if r.status_code in (432, 433):
        raise DataError("tavily monthly limit reached (1000 searches on the free plan)")
    if not r.ok:
        raise DataError(f"tavily error {r.status_code}: {_error(r)}")
    try:
        data = r.json()
    except ValueError:
        raise DataError("tavily sent something that isnt json") from None
    results = []
    for item in data.get("results") or []:
        snippet = " ".join((item.get("content") or "").split())
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "published_date": (item.get("published_date") or None),
            "snippet": snippet[:MAX_SNIPPET] + ("..." if len(snippet) > MAX_SNIPPET else ""),
        })
    return results


def web_search(query, topic="general", days=None, max_results=5, today=None):
    query = " ".join((query or "").split())
    if not query:
        raise DataError("query is empty")
    if topic not in TOPICS:
        raise DataError(f"topic must be one of {', '.join(TOPICS)}")
    if days is not None and not 1 <= days <= 3650:
        raise DataError("days must be between 1 and 3650")
    if not 1 <= max_results <= 10:
        raise DataError("max_results must be between 1 and 10")
    today = today or date.today()
    # 1h: the web moves, but the same question twice in a session shouldnt cost 2 credits
    results, meta = cached("web", [query.lower(), topic, days, max_results, today.isoformat()], 3600,
                           lambda: _fetch(query, topic, days, max_results, today))
    return {
        "query": query,
        "topic": topic,
        "n_results": len(results),
        "results": results,
        # read right before the model's next step -> works better here than in the system msg
        "note": "These are short snippets, not the pages. If they don't contain the answer (a table, "
                "a ranking, a full article), call fetch on the most promising url to read it.",
        "source": "tavily",
        **meta,
    }
