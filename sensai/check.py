"""ev1 number check: each number in an answer is looked up in the data fetched for it

no model call, runs after every answer. a number is
- sourced: found in a tool result, the run_python stdout, a tool call's args or the question,
  at the precision it was written w/ (217.15 matches 217.1499, 26% matches 0.2601)
- derived: a - b, a / b or the % change of 2 sourced numbers of the same answer
- unsourced: none of the above -> flagged under the answer
a match says the number exists in the sources, whether it was used for the right thing is for the
judge (judge.py)

a news dump or a page of search results holds hundreds of numbers, a round 25% always finds 1 of
them (25 robots, sales up 25%) -> a % claim needs a % or a fraction in the source, and a claim w/ 2
significant digits or less (25.0%, 15, 0.26) found in free text (news, web, fetched pages) or in an
older turn also needs a word in common w/ its source (a ticker, a field name, a word around it)
"""

import ast
import json
import math

from sensai.numbers import numbers, words

# their results are text written by others, full of numbers that have nothing to do w/ the question
TEXT_TOOLS = {"get_news", "web_search", "fetch"}
# sensai's own tools (loop.py), their args and results hold no data, the note would source itself
LOCAL = {"plan", "update_note"}


def _from_text(text, label, out, anchor=False):
    for n in numbers(text):
        near = words(text[max(0, n["start"] - 80):n["end"] + 80])
        frac = not n["unit"] and n["decimals"] > 0 and abs(n["value"]) <= 1.5
        out.append({"value": n["value"], "label": label, "pct": n["pct"], "frac": frac, "words": near,
                    "anchor": anchor})


def _walk(value, label, out, anchor=False, ctx=frozenset(), key=""):
    """the numbers of a json value w/ the words around each: its key, the strings of its object
    (ticker, name) and the objects above it, numbers in long strings get the words next to them"""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        if math.isfinite(value):
            pct = "pct" in key or "percent" in key
            out.append({"value": float(value), "label": label, "pct": pct,
                        "frac": not pct and isinstance(value, float) and abs(value) <= 1.5,
                        "words": ctx | words(key.replace("_", " ")), "anchor": anchor})
    elif isinstance(value, str):
        _from_text(value, label, out, anchor)
    elif isinstance(value, dict):
        own = words(" ".join([*value.keys(), *(v for v in value.values() if isinstance(v, str) and len(v) <= 60)]))
        for k, v in value.items():
            _walk(v, label, out, anchor, ctx | own, k)
    elif isinstance(value, list):
        for v in value:
            _walk(v, label, out, anchor, ctx, key)


def _parse(content, label, out, anchor):
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        _from_text(str(content), label, out, anchor)
        return
    _walk(data, label, out, anchor)


def sources(messages):
    """-> [{value, label, ref, pct, frac, words, anchor}] from the history: tool results, tool call args
    and the questions

    tool results of the last question are labeled like its steps (`get_prices, step 2`), older
    ones `earlier`, failed calls, the plan and the note hold no data
    the ref carries the question nb (`q2 get_prices step 1`) for the note, which spans questions
    """
    last_q = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    out, step, q = [], 0, 0

    def tag(start, ref):
        for s in out[start:]:
            s["ref"] = ref

    for i, m in enumerate(messages):
        role, start = m.get("role"), len(out)
        if role == "user":
            q, step = q + 1, 0
            _from_text(m.get("content") or "", "the question", out)
            tag(start, f"q{q} question")
        elif role == "assistant":
            for call in m.get("tool_calls") or []:
                fn = call.get("function") or {}
                if fn.get("name") in LOCAL:
                    continue
                start = len(out)
                args = fn.get("arguments") if isinstance(fn.get("arguments"), dict) else {}
                args = {k: v for k, v in args.items() if k not in ("thought", "code")}
                _walk(args, f"{fn.get('name')} args", out, ctx=frozenset(words(fn.get("name") or "")))
                tag(start, f"q{q} {fn.get('name')} args")
        elif role == "tool" and m.get("tool_name") not in LOCAL:
            name = m.get("tool_name", "tool")
            step += 1
            if not (m.get("content") or "").startswith("error:"):
                now = i > last_q
                _parse(m["content"], f"{name}, step {step}" if now else f"{name}, earlier", out,
                       anchor=name in TEXT_TOOLS or not now)
                tag(start, f"q{q} {name} step {step}")
    # this question's results 1st, a number found there and in an old result comes from there
    return sorted(out, key=lambda s: "step" not in s["label"])


def matches(claim, src):
    """claim at its written precision vs 1 source, rounded or cut
    a % claim takes a % or a fraction (0.26 -> 26%), a precise claim (3+ significant digits) any
    number, the sign counts when the claim wrote 1 (dropped 5.93% <-> -5.93)"""
    v, tol, s = claim["value"], claim["tol"], src["value"]
    strong = claim["sig"] >= 3
    if not strong and src["anchor"] and not claim["words"] & src["words"]:
        return False
    if claim["pct"]:
        cands = ([s] if src["pct"] or strong else []) + ([s * 100] if src["frac"] else [])
    else:
        cands = [s]
    for c in cands:
        if claim["signed"] and v and c and (c > 0) != (v > 0):
            continue
        gap = abs(c) - abs(v)
        if -tol - 1e-9 <= gap < 2 * tol + 1e-9:
            return True
    return False


def _derived(claim, done):
    """a - b, a / b, % change of 2 sourced numbers already in the answer -> a label, or None
    no sums, 9.0% + 6.0% = 15.0% is how a made up pie chart adds up
    inputs w/ 3+ significant digits, an integer like 100 is ±0.5 and turns any gap of ~5 into a match"""
    v, tol = claim["value"], claim["tol"]
    precise = [d for d in done if d["sig"] >= 3]
    for a in precise:
        for b in precise:
            if a is b or not b["value"]:
                continue
            x, y = a["value"], b["value"]
            rel = abs(x / y) * (a["tol"] / max(abs(x), 1e-12) + b["tol"] / abs(y))
            ops = [(x - y, f"{a['text']} - {b['text']}", tol + a["tol"] + b["tol"]),
                   (x / y, f"{a['text']} / {b['text']}", tol + rel),
                   ((x / y - 1) * 100, f"{a['text']} vs {b['text']}", tol + 100 * rel)]
            for d, how, err in ops:
                if claim["signed"] and v and d and (d > 0) != (v > 0):
                    continue
                if abs(abs(d) - abs(v)) <= err + 1e-9:
                    return how
    return None


def _line_around(text, start, end, width):
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = text[line_start:None if line_end == -1 else line_end]
    at = start - line_start
    return line[max(0, at - width):at + (end - start) + width]


def _literals(code):
    """number lists / tuples / dicts written in python code -> list of [numbers]"""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []

    def num(node):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            v = num(node.operand)
            return None if v is None else -v
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        return None

    out = []
    for node in ast.walk(tree):
        elts = node.values if isinstance(node, ast.Dict) else getattr(node, "elts", None)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)) and elts:
            values = [num(e) for e in elts]
            if all(v is not None for v in values):
                out.append([(v, e) for v, e in zip(values, elts)])
    return out


def hardcoded(messages, pool):
    """run_python code of the last question that types data in: a list or dict of 4+ numbers (3+ w/
    a decimal) not in the tool results -> the made up market shares of a pie chart
    3 round ints ([20, 50, 200] windows) or a figsize stay out"""
    last_q = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    flags, step = [], 0
    for m in messages[last_q + 1:]:
        for call in m.get("tool_calls") or [] if m.get("role") == "assistant" else []:
            fn = call.get("function") or {}
            if fn.get("name") in LOCAL:
                continue
            step += 1
            code = (fn.get("arguments") or {}).get("code") if isinstance(fn.get("arguments"), dict) else None
            if fn.get("name") != "run_python" or not isinstance(code, str):
                continue
            for values in _literals(code):
                decimal = any(isinstance(e, ast.Constant) and isinstance(e.value, float) for _, e in values)
                if len(values) < 4 and not (decimal and len(values) >= 3):
                    continue
                missing = [v for v, e in values
                           if not any(matches({"value": v, "tol": 1e-9, "pct": False, "signed": False, "sig": 3,
                                               "words": set()}, s) for s in pool)]
                if len(missing) >= 3:
                    sample = ", ".join(f"{v:g}" for v in missing[:4]) + (", ..." if len(missing) > 4 else "")
                    flags.append({"step": step, "count": len(missing), "sample": f"[{sample}]"})
    return flags


def check_answer(text, messages, label="label"):
    """-> {n, sourced, derived, unsourced, items, hardcoded}, items in the order of the answer
    label="ref" -> the sources w/ their question nb, for the note"""
    pool = sources(messages)
    items = []
    for claim in numbers(text, claims_only=True):
        claim["words"] = words(_line_around(text, claim["start"], claim["end"], 100))
        src = next((s for s in pool if matches(claim, s)), None)
        items.append({**claim, "status": "sourced" if src else None, "source": src and src[label]})
    done = [i for i in items if i["status"] == "sourced"]
    for item in items:
        if item["status"] is None:
            how = _derived(item, done)
            item["status"], item["source"] = ("derived", how) if how else ("unsourced", None)
        item["context"] = " ".join(_line_around(text, item["start"], item["end"], 40).split())
    counts = {s: sum(i["status"] == s for i in items) for s in ("sourced", "derived", "unsourced")}
    return {"n": len(items), **counts,
            "items": [{k: i[k] for k in ("text", "value", "status", "source", "context", "start", "end")}
                      for i in items],
            "hardcoded": hardcoded(messages, pool)}
