"""Unit tests for the demo profiles (ADR-0013 + ADR-0014 vault block).

Offline and free, like the rest of the gate: no network, no index. Symbols are
imported inside each test body (the ``test_a2a.py`` convention), and the vault
path comes from a monkeypatched env var — never from ``.env``, which the runtime
reads too late (``DOCS_DIR`` resolves at import).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VAULT_DIR = "/tmp/some-vault"


def test_profile_docs_dir_expands_env_var(monkeypatch):
    from a2a_agent.profiles import load_profile

    monkeypatch.setenv("INTERCHANGE_VAULT_DIR", VAULT_DIR)
    profile = load_profile("vault")
    assert profile["docs_dir"] == VAULT_DIR


def test_profile_unset_env_var_fails_plainly(monkeypatch):
    import pytest

    from a2a_agent.profiles import load_profile

    monkeypatch.delenv("INTERCHANGE_VAULT_DIR", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        load_profile("vault")
    assert "INTERCHANGE_VAULT_DIR" in str(exc_info.value)


def test_profile_env_export_lines_include_generic_ignore_and_no_golden(monkeypatch):
    from a2a_agent.profiles import load_profile, profile_env

    monkeypatch.setenv("INTERCHANGE_VAULT_DIR", VAULT_DIR)
    env = profile_env(load_profile("vault"))
    assert env["INTERCHANGE_COLLECTION"] == "vault"
    assert env["INTERCHANGE_DOCS_DIR"] == VAULT_DIR
    # The committed vault block is a generic shape: only generic Obsidian
    # housekeeping ignores, no personal filenames or folder layout.
    assert ".obsidian/" in env["INTERCHANGE_IGNORE"]
    assert "Templates/" in env["INTERCHANGE_IGNORE"]
    # It carries no personal golden set; a real one is referenced from the
    # private overlay's `golden:` key (ADR-0016), never committed.
    assert "INTERCHANGE_GOLDEN" not in env


def test_rail_profile_unchanged_by_vault_block(monkeypatch):
    from a2a_agent.profiles import load_profile, profile_env

    profile = load_profile("rail")
    assert profile["collection"] == "edi"
    assert profile["docs_dir"] == "docs"

    env = profile_env(profile)
    assert env["INTERCHANGE_COLLECTION"] == "edi"
    assert env["INTERCHANGE_DOCS_DIR"] == "docs"
    assert "INTERCHANGE_IGNORE" not in env
    assert env["INTERCHANGE_GOLDEN"] == "eval/golden.jsonl"


def test_profiles_main_export_prints_shell_lines(monkeypatch):
    import os

    env = dict(os.environ)
    env["INTERCHANGE_VAULT_DIR"] = VAULT_DIR
    proc = subprocess.run(
        [sys.executable, "-m", "a2a_agent.profiles", "vault", "--export"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines
    for line in lines:
        assert line.startswith("export "), line
