# Status (reprinted after compaction)

Goal: Goal A of the A2A demonstration (learning/a2a-acceptance-criteria.md), branch feat/a2a-demo.
Gate: scripts/a2a-accept.sh, run as `INTERCHANGE_ENGINE=claude-code scripts/a2a-accept.sh` so P1 costs $0.
Done so far (2026-09-21): P2, P3, P4 satisfied; app.py, answer_detail, stub engine, caller audit field, corpus override committed; content files (hotel-demo, profiles, orchestrate yaml, agent tiers, ADR-0013, lesson 07, README section) committed.
Current: a2a_agent package (keys, server, requester, Makefile a2a-demo, tests/test_a2a.py, features/a2a_handoff.feature) being built; then run the gate.
Last AC passed: none yet (gate not run end to end).
Rules: never edit the gate, eval/baseline.json, or existing tests; commit after each AC with the AC number.
