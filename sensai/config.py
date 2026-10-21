"""config.yaml + .env -> 1 dict, cli flags win over the yaml"""

from pathlib import Path

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    """bad or missing cfg, shown to the user as a plain msg w/o traceback"""


def load_config(path, model=None, host=None):
    # vars already set in the shell win over .env
    load_dotenv(override=False)

    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid yaml in {path}: {e}") from None
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path} must be a mapping at the top level")

    cfg.setdefault("ollama", {})
    if model:
        cfg["model"] = model
    if host:
        cfg["ollama"]["host"] = host
    if not cfg.get("model"):
        raise ConfigError("no model set, use --model or `model:` in the config")
    if not cfg["ollama"].get("host"):
        raise ConfigError("no ollama host set, use --host or `ollama.host` in the config")
    return cfg
