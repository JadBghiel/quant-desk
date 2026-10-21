"""terminal bits: ansi codes, the thinking spinner and the tool call lines"""

import threading
import time

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


def fmt_args(args, width=70):
    """{"ticker": "AAPL", "days": 7} -> ticker=AAPL, days=7, cut at width"""
    if not isinstance(args, dict):
        text = repr(args)
    else:
        text = ", ".join(f"{k}={v}" for k, v in args.items())
    return text if len(text) <= width else text[:width - 3] + "..."


def tool_line(name, args, secs, ok, error=None, tty=True):
    """1 line per call: ⚙ get_prices(ticker=AAPL)  0.4s ✓, or ✗ + the 1st line of the error"""
    dim, reset, green, red = (DIM, RESET, GREEN, RED) if tty else ("", "", "", "")
    line = f"{dim}⚙ {name}({fmt_args(args)})  {secs:.1f}s{reset} "
    if ok:
        return line + f"{green}✓{reset}"
    msg = (error or "failed").strip().splitlines()[0].removeprefix(f"Error executing tool {name}: ")
    return line + f"{red}✗ {msg[:120]}{reset}"
