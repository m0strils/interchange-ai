# ADR-0006: Quality gate — a local git hook, not hosted CI

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** Jeff Lynch

## Context
The test suite (ADR-0005) should run automatically as a gate, not on demand. The
obvious home is hosted CI (GitHub Actions on push), but the GitHub Actions minutes
are exhausted — and paying for CI cuts against this project's $0 stance (ADR-0003).

Two facts make a hosted runner unnecessary here: the tests are **hermetic** (no
network, no model, temp audit path) and **instant** (~0.02s), so they run fine on
the developer's own machine at the moment code would leave it.

## Options considered
1. **Hosted CI (GitHub Actions).** Standard, clean-room. *Cons:* out of minutes;
   metered — reintroduces spend for a solo learning repo.
2. **Local `pre-push` git hook.** Runs the suite before every push — the same
   checkpoint CI-on-push occupies. *Pros:* $0, no minutes, deterministic, instant.
   *Cons:* runs on the dev's machine (not a clean room) and only for whoever
   installed it.
3. **Manual `pytest`.** No enforcement — a gate in name only.

## Decision
Use a **committed `pre-push` hook** (`.githooks/pre-push`) that runs `pytest`, wired
via `git config core.hooksPath .githooks` (install once per clone). A failing suite
aborts the push (`git push --no-verify` bypasses in a pinch).

## Consequences
- A **$0 automatic gate** at the last checkpoint before code leaves the machine.
- Enforcement is per-clone (the hooksPath config isn't committed) and machine-local,
  not a clean room — acceptable because the tests are hermetic.
- **Trivially portable to hosted CI later:** the gate is just `pytest`. If the
  minutes come back or the project goes multi-contributor, a one-file GitHub Actions
  workflow supersedes this — the command doesn't change.
