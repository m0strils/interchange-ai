# Workbench acceptance gate — result

*Gate: `make workbench-accept` (`scripts/workbench-accept.sh` + `scripts/workbench_accept.py`). Branch `feature/browser-workbench`, commit `6081d8e`, run started 2026-09-22T12:17:08-0400, clean tree, exit 0. Engine: `claude-code` (headless `claude -p` on the Claude subscription). `claude -p` invocations: 5 (P2 login proof, AC3, AC4, AC6a, AC9); the run-log `calls` field counts the 3 generate frames the driver observed (AC9 closes its stream before generate, P2 is outside the driver). Shadow cost delta $0.378 (measured from the CLI JSON, ADR-0004), billed delta $0.0000. Model that ran: `claude-opus-4-7`. Honest notes: AC9 proves the orphaned worker holds and then releases its slot; it does not exercise the `cancel` path (the subprocess always spawns; `cancel` is covered by `tests/test_workbench.py::test_cancel_honoured_between_stages` only). AC4 keepalives were 0 because generate took 12.6 s, under the 15 s silence interval, so the `==0` band applied. The gate is not yet in `.claude/hooks/protect-paths.sh` `PROTECTED`; add both script paths there by hand (AC13e NOTE).*

```
== Preconditions
PASS  P1    claude CLI on PATH
PASS  P2    claude -p login proof: JSON, is_error=false, usage present (models: claude-opus-4-7)
PASS  P3    edi index has chunks
PASS  P4    offline pytest suite green
PASS  P5    bogus engine is a startup failure naming the allowed engines
PASS  P6    server ready on 127.0.0.1:8790 (engine=claude-code, pid 75221)
== HTTP acceptance
PASS  AC1   health engine=claude-code, index+ui true, collection=edi
PASS  AC2   metered off, vault excluded, typesafe unavailable
PASS  AC3   measured, model=claude-opus-4-7, in_tokens=32520, cost=$0.1534, marginal=$0
PASS  AC4   stage order ok, generate.ms=12584, keepalives=0==0
PASS  AC8a  429 busy, Retry-After 5, audit blocked=busy caller web/
PASS  AC8b  same POST now 400 with blocked set (slot released)
PASS  AC5   guard-only, done.blocked set, audit in_tokens=0 cost=0
PASS  AC6a  pinned 2 chunk(s) in order, grounded
PASS  AC6b  altered pin token -> 403 pin_invalid
PASS  AC7   corpus/metered/mode/k refused (403/403/422/422); no audit rows
PASS  AC9   orphan held slot (429 busy), claude child drained <=190 s, slot released
PASS  AC10  429 rate_limited after loop, Retry-After 1, audit blocked=rate_limit
== CLI
PASS  AC11  --explain: 7 lines all prefixed '  ┃ [explain] ', stages 1/5..5/5, passed/audit, engine=stub
PASS  AC12  billed delta 0.0000 (==0.0000), shadow delta 0.3780 (>0)
== Hygiene
PASS  AC13a server pid 75221 stopped
PASS  AC13b port 8790 free
PASS  AC13c no orphaned children of 75221
PASS  AC13d tree clean (docs/workbench-RESULT.md excepted)
NOTE  AC13e gate files differ from dev merge-base (expected on this feature branch); the gate is NOT yet protected — add scripts/workbench-accept.sh + scripts/workbench_accept.py to PROTECTED in .claude/hooks/protect-paths.sh
PASS  AC13f run-log line appended to eval/workbench-accept-runs.jsonl

WORKBENCH ACCEPTANCE: ALL PASS
```
