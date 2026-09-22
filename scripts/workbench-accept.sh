#!/usr/bin/env bash
# Real-engine acceptance gate for the browser workbench (ADR-0015).
#
# Proves the /ui + /ask + /ask/stream surface on the *real* claude-code engine —
# the things the stub cannot show: a multi-second `generate` stage, keepalive
# comments under silence, evidence arriving before the answer, a measured audit
# row with real token counts and a shadow cost, the guardrail still blocking, the
# concurrency + rate limits holding under a real subprocess, and the CLI still
# intact. Starts ONE server on the Max subscription engine, drives it via
# scripts/workbench_accept.py, then checks the CLI, process hygiene and the
# run-log, and prints the sentinel.
#
# Cost: ~5 `claude -p` calls (P2 login proof + 4 driver calls) ≈ $1 API-equivalent
# SHADOW cost, $0 marginal on the subscription (ADR-0004). WB_ENGINE=stub is a $0
# self-test: the real-engine-only checks become SKIP.
#
# The `cancel` path is NOT exercised here — the pre-generate check runs
# microseconds after the retrieve emit, so the subprocess always finishes
# (ADR-0015). `cancel` stays covered by pytest only
# (tests/test_workbench.py::test_cancel_honoured_between_stages).
#
# The verbatim output is committed to docs/workbench-RESULT.md (in the
# docs/a2a-RESULT.md provenance style). NOT part of the pre-push hook: it needs a
# logged-in `claude` CLI and takes minutes; it is the manual gate before any merge
# that touches the HTTP surface or the engine.
#
# Usage:  bash scripts/workbench-accept.sh                 # real engine (claude-code)
#         WB_ENGINE=stub bash scripts/workbench-accept.sh  # $0 mechanics self-test
# Env:    WB_PORT (default 8790), WB_ENGINE (claude-code|stub, default claude-code),
#         WB_LOG (default eval/workbench-accept-runs.jsonl).

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python

WB_PORT="${WB_PORT:-8790}"
WB_ENGINE="${WB_ENGINE:-claude-code}"
WB_LOG="${WB_LOG:-eval/workbench-accept-runs.jsonl}"

fail=0
PHASE="startup"
SERVER_PID=""
WB_MODELS=""
SHADOW_DELTA=""
RUNLOG_DONE=""
CLEANED=""
TMP="$(mktemp -d)"

pass() { printf 'PASS  %-5s %s\n' "$1" "$2"; }
bad()  { printf 'FAIL  %-5s %s\n' "$1" "$2"; fail=1; }
skip() { printf 'SKIP  %-5s %s\n' "$1" "$2"; }
note() { printf 'NOTE  %-5s %s\n' "$1" "$2"; }
has()  { grep -qiE "$2" "$1" 2>/dev/null; }

# One server, started with $SERVER_PID; stop only what this gate started — never
# `pgrep -f uvicorn` / `pkill -f`, which would hit a developer's own server.
stop_server() {
  [ -n "$SERVER_PID" ] || return 0
  if kill -0 "$SERVER_PID" 2>/dev/null; then
    kill -TERM "$SERVER_PID" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do   # up to ~3 s
      kill -0 "$SERVER_PID" 2>/dev/null || break
      sleep 0.3
    done
    kill -KILL "$SERVER_PID" 2>/dev/null
  fi
  wait "$SERVER_PID" 2>/dev/null
}

# Append one JSON line to $WB_LOG. Built from $TMP/summary.json (the driver's
# per-run summary) when present; otherwise the aborted form with the phase we
# died in. ts/commit/engine and the whole-run shadow delta come from the wrapper.
append_runlog() {
  [ -n "$RUNLOG_DONE" ] && return 0
  RUNLOG_DONE=1
  WB_LOG="$WB_LOG" WB_ENGINE="$WB_ENGINE" \
  RL_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  RL_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" \
  RL_SUMMARY="$TMP/summary.json" RL_PHASE="$PHASE" RL_SHADOW="$SHADOW_DELTA" \
  RL_PASS="$([ "$fail" -eq 0 ] && echo 1 || echo 0)" \
  "$PY" - <<'PYEOF'
import json, os, pathlib
logp = pathlib.Path(os.environ["WB_LOG"])
logp.parent.mkdir(parents=True, exist_ok=True)
ts, commit, engine = os.environ["RL_TS"], os.environ["RL_COMMIT"], os.environ["WB_ENGINE"]
try:
    s = json.load(open(os.environ["RL_SUMMARY"]))
except Exception:
    s = {}
if s:
    sh = os.environ.get("RL_SHADOW", "")
    line = {
        "ts": ts, "commit": commit, "engine": engine,
        "model": s.get("model"),
        "calls": s.get("calls"),
        "shadow_delta": (float(sh) if sh not in ("", "None") else s.get("shadow_delta")),
        "generate_ms": s.get("generate_ms"),
        "keepalives": s.get("keepalives"),
        "pass": (os.environ.get("RL_PASS") == "1") and bool(s.get("pass", True)),
    }
else:
    line = {"ts": ts, "commit": commit, "engine": engine,
            "pass": False, "aborted_at": os.environ["RL_PHASE"]}
with open(logp, "a") as f:
    f.write(json.dumps(line) + "\n")
PYEOF
}

cleanup() {
  [ -n "$CLEANED" ] && return 0
  CLEANED=1
  stop_server
  append_runlog
  rm -rf "$TMP"
}
trap cleanup EXIT INT TERM

# --- audit baseline, captured before the server (and its calls) start ----------
audit_before="$("$PY" interchange.py --audit 2>/dev/null || true)"
shadow_before="$(printf '%s' "$audit_before" | grep -oE 'shadow_cost=\$[0-9.]+' | grep -oE '[0-9.]+' | head -1)"
billed_before="$(printf '%s' "$audit_before" | grep -oE 'billed=\$[0-9.]+' | grep -oE '[0-9.]+' | head -1)"
[ -n "$shadow_before" ] || shadow_before=0
[ -n "$billed_before" ] || billed_before=0

# =============================================================================
PHASE="preconditions"
echo "== Preconditions"

# P1 — claude CLI present
if command -v claude >/dev/null 2>&1; then pass P1 "claude CLI on PATH"
else bad P1 "claude CLI not on PATH"; fi

# P2 — one cheap real call proves login + measured usage; capture modelUsage keys
if [ "$WB_ENGINE" = "stub" ]; then
  skip P2 "stub engine: no real claude -p login proof (WB_MODELS empty)"
  WB_MODELS=""
else
  HCWD="$("$PY" -c 'import interchange; print(interchange.headless_cwd())' 2>/dev/null)"
  ( cd "${HCWD:-.}" && claude -p "Reply with the single word OK" \
        --output-format json --setting-sources user ) >"$TMP/p2.json" 2>"$TMP/p2.err"
  if WB_MODELS="$("$PY" - "$TMP/p2.json" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("is_error") is False, "is_error is not false"
assert "usage" in d, "no usage key"
print(",".join((d.get("modelUsage") or {}).keys()))
PYEOF
)"; then
    pass P2 "claude -p login proof: JSON, is_error=false, usage present (models: ${WB_MODELS:-none})"
  else
    bad P2 "claude -p login proof failed (see $TMP/p2.json / $TMP/p2.err)"
    WB_MODELS=""
  fi
fi

# P3 — the edi corpus is indexed
if "$PY" -c "import interchange; assert interchange.index_meta('edi')['chunks']" 2>"$TMP/p3.err"; then
  pass P3 "edi index has chunks"
else
  bad P3 "edi index missing/empty (see $TMP/p3.err)"
fi

# P4 — the offline suite is green
if "$PY" -m pytest -q >"$TMP/pytest.log" 2>&1; then
  pass P4 "offline pytest suite green"
else
  bad P4 "pytest failed ($TMP/pytest.log)"
fi

# P5 — a bogus engine is a startup failure that names the allowed engines (F2)
if INTERCHANGE_ENGINE=bogus "$PY" -c "import app" 2>"$TMP/p5.err"; then
  bad P5 "import app with a bogus engine did NOT fail"
else
  if grep -q 'claude-code' "$TMP/p5.err" && grep -q 'stub' "$TMP/p5.err"; then
    pass P5 "bogus engine is a startup failure naming the allowed engines"
  else
    bad P5 "startup failed but stderr did not name the engines ($TMP/p5.err)"
  fi
fi

# P6 — start the one server on the target engine and wait for /health
PHASE="server-start"
INTERCHANGE_ENGINE="$WB_ENGINE" INTERCHANGE_MAX_CONCURRENT=1 INTERCHANGE_RATE_PER_MIN=60 \
  INTERCHANGE_CORPORA=edi,hotel \
  "$PY" -m uvicorn app:app --host 127.0.0.1 --port "$WB_PORT" --log-level warning \
    >"$TMP/server.log" 2>&1 &
SERVER_PID=$!
ready=0
for _ in $(seq 1 100); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then break; fi
  if "$PY" -c "
import sys, urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:${WB_PORT}/health', timeout=1).read()
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; then ready=1; break; fi
  sleep 0.3
done
if [ "$ready" -eq 1 ] && kill -0 "$SERVER_PID" 2>/dev/null; then
  pass P6 "server ready on 127.0.0.1:$WB_PORT (engine=$WB_ENGINE, pid $SERVER_PID)"
else
  bad P6 "server did not become ready on port $WB_PORT — first 40 server-log lines:"
  sed -n '1,40p' "$TMP/server.log" | sed 's/^/         /'
  echo
  echo "WORKBENCH ACCEPTANCE: FAILED"
  exit 1
fi

# =============================================================================
PHASE="http"
echo "== HTTP acceptance"
# The driver owns AC1–AC10 (per-frame arrival times, a socket closed AT a frame, a
# stream held open while a second request fires — none expressible in curl). It
# prints its own PASS/FAIL/SKIP lines and writes $TMP/summary.json; its exit status
# decides fail. Do not re-print its lines here.
if [ -f scripts/workbench_accept.py ]; then
  WB_PORT="$WB_PORT" WB_SERVER_PID="$SERVER_PID" WB_ENGINE="$WB_ENGINE" \
    WB_AUDIT=audit.jsonl WB_SUMMARY="$TMP/summary.json" WB_MODELS="$WB_MODELS" \
    "$PY" scripts/workbench_accept.py | tee "$TMP/driver.log"
  drc=${PIPESTATUS[0]}
  [ "$drc" -eq 0 ] || fail=1
else
  bad AC1 "scripts/workbench_accept.py not found — HTTP acceptance skipped"
fi

# =============================================================================
PHASE="cli"
echo "== CLI"
# AC11 — the CLI --explain trace is intact (7 box-prefixed lines, all five stages)
"$PY" interchange.py --engine stub --explain --ask "what is an 824?" 2>"$TMP/explain.err" >/dev/null
lc="$(awk 'END{print NR}' "$TMP/explain.err")"
prefixed="$(grep -Fc '  ┃ [explain] ' "$TMP/explain.err")"
if [ "${lc:-0}" -eq 7 ] && [ "${prefixed:-0}" -eq 7 ] \
   && has "$TMP/explain.err" 'stage 1/5' && has "$TMP/explain.err" 'stage 5/5' \
   && has "$TMP/explain.err" 'passed:' && has "$TMP/explain.err" 'audit:' \
   && has "$TMP/explain.err" 'engine=stub'; then
  pass AC11 "--explain: 7 lines all prefixed '  ┃ [explain] ', stages 1/5..5/5, passed/audit, engine=stub"
else
  bad AC11 "--explain output off (lines=$lc prefixed=$prefixed; see $TMP/explain.err)"
fi

# AC12 — billed unchanged (subscription), shadow grew (honest shadow cost)
audit_after="$("$PY" interchange.py --audit 2>/dev/null || true)"
shadow_after="$(printf '%s' "$audit_after" | grep -oE 'shadow_cost=\$[0-9.]+' | grep -oE '[0-9.]+' | head -1)"
billed_after="$(printf '%s' "$audit_after" | grep -oE 'billed=\$[0-9.]+' | grep -oE '[0-9.]+' | head -1)"
[ -n "$shadow_after" ] || shadow_after=0
[ -n "$billed_after" ] || billed_after=0
SHADOW_DELTA="$("$PY" -c "print(f'{float('$shadow_after')-float('$shadow_before'):.4f}')")"
BILLED_DELTA="$("$PY" -c "print(f'{float('$billed_after')-float('$billed_before'):.4f}')")"
if [ "$WB_ENGINE" = "stub" ]; then
  skip AC12 "stub engine: no real calls, shadow delta is 0 (billed delta=$BILLED_DELTA, shadow delta=$SHADOW_DELTA)"
else
  if [ "$BILLED_DELTA" = "0.0000" ] && "$PY" -c "import sys; sys.exit(0 if float('$SHADOW_DELTA')>0 else 1)"; then
    pass AC12 "billed delta $BILLED_DELTA (==0.0000), shadow delta $SHADOW_DELTA (>0)"
  else
    bad AC12 "billed delta $BILLED_DELTA / shadow delta $SHADOW_DELTA — expected 0.0000 and >0"
  fi
fi

# =============================================================================
PHASE="hygiene"
echo "== Hygiene"
stop_server   # the gate stops what it started BEFORE asserting nothing is left

# AC13a — the server pid is gone
if kill -0 "$SERVER_PID" 2>/dev/null; then bad AC13a "server pid $SERVER_PID still alive"
else pass AC13a "server pid $SERVER_PID stopped"; fi

# AC13b — nothing still listening on the port
if lsof -nP -iTCP:"$WB_PORT" -sTCP:LISTEN 2>/dev/null | grep -q .; then bad AC13b "port $WB_PORT still listening"
else pass AC13b "port $WB_PORT free"; fi

# AC13c — no orphaned child of the server (e.g. a leaked `claude`)
if pgrep -P "$SERVER_PID" >/dev/null 2>&1; then bad AC13c "child processes of $SERVER_PID remain"
else pass AC13c "no orphaned children of $SERVER_PID"; fi

# AC13d — tree clean except the committed result
dirty="$(git status --porcelain 2>/dev/null | grep -vE 'docs/workbench-RESULT\.md' || true)"
if [ -z "$dirty" ]; then pass AC13d "tree clean (docs/workbench-RESULT.md excepted)"
else bad AC13d "unexpected working-tree changes:"; printf '%s\n' "$dirty" | sed 's/^/         /'; fi

# AC13e — weak self-check: the gate has not been rewritten. Printed as NOTE, not a
# PASS/FAIL: the gate is NOT in protect-paths until a person adds it there.
BASE="$(git merge-base HEAD dev 2>/dev/null || echo "")"
if [ -n "$BASE" ] && git diff --quiet "$BASE" -- scripts/workbench-accept.sh scripts/workbench_accept.py 2>/dev/null; then
  note AC13e "gate files unchanged vs merge-base with dev"
else
  note AC13e "gate files differ from dev merge-base (expected on this feature branch); the gate is NOT yet protected — add scripts/workbench-accept.sh + scripts/workbench_accept.py to PROTECTED in .claude/hooks/protect-paths.sh"
fi

# AC13f — a run-log line is appended (append here so it is verifiable; the EXIT
# trap's append is then a guarded no-op)
before_lines="$( [ -f "$WB_LOG" ] && wc -l <"$WB_LOG" || echo 0 )"
append_runlog
after_lines="$( [ -f "$WB_LOG" ] && wc -l <"$WB_LOG" || echo 0 )"
if [ "${after_lines:-0}" -gt "${before_lines:-0}" ]; then pass AC13f "run-log line appended to $WB_LOG"
else bad AC13f "run-log line NOT appended to $WB_LOG"; fi

# =============================================================================
PHASE="done"
echo
if [ "$fail" -eq 0 ]; then
  echo "WORKBENCH ACCEPTANCE: ALL PASS"
  exit 0
else
  echo "WORKBENCH ACCEPTANCE: FAILED"
  exit 1
fi
