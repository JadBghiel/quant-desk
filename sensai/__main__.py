"""cli entry, `python -m sensai`"""

import argparse
import sys

from sensai import __version__
from sensai import profile as prof
from sensai.chat import Session
from sensai.commands import resumed_msg, tool_warnings
from sensai.config import ConfigError, load_config
from sensai.home import user_dir
from sensai.mcp_client import ToolHub
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
    p.add_argument("--trace", action="store_true", help="show the details of each step (results, tokens)")
    p.add_argument("--version", action="version", version=f"sensai {__version__}")
    return p.parse_args(argv)


def load_or_setup_profile(path):
    """1st run -> questions if stdin is a terminal, a broken file -> warning + no profile"""
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


def start_tools(cfg, home):
    """starts the MCP servers, a broken one -> warning, None if no server is set"""
    servers = cfg.get("mcp_servers") or []
    if not servers:
        return None
    hub = ToolHub(log_dir=home / "logs")
    for w in hub.start(servers):
        print(f"[warning] {w}")
    return hub


def tools_msg(hub):
    if not hub:
        return "no tools, add MCP servers under mcp_servers in config.yaml"
    up = [s for s in hub.servers.values() if s["status"] == "up"]
    return f"tools: {len(hub.tools)} from {len(up)} server(s), /tools to list them"


def main(argv=None):
    args = parse_args(argv)
    try:
        cfg = load_config(args.config, model=args.model, host=args.host)
        client = OllamaClient(cfg["ollama"]["host"], cfg["ollama"].get("timeout", 120))
        # fail at startup, before the 1st prompt
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
    profile = load_or_setup_profile(profile_path)
    try:
        hub = start_tools(cfg, home)
    except KeyboardInterrupt:
        return 130
    try:
        session = Session(client, cfg["model"], cfg.get("system_prompt"), cfg.get("show_thinking", True),
                          store=store, profile=profile, profile_path=profile_path,
                          hub=hub, max_steps=cfg.get("max_steps", 12),
                          token_budget=cfg.get("token_budget", 60000), show_trace=args.trace,
                          judge_model=cfg.get("judge_model"))
        intro = [tools_msg(hub), *tool_warnings(hub)]
        if record:
            session.load_record(record)
            intro.append(resumed_msg(session, record, sys.stdout.isatty()))
        repl(session, "\n".join(intro))
    finally:
        if hub:
            hub.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
