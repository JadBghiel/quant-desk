"""input loop: questions go to the session, /cmds to commands.py

readline edits the line: arrow keys, up / down through the past inputs (kept across runs in
~/.sensai/history), tab completion of the /cmds. macOS python ships libedit (GNU readline elsewhere), the 2
bind tab w/ a different syntax. libedit cant tell a paste from typing -> a multi line question goes
between 2 lines of 3 double quotes
"""

import os

from sensai.commands import CMDS, handle_cmd, send
from sensai.home import user_dir

try:
    import readline
except ImportError:  # windows w/o pyreadline, plain input() and the blocks still work
    readline = None

BLOCK = '"""'
HISTORY_LEN = 1000
SUBCMDS = {"/profile": ["setup", "edit"]}


def history_path():
    return user_dir() / "history"


def candidates(line, store=None):
    """the line typed so far -> the completions of its last word"""
    words = line.split(" ")
    if len(words) == 1:
        if not words[0].startswith("/"):
            return []
        return [c for c in sorted([*CMDS, "/exit"]) if c.startswith(words[0])]
    if len(words) == 2:
        cmd, part = words
        options = SUBCMDS.get(cmd, [])
        if cmd == "/resume" and store:
            # newest 1st, the ids are start times
            options = ["last", *sorted((p.stem for p in store.dir.glob("*.json")), reverse=True)]
        return [o for o in options if o.startswith(part)]
    return []


def setup(store=None):
    """history + tab completion, nothing w/o readline"""
    if readline is None:
        return
    # added by hand in remember() -> a block is 1 entry
    readline.set_auto_history(False)
    readline.set_history_length(HISTORY_LEN)
    try:
        readline.read_history_file(history_path())
    except OSError:
        pass  # 1st run or a broken file, rewritten at the next input

    def complete(text, state):
        options = candidates(readline.get_line_buffer()[:readline.get_endidx()], store)
        return options[state] if state < len(options) else None

    readline.set_completer(complete)
    # "/" stays in the word, `/re` + tab completes the whole cmd
    readline.set_completer_delims(" \t\n")
    libedit = getattr(readline, "backend", "") == "editline" or "libedit" in (readline.__doc__ or "")
    readline.parse_and_bind("bind ^I rl_complete" if libedit else "tab: complete")


def remember(text):
    """1 history entry per input, a block on 1 line (a newline would split it in the file), the file
    written each time -> kept even if sensai is killed"""
    if readline is None:
        return
    entry = " ".join(text.split())
    n = readline.get_current_history_length()
    if n and readline.get_history_item(n) == entry:
        return
    readline.add_history(entry)
    path = history_path()
    try:
        readline.write_history_file(path)
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_input(read=None):
    """1 question or cmd, None when the user quits (Ctrl+D or Ctrl+C at the prompt)
    a line w/ 3 double quotes alone opens a block, the next 1 sends it as 1 question"""
    read = read or input
    while True:
        # the blank line printed apart, a \n inside the prompt breaks the redraw of a recalled line
        print()
        try:
            line = read("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if line.strip() != BLOCK:
            return line.strip()
        lines = []
        try:
            while (line := read("... ")).strip() != BLOCK:
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            print("\nblock cancelled")
            continue
        return "\n".join(lines).strip()


def repl(session, intro=None):
    print(f"sensai, model {session.model}. /help for cmds")
    if intro:
        print(intro)
    setup(session.store)
    while True:
        text = read_input()
        if text is None:
            return
        if not text:
            print("empty input, type a question or /help")
            continue
        remember(text)
        if text.startswith("/"):
            if handle_cmd(session, text):
                return
            continue
        send(lambda: session.ask(text))
