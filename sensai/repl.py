"""input loop: questions go to the session, /cmds to commands.py"""

from sensai.commands import handle_cmd
from sensai.ollama import OllamaError


def repl(session, intro=None):
    print(f"sensai, model {session.model}. /help for cmds")
    if intro:
        print(intro)
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
