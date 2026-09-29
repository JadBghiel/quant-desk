"""user profile, ~/.sensai/profile.yaml -> injected in the system prompt at init

every field is optional, an empty one is just left out of the prompt
"""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import yaml

# key, question asked in the setup, kind. order = order in the yaml and in the prompt
FIELDS = [
    ("name", "your name", "text"),
    ("sectors", "sectors / industries you follow, comma separated", "list"),
    ("watchlist", "main tickers you follow, comma separated", "tickers"),
    ("benchmark", "benchmark (e.g. SPY)", "ticker"),
    ("style", "research style (e.g. concise, formula before the number)", "text"),
    ("notes", "anything sensai should always know", "notes"),
]
KINDS = {k: kind for k, _, kind in FIELDS}
LABELS = {
    "name": "Name",
    "sectors": "Sectors followed",
    "watchlist": "Main tickers",
    "benchmark": "Benchmark",
    "style": "Research style",
}


class ProfileError(Exception):
    """bad profile file or bad cmd arg, shown as a plain msg"""


def normalize(raw):
    """known fields coerced to their kind, empty ones dropped, unknown keys kept as is"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ProfileError("the profile must be a mapping of fields")
    p = {}
    for key, value in raw.items():
        kind = KINDS.get(key)
        if kind is None:
            p[key] = value
            continue
        if value is None or value == "" or value == []:
            continue
        if kind in ("list", "tickers", "notes"):
            items = value.split(",") if isinstance(value, str) and kind != "notes" else value
            if isinstance(items, str):
                items = [items]
            if not isinstance(items, list):
                raise ProfileError(f"{key} must be a list")
            items = [str(x).strip() for x in items if str(x).strip()]
            if kind == "tickers":
                items = [x.upper() for x in items]
            if items:
                p[key] = items
        else:
            text = str(value).strip()
            if text:
                p[key] = text.upper() if kind == "ticker" else text
    return p


def load_profile(path):
    """None when there is no profile yet (-> 1st run setup), ProfileError when the yaml is broken"""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return normalize(yaml.safe_load(path.read_text(encoding="utf-8")))
    except yaml.YAMLError as e:
        raise ProfileError(f"invalid yaml in {path}: {e}") from None


def save_profile(path, p):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    body = yaml.safe_dump(p, sort_keys=False, allow_unicode=True) if p else "{}\n"
    # comments are lost on rewrite, the fields are documented in the rdme
    tmp.write_text("# sensai profile, every field is optional. /profile edit to change it\n" + body,
                   encoding="utf-8")
    os.replace(tmp, path)


def setup(ask=input, current=None, say=print):
    """asks every field, Enter skips (or keeps the current value), "-" clears it

    ask is injectable for the tests. Ctrl+C / Ctrl+D go up to the caller, nothing is saved then
    """
    first_run = current is None
    current = dict(current or {})
    if first_run:
        answer = ask("first time here. set up your profile now? every question is optional [Y/n] ")
        if answer.strip().lower() in ("n", "no"):
            return {}
        say("Enter skips a question")
    else:
        say("Enter keeps the current value, - clears it")
    p = {k: v for k, v in current.items() if k not in KINDS}
    for key, question, kind in FIELDS:
        old = current.get(key)
        if kind == "notes":
            notes = list(old or [])
            if notes:
                say(f"{len(notes)} note(s) kept, add more:")
            say(f"{question}, 1 per line, empty line to finish")
            while True:
                line = ask("  - ").strip()
                if not line:
                    break
                notes.append(line)
            if notes:
                p[key] = notes
            continue
        shown = ", ".join(old) if isinstance(old, list) else old
        answer = ask(f"{question}{f' [{shown}]' if shown else ''}: ").strip()
        if answer == "-":
            continue
        value = answer or old
        if value:
            p[key] = value
    return normalize(p)


def render(p):
    """profile -> the "about the user" block of the system prompt, "" when empty"""
    if not p:
        return ""
    lines = []
    for key, label in LABELS.items():
        value = p.get(key)
        if value:
            lines.append(f"- {label}: {', '.join(value) if isinstance(value, list) else value}")
    if p.get("notes"):
        lines.append("- Always keep in mind:")
        lines += [f"  - {n}" for n in p["notes"]]
    return "About the user:\n" + "\n".join(lines) if lines else ""


def show(p, path):
    """human view for /profile, notes numbered so /forget n is easy"""
    if not p:
        return f"profile is empty ({path}), /profile setup to fill it"
    out = []
    for key, _, kind in FIELDS:
        value = p.get(key)
        if not value:
            continue
        if kind == "notes":
            out.append("notes:")
            out += [f"  {i}. {n}" for i, n in enumerate(value, 1)]
        else:
            out.append(f"{key}: {', '.join(value) if isinstance(value, list) else value}")
    out.append(f"({path})")
    return "\n".join(out)


def remember(path, p, fact):
    fact = fact.strip()
    if not fact:
        raise ProfileError("nothing to remember, usage: /remember <fact>")
    p = dict(p or {})
    p["notes"] = [*p.get("notes", []), fact]
    save_profile(path, p)
    return p


def forget(path, p, n):
    notes = list((p or {}).get("notes", []))
    try:
        i = int(n)
        if i < 1:
            raise IndexError
        removed = notes.pop(i - 1)
    except (ValueError, IndexError):
        raise ProfileError(f"no note {n}, /profile lists them") from None
    p = dict(p)
    if notes:
        p["notes"] = notes
    else:
        p.pop("notes", None)
    save_profile(path, p)
    return p, removed


def editor_cmd():
    for var in ("VISUAL", "EDITOR"):
        if os.environ.get(var):
            return shlex.split(os.environ[var])
    for name in ("nano", "vi"):
        if shutil.which(name):
            return [name]
    raise ProfileError("no editor found, set $EDITOR or edit the file by hand")


def edit(path, p):
    """opens the file in the editor, returns the reloaded profile. bad yaml -> ProfileError, old one kept"""
    path = Path(path)
    if not path.is_file():
        save_profile(path, p or {})
    subprocess.run([*editor_cmd(), str(path)], check=False)
    new = load_profile(path)
    return new or {}
