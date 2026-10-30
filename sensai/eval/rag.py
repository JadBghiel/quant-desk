"""r1 eval: does the search find the articles a person would pick, no cloud call

python -m sensai.eval --rag, questions + the titles labelled by hand in eval/rag.yaml, on the frozen news
top 5 of search_news next to the top 5 of get_news for the same days, get_news = the tool w/o a search
"""

from datetime import date

from sensai.data import news, now as _now, rag


def _score(titles, relevant):
    """-> {hit: a relevant title in the list, rank: the 1st 1, found: how many}"""
    ranks = [i for i, t in enumerate(titles, 1) if any(r.lower() in t.lower() for r in relevant)]
    return {"hit": bool(ranks), "rank": ranks[0] if ranks else None, "found": len(ranks)}


def run_case(case, limit=5):
    relevant = case["relevant"]
    found = rag.search_news(case["q"], case["ticker"], case.get("start"), case.get("end"), limit)
    days = (_now().date() - date.fromisoformat(case["start"])).days + 1 if case.get("start") else 30
    # get_news doesnt filter on an end day, the fair baseline is more articles cut to the same days
    listed = news.get_news(case["ticker"], days, 50)["articles"]
    if case.get("end"):
        listed = [a for a in listed if a["time"][:10] <= case["end"]]
    return {"id": case["id"], "q": case["q"], "n_relevant": len(relevant),
            "search": _score([h["title"] for h in found["hits"]], relevant),
            "baseline": _score([a["title"] for a in listed[:limit]], relevant),
            "top": [{"title": h["title"], "score": h["score"]} for h in found["hits"][:3]]}


def summary(results):
    n = len(results)

    def side(name):
        ranks = [1 / r[name]["rank"] for r in results if r[name]["rank"]]
        return {"hits": sum(r[name]["hit"] for r in results), "found": sum(r[name]["found"] for r in results),
                "mrr": round(sum(ranks) / n, 2) if n else None}
    return {"questions": n, "relevant": sum(r["n_relevant"] for r in results), "search": side("search"),
            "baseline": side("baseline")}


def table(results, s, meta):
    def cell(x):
        return f"{x['found']} found, 1st at {x['rank']}" if x["hit"] else "none"
    lines = [f"{'question':<24} {'relevant':>8}  {'search_news top 5':<22} get_news top 5"]
    for r in results:
        lines.append(f"{r['id']:<24} {r['n_relevant']:>8}  {cell(r['search']):<22} {cell(r['baseline'])}")
    a, b = s["search"], s["baseline"]
    lines += ["", f"embeddings {meta['model']} · data {meta['today']} (frozen) · {s['questions']} questions, labelled by hand",
              f"search_news: {a['hits']}/{s['questions']} questions with a relevant article in the top 5, "
              f"{a['found']} found, MRR {a['mrr']}",
              f"get_news:    {b['hits']}/{s['questions']} questions with a relevant article in the top 5, "
              f"{b['found']} found, MRR {b['mrr']}"]
    return "\n".join(lines)
