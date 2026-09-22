"""Executable acceptance criteria for Interchange's governance layer (ADR-0005).

Gherkin lives in ``features/governed_answers.feature``; the steps below bind each
Given/When/Then to the real pipeline with only the *generation boundary* stubbed —
so every run is offline, free, and deterministic (never calls a live model).

Stub seams (per the shared contract):
  * RAG:          fake engine injected into ``interchange.ENGINES["api"]`` +
                  ``interchange.retrieve`` patched to a canned passage.
  * Subscription: ``agent_sub.subprocess.run`` returns a canned ``claude -p`` JSON
                  and ``agent_sub.shutil.which`` reports the CLI as installed.

Audit assertions read the last row from ``enterprise.AUDIT_PATH`` (redirected to a
tmp file by the autouse fixture in conftest.py).
"""
from __future__ import annotations

import json
import pathlib

from pytest_bdd import given, parsers, scenarios, then, when

import agent_sub
import interchange
from tests.conftest import last_audit_row

scenarios("governed_answers.feature")


# --- test doubles ----------------------------------------------------------
class FakeProc:
    """Stand-in for ``subprocess.CompletedProcess`` from ``claude -p``."""

    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


# --- Background ------------------------------------------------------------
@given("a fresh audit log")
def fresh_audit_log(context, isolated_audit_log):
    """The autouse fixture already redirects AUDIT_PATH to an empty tmp file;
    record it in the context so steps read the same log."""
    context["audit_path"] = isolated_audit_log


@given(parsers.parse('the knowledge base returns a passage from "{source}"'))
def kb_returns_passage(context, monkeypatch, source):
    passage = ("An 824 reports application errors.", {"source": source, "chunk": 0})
    monkeypatch.setattr(interchange, "retrieve", lambda q: [passage])
    context["source"] = source


# --- model-answer setup (RAG) ---------------------------------------------
@given(parsers.parse('the model answers "{text}" with no citation'))
def model_answers_uncited(context, text):
    context["model_text"] = text


@given(parsers.parse('the model answers "{text}" with a citation'))
def model_answers_cited(context, text):
    context["model_text"] = text


# --- subscription setup ----------------------------------------------------
@given(parsers.parse(
    'the subscription CLI reports usage input {input_tokens:d}, '
    'cache_creation {cache_creation:d}, cache_read {cache_read:d}, '
    'output {output_tokens:d}, total_cost {total_cost:f}, model "{model}" '
    'and a result citing "{source}"'
))
def subscription_cli_usage(context, monkeypatch, input_tokens, cache_creation,
                           cache_read, output_tokens, total_cost, model, source):
    canned = json.dumps({
        "result": f"A 214 is a shipment status message [{source}].",
        "usage": {
            "input_tokens": input_tokens,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
            "output_tokens": output_tokens,
        },
        "total_cost_usd": total_cost,
        "modelUsage": {
            model: {"costUSD": total_cost, "outputTokens": output_tokens},
        },
    })
    def fake_run(*a, **k):
        # record argv/cwd so the "runs outside the repo" scenario can assert on them,
        # while still returning the same canned proc the telemetry scenario needs.
        context["sub_argv"] = a[0] if a else k.get("args")
        context["sub_cwd"] = k.get("cwd")
        return FakeProc(stdout=canned)

    monkeypatch.setattr(agent_sub.subprocess, "run", fake_run)
    monkeypatch.setattr(agent_sub.shutil, "which", lambda name: "/usr/bin/claude")


# --- When ------------------------------------------------------------------
@when(parsers.parse('I ask "{question}"'))
def i_ask(context, monkeypatch, question):
    """Install the fake generation engine (recording that it ran) and run the
    RAG pipeline. On an injection block the engine is never reached."""
    context["engine_called"] = False
    model_text = context.get("model_text", "An 824 reports errors [x12-overview.md].")

    def fake(user_content):
        context["engine_called"] = True
        context["engine_user_content"] = user_content
        return {
            "text": model_text,
            "in": 100,
            "out": 20,
            "cost": None,
            "telemetry": "measured",
            "model": interchange.MODEL,
        }

    monkeypatch.setitem(interchange.ENGINES, "api", fake)
    context["answer"] = interchange.answer(question, engine="api")


@when(parsers.parse('I run the agentic subscription answer for "{question}"'))
def i_run_subscription(context, question):
    context["answer"] = agent_sub.answer_agentic_sub(question)


# --- Then: guardrails ------------------------------------------------------
@then("the request is blocked by the input guardrail")
def request_blocked(context):
    assert context["answer"].startswith("🛑"), context["answer"]


@then("the model is never called")
def model_never_called(context):
    assert context["engine_called"] is False


@then("the answer is flagged ungrounded")
def flagged_ungrounded(context):
    assert "UNGROUNDED" in context["answer"], context["answer"]


@then("the answer is not flagged ungrounded")
def not_flagged_ungrounded(context):
    assert "UNGROUNDED" not in context["answer"], context["answer"]


# --- Then: audit record ----------------------------------------------------
@then("the audit records that the request was blocked")
def audit_blocked(context):
    assert last_audit_row()["blocked"]


@then("the audit records grounded false")
def audit_grounded_false(context):
    assert last_audit_row()["grounded"] is False


@then("the audit records grounded true")
def audit_grounded_true(context):
    assert last_audit_row()["grounded"] is True


@then(parsers.parse('the audit telemetry is "{telemetry}"'))
def audit_telemetry(context, telemetry):
    assert last_audit_row()["telemetry"] == telemetry


@then(parsers.parse("the audit in_tokens equal {n:d}"))
def audit_in_tokens(context, n):
    assert last_audit_row()["in_tokens"] == n


@then(parsers.parse("the audit marginal_usd is {n:d}"))
def audit_marginal(context, n):
    assert last_audit_row()["marginal_usd"] == n


@then(parsers.parse('the audit model is "{model}"'))
def audit_model(context, model):
    assert last_audit_row()["model"] == model


# --- Then: headless session isolation --------------------------------------
@then("the headless session ran outside the calling repository")
def headless_outside_repo(context):
    """The recorded `cwd` is the repo-free headless temp dir, not the repo (whose
    project hooks would otherwise hijack the child session's reply)."""
    cwd = pathlib.Path(context["sub_cwd"])
    assert cwd.exists()
    repo = pathlib.Path(interchange.__file__).parent.resolve()
    resolved = cwd.resolve()
    assert resolved != repo and repo not in resolved.parents
    assert context["sub_cwd"] == interchange.headless_cwd()
