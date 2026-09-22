"""Headless `claude -p` must run OUTSIDE the calling repository (feature/claude-code-engine-cwd).

Observed defect: launched from inside this repo, the child Claude session loaded the
repo's `.claude/` project settings and hooks — a Stop hook ran the pytest gate in the
child and its reply came back as hook commentary (flagged UNGROUNDED) instead of the
answer. Fix: both headless call sites run in `interchange.headless_cwd()` (a repo-free
temp dir) with `--setting-sources user` so project settings/hooks cannot load.

These tests keep the model boundary stubbed (ADR-0005): monkeypatch `subprocess.run`
with a fake that records its kwargs/argv and returns a canned `--output-format json`
payload, like the existing fake in tests/test_governed_answers.py — offline and free.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import agent_sub
import interchange


class FakeProc:
    """Stand-in for ``subprocess.CompletedProcess`` from ``claude -p``."""

    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _canned(source: str = "x12-overview.md") -> str:
    return json.dumps({
        "result": f"A 214 is a shipment status message [{source}].",
        "usage": {
            "input_tokens": 2,
            "cache_creation_input_tokens": 21135,
            "cache_read_input_tokens": 0,
            "output_tokens": 40,
        },
        "total_cost_usd": 0.21,
        "modelUsage": {"claude-opus-4-8": {"costUSD": 0.21, "outputTokens": 40}},
    })


def _recording_run(recorded: dict):
    def fake_run(*a, **k):
        recorded["argv"] = a[0] if a else k.get("args")
        recorded["cwd"] = k.get("cwd")
        return FakeProc(stdout=_canned())
    return fake_run


def _assert_outside_repo(recorded_cwd: str):
    cwd = pathlib.Path(recorded_cwd)
    assert cwd.exists()
    repo = pathlib.Path(interchange.__file__).parent.resolve()
    resolved = cwd.resolve()
    assert resolved != repo and repo not in resolved.parents
    assert recorded_cwd == interchange.headless_cwd()


def test_claude_code_engine_runs_outside_the_repo(monkeypatch):
    """The `--engine claude-code` RAG path runs headless Claude in the repo-free
    temp cwd, never inside the repo whose hooks would hijack the reply."""
    recorded: dict = {}
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(subprocess, "run", _recording_run(recorded))

    interchange._generate_claude_code("ctx")

    _assert_outside_repo(recorded["cwd"])


def test_agent_sub_headless_runs_outside_the_repo(monkeypatch):
    """The subscription agent (claude -p + MCP) runs headless Claude in the same
    repo-free temp cwd — reached via its smallest public entry point."""
    recorded: dict = {}
    monkeypatch.setattr(agent_sub.subprocess, "run", _recording_run(recorded))
    monkeypatch.setattr(agent_sub.shutil, "which", lambda name: "/usr/bin/claude")

    agent_sub.answer_agentic_sub("what is a 214?")

    _assert_outside_repo(recorded["cwd"])


def test_headless_call_restricts_setting_sources(monkeypatch):
    """Both headless call sites pass `--setting-sources user` (confirmed in
    `claude --help`) so project settings/hooks cannot load even if cwd ever changes."""
    rag: dict = {}
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(subprocess, "run", _recording_run(rag))
    interchange._generate_claude_code("ctx")

    sub: dict = {}
    monkeypatch.setattr(agent_sub.subprocess, "run", _recording_run(sub))
    monkeypatch.setattr(agent_sub.shutil, "which", lambda name: "/usr/bin/claude")
    agent_sub.answer_agentic_sub("what is a 214?")

    for argv in (rag["argv"], sub["argv"]):
        assert "--setting-sources" in argv
        assert argv[argv.index("--setting-sources") + 1] == "user"
