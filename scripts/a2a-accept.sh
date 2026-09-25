#!/usr/bin/env bash
# Goal A acceptance gate for the A2A demonstration. Copy to interchange-ai/scripts/a2a-accept.sh,
# commit it, and add it to the repo's protected paths BEFORE starting /goal so the run cannot
# edit its own gate. Runs AC1..AC12 offline at $0. Criteria (inline): preconditions
# (interchange answers, suite green, /health present, a2a-sdk 1.1.x installed and
# unshadowed); demo runs (hotel + rail each verify a signed card and cite a grounded
# answer as caller a2a:requester on the stub engine, no server left running); tests
# and scenarios (test_a2a.py green: tampered/unsigned/unknown-kid cards rejected,
# injection fails the task without calling the engine, missing API key -> 401,
# profile switch changes corpus, streaming WORKING->COMPLETED, MCP and A2A audit
# rows share keys, verifier pins ES256 and rejects a jku fetch); regression (full
# suite green, eval/baseline.json untouched); artifacts (ADR, lesson, profiles,
# orchestrate card, feature file, 3+ hotel pages, per-agent tier, README OWASP +
# MCP/A2A table); hygiene (only public keys tracked, no .env/audit.jsonl, clean tree,
# no removed tests or added skip/xfail).
# Exits 0 only when every line is PASS. Leaves no process running.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
PKG="${A2A_PKG:-a2a_agent}"
fail=0
pass() { printf 'PASS  %-5s %s\n' "$1" "$2"; }
bad()  { printf 'FAIL  %-5s %s\n' "$1" "$2"; fail=1; }
has()  { grep -qiE "$2" "$1" 2>/dev/null; }
tmo() { # portable timeout: macOS has no coreutils timeout by default
  local secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$secs" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$secs" "$@"
  else "$@" & local pid=$!; ( sleep "$secs"; kill "$pid" 2>/dev/null ) & local w=$!; wait "$pid"; local rc=$?; kill "$w" 2>/dev/null; return $rc; fi
}

BASE=$(git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null || echo "")

echo "== Preconditions"
$PY interchange.py --ask "What is an 824?" 2>/dev/null | grep -qi "824" && pass P1 "interchange answers" || bad P1 "interchange --ask failed"
$PY -m pytest -q -x --ignore=tests/test_a2a.py >/tmp/a2a_pre.log 2>&1 && pass P2 "existing suite green" || bad P2 "existing suite red (/tmp/a2a_pre.log)"
[ -f app.py ] && grep -q "health" app.py && pass P3 "app.py with /health present" || bad P3 "app.py or /health missing (scheduled 09-22)"
$PY -c "import importlib.metadata as m; v=m.version('a2a-sdk'); assert v.startswith('1.1.')" 2>/dev/null && pass P4a "a2a-sdk 1.1.x installed" || bad P4a "a2a-sdk 1.1.x missing"
$PY -c "import a2a,sys; sys.exit(0 if 'site-packages' in a2a.__file__ else 1)" 2>/dev/null && pass P4b "import a2a resolves to the SDK" || bad P4b "import a2a resolves to a repo folder: rename the local package"

echo "== Demo runs"
run_demo() { # $1 profile, $2 corpus keyword, $3 answer keyword
  local log=/tmp/a2a_demo_$1.log
  if tmo 240 make a2a-demo PROFILE="$1" >"$log" 2>&1; then
    has "$log" "verified" && has "$log" "kid=" && has "$log" "$3" && has "$log" "grounded[:= ]+true" \
      && has "$log" "caller.{0,4}a2a:requester" && has "$log" "engine.{0,4}stub" \
      && pass "AC-$1" "make a2a-demo PROFILE=$1: verified card, cited $2 answer, audit caller a2a:requester, stub engine" \
      || bad "AC-$1" "demo ran but output lacks one of: verified/kid=/$3/grounded true/caller a2a:requester/engine stub ($log)"
  else bad "AC-$1" "make a2a-demo PROFILE=$1 failed or timed out ($log)"; fi
}
run_demo hotel hotel "checkout"     # AC1
run_demo rail  edi   "997"          # AC2
pgrep -f "uvicorn app:app" >/dev/null && { bad AC3 "server left running"; pkill -f "uvicorn app:app"; } || pass AC3 "no stray server process"

echo "== Tests and scenarios"
$PY -m pytest -q tests/test_a2a.py >/tmp/a2a_tests.log 2>&1 && pass AC4 "tests/test_a2a.py green" || bad AC4 "tests/test_a2a.py red (/tmp/a2a_tests.log)"
T=tests/test_a2a.py; F=features/a2a_handoff.feature
scen() { { has "$T" "$2" || has "$F" "$2"; } && pass "AC5.$1" "$3" || bad "AC5.$1" "missing scenario: $3"; }
scen a "tamper" "tampered card rejected"
scen b "InvalidSignatures" "InvalidSignaturesError asserted"
scen c "unsigned|NoSignature" "unsigned card rejected (NoSignatureError)"
scen d "unknown.{0,10}kid" "unknown kid rejected"
scen e "inject" "injection over A2A yields failed task, engine never called"
scen f "401|missing.{0,10}api.?key" "missing API key returns 401"
scen g "profile" "profile switch changes corpus"
scen h "WORKING" "streaming yields WORKING then COMPLETED"
scen i "mcp" "MCP and A2A audit rows have identical keys"
grep -rqE 'algorithms=\["ES256"\]' "$PKG"/ 2>/dev/null && pass AC6a "verifier pins algorithms=[\"ES256\"]" || bad AC6a "algorithms not pinned to ES256 in $PKG/"
grep -rqiE 'jku' "$PKG"/keys.py 2>/dev/null && pass AC6b "key_provider handles jku (must raise)" || bad AC6b "no jku handling in $PKG/keys.py"

echo "== Regression"
$PY -m pytest -q >/tmp/a2a_full.log 2>&1 && pass AC7 "full suite green" || bad AC7 "full suite red (/tmp/a2a_full.log)"
if [ -n "$BASE" ]; then
  git diff --quiet "$BASE" -- eval/baseline.json && pass AC8 "eval/baseline.json untouched" || bad AC8 "eval/baseline.json changed"
else pass AC8 "no base branch (skipped)"; fi

echo "== Artifacts"
f() { [ -e "$2" ] && pass "AC9.$1" "$2" || bad "AC9.$1" "missing $2"; }
f a docs/adr/0013-a2a-agent-interop.md
f b lessons/07-a2a-handoff.md
f c "$PKG/profiles.yaml"
f d "$PKG/orchestrate/interchange-knowledge.yaml"
f e "$F"
[ "$(ls hotel-demo/*.md 2>/dev/null | wc -l | tr -d ' ')" -ge 3 ] && pass AC9.f "hotel-demo has 3+ pages" || bad AC9.f "hotel-demo needs 3 policy pages"
for a in interchange-knowledge requester; do has "agents/$a/instance.yaml" "^tier:" && pass "AC9.$a" "agents/$a/instance.yaml declares tier" || bad "AC9.$a" "agents/$a/instance.yaml missing or no tier:"; done
has README.md "ASI03" && has README.md "ASI07" && has README.md "\| *MCP" && has README.md "\| *A2A" && pass AC9.g "README: OWASP mapping + MCP vs A2A table" || bad AC9.g "README lacks ASI03/ASI07 or the MCP vs A2A table"
has "$PKG/profiles.yaml" "^ *rail:" && has "$PKG/profiles.yaml" "^ *hotel:" && pass AC9.h "profiles rail and hotel" || bad AC9.h "profiles.yaml lacks rail/hotel"

echo "== Hygiene"
git ls-files | grep -E '\.pem$' | grep -vqE '\.pub\.pem$' && bad AC10a "private key tracked in git" || pass AC10a "only public keys tracked"
git ls-files | grep -qE '(^|/)(\.env|audit\.jsonl)$' && bad AC10b ".env or audit.jsonl tracked" || pass AC10b "no .env / audit.jsonl tracked"
[ -z "$(git status --porcelain)" ] && pass AC10c "working tree clean" || bad AC10c "uncommitted changes"
if [ -n "$BASE" ]; then
  git diff "$BASE" -- tests/ eval/ features/ | grep -E '^-\s*(def test_|Scenario:)' >/dev/null && bad AC11a "a test or scenario was removed since base" || pass AC11a "no removed tests or scenarios"
  git diff "$BASE" -- tests/ | grep -E '^\+\s*@pytest\.mark\.(skip|xfail)' >/dev/null && bad AC11b "skip/xfail added since base" || pass AC11b "no skip/xfail added"
fi
$PY -c "import a2a,sys; sys.exit(0 if 'site-packages' in a2a.__file__ else 1)" 2>/dev/null && pass AC12 "SDK import still unshadowed" || bad AC12 "local package shadows a2a-sdk"

echo
[ "$fail" -eq 0 ] && { echo "A2A ACCEPTANCE: ALL PASS"; exit 0; } || { echo "A2A ACCEPTANCE: FAILED"; exit 1; }
