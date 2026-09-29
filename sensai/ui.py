"""terminal bits: ansi codes + the thinking spinner"""

import threading
import time

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
