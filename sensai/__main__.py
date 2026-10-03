"""cli entry, `python -m sensai`"""

import argparse
import sys

from sensai import __version__
from sensai import profile as prof
from sensai.chat import Session
from sensai.commands import resumed_msg
from sensai.config import ConfigError, load_config
from sensai.home import user_dir
from sensai.ollama import OllamaClient, OllamaError
from sensai.repl import repl
from sensai.sessions import SessionError, SessionStore


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="sensai", description="research agent for quants, runs on ollama")
    p.add_argument("--model", help="ollama model to use, overrides config.yaml")
    p.add_argument("--host", help="ollama host, overrides config.yaml")
    p.add_argument("--config", default="config.yaml", help="path to the config file (default: config.yaml)")
    p.add_argument("--resume", nargs="?", const="last", metavar="ID",
                   help="reopen a saved session, the last one if no id is given (a prefix works)")
    p.add_argument("--version", action="version", version=f"sensai {__version__}")
    return p.parse_args(argv)


def load_or_setup_profile(path):
    """1st run -> questions if stdin is a terminal. a broken file -> warning + no profile, not a crash"""
    try:
        p = prof.load_profile(path)
    except prof.ProfileError as e:
        print(f"[warning] {e}\nrunning w/o a profile, /profile edit to fix it")
        return {}
    if p is not None:
        return p
    if not sys.stdin.isatty():
        return {}
    try:
        p = prof.setup()
    except (KeyboardInterrupt, EOFError):
        # nothing saved -> asked again next time
        print("\nsetup skipped, it will be asked again next time")
        return {}
    prof.save_profile(path, p)
    if p:
        print(f"profile saved to {path}, /profile to see it, /profile setup to redo it")
    else:
        print("no profile for now, /profile setup whenever you want")
    return p


def main(argv=None):
    args = parse_args(argv)
    try:
        cfg = load_config(args.config, model=args.model, host=args.host)
        client = OllamaClient(cfg["ollama"]["host"], cfg["ollama"].get("timeout", 120))
        # fail at startup not on the 1st prompt
        client.check_auth()
        client.check_model(cfg["model"])
        home = user_dir()
        store = SessionStore(home / "sessions")
        record = store.load(args.resume) if args.resume else None
    except (ConfigError, OllamaError, SessionError, OSError) as e:
        print(f"sensai: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130

    profile_path = home / "profile.yaml"
    session = Session(client, cfg["model"], cfg.get("system_prompt"), cfg.get("show_thinking", True),
                      store=store, profile=load_or_setup_profile(profile_path), profile_path=profile_path)
    intro = None
    if record:
        session.load_record(record)
        intro = resumed_msg(session, record, sys.stdout.isatty())
    repl(session, intro)
    return 0


if __name__ == "__main__":
    sys.exit(main())
