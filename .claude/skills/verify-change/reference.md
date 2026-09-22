# Weakened-test checklist

Read only when step 3 of the skill finds test-side changes. Each row is a pattern that makes a red suite green without fixing the code. Any match without a stated reason in the diff or commit message is a FAIL.

| Pattern | What it looks like in a diff | Why it matters |
|---|---|---|
| Deleted test | A test function or file removed | The behavior it covered is now unverified |
| Skipped test | `@pytest.mark.skip`, `@skip`, `xit(`, `it.skip(`, `t.Skip(`, `#[ignore]` added | Same as deleted, but hidden in a green run |
| Expected failure | `@pytest.mark.xfail` added | Turns a failure into a pass without a fix |
| Loosened assertion | `assertEqual` → `assertIn`, `==` → `in`, `toBe` → `toBeTruthy`, exact match → regex, `assert x` → `assert x is not None` | The test accepts more outputs than before |
| Widened tolerance | `abs=0.01` → `abs=0.5`, `rel=` increased, `approx` added, timeouts raised | Precision the test used to enforce is gone |
| Mocked-out gate | A real call replaced with a mock or fake inside the test being fixed | The code path under test is no longer exercised |
| Threshold lowered | `hit@k >= 0.8` → `>= 0.6`, coverage `--cov-fail-under` reduced, eval bars edited | The quality bar moved instead of the code |
| Golden set edited | Expected outputs in a golden or fixture file changed to match new output | The reference answer was rewritten to fit the code. Requires a human author line and a reason. |
| Try/except around assertion | `try: assert ... except: pass` | The assertion can no longer fail |
| Conditional assertion | `if env == "ci": assert ...` | The assertion runs only sometimes |
| Test data narrowed | Edge cases removed from parametrize lists or table-driven cases | Coverage shrank silently |
| Certificate rounded up | A rule moved from instruction-only to enforced with no hook or script added | The kit's single most dangerous edit |

## Acceptable test-side changes

These are fine when the diff or commit message says so:

- A test updated because the intended behavior changed, with the new behavior named.
- A flaky test quarantined with a linked issue and a date.
- A golden set entry corrected with `authored_by: human` and a reason.
- New tests added. Always fine.

## When the gate is red and the reason is outside the change

Report FAIL and name the pre-existing failure. Do not skip it, mock it, or mark it xfail inside this change. A separate change can quarantine it with a reason.
