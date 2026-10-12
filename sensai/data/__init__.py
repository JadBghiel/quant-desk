"""market data layer, used by the MCP server now and by the sandbox / eval later

no printing, no MCP here. every failure the user can act on is a DataError w/ a plain msg
"""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class DataError(Exception):
    """bad ticker, api limit, missing key... msg goes as is to the model"""


def data_dir():
    """$SENSAI_DATA or <repo>/data. market data isnt personal so it stays next to the code, gitignored"""
    d = Path(os.environ.get("SENSAI_DATA") or REPO / "data").expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def sub_dir(name):
    d = data_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d
