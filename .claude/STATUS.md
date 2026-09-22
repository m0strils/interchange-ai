# Status (reprinted after compaction)

Goal: ship the browser workbench (ADR-0015) to `dev` with a real-engine acceptance gate.
Gate: `make workbench-accept` (5 claude -p calls on the subscription, $0 marginal); `WB_ENGINE=stub make workbench-accept` self-tests at $0. Offline gate: `.venv/bin/python -m pytest -q` (pre-push hook).
Done (2026-09-22): workbench shipped (bb47f16); gate + fail-fast engine + audited busy + clean timeout (6081d8e); real run ALL PASS captured in docs/workbench-RESULT.md.
Current: merge feature/browser-workbench → dev (--no-ff), push dev. No main merge, no public deploy (go-public decision pending).
Follow-ups (ADR-0015): TRUSTED_PROXY rate-limit keying before any proxied deploy; JS test runner; token streaming via on_event; --agent path in the UI. Add scripts/workbench-accept.sh + scripts/workbench_accept.py to PROTECTED in .claude/hooks/protect-paths.sh by hand.
Rules: never edit the gates, eval/golden.jsonl, or weaken existing tests; commit per slice with the ADR number.
