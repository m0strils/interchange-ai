# Status (reprinted after compaction)

Goal: land ADR-0016 (corpus profiles as portable data) on `feature/corpus-profiles`, then merge to `dev` (--no-ff). No main merge, no public deploy.
Gate: `.venv/bin/python -m pytest -q` (pre-push hook); `.claude/skills/verify-change/check.sh` + `weakened-tests.sh dev` before each commit.
Done (2026-09-23): slices 0-3 + 6a committed (ADR Proposed, overlay + persona/retrieval/tools keys, INTERCHANGE_CHROMA_DIR + --profile + timed reindex, persona by collection, launchd template + CORS). Measured: rail 0.3 s, brain 3.0 s, research 5.5 s, vault 30.2 s rebuilds; evals reproduce (rail 14/14, vault 11/18 hybrid, 15/18 rerank).
Current: slices 4+5 (retrieval mode per profile + conditional MCP tool; --golden-add) in a coder run; then brain eval baseline, ADR-0016 -> Accepted, commit, merge to dev.
Outside the repo: vault ~/Documents/Brain, workspace ~/.interchange (profiles.yaml overlay, chroma, golden-brain.jsonl), shell functions brain/research in ~/.zshrc. Obsidian Local REST API key for the Brain vault still to be wired into ~/.claude.json once the vault is opened.
Rules: never edit the gates, eval/golden.jsonl, or weaken existing tests; commit per slice with the ADR number.
