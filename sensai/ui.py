"""terminal bits: ansi codes, the thinking spinner, the tool call lines and file links"""

import base64
import os
import threading
import time
from pathlib import Path

DIM, RESET, CLEAR_LINE = "\033[2m", "\033[0m", "\r\033[K"
GREEN, RED = "\033[32m", "\033[31m"
FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Spinner:
    """animated "thinking 1.2s" line, redrawn by a thread until stop() wipes it

    stop() joins the thread -> nothing it writes can land in the middle of the answer
    1 shot, a new Spinner for every wait
    """

    def __init__(self, out, label="thinking", interval=0.1):
        self.out = out
        self.label = label
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        t0 = time.monotonic()

        def run():
            i = 0
            while not self._stop.is_set():
                self.out.write(f"{CLEAR_LINE}{DIM}{FRAMES[i % len(FRAMES)]} {self.label} {time.monotonic() - t0:.1f}s{RESET}")
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


def file_link(path, tty=True):
    """path as a terminal link (OSC 8), cmd/ctrl+click opens it, the terminal's own path detection
    stops at the 1st space and the repo path has 1 -> the link carries the full url, a terminal w/o
    OSC 8 shows the plain path"""
    if not tty:
        return str(path)
    return f"\033]8;;{Path(path).resolve().as_uri()}\033\\{path}\033]8;;\033\\"


# terminals that draw images sent w/ the iTerm2 protocol, VS Code needs terminal.integrated.enableImages
IMAGE_TERMS = {"vscode", "iTerm.app", "WezTerm"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif"}
MAX_IMAGE = 5_000_000  # bytes, a bigger file stays a link


def inline_image(path, tty=True, width="60%"):
    """the image as an iTerm2 escape code the terminal draws in place, "" when it cant -> the link
    above it is the fallback, a terminal that doesnt know the code ignores it"""
    path = Path(path)
    if not tty or os.environ.get("TERM_PROGRAM") not in IMAGE_TERMS or path.suffix.lower() not in IMAGE_EXTS:
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > MAX_IMAGE:
        return ""
    name = base64.b64encode(path.name.encode()).decode()
    return (f"\033]1337;File=name={name};size={len(data)};inline=1;width={width};preserveAspectRatio=1:"
            f"{base64.b64encode(data).decode()}\a")


def fmt_args(args, width=70):
    """{"ticker": "AAPL", "days": 7} -> ticker=AAPL, days=7, cut at width, a multi line value
    (the sandbox's code) squeezed on 1 line"""
    if not isinstance(args, dict):
        text = repr(args)
    else:
        text = ", ".join(f"{k}={v}" for k, v in args.items())
    text = " ".join(text.split())
    return text if len(text) <= width else text[:width - 3] + "..."


def tool_line(name, args, secs, ok, error=None, tty=True):
    """1 line per call: ⚙ get_prices(ticker=AAPL)  0.4s ✓, or ✗ + the 1st line of the error"""
    dim, reset, green, red = (DIM, RESET, GREEN, RED) if tty else ("", "", "", "")
    line = f"{dim}⚙ {name}({fmt_args(args)})  {secs:.1f}s{reset} "
    if ok:
        return line + f"{green}✓{reset}"
    msg = (error or "failed").strip().splitlines()[0].removeprefix(f"Error executing tool {name}: ")
    return line + f"{red}✗ {msg[:120]}{reset}"
