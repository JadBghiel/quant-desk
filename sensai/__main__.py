"""cli entry, `python -m sensai`"""

import argparse
import sys

from sensai import __version__
from sensai.config import ConfigError, load_config


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
    except ConfigError as e:
        print(f"sensai: {e}", file=sys.stderr)
        return 1
    # chat loop lands in #2
    print(f"model: {cfg['model']}")
    print(f"host:  {cfg['ollama']['host']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
