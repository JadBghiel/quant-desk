"""eval results -> the scores, a table for the terminal and a JSON file"""

import json
from datetime import datetime


def _pct(a, b):
    return round(100 * a / b, 1) if b else None


def _mean(values):
    values = list(values)
    return round(sum(values) / len(values), 2) if values else None


def summary(results):
    ok = [r for r in results if "error" not in r]
    normal = [r for r in ok if not r["trap"]]
    expected = [e for r in normal for e in r["expected"]]
    n = sum(r["checks"]["n"] for r in ok)
    backed = sum(r["checks"]["sourced"] + r["checks"]["derived"] for r in ok)
    planted = [r["planted"] for r in ok if r["planted"]]
    traps = [r for r in ok if r["trap"]]
    judged = [r["judge"] for r in ok if r.get("judge")]
    return {
        "questions": len(results),
        "errors": len(results) - len(ok),
        "correct_pct": _pct(sum(e["found"] for e in expected), len(expected)),
        "correct": [sum(e["found"] for e in expected), len(expected)],
        "faithfulness_pct": _pct(backed, n),
        "numbers": [backed, n],
        "planted_caught_pct": _pct(sum(p["caught"] for p in planted), len(planted)),
        "planted": [sum(p["caught"] for p in planted), len(planted)],
        "traps": [sum(r["trap_ok"] for r in traps), len(traps)],
        "judge": {k: _mean(j[k] for j in judged) for k in ("relevance", "coherence", "faithfulness")},
        "judged": len(judged),
        "avg_secs": _mean(r["secs"] for r in ok),
        "avg_tokens": _mean(r["tokens"] for r in ok),
        "avg_rounds": _mean(r["rounds"] for r in ok),
    }


def _row(r):
    if "error" in r:
        return f"{r['id']:<22} error: {r['error'][:60]}"
    if r["trap"]:
        correct = "trap ok" if r["trap_ok"] else "trap ✗"
    else:
        correct = f"{sum(e['found'] for e in r['expected'])}/{len(r['expected'])}"
    c = r["checks"]
    planted = "-" if not r["planted"] else ("caught" if r["planted"]["caught"] else "MISSED")
    j = r.get("judge")
    judged = f"{j['relevance']}/{j['coherence']}/{j['faithfulness']}" if j else "-"
    return (f"{r['id']:<22} {correct:<8} {c['n']:>7} {c['unsourced']:>7}  {planted:<7} {judged:<11} "
            f"{len(r['tools']):>5} {r['secs']:>6.1f}")


def table(results, s, meta):
    lines = [f"{'question':<22} {'correct':<8} {'numbers':>7} {'flagged':>7}  {'planted':<7} {'judge r/c/f':<11} "
             f"{'steps':>5} {'secs':>6}"]
    lines += [_row(r) for r in results]
    lines.append("")
    lines.append(f"model {meta['model']} · judge {meta.get('judge_model') or 'off'} · data {meta['today']}"
                 f" ({'live, recording' if meta.get('record') else 'frozen'})")
    lines.append(f"correct {s['correct_pct']}% ({s['correct'][0]}/{s['correct'][1]} expected values) · "
                 f"faithfulness {s['faithfulness_pct']}% ({s['numbers'][0]}/{s['numbers'][1]} numbers found or "
                 f"derived) · planted caught {s['planted'][0]}/{s['planted'][1]} · traps {s['traps'][0]}/{s['traps'][1]}")
    if s["judged"]:
        j = s["judge"]
        lines.append(f"judge on {s['judged']}: relevance {j['relevance']} · coherence {j['coherence']} · "
                     f"faithfulness {j['faithfulness']} (out of 5)")
    lines.append(f"per question: {s['avg_secs']}s, {s['avg_rounds']} rounds, {s['avg_tokens']} tokens"
                 + (f" · {s['errors']} error(s)" if s["errors"] else ""))
    return "\n".join(lines)


def save(results, s, meta, folder):
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now():%Y%m%d-%H%M%S}_{meta['model'].replace(':', '-').replace('/', '-')}.json"
    path = folder / name
    path.write_text(json.dumps({"meta": meta, "summary": s, "results": results}, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    return path
