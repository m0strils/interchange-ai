"""Policy layer for the web/HTTP surface (ADR-0015, review findings #2/#4/#10/#13/#22).

The env is the *policy* tier and a request is the *preference* tier; policy wins.
Every knob a web request may set (corpus, mode, rerank, k) is bounded here, and the
governance controls a public host needs — a per-client rate limit, a generation
concurrency bound, a daily budget for metered calls, and the fail-closed public
auth rule — live here rather than being scattered through the handlers.

Two rules of thumb, both to keep the tests hermetic and the operator in control:

* **Env is read at request time**, not import time, so a test can ``monkeypatch``
  a knob and the very next request sees it (and no server restart is needed).
* **Optional backends are probed once at import** with ``importlib.util.find_spec``
  and never imported in a request — the offline gate never pulls torch/onnx/typesafe,
  and a request thread never blocks on a multi-second model import (review #22).
"""
from __future__ import annotations

import importlib.util
import json
import os
import threading
import time
from urllib.parse import urlparse

import enterprise

# --- optional rerank backends: availability probed ONCE, at import ---------
# find_spec only checks importability; it does not import the module, so this is
# cheap and offline-safe. Whether a *metered* backend may actually run is a policy
# question answered per-request in ``rerank_availability``.
_HAVE_BACKEND = {
    "cross-encoder": importlib.util.find_spec("sentence_transformers") is not None,
    "flashrank": importlib.util.find_spec("flashrank") is not None,
    "typesafe": importlib.util.find_spec("typesafe_sdk") is not None,
}


# --- env readers (policy tier; read at request time) -----------------------
def corpora() -> list[str]:
    """Corpora a web/HTTP request may name (``INTERCHANGE_CORPORA``)."""
    raw = os.environ.get("INTERCHANGE_CORPORA", "edi,hotel")
    return [c.strip() for c in raw.split(",") if c.strip()]


def default_corpus() -> str:
    allowed = corpora()
    return allowed[0] if allowed else "edi"


def locked_knobs() -> set[str]:
    """Knobs (``mode``/``rerank``/``k``) a request may not override."""
    raw = os.environ.get("INTERCHANGE_LOCKED", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def unlocked_knobs() -> set[str]:
    """Knobs that are **locked by default** and a request may name only when the
    operator opts them in via ``INTERCHANGE_UNLOCKED`` (comma list; default empty).

    ADR-0018 locks the HTTP ``context`` knob by default — a shared/public surface must
    not let a caller widen its own context to whole notes over a personal vault — so it
    is honoured only when ``"context"`` appears here. This is the inverse of
    ``locked_knobs`` (which starts open and names what to close)."""
    raw = os.environ.get("INTERCHANGE_UNLOCKED", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def allow_metered() -> bool:
    """Whether ``rerank=typesafe`` is permitted at all (``INTERCHANGE_ALLOW_METERED``)."""
    return os.environ.get("INTERCHANGE_ALLOW_METERED", "0") == "1"


def metered_budget_usd() -> float:
    return float(os.environ.get("INTERCHANGE_METERED_BUDGET_USD", "1.00"))


def max_concurrent() -> int:
    return int(os.environ.get("INTERCHANGE_MAX_CONCURRENT", "2"))


def rate_per_min() -> int:
    return int(os.environ.get("INTERCHANGE_RATE_PER_MIN", "10"))


def ui_enabled() -> bool:
    """Whether the ``/ui`` mount is served (``INTERCHANGE_UI``; ``0`` = API-only)."""
    return os.environ.get("INTERCHANGE_UI", "1") != "0"


# --- context-assembly clamp (ADR-0018; policy over profile) ----------------
#: Context modes in increasing order of how much context they assemble.
_CONTEXT_MODE_ORDER = ("chunks", "notes")


def context_mode_max() -> str:
    """The most permissive context mode a profile may resolve to (ADR-0018).

    ``INTERCHANGE_CONTEXT_MODE_MAX`` if set, else ``chunks`` on a genuinely public
    deploy and ``notes`` locally — reusing ``auth_required()`` (a public host is one
    whose ``A2A_PUBLIC_URL`` is not localhost), so the default tracks the same
    public-deploy signal the auth rule does.
    """
    default = "chunks" if auth_required() else "notes"
    return os.environ.get("INTERCHANGE_CONTEXT_MODE_MAX", default)


def context_budget_max() -> int:
    """The budget ceiling a profile's ``budget_chars`` is capped at
    (``INTERCHANGE_CONTEXT_BUDGET_MAX``, default 24000)."""
    return int(os.environ.get("INTERCHANGE_CONTEXT_BUDGET_MAX", "24000"))


def clamp_context(settings: dict) -> dict:
    """Clamp resolved context ``settings`` by policy (ADR-0018): policy over profile.

    Lowers ``context`` to ``context_mode_max()`` (``chunks`` < ``notes``) and caps
    ``budget_chars`` at ``context_budget_max()``, then restores the
    ``note_max_chars <= budget_chars`` invariant if the cap made it too big. Pure;
    returns a new dict and leaves keys it does not manage untouched.
    """
    out = dict(settings)

    def _rank(mode: str) -> int:
        return _CONTEXT_MODE_ORDER.index(mode) if mode in _CONTEXT_MODE_ORDER else 0

    mode_max = context_mode_max()
    if "context" in out and _rank(out["context"]) > _rank(mode_max):
        out["context"] = mode_max

    budget_max = context_budget_max()
    if out.get("budget_chars") is not None and out["budget_chars"] > budget_max:
        out["budget_chars"] = budget_max
    if (out.get("note_max_chars") is not None and out.get("budget_chars") is not None
            and out["note_max_chars"] > out["budget_chars"]):
        out["note_max_chars"] = out["budget_chars"]
    return out


# --- fail-closed public auth (review #10) ----------------------------------
def _is_localhost(host: str | None) -> bool:
    return (host or "").lower() in {"localhost", "127.0.0.1", "::1", ""}


def auth_required() -> bool:
    """True on a genuinely public deploy: ``A2A_PUBLIC_URL`` host is not localhost.

    A host that publishes a signed Agent Card is discoverable; its ``/ask*`` routes
    must then require a key. Locally (the default) they stay open for the demo.
    """
    public = os.environ.get("A2A_PUBLIC_URL", "http://localhost:8000")
    return not _is_localhost(urlparse(public).hostname)


def web_key_ok(presented: str | None) -> tuple[bool, str | None]:
    """When auth is required, validate ``X-API-Key`` against ``A2A_API_KEYS``.

    Returns ``(ok, code)``: ``(True, None)`` when auth is not required or the key is
    valid; ``(False, "web_disabled_public")`` when keys are unset (fail-closed); and
    ``(False, "unauthorized")`` when a wrong/absent key is presented.
    """
    if not auth_required():
        return True, None
    from a2a_agent.server import api_key_labels, caller_label

    if not api_key_labels():
        return False, "web_disabled_public"
    if caller_label(presented) == "unknown":
        return False, "unauthorized"
    return True, None


def caller_for(session: str | None, api_key: str | None) -> str:
    """The audit ``caller`` for a web request: the API-key label when auth is
    required, else ``web/<sess8>`` (correlation, not identity — ADR-0015)."""
    if auth_required():
        from a2a_agent.server import caller_label

        return caller_label(api_key)
    return f"web/{(session or 'anon')[:8]}"


# --- rerank availability ----------------------------------------------------
def rerank_availability() -> tuple[list[str], dict[str, str]]:
    """``(allowed, unavailable)`` for the rerank knob given install state + policy.

    ``allowed`` always starts with ``none``; a backend joins it only when its module
    is importable and (for the metered one) policy and key allow it. ``unavailable``
    maps each excluded backend to a short, honest reason for ``/options``.
    """
    allowed = ["none"]
    unavailable: dict[str, str] = {}
    for backend in ("cross-encoder", "flashrank", "typesafe"):
        reason = backend_reason(backend)
        if reason is None:
            allowed.append(backend)
        else:
            unavailable[backend] = reason
    return allowed, unavailable


def backend_reason(backend: str) -> str | None:
    """``None`` if ``backend`` may run, else the reason it may not."""
    if backend == "typesafe":
        if not allow_metered():
            return "Metered reranking is disabled by policy."
        if not _HAVE_BACKEND["typesafe"]:
            return "Not installed."
        if not os.environ.get("TYPESAFE_API_KEY"):
            return "TYPESAFE_API_KEY not set."
        return None
    if not _HAVE_BACKEND.get(backend):
        return "Not installed."
    return None


# --- per-host rate limit (token bucket) ------------------------------------
_BUCKETS: dict[str, tuple[float, float, int]] = {}
_BUCKET_LOCK = threading.Lock()


def rate_check(host: str) -> int | None:
    """Consume one token for ``host``; return ``None`` if allowed, else the
    ``Retry-After`` seconds. Capacity is ``INTERCHANGE_RATE_PER_MIN``, refilling
    continuously; a bucket resets when the configured capacity changes.

    Keying (S4): ``host`` is the **socket peer** (``request.client.host``), never a
    forwarded header. Behind a reverse proxy every client shares the proxy's IP, so
    all callers collapse into one bucket — deliberately conservative (fail toward
    over-limiting, never under). ``X-Forwarded-For`` is **not trusted**: it is
    client-spoofable and would let an attacker mint a fresh bucket per forged IP,
    defeating the limit. Trusting a real ``X-Forwarded-For`` requires knowing the
    proxy hop count — a ``TRUSTED_PROXY`` parse is a follow-up to land before any
    non-localhost deploy that sits behind a proxy."""
    cap = rate_per_min()
    now = time.monotonic()
    with _BUCKET_LOCK:
        tokens, last, bcap = _BUCKETS.get(host, (float(cap), now, cap))
        if bcap != cap:
            tokens, last = float(cap), now
        tokens = min(float(cap), tokens + (now - last) * (cap / 60.0))
        if tokens >= 1.0:
            _BUCKETS[host] = (tokens - 1.0, now, cap)
            return None
        _BUCKETS[host] = (tokens, now, cap)
    return max(1, int(60.0 / cap)) if cap else 60


def reset_buckets() -> None:
    """Drop all rate-limit state (test isolation)."""
    with _BUCKET_LOCK:
        _BUCKETS.clear()


# --- generation concurrency bound ------------------------------------------
_SEMA: threading.Semaphore | None = None
_SEMA_SIZE: int | None = None
_SEMA_LOCK = threading.Lock()


def gen_semaphore() -> threading.Semaphore:
    """The process-wide generation semaphore, sized to ``INTERCHANGE_MAX_CONCURRENT``
    (rebuilt if that changes). A handler acquires it non-blocking and answers 429
    ``busy`` when full, so a slow subprocess can never queue the whole box."""
    global _SEMA, _SEMA_SIZE
    size = max(1, max_concurrent())
    with _SEMA_LOCK:
        if _SEMA is None or _SEMA_SIZE != size:
            _SEMA = threading.Semaphore(size)
            _SEMA_SIZE = size
        return _SEMA


def reset_semaphore() -> None:
    """Rebuild the generation semaphore fresh (test isolation)."""
    global _SEMA, _SEMA_SIZE
    with _SEMA_LOCK:
        _SEMA = None
        _SEMA_SIZE = None


# --- metered daily budget (from the audit ledger) --------------------------
def spend_today() -> float:
    """Sum of ``cost_usd`` over today's audit rows that were **actually billed** —
    every row whose ``marginal_usd > 0`` (``api`` generation and metered rerank).

    This is the honest daily metered spend the budget is enforced against, read
    from the same ledger ``--audit`` reports, so a day's metered spend cannot exceed
    ``INTERCHANGE_METERED_BUDGET_USD`` (review #2).

    Prior to the 2026-09-24 plan review this summed only ``telemetry == "estimated"``
    rows (defect #1). The ``api`` engine reports ``telemetry: "measured"`` whenever
    real token usage is present, so genuine API generation cost — the largest metered
    line — was silently excluded and never counted against the budget. Keying on
    ``marginal_usd`` (what the ledger records as actually paid) counts measured API
    rows and estimated metered-rerank rows alike, and still ignores subscription rows
    ($0 marginal).
    """
    path = enterprise.AUDIT_PATH
    if not path.exists():
        return 0.0
    today = time.strftime("%Y-%m-%d")
    total = 0.0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (row.get("marginal_usd", 0) or 0) > 0 and str(row.get("ts", "")).startswith(today):
            total += row.get("cost_usd", 0) or 0
    return total


def estimated_spend_today() -> float:
    """Deprecated alias for :func:`spend_today`.

    The old name is a misnomer: the budget counts every *billed* row
    (``marginal_usd > 0``), measured or estimated — not only ``telemetry ==
    "estimated"`` ones (defect #1, 2026-09-24 plan review). New code should call
    :func:`spend_today`; this alias is kept for existing callers.
    """
    return spend_today()


def budget_exceeded() -> bool:
    return spend_today() >= metered_budget_usd()


# --- error catalogue (review #11) ------------------------------------------
# The wire never carries ``str(e)`` (it leaks paths and stderr). An exception is
# mapped to one of these codes by cause; the raw text is logged server-side only.
ERROR_CATALOGUE: dict[str, tuple[int, str]] = {
    "index_missing": (503, "The index is empty. Run --reindex."),
    "rerank_unavailable": (503, "The selected reranker is not available on this host."),
    "metered_unavailable": (503, "Metered reranking is unavailable."),
    "engine_failed": (503, "The generation engine failed."),
    "internal": (500, "An internal error occurred."),
}


def classify_error(exc: BaseException) -> str:
    """Map an exception to an error-catalogue code by cause (never by leaking it)."""
    msg = str(exc).lower()
    if "no index" in msg or "reindex" in msg:
        return "index_missing"
    if "typesafe" in msg or "metered" in msg:
        return "metered_unavailable"
    if "rerank" in msg or "requirements-rerank" in msg:
        return "rerank_unavailable"
    if "engine" in msg or "anthropic_api_key" in msg or "claude" in msg:
        return "engine_failed"
    return "internal"
