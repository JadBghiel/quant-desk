"""the reasoning loop (a1): 1 question -> rounds of model calls and tool calls -> 1 streamed answer

round = 1 streamed model call, the model plans through the plan tool, calls tools w/ a thought
each, reads the results and goes again until it answers
a budget of steps and tokens per question stops it, every step goes in the question's trace
the session (history, system msg, saving) is in chat.py, the reasoning bits (plan tool, rules,
trace) in react.py
"""

import json
import time

from sensai import react
from sensai.react import Cleaner
from sensai.ui import DIM, RESET, Spinner, file_link, inline_image, tool_line


def answer(session, out, tty, trace):
    """round = 1 model call, the model plans (plan tool), calls tools w/ a thought each, reads
    the results and goes again until it answers, over the step or token budget or after
    react.MAX_FAILS failed calls in a row -> 1 last round w/o tools to answer w/ what it has"""
    dim, reset = (DIM, RESET) if tty else ("", "")
    tools = react.tools_for_model(session.hub.tools) if session.hub and session.hub.tools else None
    retried = False
    nudge = None
    fails = 0  # failed tool calls in a row, a success resets it
    saved = []  # files the tools wrote for this question, shown under the answer
    while True:
        over = None
        if tools and fails >= react.MAX_FAILS:
            over = "failures"
        elif tools and len(trace.steps) >= session.max_steps:
            over = "steps"
        elif tools and trace.tokens >= session.token_budget:
            over = "tokens"
        if over == "failures":
            trace.stop = over
            out.write(f"{dim}[{fails} failed tool calls in a row, stopping the tools]{reset}\n")
            nudge = {"role": "user", "content": f"{fails} tool calls failed in a row. Stop calling tools: "
                                                "answer with what you have and say what failed."}
        elif over:
            trace.stop = over
            used = (f"{len(trace.steps)} steps" if over == "steps"
                    else f"{react.tokens_k(trace.tokens)} of {react.tokens_k(session.token_budget)} tokens")
            out.write(f"{dim}[budget reached: {used}, answering w/ what it has]{reset}\n")
        content, calls, stats = stream_round(session, out, tty, None if over else tools, nudge)
        nudge = None
        trace.add_round(stats)
        if session.show_trace:
            if content and not content.endswith("\n"):
                out.write("\n")
            out.write(f"{dim}  round {trace.rounds} · {react.tokens_k(stats.get('prompt', 0))} in · "
                      f"{react.tokens_k(stats.get('output', 0))} out · {react.tokens_k(trace.tokens)} of "
                      f"{react.tokens_k(session.token_budget)} used{reset}\n")
        if not calls and tools and not over and not retried and react.TEXT_CALL.search(content):
            # call written as text -> no call went out and the text after it is made up
            retried = True
            out.write(f"\n{dim}[a tool call came as text, asking the model again]{reset}\n")
            nudge = {"role": "user", "content": "Your tool call was written as text, so it did not run. "
                                                "Make a real tool call, then answer from its result."}
            continue
        if not calls or over:
            session.messages.append({"role": "assistant", "content": content})
            trace.stop = trace.stop or "answered"
            show_files(out, saved, tty, content)
            return content
        session.messages.append({"role": "assistant", "content": content, "tool_calls": calls})
        for call in calls:
            if (call.get("function") or {}).get("name") == "plan":
                plan_step(session, call, out, tty, trace)
            else:
                name, args, ok, secs, result, thought = run_tool(session, call, out, tty)
                trace.add_step(thought, name, args, ok, secs, result)
                fails = 0 if ok else fails + 1
                saved += [f for f in react.result_files(result) if f not in saved] if ok else []


def show_files(out, paths, tty, content):
    """under the answer, trace on or off: 1 link per saved file, the image drawn below when the
    terminal can"""
    if not paths:
        return
    dim, reset = (DIM, RESET) if tty else ("", "")
    out.write(("" if not content or content.endswith("\n") else "\n") + f"\n{dim}saved:{reset}\n")
    for path in paths:
        out.write(f"  {file_link(path, tty)}\n")
        image = inline_image(path, tty)
        if image:
            out.write(f"  {image}\n")
    out.flush()


def plan_step(session, call, out, tty, trace):
    """the plan tool is sensai's own: show the steps, keep them in the trace, tell the model to go on"""
    dim, reset = (DIM, RESET) if tty else ("", "")
    args = (call.get("function") or {}).get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    trace.plan = react.plan_text(args.get("steps") if isinstance(args, dict) else None) or None
    out.write(f"{dim}Plan:\n" + "".join(f"  {line}\n" for line in (trace.plan or "(empty)").splitlines())
              + reset)
    msg = {"role": "tool", "tool_name": "plan", "content": "plan noted, now carry it out"}
    if call.get("id"):
        msg["tool_call_id"] = call["id"]
    session.messages.append(msg)


def stream_round(session, out, tty, tools, nudge=None):
    """1 model call streamed to out -> (content, tool calls, token counts)

    the spinner turns while nothing else is on screen: waiting for the 1st chunk, and the
    whole thinking phase when /think hides it, thinking stays out of the history
    nudge = 1 extra msg for this round, not kept
    """
    dim, reset = (DIM, RESET) if tty else ("", "")
    calls, stats, state = [], {}, None
    text = Cleaner()
    messages = session.messages + ([nudge] if nudge else [])
    # cloud models can take seconds before the 1st chunk
    spinner = Spinner(out).start() if tty else None
    try:
        for kind, chunk in session.client.chat_stream(session.model, messages, tools):
            if kind == "thinking":
                if session.show_thinking:
                    if spinner and spinner.running:
                        spinner.stop()
                    out.write((dim if state is None else "") + chunk)
                state = state or "thinking"
            elif kind == "tool_call":
                calls.append(chunk)
            elif kind == "stats":
                stats = chunk
            else:
                if spinner and spinner.running:
                    spinner.stop()
                elif state == "thinking" and session.show_thinking:
                    out.write(reset + "\n\n")
                state = "content"
                out.write(text.feed(chunk))
            out.flush()
    finally:
        if spinner:
            spinner.stop()
    tail, content = text.finish()
    out.write(tail)
    if state == "thinking" and session.show_thinking:
        # thought then went straight to a tool call
        out.write(reset + "\n")
    elif calls and content and not content.endswith("\n"):
        out.write("\n")
    return content, calls, stats


def run_tool(session, call, out, tty):
    """1 call through the hub, prints its line, appends the tool msg, a failed call goes back
    to the model as an error msg and it decides what to do w/ it"""
    dim, reset = (DIM, RESET) if tty else ("", "")
    fn = call.get("function") or {}
    name, args = fn.get("name", "?"), fn.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            pass
    thought = None
    if isinstance(args, dict):
        # a copy, the call in the history keeps its thought and the server gets the args w/o it
        args = dict(args)
        thought = args.pop("thought", None)
    if thought:
        out.write(f"{dim}Thought: {thought}{reset}\n")
    if session.show_trace and isinstance(args, dict) and isinstance(args.get("code"), str):
        # the code the model wrote, the tool line has its start
        out.write(f"{dim}{react.indent(args['code'], 4)}{reset}\n")
    spinner = Spinner(out, name).start() if tty else None
    t0 = time.monotonic()
    try:
        ok, result = session.hub.call(name, args)
    finally:
        if spinner:
            spinner.stop()
    secs = time.monotonic() - t0
    out.write(tool_line(name, args, secs, ok, None if ok else result, tty) + "\n")
    if session.show_trace:
        for path in react.result_files(result) if ok else []:
            out.write(f"{dim}    ↳ {file_link(path, tty)}{reset}\n")
        out.write(f"{dim}    → {react.preview(result, 160)}{reset}\n")
    out.flush()
    msg = {"role": "tool", "tool_name": name, "content": result if ok else f"error: {result}"}
    if call.get("id"):
        msg["tool_call_id"] = call["id"]
    session.messages.append(msg)
    return name, args, ok, secs, result, thought
