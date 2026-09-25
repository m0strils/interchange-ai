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

Profiles are *portable data* (ADR-0016): the committed ``profiles.yaml`` is the
public baseline, and a private, uncommitted **overlay** may extend it. The
overlay path comes from ``INTERCHANGE_PROFILES`` (default
``~/.interchange/profiles.yaml``; set it to the empty string to disable, or to a
path to use that file). For each profile the overlay names it shallow-merges its
keys over the committed block — scalars replace, list keys replace whole (never
concatenate) — and a name the committed file does not have is added entire. This
lets someone point ``vault`` at their own notes, tune ``persona`` / ``retrieval``
/ ``tools``, or add whole new corpora without ever editing (or publishing) the
committed file.
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
#: Env var naming the private profiles overlay (ADR-0016).
OVERLAY_ENV = "INTERCHANGE_PROFILES"
#: Default overlay location when ``OVERLAY_ENV`` is unset.
DEFAULT_OVERLAY = "~/.interchange/profiles.yaml"

#: The tools the knowledge agent may be granted; the rail default keeps both.
KNOWN_TOOLS = {"search_docs", "lookup_segment"}
DEFAULT_TOOLS = ["search_docs", "lookup_segment"]


def overlay_path() -> pathlib.Path | None:
    """The private overlay file to merge, or ``None`` when there is none.

    ``INTERCHANGE_PROFILES`` unset → the default (``~/.interchange/profiles.yaml``,
    expanded); set to the empty string → ``None`` (overlay disabled); set to a path
    → that path (expanded). Returns ``None`` too when the resolved file is absent, so
    a missing overlay is simply no overlay rather than an error.
    """
    raw = os.environ.get(OVERLAY_ENV)
    if raw is None:
        raw = DEFAULT_OVERLAY
    elif raw == "":
        return None
    path = pathlib.Path(os.path.expanduser(raw))
    return path if path.exists() else None


def load_profiles() -> dict[str, dict]:
    """Every profile block, committed with the private overlay merged on top.

    The committed ``profiles.yaml`` is the baseline; each profile the overlay
    (``overlay_path``) names is shallow-merged over its committed block — scalar
    keys replace, list keys replace whole (never concatenate) — and a name the
    committed file lacks is added entire. An empty/``None`` overlay changes nothing.
    """
    committed = yaml.safe_load(PROFILES_PATH.read_text(encoding="utf-8")) or {}
    path = overlay_path()
    if path is None:
        return committed
    overlay = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for name, block in overlay.items():
        base = committed.get(name)
        if isinstance(base, dict) and isinstance(block, dict):
            merged = dict(base)
            merged.update(block)  # scalars + list keys replace; no concatenation
            committed[name] = merged
        else:
            committed[name] = block
    return committed


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
    golden = profile.get("golden")
    if isinstance(golden, str):
        profile["golden"] = os.path.expanduser(golden)
    return profile


def profile_for_collection(name: str) -> dict | None:
    """The first profile whose ``collection`` equals ``name`` (name attached), or
    ``None`` if none matches.

    Tolerant by design: a profile whose ``docs_dir`` cannot expand yet (e.g.
    ``vault`` with no ``INTERCHANGE_VAULT_DIR``) must not raise here — a caller
    resolving a collection to its persona/tools should not depend on the shell. We
    catch the ``SystemExit`` ``load_profile`` would raise and return the raw block
    (name attached, ``docs_dir`` left unexpanded) instead.
    """
    for pname, block in load_profiles().items():
        if isinstance(block, dict) and str(block.get("collection")) == name:
            try:
                return load_profile(pname)
            except SystemExit:
                return {"name": pname, **block}
    return None


def profile_persona(profile: dict) -> str | None:
    """The profile's system persona (stripped), or ``None`` when it carries none."""
    persona = profile.get("persona")
    if isinstance(persona, str) and persona.strip():
        return persona.strip()
    return None


def profile_retrieval(profile: dict) -> dict:
    """The profile's retrieval policy:
    ``{"mode", "rerank", "context", "budget_chars", "note_max_chars", "chunks_only"}``.

    ``mode`` / ``rerank`` are unchanged (default ``hybrid`` / ``None``). The context
    keys (ADR-0018) default to ``chunks`` and the ``interchange`` constants when the
    ``retrieval`` block omits them. ``chunks_only`` (ADR-0018 Update 2026-09-24) is a
    list of POSIX-path prefixes, relative to the corpus root (e.g.
    ``"30-Career/People/"``), whose notes are indexed but never assembled whole: in
    ``notes`` mode a hit under one of them is seeded and never expanded. It defaults to
    ``[]``, must be a list of non-empty strings, and each entry is normalised to
    forward slashes. Validation (a lazy ``interchange`` import, to avoid an import
    cycle): ``mode`` in ``MODES``; ``context`` in ``CONTEXT_MODES``; ``budget_chars`` /
    ``note_max_chars`` positive ``int`` (a string like ``"12000"`` is rejected —
    clamping is policy's job, not the profile's); and ``note_max_chars <=
    budget_chars``. Every failure raises a ``ValueError`` naming the profile and the
    offending key.
    """
    block = profile.get("retrieval") or {}
    mode = block.get("mode", "hybrid")
    rerank = block.get("rerank")
    from interchange import (  # lazy: interchange imports are heavier + can cycle
        CONTEXT_BUDGET_CHARS,
        CONTEXT_MODES,
        MODES,
        NOTE_MAX_CHARS,
    )

    name = profile.get("name")
    if mode not in MODES:
        raise ValueError(
            f"profile {name!r}: unknown retrieval mode {mode!r}; "
            f"expected one of {MODES}"
        )
    context = block.get("context", CONTEXT_MODES[0])
    if context not in CONTEXT_MODES:
        raise ValueError(
            f"profile {name!r}: unknown context mode {context!r}; "
            f"expected one of {CONTEXT_MODES}"
        )
    budget_chars = block.get("budget_chars", CONTEXT_BUDGET_CHARS)
    note_max_chars = block.get("note_max_chars", NOTE_MAX_CHARS)
    for key, value in (("budget_chars", budget_chars),
                       ("note_max_chars", note_max_chars)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(
                f"profile {name!r}: {key} must be a positive int, got {value!r}"
            )
    if note_max_chars > budget_chars:
        raise ValueError(
            f"profile {name!r}: note_max_chars ({note_max_chars}) must be "
            f"<= budget_chars ({budget_chars})"
        )
    raw_chunks_only = block.get("chunks_only", [])
    if not isinstance(raw_chunks_only, list):
        raise ValueError(
            f"profile {name!r}: chunks_only must be a list of path prefixes, "
            f"got {raw_chunks_only!r}"
        )
    chunks_only: list[str] = []
    for prefix in raw_chunks_only:
        if not isinstance(prefix, str) or not prefix.strip():
            raise ValueError(
                f"profile {name!r}: chunks_only entries must be non-empty strings, "
                f"got {prefix!r}"
            )
        chunks_only.append(prefix.strip().replace("\\", "/"))
    return {"mode": str(mode), "rerank": rerank, "context": str(context),
            "budget_chars": budget_chars, "note_max_chars": note_max_chars,
            "chunks_only": chunks_only}


def profile_tools(profile: dict) -> list[str]:
    """The tools the knowledge agent may use for this profile.

    Defaults to ``["search_docs", "lookup_segment"]`` (the rail behaviour) when the
    profile names none. Every entry is validated against ``KNOWN_TOOLS``; an unknown
    tool raises ``ValueError`` naming the profile and the offending tool.
    """
    tools = profile.get("tools")
    if tools is None:
        return list(DEFAULT_TOOLS)
    names = [str(t) for t in tools]
    for tool in names:
        if tool not in KNOWN_TOOLS:
            raise ValueError(
                f"profile {profile.get('name')!r}: unknown tool {tool!r}; "
                f"expected a subset of {sorted(KNOWN_TOOLS)}"
            )
    return names


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
