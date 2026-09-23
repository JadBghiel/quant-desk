"""chat session + repl, the base loop every later feature plugs into"""

import sys
import threading
import time

from sensai.ollama import OllamaError

HELP = """cmds:
  /model          show the current model and the available ones
  /model <name>   switch model, history is kept
  /clear          empty the history
  /think          show or hide the model's thinking
  /help           this list
  /exit           quit (Ctrl+D works too)
Ctrl+C during an answer stops it"""


DIM, RESET, CLEAR_LINE = "\033[2m", "\033[0m", "\r\033[K"
FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Spinner:
    """animated "thinking 1.2s" line, redrawn by a thread until stop() wipes it

    stop() joins the thread so nothing it writes can land in the middle of the answer
    """

    def __init__(self, out, interval=0.1):
        self.out = out
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        t0 = time.monotonic()

        def run():
            i = 0
            while not self._stop.is_set():
                self.out.write(f"{CLEAR_LINE}{DIM}{FRAMES[i % len(FRAMES)]} thinking {time.monotonic() - t0:.1f}s{RESET}")
                self.out.flush()
                i += 1
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return self

    @property
    def running(self):
        return self._thread is not None

    def stop(self):
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()
        self._thread = None
        self.out.write(CLEAR_LINE)
        self.out.flush()


class Session:
    def __init__(self, client, model, system_prompt=None, show_thinking=True):
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.show_thinking = show_thinking
        self.messages = []
        self.clear()

    def clear(self):
        self.messages = [{"role": "system", "content": self.system_prompt}] if self.system_prompt else []

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
        return answer


def repl(session):
    print(f"sensai, model {session.model}. /help for cmds")
    while True:
        try:
            text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            print("empty input, type a question or /help")
            continue
        if text.startswith("/"):
            if handle_cmd(session, text):
                return
            continue
        try:
            session.ask(text)
            print()
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except OllamaError as e:
            print(f"\n[error] {e}")


def handle_cmd(session, text):
    """returns True when the repl should stop"""
    cmd, _, arg = text.partition(" ")
    arg = arg.strip()
    if cmd == "/exit":
        return True
    if cmd == "/help":
        print(HELP)
    elif cmd == "/clear":
        session.clear()
        print("history cleared")
    elif cmd == "/think":
        session.show_thinking = not session.show_thinking
        print(f"thinking {'shown' if session.show_thinking else 'hidden'}")
    elif cmd == "/model":
        try:
            if not arg:
                print(f"current: {session.model}")
                print("available: " + ", ".join(session.client.list_models()))
            else:
                session.client.check_model(arg)
                session.model = arg
                print(f"switched to {arg}, history kept")
        except OllamaError as e:
            print(f"[error] {e}")
    else:
        print(f"unknown cmd {cmd}, /help for the list")
    return False
