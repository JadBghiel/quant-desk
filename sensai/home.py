"""per user folder for everything personal: profile + sessions

lives outside the repo so nothing personal can get committed, and the os user
already separates people on the same machine so no auth needed
"""

import os
from pathlib import Path


def user_dir():
    """$SENSAI_HOME or ~/.sensai, created 0700 on 1st use bc it holds the conversations"""
    d = Path(os.environ.get("SENSAI_HOME") or Path.home() / ".sensai").expanduser()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    (d / "sessions").mkdir(mode=0o700, exist_ok=True)
    return d
