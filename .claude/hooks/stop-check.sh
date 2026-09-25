#!/usr/bin/env bash
# Stop hook: refuse to end the turn while the repo's gate fails.
#
# Exit 0 = Claude may stop. Exit 2 = not done; stderr goes back to Claude.
# Reads stop_hook_active from the hook JSON and exits 0 when set, so a
# failing gate cannot loop the session forever.
#
# The gate is .claude/skills/verify-change/check.sh so the Stop hook and the
# verification skill share one definition of "the tests".

set -uo pipefail

INPUT=$(cat 2>/dev/null) || INPUT=""

# Loop guard. If this hook already blocked once this turn, let Claude stop and
# report the failure in words instead of running the gate again.
if printf '%s' "$INPUT" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
GATE="$ROOT/.claude/skills/verify-change/check.sh"

# No gate installed: nothing to enforce. Say so on stderr for the log, allow.
if [ ! -x "$GATE" ]; then
  echo "stop-check: no executable $GATE; turn allowed to end unverified" >&2
  exit 0
fi

# Nothing changed: no reason to run the gate.
if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git -C "$ROOT" diff --quiet && git -C "$ROOT" diff --cached --quiet \
     && [ -z "$(git -C "$ROOT" ls-files --others --exclude-standard)" ]; then
    exit 0
  fi
fi

OUT=$(cd "$ROOT" && "$GATE" 2>&1)
STATUS=$?

if [ "$STATUS" -ne 0 ]; then
  {
    echo "stop-check: the gate failed (exit $STATUS). The turn is not done."
    echo "Fix the failure or explain why it cannot be fixed. Last 40 lines:"
    printf '%s\n' "$OUT" | tail -40
  } >&2
  exit 2
fi

exit 0
