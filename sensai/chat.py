"""chat session: history, system msg, persistence, 1 question goes to the reasoning loop in loop.py"""

import copy
import sys
from datetime import datetime

from sensai import loop, note, react
from sensai import profile as prof
from sensai.data import today as data_today
from sensai.react import Trace
from sensai.ui import RESET


def build_system(base, profile, tools=None, today=None):
    """cfg prompt + today's date + the tools and their limits + the profile block, rebuilt on every
    start, resume and profile change"""
    today = today or data_today()
    parts = [base] if base else []
    parts.append(f"Today is {today:%A %Y-%m-%d}.")
    if tools:
        parts.append(tools)
    about = prof.render(profile)
    if about:
        parts.append(about)
    return "\n\n".join(parts)


def _now():
    return datetime.now().isoformat(timespec="seconds")


class Session:
    def __init__(self, client, model, system_prompt=None, show_thinking=True, store=None,
                 profile=None, profile_path=None, hub=None, max_steps=12, token_budget=60000,
                 show_trace=False, judge_model=None, notes=True):
        self.client = client
        # ev1: /judge asks this model, the chat model when the cfg has none
        self.judge_model = judge_model or model
        self.hub = hub
        # the reasoning loop's budget per question: tool calls, and tokens read + written
        self.max_steps = max_steps
        self.token_budget = token_budget
        self.show_trace = show_trace
        # m4: the update_note tool + its rule, off in the eval -> its scores stay comparable
        self.notes = notes
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
        tools = None
        if self.hub and self.hub.servers:
            names = [t["function"]["name"] for t in self.hub.tools]
            tools = self.hub.capabilities() + "\n\n" + react.rules(names, self.notes)
        return build_system(self.system_prompt, self.profile, tools)

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
        self.traces = []
        self.note = note.empty()
        self.messages = [{"role": "system", "content": self.system_text()}]

    def load_record(self, record):
        """resume a saved session, the system msg is rebuilt w/ today's date, the tools and the profile"""
        self.id = record["id"]
        self.title = record.get("title")
        self.created = record.get("created", _now())
        self.traces = list(record.get("traces") or [])
        self.note = record.get("note") or note.empty()
        # tool msgs kept -> the model still has the data it fetched
        self.messages = [{"role": "system", "content": self.system_text()},
                         *[m for m in record["messages"] if m.get("role") in ("user", "assistant", "tool")]]

    def record(self):
        return {"id": self.id, "title": self.title, "created": self.created, "updated": _now(),
                "model": self.model, "messages": self.turns(), "traces": self.traces,
                "note": self.note}

    def save(self):
        """a failed save is a warning, the chat goes on"""
        if not self.store or not self.turns():
            return
        try:
            self.store.save(self.record())
        except OSError as e:
            print(f"\n[warning] session not saved: {e}")

    # --- 1 question -> reasoning rounds -> 1 streamed answer

    def ask(self, text, out=sys.stdout):
        """streams the answer to out, the turn stays in the history if the answer completed

        error or Ctrl+C at any point (mid stream, mid tool call) -> history back to before the
        question and no trace, a retry sends a clean history
        """
        tty = out.isatty()
        start = len(self.messages)
        self.messages.append({"role": "user", "content": text})
        trace = Trace(text)
        before = copy.deepcopy(self.note)
        try:
            answer = loop.answer(self, out, tty, trace)
        except BaseException:
            out.write(RESET if tty else "")
            del self.messages[start:]
            if self.note != before:
                # the note follows the history, no ref to a question that's gone
                self.note = before
                try:
                    note.write(self)
                except OSError:
                    pass
            raise
        self.traces.append(trace.to_dict())
        if self.title is None:
            self.title = " ".join(text.split())[:60]
        self.save()
        return answer
