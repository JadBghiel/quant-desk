"""ev1 judge: a 2nd model grades 1 answer on the data the tools returned for it

called by /judge and the eval, after each answer it would cost 1 more model call and the free tier
allows 1 at a time
scores relevance, coherence and source faithfulness 1 to 5, and goes through the claims the number
check cant read (names, events, directions) -> supported, contradicted or unverifiable
the reply is asked w/ a JSON schema (ollama structured outputs) and validated

the cloud doesnt hold gpt-oss to the schema: 1 reply had no relevance, the next 1 named the verdict
"status" and skipped the comment -> the shape is also written in the prompt, and close variants are
accepted (status for verdict, scores as "4" or under "scores"), the 3 scores stay required
"""

import json

VERDICTS = ("supported", "contradicted", "unverifiable")
SCHEMA = {
    "type": "object",
    "properties": {
        "relevance": {"type": "integer", "minimum": 1, "maximum": 5},
        "coherence": {"type": "integer", "minimum": 1, "maximum": 5},
        "faithfulness": {"type": "integer", "minimum": 1, "maximum": 5},
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "claim": {"type": "string"},
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "source": {"type": "string"},
        }, "required": ["claim", "verdict", "source"]}},
        "comment": {"type": "string"},
    },
    "required": ["relevance", "coherence", "faithfulness", "claims", "comment"],
}
SYSTEM = """You grade one answer of a research assistant for quantitative finance. You get the user's \
question, the data its tools returned (the only facts it had), the result of an automatic number check, \
and the answer.

Score each from 1 (bad) to 5 (good):
- relevance: does it answer the question that was asked (right ticker, period, metric)?
- coherence: is it clear, consistent and well reasoned?
- faithfulness: is everything it states backed by the tool data? A number or a fact that isn't in the \
data lowers it, even if it may be true.

Then list the answer's factual claims (at most 10, most important first): each one is "supported" \
(the tool data says it), "contradicted" (the tool data says otherwise) or "unverifiable" (not in the \
tool data). "source" names the tool result that backs or contradicts it, or "none". Judge only from \
the data given, not from what you know.

Reply with this JSON object only:
{"relevance": 1-5, "coherence": 1-5, "faithfulness": 1-5,
 "claims": [{"claim": "...", "verdict": "supported" | "contradicted" | "unverifiable", "source": "..."}],
 "comment": "1 or 2 sentences on the main problem, or why it is good"}"""
MAX_SOURCE = 2000  # chars per tool result
MAX_SOURCES = 14000  # chars for all of them


class JudgeError(Exception):
    pass


def last_exchange(messages):
    """-> (question, answer, the msgs in between) of the last answered question, or None"""
    answers = [i for i, m in enumerate(messages)
               if m.get("role") == "assistant" and m.get("content") and not m.get("tool_calls")]
    if not answers:
        return None
    a = answers[-1]
    q = max((i for i in range(a) if messages[i].get("role") == "user"), default=None)
    if q is None:
        return None
    return messages[q]["content"], messages[a]["content"], messages[q + 1:a]


def sources_text(between):
    """the tool results of 1 question, each cut, the plan tool left out"""
    parts, used = [], 0
    for m in between:
        if m.get("role") != "tool" or m.get("tool_name") == "plan":
            continue
        text = m.get("content") or ""
        if len(text) > MAX_SOURCE:
            text = text[:MAX_SOURCE] + f" [cut, {len(text) - MAX_SOURCE} more chars]"
        part = f"[{len(parts) + 1}] {m.get('tool_name', 'tool')}: {text}"
        if used + len(part) > MAX_SOURCES:
            parts.append(f"[{len(parts) + 1}...] more results left out")
            break
        parts.append(part)
        used += len(part)
    return "\n\n".join(parts) or "(no tool was called, the answer had no data)"


def check_text(checks):
    code = "".join(f"\nthe code of step {h['step']} types in {h['count']} numbers that are not in the tool data "
                   f"{h['sample']}" for h in (checks or {}).get("hardcoded") or [])
    if not checks or not checks.get("n"):
        return "no number in the answer" + code
    missing = [i["text"] for i in checks["items"] if i["status"] == "unsourced"]
    return (f"{checks['n']} numbers, {checks['sourced']} found in the tool data, {checks['derived']} "
            f"derived from them, not found: {', '.join(missing) or 'none'}" + code)


def _score(v):
    """4, 4.0 or "4" -> 4, anything else -> None"""
    if isinstance(v, bool):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return int(v) if v == int(v) and 1 <= v <= 5 else None


def validate(data):
    """the parsed reply -> the verdict dict, ValueError when it doesnt fit"""
    if not isinstance(data, dict):
        raise ValueError("not an object")
    if isinstance(data.get("scores"), dict):
        data = {**data["scores"], **data}
    out = {}
    for k in ("relevance", "coherence", "faithfulness"):
        out[k] = _score(data.get(k))
        if out[k] is None:
            raise ValueError(f"{k} must be an integer from 1 to 5, got {data.get(k)!r}")
    claims = data.get("claims") or []
    if not isinstance(claims, list):
        raise ValueError("claims must be a list")
    out["claims"] = []
    for c in claims:
        verdict = str((c.get("verdict") or c.get("status") or c.get("label") or "") if isinstance(c, dict) else "").lower()
        if verdict not in VERDICTS or not isinstance(c.get("claim"), str):
            raise ValueError(f"bad claim, verdict must be 1 of {', '.join(VERDICTS)}: {c!r}")
        out["claims"].append({"claim": c["claim"], "verdict": verdict, "source": str(c.get("source") or "none")})
    out["comment"] = str(data.get("comment") or "")
    return out


def judge(client, model, question, answer, between, checks=None):
    """-> {relevance, coherence, faithfulness, claims, comment, model, tokens}
    a reply that isnt valid -> 1 retry w/ the reason, then JudgeError"""
    user = (f"QUESTION:\n{question}\n\nTOOL DATA:\n{sources_text(between)}\n\nNUMBER CHECK:\n"
            f"{check_text(checks)}\n\nANSWER:\n{answer}")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    tokens = 0
    for attempt in range(2):
        content, stats = client.chat(model, messages, format=SCHEMA, options={"temperature": 0})
        tokens += stats.get("prompt", 0) + stats.get("output", 0)
        try:
            verdict = validate(json.loads(content))
        except ValueError as e:  # json errors are ValueErrors too
            if attempt:
                raise JudgeError(f"the judge ({model}) didnt reply w/ valid JSON twice: {e}") from None
            messages += [{"role": "assistant", "content": content},
                         {"role": "user", "content": f"That reply is not valid ({e}). Reply again with the "
                                                     "JSON object only, with the keys relevance, coherence, "
                                                     "faithfulness, claims and comment."}]
            continue
        return {**verdict, "model": model, "tokens": tokens}


def run(client, model, messages, checks=None):
    """judge the last answer of a history, OllamaError and JudgeError go to the caller"""
    found = last_exchange(messages)
    if not found:
        raise JudgeError("no answer to judge yet")
    question, answer, between = found
    return judge(client, model, question, answer, between, checks)
