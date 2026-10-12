"""chat session: history, system msg, persistence, 1 question -> tool rounds -> 1 streamed answer"""

import json
import sys
import time
from datetime import date, datetime

from sensai import profile as prof
from sensai.ui import DIM, RESET, Spinner, tool_line


def build_system(base, profile, today=None):
    """cfg prompt + today's date + the profile block, rebuilt on every start, resume and profile change"""
    today = today or date.today()
    parts = [base] if base else []
    parts.append(f"Today is {today:%A %Y-%m-%d}.")
    about = prof.render(profile)
    if about:
        parts.append(about)
    return "\n\n".join(parts)


def _now():
    return datetime.now().isoformat(timespec="seconds")


class Session:
    def __init__(self, client, model, system_prompt=None, show_thinking=True, store=None,
                 profile=None, profile_path=None, hub=None, max_tool_rounds=6):
        self.client = client
        self.hub = hub
        self.max_tool_rounds = max_tool_rounds
        self.model = model
        self.system_prompt = system_prompt
        self.show_thinking = show_thinking
        self.store = store
        self.profile = profile or {}
        self.profile_path = profile_path
        self.messages = []
        self.clear()

    # --- history + persistence

    def system_text(self):
        return build_system(self.system_prompt, self.profile)

    def turns(self):
        return [m for m in self.messages if m["role"] != "system"]

    def set_system(self):
        """rebuild messages[0], called when the profile changes mid session"""
        self.messages = [{"role": "system", "content": self.system_text()}, *self.turns()]

    def set_profile(self, p):
        self.profile = p or {}
        self.set_system()

    def clear(self):
        """new session w/ a new id, the previous one stays on disk"""
        self.id = self.store.new_id() if self.store else None
        self.title = None
        self.created = _now()
        self.messages = [{"role": "system", "content": self.system_text()}]

    def load_record(self, record):
        """resume a saved session, system msg rebuilt fresh not taken from the file"""
        self.id = record["id"]
        self.title = record.get("title")
        self.created = record.get("created", _now())
        # tool msgs kept so the model still has the data it fetched
        self.messages = [{"role": "system", "content": self.system_text()},
                         *[m for m in record["messages"] if m.get("role") in ("user", "assistant", "tool")]]

    def record(self):
        return {"id": self.id, "title": self.title, "created": self.created, "updated": _now(),
                "model": self.model, "messages": self.turns()}

    def save(self):
        """a failed save is a warning, the chat goes on"""
        if not self.store or not self.turns():
            return
        try:
            self.store.save(self.record())
        except OSError as e:
            print(f"\n[warning] session not saved: {e}")

    # --- 1 question -> tool rounds -> 1 streamed answer

    def ask(self, text, out=sys.stdout):
        """streams the answer to out, the turn only stays in the history if the answer completed

        error or Ctrl+C at any point (mid stream, mid tool call) -> history back to before the
        question so a retry sends a clean history
        """
        tty = out.isatty()
        start = len(self.messages)
        self.messages.append({"role": "user", "content": text})
        try:
            answer = self._answer(out, tty)
        except BaseException:
            out.write(RESET if tty else "")
            del self.messages[start:]
            raise
        if self.title is None:
            self.title = " ".join(text.split())[:60]
        self.save()
        return answer

    def _answer(self, out, tty):
        """round = 1 model call. tool calls -> run them, results appended, next round.
        the last round goes w/o tools so the model has to answer w/ what it has"""
        tools = self.hub.tools if self.hub else None
        for n in range(self.max_tool_rounds + 1):
            last = n == self.max_tool_rounds
            if last and tools:
                out.write(f"{DIM if tty else ''}[{self.max_tool_rounds} tool rounds, answering w/ what it has]"
                          f"{RESET if tty else ''}\n")
            content, calls = self._stream_round(out, tty, None if last else tools)
            if not calls:
                self.messages.append({"role": "assistant", "content": content})
                return content
            self.messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            if content:
                out.write("\n")
            for call in calls:
                self._run_tool(call, out, tty)
        return content

    def _stream_round(self, out, tty, tools):
        """1 model call streamed to out -> (content, tool calls)

        the spinner runs while nothing else is on screen: waiting for the 1st chunk, and the
        whole thinking phase when /think hides it. thinking is never kept in the history
        """
        dim, reset = (DIM, RESET) if tty else ("", "")
        parts, calls, state = [], [], None
        # cloud models can take seconds before the 1st chunk
        spinner = Spinner(out).start() if tty else None
        try:
            for kind, chunk in self.client.chat_stream(self.model, self.messages, tools):
                if kind == "thinking":
                    if self.show_thinking:
                        if spinner and spinner.running:
                            spinner.stop()
                        out.write((dim if state is None else "") + chunk)
                    state = state or "thinking"
                elif kind == "tool_call":
                    calls.append(chunk)
                else:
                    if spinner and spinner.running:
                        spinner.stop()
                    elif state == "thinking" and self.show_thinking:
                        out.write(reset + "\n\n")
                    state = "content"
                    parts.append(chunk)
                    out.write(chunk)
                out.flush()
        finally:
            if spinner:
                spinner.stop()
        if state == "thinking" and self.show_thinking:
            # thought then went straight to a tool call
            out.write(reset + "\n")
        return "".join(parts), calls

    def _run_tool(self, call, out, tty):
        """runs 1 call through the hub, prints its line, appends the tool msg. a failed call is
        sent back to the model as an error msg, it decides what to do w/ it"""
        fn = call.get("function") or {}
        name, args = fn.get("name", "?"), fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                pass
        spinner = Spinner(out, name).start() if tty else None
        t0 = time.monotonic()
        try:
            ok, result = self.hub.call(name, args)
        finally:
            if spinner:
                spinner.stop()
        out.write(tool_line(name, args, time.monotonic() - t0, ok, None if ok else result, tty) + "\n")
        out.flush()
        msg = {"role": "tool", "tool_name": name, "content": result if ok else f"error: {result}"}
        if call.get("id"):
            msg["tool_call_id"] = call["id"]
        self.messages.append(msg)
