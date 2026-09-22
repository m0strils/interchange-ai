#!/usr/bin/env bash
# The repo's gate. Shared by the verify-change skill and the Stop hook so both
# use one definition of "the tests". Exit code is the verdict.
#
# Detection order (first match wins). Override by setting VERIFY_GATE_CMD in
# the environment or in .claude/verify-gate (one line, the command to run).

set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$ROOT" || exit 1

if [ -n "${VERIFY_GATE_CMD:-}" ]; then
  echo "gate: \$VERIFY_GATE_CMD"; exec bash -c "$VERIFY_GATE_CMD"
fi
if [ -f .claude/verify-gate ]; then
  CMD=$(head -1 .claude/verify-gate)
  echo "gate: .claude/verify-gate -> $CMD"; exec bash -c "$CMD"
fi
if [ -x scripts/certify.sh ]; then
  echo "gate: scripts/certify.sh"; exec ./scripts/certify.sh
fi
if [ -f run_attacks.py ]; then
  echo "gate: python run_attacks.py"; exec python3 run_attacks.py
fi
if [ -f pytest.ini ] || [ -f pyproject.toml ] || ls tests/*.py >/dev/null 2>&1; then
  PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
  echo "gate: $PY -m pytest -q"; exec "$PY" -m pytest -q
fi
if [ -f package.json ] && grep -q '"test"' package.json; then
  echo "gate: npm test"; exec npm test --silent
fi
if [ -f go.mod ]; then
  echo "gate: go test ./..."; exec go test ./...
fi
if [ -f Cargo.toml ]; then
  echo "gate: cargo test"; exec cargo test --quiet
fi

echo "gate: no test command detected in $ROOT" >&2
echo "Create .claude/verify-gate with the command to run, or set VERIFY_GATE_CMD." >&2
exit 3
