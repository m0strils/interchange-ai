# Status (reprinted after compaction)

Goal: ADR-0018 done on `feature/passage-eval` (stacked on feature/corpus-profiles). Next: merge both branches to `dev` (--no-ff) when the owner says so. No main merge, no public deploy.
Gate: `.venv/bin/python -m pytest -q` (374); `.claude/skills/verify-change/check.sh` + `weakened-tests.sh dev` before each commit; commit per slice with the ADR number.
Done (2026-09-24): ADR-0017 Accepted (metric kept, merge rejected). ADR-0018 Accepted: fair-share context assembly wired on every surface; brain profile hybrid/notes/20000/16000 -> context@4 7/7, note@4 21/24, mean chars 12,961, 0 per-row ranking changes, rail 14/14 and vault 15/18 unchanged, live answers grounded, graded 93%/97%. Judge fixed to grade the governed path (was 40%). onnxruntime telemetry off (exit-time abort, 9b94d3c; same fix on compliance-rag feature/ort-telemetry).
Frozen artifacts: golden-brain.jsonl sha256 b92dca86... (25 rows / 7 section rows); graded-brain.jsonl (3 rows). Corpus freeze on ~/Documents/Brain is LIFTED.
Follow-ups (P2): explicit audit write flag; HTTP retrieval mode from profile; stdin prompt; snapshot threading; cache bound + build stamp; overlay deep-merge; research stays on chunks until an injection scan exists.
Rules: never edit the gates, eval/golden.jsonl, or weaken existing tests.
