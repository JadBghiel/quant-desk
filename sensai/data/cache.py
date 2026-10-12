"""disk cache for every api call, 1 json per call in data/cache/<kind>/

free tiers rate limit fast (alpha vantage 25/day), and when a fetch fails the last
cached value is served as stale instead of an error, thats what keeps a demo alive
"""

import hashlib
import json
import os
import time

from sensai.data import DataError, sub_dir

FOREVER = None


def _path(kind, key):
    raw = json.dumps(key, sort_keys=True, default=str)
    return sub_dir(f"cache/{kind}") / f"{hashlib.sha256(raw.encode()).hexdigest()[:24]}.json"


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write(path, entry):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def cached(kind, key, ttl, fetch, now=None):
    """(value, meta). ttl in secs, FOREVER = never expires

    meta = {"cached": bool, "stale": bool, "age_s": int}. fetch must return json serializable data
    and raise DataError on failure, a stale entry is then served if there is one
    """
    now = time.time() if now is None else now
    path = _path(kind, key)
    entry = _read(path)
    if entry is not None:
        age = now - entry["fetched_at"]
        if ttl is FOREVER or age < ttl:
            return entry["value"], {"cached": True, "stale": False, "age_s": int(age)}
    try:
        value = fetch()
    except DataError:
        if entry is None:
            raise
        # api down or limit hit, old data beats no data
        return entry["value"], {"cached": True, "stale": True, "age_s": int(now - entry["fetched_at"])}
    _write(path, {"fetched_at": now, "key": key, "value": value})
    return value, {"cached": False, "stale": False, "age_s": 0}
