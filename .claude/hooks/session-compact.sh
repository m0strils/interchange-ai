#!/usr/bin/env bash
# SessionStart hook, matcher "compact": reprint working state after compaction.
#
# Plain text on stdout is added to context on SessionStart. Prints
# .claude/STATUS.md when it exists (keep it short: current item, today's
# shippable line, cut line), otherwise recent commits and dirty files.
# Never blocks; SessionStart ignores blocking anyway.

set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

echo "## State restored after compaction ($(date '+%Y-%m-%d %H:%M'))"

if [ -f "$ROOT/.claude/STATUS.md" ]; then
  echo
  cat "$ROOT/.claude/STATUS.md"
fi

if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo
  echo "Branch: $(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)"
  echo "Recent commits:"
  git -C "$ROOT" log --oneline -5 2>/dev/null | sed 's/^/  /'
  DIRTY=$(git -C "$ROOT" status --porcelain 2>/dev/null)
  if [ -n "$DIRTY" ]; then
    echo "Uncommitted changes:"
    printf '%s\n' "$DIRTY" | sed 's/^/  /'
  fi
fi

exit 0
