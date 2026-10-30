"""chat session: history, system msg, persistence, 1 question goes to the reasoning loop in loop.py"""

import copy
import sys
from datetime import datetime

from sensai import loop, note, react
from sensai import profile as prof
from sensai.data import today as data_today
from sensai.react import Trace
from sensai.ui import RESET

NOTE_KEPT = "this answer was saved before note rollback existed, the note stays as it is"


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
                 show_trace=False, judge_model=None, notes=True, guard=True, pretty=False):
        self.client = client
        # ev1: /judge asks this model, the chat model when the cfg has none
        self.judge_model = judge_model or model
        self.hub = hub
        # the reasoning loop's budget per question: tool calls, and tokens read + written
        self.max_steps = max_steps
        self.token_budget = token_budget
        self.show_trace = show_trace
        # /pretty: display only and not saved, the eval stays raw
        self.pretty = pretty
        # m4: the update_note tool + its rule, off in the eval -> its scores stay comparable
        self.notes = notes
        # ev4: the rule on instructions inside tool results, off in the eval like the note
        self.guard = guard
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
            tools = self.hub.capabilities() + "\n\n" + react.rules(names, self.notes, self.guard)
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
        self.failed = None
        self.messages = [{"role": "system", "content": self.system_text()}]

    def load_record(self, record):
        """resume a saved session, the system msg is rebuilt w/ today's date, the tools and the profile"""
        self.id = record["id"]
        self.title = record.get("title")
        self.created = record.get("created", _now())
        self.traces = list(record.get("traces") or [])
        self.note = record.get("note") or note.empty()
        self.failed = None
        # tool msgs kept -> the model still has the data it fetched
        self.messages = [{"role": "system", "content": self.system_text()},
                         *[m for m in record["messages"] if m.get("role") in ("user", "assistant", "tool")]]

    def record(self):
        return {"id": self.id, "title": self.title, "created": self.created, "updated": _now(),
                "model": self.model, "messages": self.turns(), "traces": self.traces,
                "note": self.note}

    def save(self):
        """a failed save is a warning, the chat goes on. 0 turns left after /undo -> the file goes,
        --resume then finds the session before it"""
        if not self.store:
            return
        try:
            if self.turns():
                self.store.save(self.record())
            else:
                self.store.delete(self.id)
        except OSError as e:
            print(f"\n[warning] session not saved: {e}")

    def set_note(self, value):
        """the note and its file follow the history, no ref to a question that's gone"""
        if value == self.note:
            return
        self.note = value
        try:
            note.write(self)
        except OSError as e:
            print(f"\n[warning] note file not updated: {e}")

    # --- 1 question -> reasoning rounds -> 1 streamed answer

    def ask(self, text, out=sys.stdout):
        """streams the answer to out, the turn stays in the history if the answer completed

        error or Ctrl+C at any point (mid stream, mid tool call) -> history back to before the
        question and no trace, the question stays in self.failed for /retry
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
            self.set_note(before)
            self.failed = text
            raise
        entry = trace.to_dict()
        if self.note != before:
            # the note as it was before this turn, /undo needs it after a --resume too
            entry["note_before"] = before
        self.traces.append(entry)
        self.failed = None
        if self.title is None:
            self.title = " ".join(text.split())[:60]
        self.save()
        return answer

    # --- /undo and /retry

    def last_question(self):
        """what /retry sends: the question that just failed, or the last 1 in the history, None w/o any"""
        if self.failed:
            return self.failed
        return next((m["content"] for m in reversed(self.messages) if m["role"] == "user"), None)

    def pop_turn(self):
        """the last turn out of the history (question, tool calls, tool msgs, answer), its trace and
        its note edits -> what put_back() needs, None w/o a turn"""
        users = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
        if not users:
            return None
        msgs = self.messages[users[-1]:]
        # note_step edits the note in place, the copies keep the old turn safe during a retry
        turn = {"messages": msgs, "title": self.title, "note": copy.deepcopy(self.note), "trace": None}
        del self.messages[users[-1]:]
        # the sessions older than the traces have turns w/o 1
        if self.traces and self.traces[-1].get("question") == msgs[0]["content"]:
            turn["trace"] = self.traces.pop()
        trace = turn["trace"] or {}
        if "note_before" in trace:
            self.set_note(copy.deepcopy(trace["note_before"]))
        # edits saved before the snapshots existed, the note cant go back
        turn["note_kept"] = "note_before" not in trace and any(n.get("ok") for n in trace.get("notes") or [])
        if len(users) == 1:
            self.title = None
        return turn

    def put_back(self, turn):
        """reverse of pop_turn()"""
        self.messages += turn["messages"]
        if turn["trace"]:
            self.traces.append(turn["trace"])
        self.title = turn["title"]
        self.set_note(turn["note"])

    def undo(self):
        """the last turn removed from the history and the saved session -> the turn, None w/o a turn
        the failed question goes too, it was asked on a history that changes"""
        turn = self.pop_turn()
        if turn:
            self.failed = None
            self.save()
        return turn

    def retry(self, out=sys.stdout):
        """asks last_question() again. after a normal answer the new turn replaces the old 1 once it
        completes, a failure brings the old 1 back and the session file never changed"""
        if self.failed:
            return self.ask(self.failed, out)
        turn = self.pop_turn()
        if turn["note_kept"]:
            out.write(f"{NOTE_KEPT}\n")
        try:
            return self.ask(turn["messages"][0]["content"], out)
        except BaseException:
            self.put_back(turn)
            # back in the history, a next /retry must not send it twice
            self.failed = None
            raise
