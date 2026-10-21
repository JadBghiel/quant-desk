"""1 json file per session in ~/.sensai/sessions: user, assistant and tool msgs

the system msg isnt stored, its rebuilt on resume w/ today's date, the tools and the current profile
"""

import json
import os
from datetime import datetime
from pathlib import Path


class SessionError(Exception):
    """unknown, ambiguous or corrupt session, shown as a plain msg"""


class SessionStore:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def new_id(self, now=None):
        """start time, sortable and readable, same second -> -2, -3..."""
        base = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        sid, n = base, 2
        while (self.dir / f"{sid}.json").exists():
            sid, n = f"{base}-{n}", n + 1
        return sid

    def save(self, record):
        # tmp file then rename -> a crash mid write cant leave a half json
        path = self.dir / f"{record['id']}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def _read(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
            return None
        return data

    def recent(self, n=10):
        """(records, nb of corrupt files skipped), most recently updated 1st"""
        records, bad = [], 0
        for path in self.dir.glob("*.json"):
            data = self._read(path)
            if data is None:
                bad += 1
            else:
                records.append(data)
        records.sort(key=lambda r: r.get("updated", ""), reverse=True)
        return records[:n], bad

    def latest(self):
        records, _ = self.recent(1)
        if not records:
            raise SessionError("no saved session yet")
        return records[0]

    def load(self, ref):
        """ref = full id, a unique prefix, or "last\""""
        if ref in (None, "", "last"):
            return self.latest()
        exact = self.dir / f"{ref}.json"
        matches = [exact] if exact.is_file() else sorted(self.dir.glob(f"{ref}*.json"))
        if not matches:
            raise SessionError(f"no session matches {ref}, /sessions lists them")
        if len(matches) > 1:
            ids = ", ".join(p.stem for p in matches[:5])
            raise SessionError(f"{ref} matches {len(matches)} sessions ({ids}), be more precise")
        data = self._read(matches[0])
        if data is None:
            raise SessionError(f"session {matches[0].stem} is corrupt, cant resume it")
        return data
