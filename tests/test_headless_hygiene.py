"""Headless `claude -p` MCP/tool hygiene (feature/passage-eval).

Observed defect 2026-09-23: with no MCP restriction on the headless RAG session,
every user-scope MCP server in `~/.claude.json` (two Obsidian vaults on this
machine) loaded into what should be a pure text-generation session. The model
tried the connectors, was denied, and replied "both Obsidian connectors were
denied" instead of answering. `agent_sub` passed `--mcp-config`/`--allowedTools`
but no `--strict-mcp-config`, so user-scope servers still loaded and cost context.

Fix (verified against `claude --help`, 2.1.267):
  * RAG argv (`interchange._generate_claude_code`): `--strict-mcp-config` (with no
    `--mcp-config`, no servers load) + `--tools ""` (help: `""` disables all
    built-in tools). Manually confirmed once at $0 on the subscription that
    `--tools "" --strict-mcp-config` yields a clean tool-free reply.
  * Agent argv (`agent_sub.answer_agentic_sub`): `--strict-mcp-config` so only the
    `--mcp-config` interchange server loads; allow-list unchanged.

These tests keep the model boundary stubbed (ADR-0005): monkeypatch
`subprocess.run` with a fake that records the argv/cwd and returns a canned
`--output-format json` payload — offline and free. Explicit `scenario()` bindings
(never bulk `scenarios()`) so no other module re-binds this feature.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from pytest_bdd import given, parsers, scenario, then, when

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


@pytest.fixture
def recordings() -> dict:
    """Per-call recordings, keyed ``rag`` / ``sub``: each an {argv, cwd} dict."""
    return {}


def _fake_run_into(recordings: dict, key: str):
    def fake_run(*a, **k):
        recordings[key] = {
            "argv": a[0] if a else k.get("args"),
            "cwd": k.get("cwd"),
        }
        return FakeProc(stdout=_canned())
    return fake_run


# -- Scenario bindings (explicit; never scenarios()) --------------------------

@scenario("headless_hygiene.feature",
          "The RAG engine never loads user MCP servers")
def test_rag_engine_loads_no_user_mcp():
    pass


@scenario("headless_hygiene.feature",
          "The subscription agent loads only the interchange MCP server")
def test_subscription_agent_loads_only_interchange_mcp():
    pass


@scenario("headless_hygiene.feature",
          "The headless working directory is unchanged")
def test_headless_working_directory_is_unchanged():
    pass


# -- Steps --------------------------------------------------------------------

@given("a fake claude CLI that records its argv")
def _fake_cli(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(agent_sub.shutil, "which", lambda name: "/usr/bin/claude")


@when(parsers.parse('the RAG engine generates an answer for "{content}"'))
def _rag_generates(content, recordings, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run_into(recordings, "rag"))
    interchange._generate_claude_code(content)


@when(parsers.parse('the subscription agent answers "{question}"'))
def _agent_answers(question, recordings, monkeypatch):
    monkeypatch.setattr(agent_sub.subprocess, "run",
                        _fake_run_into(recordings, "sub"))
    agent_sub.answer_agentic_sub(question)


@then(parsers.parse('the RAG argv passes "{flag}"'))
def _rag_has_flag(flag, recordings):
    assert flag in recordings["rag"]["argv"]


@then(parsers.parse('the RAG argv does not pass "{flag}"'))
def _rag_lacks_flag(flag, recordings):
    assert flag not in recordings["rag"]["argv"]


@then("the RAG argv disables all built-in tools")
def _rag_disables_tools(recordings):
    argv = recordings["rag"]["argv"]
    # `claude --help` (2.1.267): --tools "" disables all built-in tools.
    assert "--tools" in argv
    assert argv[argv.index("--tools") + 1] == ""


@then(parsers.parse('the subscription argv passes "{flag}"'))
def _sub_has_flag(flag, recordings):
    assert flag in recordings["sub"]["argv"]


@then(parsers.parse('the subscription argv passes "{flag}" exactly once'))
def _sub_flag_once(flag, recordings):
    assert recordings["sub"]["argv"].count(flag) == 1


@then("every recorded session ran in the repo-free headless cwd")
def _both_ran_outside_repo(recordings):
    assert set(recordings) == {"rag", "sub"}
    for rec in recordings.values():
        assert rec["cwd"] == interchange.headless_cwd()


# -- Unit: flag ordering keeps `-p` as the second argv element ----------------

def test_dash_p_stays_second_on_both_call_sites(monkeypatch):
    """Some tests/lessons rely on `argv[1] == "-p"`; the new flags must not
    displace it on either headless call site."""
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(agent_sub.shutil, "which", lambda name: "/usr/bin/claude")

    rag: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run_into(rag, "rag"))
    interchange._generate_claude_code("ctx")
    assert rag["rag"]["argv"][0] == "claude"
    assert rag["rag"]["argv"][1] == "-p"

    sub: dict = {}
    monkeypatch.setattr(agent_sub.subprocess, "run", _fake_run_into(sub, "sub"))
    agent_sub.answer_agentic_sub("what is a 214?")
    assert sub["sub"]["argv"][0] == "claude"
    assert sub["sub"]["argv"][1] == "-p"
