---
name: verify-change
description: Verify a finished code change before calling it done. Runs the repo's gate (check.sh), reads the diff, mechanically scans for weakened tests (weakened-tests.sh), and reports PASS or FAIL with the evidence attached. Use after any refactor, feature, fix, or migration is finished, and whenever the user says done, finished, ready to commit, ready for PR, verify, check my work, or is this done. Fires on its own after a change; do not wait to be asked.
---

# Verify change

"Done" means the gates ran and were observed, not that the diff looks right. Walk every step, in order, every time. Never skip step 1 because the change "looks small."

## 1. Run the gate

```bash
~/.claude/skills/verify-change/check.sh
```

The skill is installed at `~/.claude/skills/verify-change/`; a repo-local copy under `.claude/skills/verify-change/` takes precedence if present. Capture the exit code and the last 40 lines. Non-zero is a FAIL regardless of anything else in this report. Do not go looking for a reason the failure "does not matter."

If the gate cannot detect a test command (exit 3), report FAIL with "no gate" and tell the user to create `.claude/verify-gate` with the command. A repo with no gate is unverified, not passing.

## 2. Read the diff

```bash
git status --short
git diff
git diff --cached
```

Read the whole diff. Note every file under `tests/`, `evals/`, `eval/`, `features/`, `*_test.*`, `*.test.*`, `*.spec.*`, golden sets, fixtures, and CI config.

## 3. Scan for weakened tests

```bash
~/.claude/skills/verify-change/weakened-tests.sh          # diffs against merge-base with main/master
~/.claude/skills/verify-change/weakened-tests.sh HEAD~1   # or against an explicit ref
```

The script prints one line per suspicious hunk and exits 1 when it finds any. It is a detector, not a verdict: read each finding against [reference.md](reference.md) and decide whether the diff or commit message states a reason. A finding with no stated reason is a FAIL even when the gate is green.

## 4. Report

Use exactly this shape and nothing else:

```
VERIFY: PASS | FAIL
Gate: <command> exit <code>
<last lines of gate output>

Diff: <n> files changed, <n> test-side
Weakened-test scan: clean | <n> findings
<each finding: file:line, pattern, reason stated? yes/no>

Verdict: <one sentence>
```

Rules for the verdict:
- Never PASS while the gate is red.
- Never PASS from reading the diff alone.
- Never PASS with an unexplained weakened-test finding.
- A pre-existing failure outside the change is still FAIL. Name it. Do not skip, mock, or xfail it inside this change.
