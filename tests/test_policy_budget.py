"""Units for the metered daily budget (2026-09-24 plan review, defect #1).

``policy.spend_today`` must count every *billed* audit row (``marginal_usd > 0``) —
a ``measured`` ``api`` generation row and an ``estimated`` metered-rerank row alike —
while ignoring a subscription row (``marginal_usd == 0``) and any row from another
day. ``budget_exceeded`` flips when that sum crosses ``INTERCHANGE_METERED_BUDGET_USD``.

The rows are written straight to the (isolated, autouse-redirected) audit ledger with
explicit ``marginal_usd``/``cost_usd``/``ts`` so the test pins the *rule* — billed vs
$0 marginal — rather than re-deriving it through ``enterprise.audit``.
"""
from __future__ import annotations

import json
import time

import enterprise
import policy


def _write_row(**fields) -> None:
    """Append one audit row (only the fields the budget rule reads need be present)."""
    with enterprise.AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(fields) + "\n")


def _today() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _yesterday() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 86400))


def test_spend_today_counts_billed_rows_and_ignores_subscription_and_yesterday():
    # measured API generation — billed, counts
    _write_row(ts=_today(), telemetry="measured", engine="api",
               cost_usd=0.02, marginal_usd=0.02)
    # metered rerank — estimated but billed, counts
    _write_row(ts=_today(), telemetry="estimated", engine="api",
               cost_usd=0.01, marginal_usd=0.01)
    # subscription answer — $0 marginal, ignored even though it has a shadow cost
    _write_row(ts=_today(), telemetry="measured", engine="claude-code",
               cost_usd=0.05, marginal_usd=0.0)
    # a billed row from yesterday — outside today's window, ignored
    _write_row(ts=_yesterday(), telemetry="measured", engine="api",
               cost_usd=0.50, marginal_usd=0.50)

    assert policy.spend_today() == 0.03
    # the deprecated alias tracks the same honest total
    assert policy.estimated_spend_today() == 0.03


def test_budget_exceeded_flips_when_billed_sum_crosses_the_env_budget(monkeypatch):
    monkeypatch.setenv("INTERCHANGE_METERED_BUDGET_USD", "0.05")
    _write_row(ts=_today(), telemetry="measured", engine="api",
               cost_usd=0.03, marginal_usd=0.03)
    assert policy.spend_today() == 0.03
    assert policy.budget_exceeded() is False

    # a second billed row pushes the day's spend over the budget
    _write_row(ts=_today(), telemetry="measured", engine="api",
               cost_usd=0.03, marginal_usd=0.03)
    assert policy.spend_today() == 0.06
    assert policy.budget_exceeded() is True
