"""
Observability for Interchange (ADR-0009) — OpenTelemetry tracing, OFF by default.

`enterprise.audit()` already records a durable, per-request governance row. This adds
the other half: per-STAGE spans within a request (retrieve -> dense/bm25/rrf, generate,
guardrails) and — via Claude Code's own built-in OTel — the nested agent/tool span tree
that the flat audit row can't show. Two complementary layers: audit is the compliance
record; traces are the dev-time debugging/latency view in a local Arize Phoenix.

Everything here is a NO-OP unless `INTERCHANGE_TRACING=1` AND the optional trace deps
are installed (`requirements-trace.txt`). So normal runs and the offline `pre-push`
test gate never import OpenTelemetry/Phoenix and never touch the network — the trace
deps are deliberately NOT in requirements-dev.txt.

Honest caveats (see ADR-0009): the OTel GenAI / OpenInference semantic conventions are
still experimental (pre-1.0) in 2026, and Claude Code's trace export is a beta feature.
"""
from __future__ import annotations

import contextlib
import os
import sys

# Local Phoenix OTLP base. Phoenix serves OTLP/HTTP on :6006; the exact port is a
# deploy-time detail (ADR-0009). Override with INTERCHANGE_OTLP_ENDPOINT.
_OTLP_BASE_DEFAULT = "http://localhost:6006"

_TRACER = None
_INIT_DONE = False


def _otlp_base() -> str:
    return os.environ.get("INTERCHANGE_OTLP_ENDPOINT", _OTLP_BASE_DEFAULT)


def tracing_enabled() -> bool:
    """True iff INTERCHANGE_TRACING=1. Off by default so normal runs and the offline
    test gate never touch OpenTelemetry/Phoenix."""
    return os.environ.get("INTERCHANGE_TRACING") == "1"


def init_tracing() -> bool:
    """Idempotently wire an OTel tracer exporting to the local Phoenix, IF tracing is
    enabled and the optional deps import. Returns True when tracing is live. If the flag
    is set but the deps are missing, print a one-line hint and no-op (a missing optional
    dep must never break a run). Absent entirely when the flag is off."""
    global _TRACER, _INIT_DONE
    if _INIT_DONE:
        return _TRACER is not None
    _INIT_DONE = True
    if not tracing_enabled():
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        print("  ┃ [trace] INTERCHANGE_TRACING=1 but trace deps are missing — run "
              "`pip install -r requirements-trace.txt` (tracing disabled this run).",
              file=sys.stderr)
        return False

    provider = TracerProvider(resource=Resource.create({"service.name": "interchange"}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{_otlp_base()}/v1/traces"))
    )
    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer("interchange")
    return True


@contextlib.contextmanager
def span(name: str, **attrs):
    """Context manager for one span, tagged with OpenInference-style attributes. A no-op
    null context when tracing is off or deps are absent — so callers wrap pipeline stages
    unconditionally and pay nothing in the default path. Yields the span (or None)."""
    if not init_tracing() or _TRACER is None:
        yield None
        return
    with _TRACER.start_as_current_span(name) as sp:
        for key, value in attrs.items():
            try:
                sp.set_attribute(key, value)
            except Exception:  # never let instrumentation break the pipeline
                pass
        yield sp


def claude_code_trace_env() -> dict:
    """Env vars to merge into the `claude -p` subprocess so Claude Code emits its own
    native OTel span tree (claude_code.interaction -> llm_request -> tool) and propagates
    `traceparent` into our MCP server — to the same local Phoenix. Empty when tracing is
    off. NB: Claude Code trace export is a BETA feature (the _BETA flag); metrics/logs GA."""
    if not tracing_enabled():
        return {}
    return {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",  # traces are beta-gated
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": _otlp_base(),
    }
