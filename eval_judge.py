"""
Answer-quality evaluation for Interchange (ADR-0008) — advisory, $0, offline-gated.

ADR-0007 measured *retrieval* (hit@k). This measures the *answer*. The catch it was
designed around: faithfulness alone is near-circular here — the RAG answer is
generated FROM the retrieved context under an "answer only from context" prompt, so
its claims are supported by construction. So the HEADLINE signals are the ones that
can actually fail on this system:

  - refusal-correctness  — for out-of-corpus questions, does the system decline
                           WITHOUT fabricating? Measured as faithfulness == 1.0 on
                           those rows (no unsupported claim). Unlike the answerable
                           case, faithfulness here is NOT circular: the model can pull
                           in ungrounded world knowledge, and this catches exactly that.
                           (A regex on decline-phrases was tried first and dropped —
                           it false-negatived good refusals that cite what IS covered,
                           and couldn't separate a clean decline from an answer that
                           hedges. Verified against real output; see ADR-0008.)
  - answer-correctness   — do answerable questions surface the expected facts?
                           (deterministic keyword coverage — no LLM needed to score)
  - faithfulness         — for ANSWERABLE rows, a secondary monitor only: the answer is
                           built from the retrieved context, so it's ≈1.0 by
                           construction (near-circular). It earns its keep on the
                           unanswerable rows above. Zero-claim (a refusal) -> 1.0.

All LLM calls run on the Claude subscription (`claude -p`) at $0 marginal cost;
telemetry is labeled `estimated` (ADR-0003/0004). This is ADVISORY — it prints a
report and, only if `--fail-under` is set, exits nonzero. It is NOT wired into the
`pre-push` gate, which stays offline/$0 (ADR-0006): an LLM eval can't live there.

The pure scoring functions are unit-tested offline; the single LLM seam
(`_run_judge`) and the generation engine are stubbed in tests.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

import interchange
from interchange import parse_claude_usage

GRADE_LOG = pathlib.Path(__file__).parent / "eval" / "grade-runs.jsonl"

JUDGE_SYSTEM = (
    "You are a strict evaluator. Decompose the ANSWER into atomic factual claims. "
    "For each claim, decide whether it is directly supported by the CONTEXT. "
    'Return ONLY JSON of the form {"claims":[{"claim":"...","supported":true|false}]}. '
    "If the ANSWER makes no factual claim (e.g. it declines to answer), return "
    '{"claims":[]}.'
)


# --- pure scoring functions (unit-tested offline) --------------------------
def answer_correctness(answer: str, expected_facts: list[str]) -> float:
    """Fraction of `expected_facts` present in `answer` (case-insensitive substring).
    No expected facts -> 1.0 (nothing was required). Deterministic — no LLM."""
    if not expected_facts:
        return 1.0
    a = answer.lower()
    return sum(1 for f in expected_facts if f.lower() in a) / len(expected_facts)


def handled_unanswerable(faithfulness: float) -> bool:
    """Correct handling of an UNANSWERABLE question = introducing no unsupported claim,
    i.e. faithfulness == 1.0 (a clean decline, or only-supported statements about what
    the corpus *does* cover). A hallucinated out-of-corpus answer drops below 1.0.
    (Replaced a decline-phrase regex that false-negatived good refusals — see ADR-0008.)"""
    return faithfulness >= 1.0


def parse_judge_verdict(text: str) -> dict:
    """Extract the judge's JSON verdict from `text` (may be wrapped in prose or
    ```json fences). Returns {"claims":[{"claim":str,"supported":bool},...]};
    on any parse failure returns {"claims": []}."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"claims": []}
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"claims": []}
    claims = obj.get("claims")
    if not isinstance(claims, list):
        return {"claims": []}
    return {"claims": [
        {"claim": str(c.get("claim", "")), "supported": bool(c.get("supported"))}
        for c in claims if isinstance(c, dict)
    ]}


def faithfulness_score(verdict: dict) -> float:
    """supported / total claims. Zero claims -> 1.0: a refusal (no factual claim)
    is trivially faithful, and must never be scored 0/0."""
    claims = verdict.get("claims") or []
    if not claims:
        return 1.0
    return sum(1 for c in claims if c.get("supported")) / len(claims)


# --- the single LLM seam (stubbed in tests) --------------------------------
def _run_judge(prompt: str) -> str:
    """Run the faithfulness judge on the subscription (`claude -p`, $0). Returns the
    model's raw result text. The one place this module shells out — tests monkeypatch
    `eval_judge.subprocess.run` / `eval_judge.shutil.which`."""
    if not shutil.which("claude"):
        sys.exit("The judge needs the `claude` CLI (Claude Code) logged into your plan, "
                 "or run without --grade.")
    proc = subprocess.run(
        ["claude", "-p", prompt, "--append-system-prompt", JUDGE_SYSTEM,
         "--output-format", "json"],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        sys.exit(f"claude -p (judge) failed: {proc.stderr.strip()[:300]}")
    return parse_claude_usage(proc.stdout, est_input_chars=len(prompt) + len(JUDGE_SYSTEM))["text"]


def judge_faithfulness(question: str, context: str, answer: str,
                       engine: str = "claude-code") -> dict:
    """Score claim-level faithfulness of `answer` against `context` via the $0 judge.
    Returns {"score", "verdict", "telemetry"}. A secondary hallucination monitor."""
    prompt = (f"CONTEXT (reference data):\n{context}\n\n"
              f"QUESTION: {question}\n\nANSWER:\n{answer}\n\n"
              "List each claim in the ANSWER and whether the CONTEXT supports it.")
    verdict = parse_judge_verdict(_run_judge(prompt))
    return {"score": faithfulness_score(verdict), "verdict": verdict, "telemetry": "estimated"}


# --- the grade run (advisory) ----------------------------------------------
def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _generate(question: str, engine: str) -> tuple[str, str, list[str]]:
    """Grade the GOVERNED answer exactly as a live request produces it — the profile's
    retrieval mode, persona, context assembly (ADR-0018) and included-source grounding
    — via `answer_detail(audit=False)`, which runs the full pipeline but writes no audit
    row (grade runs must not skew the per-request `--audit` dashboard; they get their own
    `eval/grade-runs.jsonl`). Returns (answer_text, context, sources): `context` is the
    exact assembled text the engine saw, `sources` the INCLUDED set grounding used.

    Replaces an earlier hand-rolled reproduction (retrieve -> top-k join -> engine ->
    grounding) that bypassed assembly/persona/profile-mode and so measured a context no
    surface builds any more — it graded the pre-ADR-0018 behaviour (see ADR-0008)."""
    d = interchange.answer_detail(question, engine=engine, audit=False)
    return d["text"], d["context_text"], d["sources"]


def run_grade(golden_path=None, engine: str = "claude-code", fail_under=None) -> dict:
    """Grade generated answers over the golden set. Advisory: prints a report, logs
    rows to eval/grade-runs.jsonl, returns a summary. Exits nonzero only if
    `fail_under` is set and a headline signal falls below it. $0, telemetry estimated."""
    golden_path = pathlib.Path(golden_path or interchange.GOLDEN_PATH)
    rows = [json.loads(line) for line in golden_path.read_text().splitlines() if line.strip()]
    answerable = [r for r in rows if not r.get("unanswerable")]
    unanswerable = [r for r in rows if r.get("unanswerable")]

    print(f"Answer-quality grade (engine={engine}, $0, telemetry=estimated) — "
          f"{len(answerable)} answerable + {len(unanswerable)} unanswerable\n")
    print(f"  {'':<3} {'signal':<14} {'score':<7} question")
    print(f"  {'-'*3} {'-'*14} {'-'*7} {'-'*40}")

    results, ac_scores, refusal_flags, faith_scores = [], [], [], []

    for r in answerable:
        q = r["question"]
        ans, context, _ = _generate(q, engine)
        ac = answer_correctness(ans, r.get("expected_facts") or [])
        faith = judge_faithfulness(q, context, ans, engine=engine)["score"]
        ac_scores.append(ac)
        faith_scores.append(faith)
        results.append({"kind": "answerable", "question": q, "answer_correctness": ac,
                        "faithfulness": faith})
        print(f"  {'✅' if ac >= 0.5 else '❌':<3} {'answer-corr':<14} {ac:<7.2f} {q[:40]}")

    for r in unanswerable:
        q = r["question"]
        ans, context, _ = _generate(q, engine)
        faith = judge_faithfulness(q, context, ans, engine=engine)["score"]
        rc = handled_unanswerable(faith)  # correct iff no unsupported claim (faithfulness==1)
        refusal_flags.append(rc)
        faith_scores.append(faith)
        results.append({"kind": "unanswerable", "question": q, "refusal_correct": rc,
                        "faithfulness": faith})
        print(f"  {'✅' if rc else '❌':<3} {'refusal-corr':<14} {faith:<7.2f} {q[:40]}")

    summary = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "engine": engine,
        "telemetry": "estimated",
        "n_answerable": len(answerable),
        "answer_correctness": round(_mean(ac_scores), 3),
        "n_unanswerable": len(unanswerable),
        "refusal_correctness": round(_mean([1.0 if f else 0.0 for f in refusal_flags]), 3),
        "mean_faithfulness": round(_mean(faith_scores), 3),
    }
    # headline signals gate (advisory); faithfulness is a monitor, never gates.
    summary["passed"] = (
        fail_under is None
        or (summary["answer_correctness"] >= fail_under
            and summary["refusal_correctness"] >= fail_under)
    )

    GRADE_LOG.parent.mkdir(exist_ok=True)
    with GRADE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**summary, "results": results}) + "\n")

    print(f"\n  answer-correctness   = {summary['answer_correctness']:.0%}  (headline)")
    print(f"  refusal-correctness  = {summary['refusal_correctness']:.0%}  (headline)")
    print(f"  faithfulness         = {summary['mean_faithfulness']:.0%}  (monitor, estimated — "
          f"near-circular here, watch for drops not levels)")
    if fail_under is not None:
        print(f"  fail-under {fail_under:.0%}: {'PASS' if summary['passed'] else 'FAIL'}")
    print(f"  -> {GRADE_LOG}")
    return summary
