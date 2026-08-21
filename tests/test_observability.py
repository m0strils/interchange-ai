"""Unit tests for the tracing seam (ADR-0009).

These run in the offline gate with NO trace deps installed — which is exactly the
condition they assert: tracing is a clean no-op unless INTERCHANGE_TRACING=1 AND the
optional OpenTelemetry/Phoenix deps are importable. So the pipeline instrumentation
(interchange/agent_sub) never changes behavior or touches the network by default.
"""
from __future__ import annotations

import pytest

import observability as obs


@pytest.fixture(autouse=True)
def reset_tracing_state(monkeypatch):
    """init_tracing() memoizes via module globals; reset them so tests don't leak."""
    monkeypatch.setattr(obs, "_INIT_DONE", False)
    monkeypatch.setattr(obs, "_TRACER", None)


# --- the flag ---------------------------------------------------------------
def test_tracing_disabled_by_default(monkeypatch):
    monkeypatch.delenv("INTERCHANGE_TRACING", raising=False)
    assert obs.tracing_enabled() is False


def test_tracing_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("INTERCHANGE_TRACING", "1")
    assert obs.tracing_enabled() is True


# --- span() is a working no-op context when off -----------------------------
def test_span_is_noop_context_when_disabled(monkeypatch):
    monkeypatch.delenv("INTERCHANGE_TRACING", raising=False)
    ran = []
    with obs.span("retrieve", **{"openinference.span.kind": "RETRIEVER"}) as sp:
        ran.append(True)          # wrapped code MUST still run
        assert sp is None         # ...and get a null span
    assert ran == [True]


def test_span_never_raises_even_with_odd_attrs(monkeypatch):
    monkeypatch.delenv("INTERCHANGE_TRACING", raising=False)
    with obs.span("x", weird={"not": "a-scalar"}):
        pass  # must not raise


# --- init_tracing no-ops safely when deps are absent (the gate's condition) --
def test_init_tracing_noops_when_flag_off():
    # flag off -> False, and no import attempt
    assert obs.init_tracing() is False


def test_init_tracing_noops_when_deps_missing(monkeypatch):
    # flag ON but the optional trace deps unavailable -> must return False and NOT raise
    # (a missing optional dep never breaks a run). Force the ImportError path
    # deterministically: opentelemetry *core* is present transitively via chromadb, so we
    # simulate the full trace stack being absent rather than depend on the environment.
    monkeypatch.setenv("INTERCHANGE_TRACING", "1")
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError("simulated missing trace deps")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert obs.init_tracing() is False  # clean no-op, no exception


# --- Claude Code telemetry env (pure) ---------------------------------------
def test_claude_code_trace_env_empty_when_off(monkeypatch):
    monkeypatch.delenv("INTERCHANGE_TRACING", raising=False)
    assert obs.claude_code_trace_env() == {}


def test_claude_code_trace_env_has_keys_when_on(monkeypatch):
    monkeypatch.setenv("INTERCHANGE_TRACING", "1")
    env = obs.claude_code_trace_env()
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert env["CLAUDE_CODE_ENHANCED_TELEMETRY_BETA"] == "1"  # traces are beta-gated
    assert env["OTEL_TRACES_EXPORTER"] == "otlp"
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in env


def test_otlp_endpoint_is_overridable(monkeypatch):
    monkeypatch.setenv("INTERCHANGE_TRACING", "1")
    monkeypatch.setenv("INTERCHANGE_OTLP_ENDPOINT", "http://localhost:4318")
    assert obs.claude_code_trace_env()["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4318"
