"""chat session: history, system msg, persistence, 1 question -> 1 streamed answer"""

import sys
from datetime import date, datetime

from sensai import profile as prof
from sensai.ui import DIM, RESET, Spinner


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
                 profile=None, profile_path=None):
        self.client = client
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
        self.messages = [{"role": "system", "content": self.system_text()},
                         *[m for m in record["messages"] if m.get("role") in ("user", "assistant")]]

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

    # --- 1 question -> 1 streamed answer

    def ask(self, text, out=sys.stdout):
        """streams the answer to out, the turn only stays in the history if the answer completed

        the spinner runs while nothing else is on screen: waiting for the 1st chunk, and the
        whole thinking phase when /think hides it. thinking is never kept in the history
        """
        tty = out.isatty()
        dim, reset = (DIM, RESET) if tty else ("", "")
        self.messages.append({"role": "user", "content": text})
        parts, state = [], None
        # cloud models can take seconds before the 1st chunk
        spinner = Spinner(out).start() if tty else None
        try:
            for kind, chunk in self.client.chat_stream(self.model, self.messages):
                if kind == "thinking":
                    if self.show_thinking:
                        if spinner and spinner.running:
                            spinner.stop()
                        out.write((dim if state is None else "") + chunk)
                    state = state or "thinking"
                else:
                    if spinner and spinner.running:
                        spinner.stop()
                    elif state == "thinking" and self.show_thinking:
                        out.write(reset + "\n\n")
                    state = "content"
                    parts.append(chunk)
                    out.write(chunk)
                out.flush()
        except BaseException:
            if spinner:
                spinner.stop()
            out.write(reset)
            # failed or Ctrl+C -> drop the user turn so a retry sends a clean history
            self.messages.pop()
            raise
        answer = "".join(parts)
        self.messages.append({"role": "assistant", "content": answer})
        if self.title is None:
            self.title = " ".join(text.split())[:60]
        self.save()
        return answer
