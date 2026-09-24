# Status (reprinted after compaction)

Goal: ADR-0017 slices 3-5 on `feature/passage-eval` (stacked on feature/corpus-profiles); earlier goal, land ADR-0016 (corpus profiles as portable data) on `feature/corpus-profiles`, then merge to `dev` (--no-ff). No main merge, no public deploy.
Gate: `.venv/bin/python -m pytest -q` (pre-push hook); `.claude/skills/verify-change/check.sh` + `weakened-tests.sh dev` before each commit.
Done (2026-09-23): slices 0-3 + 6a committed (ADR Proposed, overlay + persona/retrieval/tools keys, INTERCHANGE_CHROMA_DIR + --profile + timed reindex, persona by collection, launchd template + CORS). Measured: rail 0.3 s, brain 3.0 s, research 5.5 s, vault 30.2 s rebuilds; evals reproduce (rail 14/14, vault 11/18 hybrid, 15/18 rerank).
Done (2026-09-23, ADR-0017): slices 0-2 committed — ADR Proposed, headless engine strict MCP + no tools (input 31,880 -> 9,851 tok), passage@k/lead share eval, brain baseline passage@4 3/6.
Done (2026-09-23, ADR-0017 slice 3): step 1 structural lead detection kept (bda36b3); step 2 lead-chunk merge measured and REVERTED (66beeee): rail 13/14, vault rerank 12/18, brain passage@4 3/6 unchanged; lead share fell everywhere. Store rebuilt on reverted code; numbers reproduce.
Current (ADR-0017): slice 3b same-note neighbour expansion as a profile retrieval key (+ two cheaper variants: preamble-only merge, re-window merged text); same gates. Then slice 4 top_k, slice 5 Accepted.
Previously current: slices 4+5 (retrieval mode per profile + conditional MCP tool; --golden-add) in a coder run; then brain eval baseline, ADR-0016 -> Accepted, commit, merge to dev.
Outside the repo: vault ~/Documents/Brain, workspace ~/.interchange (profiles.yaml overlay, chroma, golden-brain.jsonl), shell functions brain/research in ~/.zshrc. Obsidian Local REST API key for the Brain vault still to be wired into ~/.claude.json once the vault is opened.
Rules: never edit the gates, eval/golden.jsonl, or weaken existing tests; commit per slice with the ADR number.
