"""Demo profiles — the vertical is data, not code (ADR-0013).

``profiles.yaml`` supplies the corpus, the Chroma collection, the sample
question and the display names for one demo vertical. The knowledge agent's
code is identical for every one of them; adding a third vertical is a block in
the YAML, not a new module. That is the industry-agnostic claim, made
mechanically checkable.

A profile may also carry an ``ignore`` list (extra ``INTERCHANGE_IGNORE``
patterns) and a ``golden`` path (its eval set). ``docs_dir`` is expanded
against the environment so a profile like ``vault`` can point at a path that
only the shell knows (``${INTERCHANGE_VAULT_DIR}``); see ``profile_env`` for
the env vars the runtime reads.
"""
from __future__ import annotations

import json
import os
import pathlib
import shlex
import sys

import yaml

PROFILES_PATH = pathlib.Path(__file__).parent / "profiles.yaml"
DEFAULT_PROFILE = "rail"
#: Env var naming the profile this process serves.
PROFILE_ENV = "DEMO_PROFILE"


def load_profiles() -> dict[str, dict]:
    """Every profile block in ``profiles.yaml``, keyed by name."""
    return yaml.safe_load(PROFILES_PATH.read_text(encoding="utf-8")) or {}


def load_profile(name: str | None = None) -> dict:
    """One profile, with its own name attached. Defaults to ``$DEMO_PROFILE``.

    ``docs_dir`` is expanded with ``os.path.expandvars`` then
    ``os.path.expanduser``. If it still carries an unexpanded ``${...}`` (or a
    bare ``$`` prefix) the naming variable was not exported in the shell, and we
    fail plainly rather than index the literal string — ``.env`` loads too late
    to help (``DOCS_DIR`` resolves at import).
    """
    name = name or os.environ.get(PROFILE_ENV) or DEFAULT_PROFILE
    profiles = load_profiles()
    if name not in profiles:
        raise KeyError(f"unknown demo profile {name!r}; have {sorted(profiles)}")
    profile = {"name": name, **profiles[name]}
    docs_dir = profile.get("docs_dir")
    if isinstance(docs_dir, str):
        expanded = os.path.expanduser(os.path.expandvars(docs_dir))
        if "${" in expanded or expanded.startswith("$"):
            var = docs_dir.strip("${}") or "INTERCHANGE_VAULT_DIR"
            raise SystemExit(
                f"profile {name!r}: docs_dir needs {var} exported in the shell "
                "(it cannot come from .env)"
            )
        profile["docs_dir"] = expanded
    return profile


def profile_examples(profile: dict | None = None) -> list[str]:
    """The example questions this profile ships (workbench cold-start + ``/options``).

    Reads the ``examples`` list of ``profile`` (or the active profile). Tolerant: a
    profile whose ``docs_dir`` cannot expand yet (e.g. ``vault`` with no env) returns
    ``[]`` rather than failing an unauthenticated ``/options`` request.
    """
    try:
        p = profile or load_profile()
    except (SystemExit, KeyError):
        return []
    return [str(e) for e in (p.get("examples") or [])]


def profile_env(profile: dict) -> dict[str, str]:
    """The environment variables the runtime reads for this profile.

    Always ``INTERCHANGE_COLLECTION`` and ``INTERCHANGE_DOCS_DIR``; and, only
    when the profile carries them, ``INTERCHANGE_IGNORE`` (comma-joined ignore
    patterns) and ``INTERCHANGE_GOLDEN`` (its eval set).
    """
    env: dict[str, str] = {
        "INTERCHANGE_COLLECTION": str(profile["collection"]),
        "INTERCHANGE_DOCS_DIR": str(profile["docs_dir"]),
    }
    ignore = profile.get("ignore")
    if ignore:
        env["INTERCHANGE_IGNORE"] = ",".join(ignore)
    golden = profile.get("golden")
    if golden:
        env["INTERCHANGE_GOLDEN"] = str(golden)
    return env


def _main(argv: list[str]) -> int:
    args = argv[1:]
    export = False
    if "--export" in args:
        export = True
        args = [a for a in args if a != "--export"]
    if len(args) != 1:
        print("usage: python -m a2a_agent.profiles NAME [--export]", file=sys.stderr)
        return 2
    name = args[0]
    try:
        profile = load_profile(name)
    except KeyError as e:
        print(e.args[0] if e.args else f"unknown profile {name!r}", file=sys.stderr)
        return 1
    if export:
        for key, value in profile_env(profile).items():
            print(f"export {key}={shlex.quote(value)}")
    else:
        print(json.dumps(profile, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
