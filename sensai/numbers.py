"""reading the numbers out of a text (an answer, a news summary, a script's output) for the ev1 check

each number keeps its unit, its sign when 1 is written, its scale (81.6 billion -> 81.6e9), the
precision it was written w/ (-> the tolerance) and its significant digits
dates, times, list numbering, urls, file names, code and index names (S&P 500) are blanked 1st
"""

import re

SCALES = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9,
          "billion": 1e9, "t": 1e12, "trillion": 1e12}
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
# spans that hold digits but no claim, blanked before the numbers are read
MASKS = [re.compile(p, re.I | re.M) for p in (
    r"```.*?```", r"`[^`\n]*`",
    r"\b(?:https?|sandbox|file)://\S+", r"\]\([^)]*\)",
    r"[\w./-]+\.(?:png|jpe?g|svg|csv|json|py|md|txt|pdf)\b",
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\b(?:19|20)\d{2}\s?[/-]\s?(?:(?:19|20)\d{2}|\d{2})\b",  # 2023/24, 2025-2026
    rf"\b{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+\d{{4}})?",
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH}(?:,?\s+\d{{4}})?",
    r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s?[ap]m)?\b",
    r"s&p\s?500|nasdaq[-\s]?100|russell\s?[123]000|dow\s?(?:jones\s?)?30|ftse\s?100|dax\s?40|cac\s?40|"
    r"stoxx\s?(?:50|600)|nikkei\s?225",
    r"\b\d{3,6}\.[a-z]{1,3}\b",  # tickers like 000660.KS
    r"^\s*(?:#+\s*)?(?:\*\*)?\d{1,2}[.)](?=\s)",  # list numbering
    r"\[\d+\]",
    # durations (30 day corr, last 12 months) are parameters of the question
    r"\b\d+[-\s](?:trading[-\s])?(?:day|week|month|year|quarter|hour|minute|session)s?\b",
)]
NUM = re.compile(r"(?<![\w.,])([$€£])?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")
WORD = re.compile(r"[A-Za-z][A-Za-z&]+")
STOP = set("""this that with from have were been over last which their about into than then also more
most very such when where what will would could should there these those after before between
during since until while here they them your just only some each other same based shows show
data value values total using used close""".split())
UNIT = re.compile(r"\s?(%|×|x(?![a-z])|bps|bp|pts|pp|thousand|million|billion|trillion|bn|mn|[kmbt](?![a-z]))", re.I)


def _blank(text):
    for mask in MASKS:
        text = mask.sub(lambda m: " " * len(m.group()), text)
    return text


def numbers(text, claims_only=False):
    """-> list of {text, value, tol, pct, signed, sig, start, end}, value w/ its scale applied,
    sig = significant digits as written

    claims_only skips what isnt a claim in an answer: years, integers under 10 w/o a unit
    """
    out = []
    blank = _blank(text)
    for m in NUM.finditer(blank):
        cur, whole, dec = m.groups()
        end = m.end()
        unit = UNIT.match(blank, end)
        unit_s = unit.group(1).lower() if unit else ""
        if unit:
            end = unit.end()
        elif end < len(blank) and blank[end].isalpha():
            continue  # 3nm, 10th, 4o...
        start = m.start()
        before = blank[start - 1] if start else ""
        signed = bool(before) and before in "-−+" and (start < 2 or not blank[start - 2].isalnum())
        sign = -1 if signed and before != "+" else 1
        value = float(whole.replace(",", "") + (f".{dec}" if dec else ""))
        decimals = len(dec) if dec else 0
        scale = SCALES.get(unit_s, 1.0)
        if claims_only and not cur and not dec:
            if not unit_s and (value < 10 or 1900 <= value <= 2100):
                continue
            if unit_s in ("m", "b", "t", "k") and value < 10:
                continue  # 6M = 6 months more often than 6 million
        digits = (whole.replace(",", "") + (dec or "")).lstrip("0").rstrip("0")
        out.append({"text": text[start - signed:end].strip(), "value": sign * value * scale,
                    "tol": 0.5 * 10 ** -decimals * scale, "pct": unit_s in ("%", "pts", "pp"),
                    "unit": unit_s, "signed": signed, "sig": len(digits), "decimals": decimals,
                    "start": start - signed, "end": end})
    return out


def words(text):
    """tickers and words of 4 letters or more, lowercased, a plural s dropped"""
    out = set()
    for w in WORD.findall(text):
        if w.isupper() and 2 <= len(w) <= 5 or len(w) >= 4:
            w = w.lower().replace("&", "")
            w = w[:-1] if len(w) > 4 and w.endswith("s") else w
            if w not in STOP:
                out.add(w)
    return out
