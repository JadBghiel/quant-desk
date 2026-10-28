"""m4 research note: 1 markdown file per session, the model edits it section by section w/ update_note

update_note is sensai's own tool like plan (loop.py dispatches it), no extra model call. an edit goes
through the ev1 check 1st (check.py): a number not found in the tool results -> the edit is refused
w/ a tool error naming it and the model fixes it, the numbers found get their source written next to
them, `8.28% [q2 get_prices step 1]`. the refs carry the question nb bc the note spans questions
the target section changes and the file doesnt have a timestamp -> a diff between 2 versions shows
the edited section
"""

import json
import re

from sensai import check
from sensai.home import user_dir
from sensai.sessions import atomic_write
from sensai.ui import DIM, RED, RESET, file_link

NAME = "update_note"
SECTIONS = ("question", "data", "method", "results", "caveats")
MODES = ("replace", "append")
MAX_LEN = 4000
# a ref sensai wrote, the model can copy it back from the section it got in a later replace
REF = re.compile(r" ?\[q\d+ [^\]\n]*\]")

# the rule sits in the description, gemma follows a tool description more than the system msg
NOTE_TOOL = {"type": "function", "function": {
    "name": NAME,
    "description": (
        "Update the research note of this session. For a research question (you fetched or computed data), "
        "call it before your final answer, once for each section your work adds to, all the calls in the same "
        "round: question (what is asked), data (tickers, dates, source), method (how the numbers were "
        "computed), results (the numbers), caveats (limits of the data or the method). 1 call writes 1 "
        "section: put the data in data and the method in method, not in results. "
        "Copy numbers from the tool results or compute them with run_python: each number is checked, and an "
        "edit with a number not found in the results is refused. replace rewrites the section, append adds "
        "lines to it. Not for small talk."),
    "parameters": {"type": "object", "properties": {
        "section": {"type": "string", "enum": list(SECTIONS), "description": "question: what is asked, data: "
                    "tickers, dates, source, method: how it was computed, results: the numbers, caveats: limits"},
        "mode": {"type": "string", "enum": list(MODES), "description": "replace or append"},
        "content": {"type": "string", "description": "the text of this section only, plain text, short lines"},
    }, "required": ["section", "mode", "content"]},
}}


def empty():
    return {"title": None, "model": None, "sections": {}}


def validate(args):
    """the call's args -> (section, mode, content), or a ValueError w/ the reason the model reads"""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            raise ValueError("the arguments are not valid JSON") from None
    if not isinstance(args, dict):
        raise ValueError("the arguments must be an object with section, mode and content")
    # gemma adds a thought to each call, the other tools have 1
    args = {k: v for k, v in args.items() if k != "thought"}
    missing = [k for k in ("section", "mode", "content") if k not in args]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    extra = sorted(set(args) - {"section", "mode", "content"})
    if extra:
        raise ValueError(f"unknown argument {', '.join(extra)}, only section, mode and content")
    section, mode, content = str(args["section"]).strip().lower(), str(args["mode"]).strip().lower(), args["content"]
    if section not in SECTIONS:
        raise ValueError(f"unknown section {args['section']!r}, use one of {', '.join(SECTIONS)}")
    if mode not in MODES:
        raise ValueError(f"mode must be replace or append, not {args['mode']!r}")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content is empty")
    if len(content) > MAX_LEN:
        raise ValueError(f"content is {len(content)} characters, {MAX_LEN} max")
    return section, mode, content.strip()


def annotate(content, checks, q):
    """each number found -> followed by its ref, inserted from the end -> the offsets stay right"""
    for item in sorted(checks["items"], key=lambda i: i["start"], reverse=True):
        ref = item["source"] if item["status"] == "sourced" else f"q{q} derived {item['source']}"
        content = content[:item["end"]] + f" [{ref}]" + content[item["end"]:]
    return content


def apply(sections, section, mode, content):
    """-> a new dict w/ the target section changed"""
    new = dict(sections)
    new[section] = f"{new[section]}\n{content}" if mode == "append" and new.get(section) else content
    return new


def render(note, session_id):
    lines = [f"# {note.get('title') or 'Research note'}", "", f"session {session_id or '-'} · {note.get('model') or '?'}"]
    for s in SECTIONS:
        lines += ["", f"## {s.capitalize()}", "", note["sections"].get(s) or "(empty)"]
    return "\n".join(lines) + "\n"


def path(session_id):
    d = user_dir() / "notes"
    d.mkdir(mode=0o700, exist_ok=True)
    return d / f"{session_id}.md"


def write(session):
    """the note file of the session -> its path, None w/o a store (tests, eval) or w/o a note"""
    if not session.store or not session.id:
        return None
    p = path(session.id)
    if not session.note["sections"]:
        # rolled back to nothing, a file w/ 5 empty sections isnt a note
        p.unlink(missing_ok=True)
        return None
    atomic_write(p, render(session.note, session.id))
    return p


def note_step(session, call, out, tty, trace):
    """1 update_note call -> (ok, section): validate, check its numbers, refuse or apply + write
    the tool msg tells the model which, a refusal counts as a failed call in the loop"""
    dim, red, reset = (DIM, RED, RESET) if tty else ("", "", "")
    section = mode = None
    try:
        section, mode, content = validate((call.get("function") or {}).get("arguments") or {})
        content = REF.sub("", content)
        checks = check.check_answer(content, session.messages, label="ref")
        missing = [i["text"] for i in checks["items"] if i["status"] == "unsourced"]
        if missing:
            raise ValueError(f"{', '.join(missing)} not found in the tool results. Copy numbers from the results "
                             "or compute them with run_python, then call update_note again")
    except ValueError as e:
        ok, error = False, str(e)
        out.write(f"{red}✗ note: {section or '?'} refused, {error[:120]}{reset}\n")
        reply = f"error: edit refused, {error}"
    else:
        ok, error = True, None
        q = sum(m.get("role") == "user" for m in session.messages)
        n = session.note
        if not n["sections"]:
            # set once -> a later /model or a longer title cant touch the header
            first = next(m["content"] for m in session.messages if m.get("role") == "user")
            n["title"], n["model"] = session.title or " ".join(first.split())[:60], session.model
        n["sections"] = apply(n["sections"], section, mode, annotate(content, checks, q))
        try:
            write(session)
        except OSError as e:
            out.write(f"[warning] note not saved: {e}\n")
        out.write(f"{dim}✎ note: {section} ({mode}){reset}\n")
        reply = f"{section} updated ({mode}), it now reads:\n{n['sections'][section]}"
    trace.notes.append({"section": section, "mode": mode, "ok": ok, "error": error})
    msg = {"role": "tool", "tool_name": NAME, "content": reply}
    if call.get("id"):
        msg["tool_call_id"] = call["id"]
    session.messages.append(msg)
    out.flush()
    return ok, section


def footer(session, edited, tty):
    """the line under the answer when this question edited the note, "" otherwise"""
    if not edited:
        return ""
    dim, reset = (DIM, RESET) if tty else ("", "")
    where = file_link(path(session.id), tty) if session.store and session.id else "/note"
    return f"{dim}note: {', '.join(edited)} updated ·{reset} {where}\n"
