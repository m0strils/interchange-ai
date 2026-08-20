"""Shared fixtures for the acceptance (pytest-bdd) and unit layers (ADR-0005).

Two guarantees enforced here:
  * Tests never touch the real ``audit.jsonl`` — ``enterprise.AUDIT_PATH`` is
    redirected to a per-test tmp file by an autouse fixture.
  * Steps share state through a ``context`` dict (question asked, answer returned,
    whether the fake engine was actually invoked, etc.).
"""
from __future__ import annotations

import json

import pytest

import enterprise


@pytest.fixture
def context() -> dict:
    """Mutable scratch space shared across Given/When/Then steps in one scenario."""
    return {}


@pytest.fixture(autouse=True)
def isolated_audit_log(tmp_path, monkeypatch):
    """Redirect the audit log to a throwaway tmp file so no test writes the real one.

    Autouse: every test (acceptance or unit) gets an isolated, empty audit log.
    """
    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(enterprise, "AUDIT_PATH", audit_file)
    return audit_file


def read_audit_rows(path=None) -> list[dict]:
    """Return all audit rows as parsed dicts (empty list if the log is absent)."""
    path = path or enterprise.AUDIT_PATH
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def last_audit_row(path=None) -> dict:
    """Return the most recently written audit row (the record under test)."""
    rows = read_audit_rows(path)
    assert rows, "expected at least one audit row to have been written"
    return rows[-1]
