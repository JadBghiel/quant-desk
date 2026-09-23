"""cli entry, `python -m sensai`"""

import argparse
import sys

from sensai import __version__
from sensai.chat import Session, repl
from sensai.config import ConfigError, load_config
from sensai.ollama import OllamaClient, OllamaError


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="sensai", description="research agent for quants, runs on ollama")
    p.add_argument("--model", help="ollama model to use, overrides config.yaml")
    p.add_argument("--host", help="ollama host, overrides config.yaml")
    p.add_argument("--config", default="config.yaml", help="path to the config file (default: config.yaml)")
    p.add_argument("--version", action="version", version=f"sensai {__version__}")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        cfg = load_config(args.config, model=args.model, host=args.host)
        client = OllamaClient(cfg["ollama"]["host"], cfg["ollama"].get("timeout", 120))
        # fail at startup not on the 1st prompt
        client.check_auth()
        client.check_model(cfg["model"])
    except (ConfigError, OllamaError) as e:
        print(f"sensai: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    repl(Session(client, cfg["model"], cfg.get("system_prompt"), cfg.get("show_thinking", True)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
