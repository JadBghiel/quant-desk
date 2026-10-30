"""terminal bits: ansi codes, the thinking spinner, the tool call lines, file links and the /pretty renderer"""

import base64
import os
import re
import shutil
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

DIM, BOLD, RESET, CLEAR_LINE = "\033[2m", "\033[1m", "\033[0m", "\r\033[K"
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


def web_link(url, label):
    """a web url behind a label (OSC 8), file_link is the 1 for local paths"""
    return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"


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


# terminals known to open OSC 8 links, the others keep the full url or the address would be lost
LINK_TERMS = {"vscode", "iTerm.app", "WezTerm"}

# no space or control char -> no escape code can get inside the OSC 8 sequence, 1 level of () kept for wikipedia style urls
URL = r"https?://(?:[^\s<>()\[\]`\x00-\x1f\x7f]|\([^\s<>()\x00-\x1f\x7f]*\))+"
# ** next to a word char isnt bold: 2**3**4 would print as 234. spans capped -> a line full of ** stays linear
INLINE = re.compile(r"`(?P<code>[^`\n]+)`"
                    r"|(?<![\w*])\*\*(?=\S)(?P<bold>.{1,500}?)(?<=\S)\*\*(?![\w*])"
                    r"|\[(?P<text>[^\]\n]{1,300})\]\((?P<target>" + URL + r")\)"
                    r"|(?P<url>" + URL + ")")
TITLE = re.compile(r"#{1,3}[ \t]+(.+)")
BULLET = re.compile(r"(\s*)[-*][ \t]+(.*)")
TABLE_SEP = re.compile(r"\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*")
STYLES = re.compile(r"\033\]8;;.*?\033\\|\033\[[0-9;]*m")


def visible_len(text):
    """columns the text takes on screen: w/o the styles and links, wide chars count 2"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in STYLES.sub("", text))


def table_cells(line):
    line = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


class LineRenderer:
    """/pretty: the model's markdown as real text, display only, the raw text stays in the history

    holds the text until a line is complete, a table until it ends. each line's newline waits for
    the next line -> a dropped code fence takes it over and the output ends w/ a newline when the raw
    text does, the blank lines of the loop read content.endswith("\\n")
    """

    def __init__(self, width=None, links=None):
        self.width = width
        self.links = os.environ.get("TERM_PROGRAM") in LINK_TERMS if links is None else links
        self.hold = ""
        self.owed = ""
        self.table = []  # (line, newline)
        self.code = False

    def feed(self, text):
        """-> what can be printed now, "" while the line isnt complete"""
        *lines, self.hold = (self.hold + text).split("\n")
        return "".join(self._line(line, "\n") for line in lines)

    def finish(self):
        """-> the rest: the last line, a table still held, the newline owed"""
        hold, self.hold = self.hold, ""
        shown = (self._line(hold, "") if hold else "") + self._end_table()
        owed, self.owed = self.owed, ""
        return shown + owed

    def _emit(self, text, newline):
        shown = self.owed + text
        self.owed = newline
        return shown

    def _line(self, line, newline):
        if line.lstrip().startswith("```"):
            shown = self._end_table()
            self.code = not self.code
            self.owed = newline if self.owed else ""
            return shown
        if self.code:
            return self._emit(f"{DIM}{line}{RESET}" if line else "", newline)
        if line.lstrip().startswith("|"):
            self.table.append((line, newline))
            return ""
        return self._end_table() + self._emit(self._style(line), newline)

    def _style(self, line):
        title = TITLE.fullmatch(line)
        if title:
            return f"{BOLD}{self._inline(title[1], False)}{RESET}"
        bullet = BULLET.fullmatch(line)
        if bullet:
            return f"{bullet[1]}• {self._inline(bullet[2])}"
        return self._inline(line)

    def _inline(self, text, styled=True):
        """styled=False inside a bold span or a title: the markers go, the bold stays on"""
        parts, pos = [], 0
        for m in INLINE.finditer(text):
            parts.append(text[pos:m.start()])
            pos = m.end()
            if m["code"] is not None:
                parts.append(f"{DIM}{m['code']}{RESET}" if styled else m["code"])
            elif m["bold"] is not None:
                inner = self._inline(m["bold"], False)
                parts.append(f"{BOLD}{inner}{RESET}" if styled else inner)
            elif m["target"] is not None:
                parts.append(f"{self._inline(m['text'], styled)} ({self._link(m['target'])})")
            else:
                url = m["url"].rstrip(".,;:!?'\"*")
                parts.append(self._link(url) + m["url"][len(url):])
        return "".join(parts) + text[pos:]

    def _link(self, url):
        """the real host + an arrow behind the link -> a [fool.com](evil.com) shows evil.com"""
        host = urlsplit(url).hostname if self.links else None
        return web_link(url, f"{host.removeprefix('www.')} ↗") if host else url

    def _end_table(self):
        """the lines held -> aligned columns, raw when too wide, normal lines w/o a separator row"""
        rows, self.table = self.table, []
        if not rows:
            return ""
        lines = [line for line, _ in rows]
        if len(lines) < 2 or not TABLE_SEP.fullmatch(lines[1]):
            return "".join(self._emit(self._style(line), newline) for line, newline in rows)
        cells = [table_cells(line) for line in lines[:1] + lines[2:]]
        n = max(len(row) for row in cells)
        shown = [[self._inline(c, i > 0) for c in row] + [""] * (n - len(row)) for i, row in enumerate(cells)]
        widths = [max(visible_len(row[col]) for row in shown) for col in range(n)]
        if sum(widths) + 2 * (n - 1) > (self.width or shutil.get_terminal_size().columns):
            return self._emit("\n".join(lines), rows[-1][1])

        def join(row):
            return "  ".join([c + " " * (w - visible_len(c)) for c, w in zip(row, widths[:-1])] + row[-1:])

        out = [f"{BOLD}{join(shown[0])}{RESET}", f"{DIM}{'  '.join('─' * w for w in widths)}{RESET}"]
        return self._emit("\n".join(out + [join(row) for row in shown[1:]]), rows[-1][1])


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


def _n(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def check_block(checks, tty=True):
    """the ev1 lines under the answer, "" when the answer doesnt have a number
    1 line when all are found, else the counts + 1 ✗ line per number not found w/ the words around
    it, + 1 line per run_python step that types data in, + 1 line w/ the numbers only in news or web text"""
    if not checks or not (checks.get("n") or checks.get("hardcoded")):
        return ""
    dim, reset, red = (DIM, RESET, RED) if tty else ("", "", "")
    n, derived, missing = checks["n"], checks["derived"], checks["unsourced"]
    code = [f"  {red}✗{reset} run_python (step {h['step']}) types in {h['count']} numbers not found in the tool "
            f"results {dim}{h['sample']}{reset}" for h in checks.get("hardcoded") or []]
    text = list(dict.fromkeys(i["text"] for i in checks.get("items") or [] if i.get("text_only")))
    if text:
        code.append(f"{dim}{len(text)} only in news or web text, unverified: {', '.join(text[:6])}"
                    f"{', ...' if len(text) > 6 else ''}{reset}")
    if not missing:
        how = f", {derived} derived from them" if derived else ""
        head = f"{dim}checked: {_n(n, 'number')}, all found in the tool results{how}{reset}" if n else ""
        return "\n".join([line for line in [head] if line] + code) + "\n"
    lines = [f"{dim}checked: {_n(n, 'number')} · {checks['sourced']} found · {derived} derived · "
             f"{reset}{red}{missing} not found in the tool results{reset}"]
    for item in checks["items"]:
        if item["status"] == "unsourced":
            lines.append(f"  {red}✗{reset} {item['text']}  {dim}{item['context'][:80]}{reset}")
    return "\n".join(lines + code) + "\n"


MARKS = {"sourced": "✓", "derived": "≈", "unsourced": "✗"}
VERDICT_MARKS = {"supported": "✓", "contradicted": "✗", "unverifiable": "?"}


def format_checks(checks, tty=True):
    """/check: 1 line per number, its status and where it was found"""
    dim, reset, green, red = (DIM, RESET, GREEN, RED) if tty else ("", "", "", "")
    code = [f"{red}✗{reset} run_python (step {h['step']}) types in {h['count']} numbers not found in the tool "
            f"results: {h['sample']}" for h in (checks or {}).get("hardcoded") or []]
    if not checks or not checks.get("n"):
        return "\n".join(code or ["no number in the last answer"])
    lines = [f"{checks['n']} numbers · {checks['sourced']} found · {checks['derived']} derived · "
             f"{checks['unsourced']} not found in the tool results"]
    width = max(len(i["text"]) for i in checks["items"])
    for i in checks["items"]:
        color = {"sourced": green, "unsourced": red}.get(i["status"], "")
        where = {"sourced": i["source"], "derived": f"derived: {i['source']}"}.get(i["status"], "not found")
        where += " (text only)" if i.get("text_only") else ""
        lines.append(f"  {color}{MARKS[i['status']]}{reset} {i['text']:<{width}}  {where:<26} {dim}{i['context'][:70]}{reset}")
    return "\n".join(lines + code)


def format_judge(v, tty=True):
    dim, reset, green, red = (DIM, RESET, GREEN, RED) if tty else ("", "", "", "")
    lines = [f"judge ({v['model']}): relevance {v['relevance']}/5 · coherence {v['coherence']}/5 · "
             f"faithfulness {v['faithfulness']}/5"]
    for c in v["claims"]:
        color = {"supported": green, "contradicted": red}.get(c["verdict"], "")
        src = f"  {dim}({c['source']}){reset}" if c["source"] and c["source"] != "none" else ""
        lines.append(f"  {color}{VERDICT_MARKS[c['verdict']]} {c['verdict']:<12}{reset} {c['claim']}{src}")
    if v.get("comment"):
        lines.append(f"{dim}{v['comment']}{reset}")
    return "\n".join(lines)
