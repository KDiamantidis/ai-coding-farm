# =============================================================================
# FILE:    farm/config.py
# PURPOSE: Load settings: the models.yaml registry and the .env file.
#
# EXPORTS:
#   load_env(path)        -> reads KEY=VALUE lines into os.environ
#   load_models(path)     -> dict from models.yaml (validated)
#   chain_for(cfg, role)  -> list of model names for one role
#
# DESIGN NOTES:
#   - No python-dotenv. The .env format we need is tiny, so a 10-line reader
#     is easier to defend than one more dependency.
#   - Swapping a model is a one-line edit in models.yaml. Code never contains
#     a model name. (Single source of truth.)
#   - A model is NEVER promoted automatically from public benchmarks. A person
#     edits the file after looking at `python -m farm report`.
# =============================================================================

from __future__ import annotations

import os
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Raised when models.yaml is missing or has the wrong shape."""


def load_env(path: str | Path = ".env") -> None:
    """Read KEY=VALUE lines from a .env file into os.environ.

    Existing environment variables win, so a real shell variable can always
    override the file. Missing file is fine (the keys may already be set).
    """
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_models(path: str | Path = "models.yaml") -> dict:
    """Load and validate the model registry."""
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"models file not found: {p}")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    roles = cfg.get("roles")
    if not isinstance(roles, dict) or "coder" not in roles:
        raise ConfigError("models.yaml needs a 'roles' section with a 'coder' role")
    for name, role in roles.items():
        chain = role.get("chain") if isinstance(role, dict) else None
        if not chain or not isinstance(chain, list):
            raise ConfigError(f"role '{name}' needs a non-empty 'chain' list")
    cfg.setdefault("settings", {})
    cfg["settings"].setdefault("max_attempts", 3)
    cfg["settings"].setdefault("test_timeout_s", 60)
    cfg["settings"].setdefault("call_timeout_s", 120)
    cfg["settings"].setdefault("outage_retries", 2)   # waits for a dead API, per task
    cfg["settings"].setdefault("outage_wait_s", 30)
    cfg["_path"] = str(p.resolve())
    return cfg


def chain_for(cfg: dict, role: str) -> list[str]:
    """Ordered model names for a role. Index 0 is the first choice."""
    return list(cfg["roles"][role]["chain"])
