# A2A Goal A acceptance result

_Gate: `INTERCHANGE_ENGINE=claude-code scripts/a2a-accept.sh` on branch feat/a2a-demo at 1544fd0, run 2026-09-21 21:33. Criteria: learning/a2a-acceptance-criteria.md (private). P1 ran on the Claude subscription; the demos ran on the stub engine at $0._

```
== Preconditions
PASS  P1    interchange answers
PASS  P2    existing suite green
PASS  P3    app.py with /health present
PASS  P4a   a2a-sdk 1.1.x installed
PASS  P4b   import a2a resolves to the SDK
== Demo runs
PASS  AC-hotel make a2a-demo PROFILE=hotel: verified card, cited hotel answer, audit caller a2a:requester, stub engine
PASS  AC-rail make a2a-demo PROFILE=rail: verified card, cited edi answer, audit caller a2a:requester, stub engine
PASS  AC3   no stray server process
== Tests and scenarios
PASS  AC4   tests/test_a2a.py green
PASS  AC5.a tampered card rejected
PASS  AC5.b InvalidSignaturesError asserted
PASS  AC5.c unsigned card rejected (NoSignatureError)
PASS  AC5.d unknown kid rejected
PASS  AC5.e injection over A2A yields failed task, engine never called
PASS  AC5.f missing API key returns 401
PASS  AC5.g profile switch changes corpus
PASS  AC5.h streaming yields WORKING then COMPLETED
PASS  AC5.i MCP and A2A audit rows have identical keys
PASS  AC6a  verifier pins algorithms=["ES256"]
PASS  AC6b  key_provider handles jku (must raise)
== Regression
PASS  AC7   full suite green
PASS  AC8   eval/baseline.json untouched
== Artifacts
PASS  AC9.a docs/adr/0013-a2a-agent-interop.md
PASS  AC9.b lessons/07-a2a-handoff.md
PASS  AC9.c a2a_agent/profiles.yaml
PASS  AC9.d a2a_agent/orchestrate/interchange-knowledge.yaml
PASS  AC9.e features/a2a_handoff.feature
PASS  AC9.f hotel-demo has 3+ pages
PASS  AC9.interchange-knowledge agents/interchange-knowledge/instance.yaml declares tier
PASS  AC9.requester agents/requester/instance.yaml declares tier
PASS  AC9.g README: OWASP mapping + MCP vs A2A table
PASS  AC9.h profiles rail and hotel
== Hygiene
PASS  AC10a only public keys tracked
PASS  AC10b no .env / audit.jsonl tracked
FAIL  AC10c uncommitted changes
PASS  AC11a no removed tests or scenarios
PASS  AC11b no skip/xfail added
PASS  AC12  SDK import still unshadowed

A2A ACCEPTANCE: FAILED
exit=0
```
