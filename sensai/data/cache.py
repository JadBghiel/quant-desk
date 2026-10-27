"""disk cache for every api call, 1 json per call in data/cache/<kind>/

free tiers rate limit fast (massive 5/min), and when a fetch fails the last cached value is
served as stale instead of an error, thats what keeps a demo alive
"""

import hashlib
import json
import os
import time

from sensai.data import DataError, offline, sub_dir

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


def _covering(kind, cover):
    """offline: the 1st entry of this kind whose key passes cover(key), eg a wider window of the
    same ticker"""
    for path in sorted(sub_dir(f"cache/{kind}").glob("*.json")):
        entry = _read(path)
        if entry and isinstance(entry.get("key"), list) and cover(entry["key"]):
            return entry
    return None


def cached(kind, key, ttl, fetch, now=None, fallback_key=None, cover=None):
    """(value, meta), ttl in secs, FOREVER = doesnt expire

    meta = {"cached": bool, "stale": bool, "age_s": int}, fetch returns json serializable data
    and raises DataError on failure -> a stale entry is served if there is one
    key usually holds today's date -> yesterday's entry cant match it, fallback_key (no date)
    also keeps the last good value, served as stale when the dated key has nothing
    cover(key) -> bool, used offline: an entry that holds what was asked when the exact key misses,
    the caller cuts it to the range it wants
    """
    now = time.time() if now is None else now
    path = _path(kind, key)
    entry = _read(path)
    if offline():
        # eval snapshot: whatever its age, and no api call
        entry = entry or (_read(_path(kind, ["last", fallback_key])) if fallback_key is not None else None)
        entry = entry or (_covering(kind, cover) if cover else None)
        if entry is None:
            raise DataError(f"not in the frozen eval data ({kind}), sensai runs offline. use the same "
                            "tickers and periods as the question, or say the data isnt there")
        return entry["value"], {"cached": True, "stale": False, "age_s": int(now - entry["fetched_at"])}
    if entry is not None:
        age = now - entry["fetched_at"]
        if ttl is FOREVER or age < ttl:
            return entry["value"], {"cached": True, "stale": False, "age_s": int(age)}
    try:
        value = fetch()
    except DataError:
        old = entry or (_read(_path(kind, ["last", fallback_key])) if fallback_key is not None else None)
        if old is None:
            raise
        # api down or limit hit, old data beats no data
        return old["value"], {"cached": True, "stale": True, "age_s": int(now - old["fetched_at"])}
    fresh = {"fetched_at": now, "key": key, "value": value}
    _write(path, fresh)
    if fallback_key is not None:
        _write(_path(kind, ["last", fallback_key]), fresh)
    return value, {"cached": False, "stale": False, "age_s": 0}
