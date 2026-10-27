"""market data layer, used by the MCP servers, the sandbox and the eval

no printing, no MCP here, every failure the user can act on is a DataError w/ a plain msg
"""

import os
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class DataError(Exception):
    """bad ticker, api limit, missing key... msg goes as is to the model"""


def now():
    """the clock, or $SENSAI_TODAY (2026-10-28 or a full iso time) for the eval's frozen data,
    a date alone -> the end of that day"""
    fixed = os.environ.get("SENSAI_TODAY", "").strip()
    if not fixed:
        return datetime.now()
    return datetime.fromisoformat(fixed if "T" in fixed else fixed + "T23:59:59")


def today():
    return now().date() if os.environ.get("SENSAI_TODAY") else date.today()


def offline():
    """$SENSAI_OFFLINE=1 -> the cache serves what it has, no api call (eval snapshot)"""
    return os.environ.get("SENSAI_OFFLINE", "").strip() not in ("", "0")


def data_dir():
    """$SENSAI_DATA or <repo>/data, market data isnt personal -> stays next to the code, gitignored"""
    d = Path(os.environ.get("SENSAI_DATA") or REPO / "data").expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def out_dir():
    """$SENSAI_OUT or <repo>/out, what the sandbox runs write (plots, tables), gitignored"""
    d = Path(os.environ.get("SENSAI_OUT") or REPO / "out").expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def sub_dir(name):
    d = data_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d
