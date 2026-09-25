"""Executable acceptance criteria for ADR-0016 slice 4: the retrieval mode follows the
applied profile (explicit flag wins), a declared ``hybrid+rerank`` that cannot import
fails closed, and the MCP server registers ``lookup_segment`` only when the profile's
tool list grants it.

Offline discipline (ADR-0006): no Chroma, no embeddings, no network, no subprocess.
``interchange.retrieve_detail`` is replaced by a recorder that captures the ``mode`` it
was called with and returns a ``conftest.fake_retrieval`` so the pipeline reaches
generation without touching Chroma; a fake ``stub`` engine stands in for generation. The
MCP scenarios reload ``mcp_server`` with ``DEMO_PROFILE`` set and inspect the registered
tool names via FastMCP's tool manager, restoring module state afterwards.

Placement (Slice-2 lesson): these scenarios live in their own
``features/retrieval_profile.feature`` bound here with explicit ``scenario(...)`` calls,
never appended to a feature another module bulk-binds with ``scenarios()``.
"""
from __future__ import annotations

import importlib
import os

import pytest
from pytest_bdd import given, parsers, scenario, then, when

import interchange
from tests.conftest import fake_retrieval


# --- scenario bindings (explicit; never bulk `scenarios()`) ----------------
@scenario("retrieval_profile.feature",
          "A profile's retrieval mode is the default and an explicit flag wins")
def test_mode_default_and_explicit_wins():
    pass


@scenario("retrieval_profile.feature",
          "A declared rerank mode with no reranker fails plainly")
def test_declared_rerank_no_backend_fails():
    pass


@scenario("retrieval_profile.feature",
          "The X12 segment tool is absent from a non-EDI profile's MCP server")
def test_segment_tool_gated_by_profile():
    pass


# --- helpers ---------------------------------------------------------------
def _guard_profile_state(monkeypatch):
    """Snapshot the module globals ``apply_profile`` rebinds and the env vars it writes,
    so applying a profile (via ``main()`` or an ``mcp_server`` import) never leaks into
    another test — the ``tests/test_apply_profile.py::guard_profile_state`` pattern."""
    for attr in ("DOCS_DIR", "COLLECTION", "GOLDEN_PATH",
                 "PROFILE_RETRIEVAL", "PROFILE_TOOLS"):
        monkeypatch.setattr(interchange, attr, getattr(interchange, attr))
    for key in ("INTERCHANGE_COLLECTION", "INTERCHANGE_DOCS_DIR",
                "INTERCHANGE_GOLDEN", "INTERCHANGE_IGNORE", "DEMO_PROFILE"):
        if key in os.environ:
            monkeypatch.setenv(key, os.environ[key])
        else:
            monkeypatch.delenv(key, raising=False)


def _install_stub_engine(monkeypatch):
    """A $0 generation engine that returns a grounded-looking answer."""
    def fake(user_content):
        return {"text": "an answer [src.md]", "in": 1, "out": 1, "cost": 0.0,
                "telemetry": "estimated", "model": "stub"}

    monkeypatch.setitem(interchange.ENGINES, "stub", fake)


# --- Given -----------------------------------------------------------------
@given("a recorder standing in for retrieval")
def recorder_retrieval(context, monkeypatch):
    def recorder(question, *, mode="hybrid", **kw):
        context["recorded_mode"] = mode
        return fake_retrieval({"source": "src.md", "text": "some passage.", "chunk": 0})

    monkeypatch.setattr(interchange, "retrieve_detail", recorder)
    _install_stub_engine(monkeypatch)


@given(parsers.parse('the applied profile declares mode "{mode}" with rerank "{rerank}"'))
def profile_declares_retrieval(monkeypatch, mode, rerank):
    monkeypatch.setattr(interchange, "PROFILE_RETRIEVAL", {"mode": mode, "rerank": rerank})


@given("no profile is applied")
def no_profile_applied(monkeypatch):
    monkeypatch.setattr(interchange, "PROFILE_RETRIEVAL", None)


@given("the reranker backend cannot import")
def reranker_cannot_import(monkeypatch):
    monkeypatch.setattr(interchange, "reranker_import_error", lambda: "no torch")


# --- When ------------------------------------------------------------------
@when("I answer with no explicit mode")
def answer_no_mode(context):
    interchange.answer("q", engine="stub")


@when(parsers.parse('I answer with an explicit mode "{mode}"'))
def answer_explicit_mode(context, mode):
    interchange.answer("q", engine="stub", mode=mode)


@when("I answer expecting a plain failure")
def answer_expecting_failure(context):
    with pytest.raises(SystemExit) as excinfo:
        interchange.answer("q", engine="stub")
    context["exit"] = excinfo.value


@when(parsers.parse('the MCP server starts under profile "{name}"'))
def mcp_starts_under_profile(context, monkeypatch, tmp_path, name):
    context["tools"] = _reload_mcp_tool_names(monkeypatch, tmp_path, name)


# --- Then ------------------------------------------------------------------
@then(parsers.parse('the retrieval was run with mode "{mode}"'))
def retrieval_ran_with_mode(context, mode):
    assert context["recorded_mode"] == mode


@then(parsers.parse('it fails naming "{needle}"'))
def failure_names(context, needle):
    assert needle in str(context["exit"])


@then(parsers.parse('the registered tools are exactly "{names}"'))
def registered_tools_are(context, names):
    expected = {n.strip() for n in names.split(",")}
    assert context["tools"] == expected


# --- MCP reload plumbing ---------------------------------------------------
def _reload_mcp_tool_names(monkeypatch, tmp_path, profile: str) -> set[str]:
    """Reload ``mcp_server`` under ``DEMO_PROFILE=profile`` and return the registered
    tool names. The overlay is pinned off and vault's ``INTERCHANGE_VAULT_DIR`` is set so
    ``apply_profile`` (run in-process when ``mcp_server`` imports) expands cleanly.

    ``interchange`` is deliberately NOT reloaded — reloading it rebinds its dataclasses
    and contextvars, which other already-imported modules hold by reference, leaking into
    unrelated tests. Instead the globals ``apply_profile`` rebinds are snapshotted via
    monkeypatch and restored on teardown; only ``mcp_server`` is reloaded so its tool
    registration re-runs against the applied profile."""
    monkeypatch.setenv("INTERCHANGE_PROFILES", "")
    monkeypatch.setenv("INTERCHANGE_VAULT_DIR", str(tmp_path))
    _guard_profile_state(monkeypatch)
    monkeypatch.setenv("DEMO_PROFILE", profile)
    import mcp_server
    importlib.reload(mcp_server)
    return {t.name for t in mcp_server.mcp._tool_manager.list_tools()}


# --- unit: --eval mode resolves to the profile default ---------------------
def test_eval_mode_resolves_to_profile_default(monkeypatch, tmp_path):
    """``main()`` with ``--profile vault --eval`` (no --mode) runs the eval in the
    profile's declared default mode (``hybrid+rerank``)."""
    monkeypatch.setenv("INTERCHANGE_PROFILES", "")
    monkeypatch.setenv("INTERCHANGE_VAULT_DIR", str(tmp_path))
    _guard_profile_state(monkeypatch)
    monkeypatch.setattr("sys.argv", ["interchange.py", "--profile", "vault", "--eval"])
    # run_eval is faked, so the reranker never has to import; guard the eval branch's
    # only pre-run_eval reranker touch (the "all" branch) just in case.
    monkeypatch.setattr(interchange, "reranker_import_error", lambda: None)
    captured = {}

    def fake_run_eval(*a, **kw):
        captured["mode"] = kw.get("mode")
        return {"n": 1, "hits": 1, "hit_at_k": 1.0, "k": 4, "hit_at_1": 1,
                "histogram": {}, "near_miss": 0, "absent": 0, "mode": kw.get("mode"),
                "corpus": "vault", "golden": "x", "depth": 10, "pool": 20,
                "rerank": None, "skipped": 0, "results": []}

    monkeypatch.setattr(interchange, "run_eval", fake_run_eval)
    interchange.main()
    assert captured["mode"] == "hybrid+rerank"
