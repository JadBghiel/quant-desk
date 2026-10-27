"""1 eval question: a fresh session answers it, then the number check, the expected values, a
wrong number planted in the answer, and the judge"""

import io
import re
import time

from sensai import check, judge
from sensai.ollama import OllamaError, QuotaHit

PLANT = 1.37  # the planted number = a sourced one x 1.37, at the same decimals
DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")


def found(expect, answer):
    """an expected value written in the answer at its tolerance, the sign ignored (dropped 5.93%)"""
    want, tol = abs(float(expect["value"])), float(expect.get("tol", 0))
    return any(abs(abs(n["value"]) - want) <= tol + 1e-9 for n in check.numbers(answer))


def plant(answer, checks, messages):
    """1st sourced number of the answer x PLANT -> the check must flag it, None when nothing to plant"""
    item = next((i for i in checks["items"] if i["status"] == "sourced"), None)
    if not item:
        return None
    span = answer[item["start"]:item["end"]]
    m = DIGITS.search(span)
    old = m.group()
    dec = len(old.split(".")[1]) if "." in old else 0
    new = f"{float(old.replace(',', '')) * PLANT:{',' if ',' in old else ''}.{dec}f}"
    wrong = span[:m.start()] + new + span[m.end():]
    rechecked = check.check_answer(answer[:item["start"]] + wrong + answer[item["end"]:], messages)
    at = item["start"] + m.start()
    hit = next((i for i in rechecked["items"] if i["start"] <= at < i["end"]), None)
    return {"original": span, "planted": wrong, "caught": bool(hit and hit["status"] == "unsourced")}


def run_question(q, make_session, client=None, judge_model=None):
    """-> 1 result dict, a model error stays in the result and the eval goes on, a quota hit stops it"""
    session = make_session()
    res = {"id": q["id"], "question": q["q"], "trap": bool(q.get("trap"))}
    t0 = time.monotonic()
    try:
        answer = session.ask(q["q"], out=io.StringIO())
    except QuotaHit:
        raise
    except OllamaError as e:
        res["error"] = str(e)
        return res
    trace = session.traces[-1]
    checks = trace["checks"]
    before = session.messages[:-1]  # the history the check saw, w/o the answer
    res.update({
        "answer": answer,
        "secs": round(time.monotonic() - t0, 1),
        "checks": {k: checks[k] for k in ("n", "sourced", "derived", "unsourced")},
        "flags": [i["text"] for i in checks["items"] if i["status"] == "unsourced"]
                 + [f"code step {h['step']}: {h['sample']}" for h in checks.get("hardcoded") or []],
        "expected": [{**e, "found": found(e, answer)} for e in q.get("expect") or []],
        "planted": plant(answer, checks, before),
        "tools": [s["tool"] for s in trace["steps"]],
        "rounds": trace["rounds"],
        "tokens": trace["tokens_in"] + trace["tokens_out"],
        "stop": trace["stop"],
    })
    if res["trap"]:
        # no data for it -> the right answer says so, w/o a number from nowhere
        res["trap_ok"] = not res["flags"]
    if judge_model:
        try:
            res["judge"] = judge.run(client, judge_model, session.turns(), checks)
        except QuotaHit:
            raise
        except (judge.JudgeError, OllamaError) as e:
            res["judge_error"] = str(e)
    return res
