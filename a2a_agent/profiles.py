"""Demo profiles — the vertical is data, not code (ADR-0013).

``profiles.yaml`` supplies the corpus, the Chroma collection, the sample
question and the display names for one demo vertical. The knowledge agent's
code is identical for every one of them; adding a third vertical is a block in
the YAML, not a new module. That is the industry-agnostic claim, made
mechanically checkable.
"""
from __future__ import annotations

import os
import pathlib

import yaml

PROFILES_PATH = pathlib.Path(__file__).parent / "profiles.yaml"
DEFAULT_PROFILE = "rail"
#: Env var naming the profile this process serves.
PROFILE_ENV = "DEMO_PROFILE"


def load_profiles() -> dict[str, dict]:
    """Every profile block in ``profiles.yaml``, keyed by name."""
    return yaml.safe_load(PROFILES_PATH.read_text(encoding="utf-8")) or {}


def load_profile(name: str | None = None) -> dict:
    """One profile, with its own name attached. Defaults to ``$DEMO_PROFILE``."""
    name = name or os.environ.get(PROFILE_ENV) or DEFAULT_PROFILE
    profiles = load_profiles()
    if name not in profiles:
        raise KeyError(f"unknown demo profile {name!r}; have {sorted(profiles)}")
    return {"name": name, **profiles[name]}
