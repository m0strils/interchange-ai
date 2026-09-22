#!/usr/bin/env bash
# Detect test-side changes that make a red suite green without fixing code.
# Usage: weakened-tests.sh [base-ref]
#   default base: merge-base of HEAD with main or master; falls back to HEAD
#   (working tree vs HEAD) when no main branch exists.
# Prints one line per finding: file:line  PATTERN  <the changed line>
# Exit 0 = nothing found. Exit 1 = findings (advisory; the skill judges them).
# Exit 3 = not a git repo.

set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}" || exit 3
[ -z "$ROOT" ] && exit 3
cd "$ROOT" || exit 3

BASE="${1:-}"
if [ -z "$BASE" ]; then
  BASE=$(git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null || echo HEAD)
fi

# Test-side paths. Extend per repo with .claude/verify-test-paths (one glob per line).
PATHS=(tests test spec evals eval features fixtures golden __tests__ '*_test.*' '*.test.*' '*.spec.*' 'test_*.py' '*.feature' 'CERTIFICATE.md' 'pytest.ini' 'pyproject.toml' 'package.json' '.github/workflows')
if [ -f .claude/verify-test-paths ]; then
  while IFS= read -r p; do [ -n "$p" ] && PATHS+=("$p"); done < .claude/verify-test-paths
fi

# Diff of test-side files: committed since base, plus staged and unstaged.
DIFF=$( { git diff "$BASE" -- "${PATHS[@]}" 2>/dev/null; git diff --cached -- "${PATHS[@]}" 2>/dev/null; } )
[ -z "$DIFF" ] && { echo "weakened-tests: no test-side changes vs $BASE"; exit 0; }

found=0
file=""; line=0
emit() { printf '%s:%s  %-18s %s\n' "$file" "$line" "$1" "$2"; found=1; }

# Walk the unified diff tracking file and new-side line numbers.
while IFS= read -r raw; do
  case "$raw" in
    +++\ b/*) file="${raw#+++ b/}"; continue ;;
    +++\ *|---\ *) continue ;;
    @@*) line=$(printf '%s' "$raw" | sed -E 's/^@@ -[0-9,]+ \+([0-9]+).*/\1/'); line=$((line-1)); continue ;;
  esac
  case "$raw" in
    -*)
      l="${raw#-}"
      # Removed test definitions or scenarios
      printf '%s' "$l" | grep -qE '^\s*(def test_|async def test_|it\(|test\(|func Test[A-Z]|#\[test\]|Scenario( Outline)?:)' && emit REMOVED_TEST "$l"
      # Removed assertion lines
      printf '%s' "$l" | grep -qE '^\s*(assert\b|expect\(|self\.assert|t\.(Error|Fatal)|assert_eq!|assert!)' && emit REMOVED_ASSERT "$l"
      continue ;;
    +*)
      line=$((line+1)); l="${raw#+}"
      # Skips and expected failures
      printf '%s' "$l" | grep -qE '(@pytest\.mark\.(skip|xfail)|pytest\.skip\(|unittest\.skip|@skip\b|\bit\.skip\(|\bxit\(|\btest\.skip\(|\bdescribe\.skip\(|t\.Skip\(|#\[ignore\])' && emit SKIP_ADDED "$l"
      # Assertions weakened toward truthiness or containment
      printf '%s' "$l" | grep -qE '(toBeTruthy\(|toBeDefined\(|assertIsNotNone|is not None\s*$|assertTrue\(\s*\w+\s*\)|assertIn\(|\bin\s+str\()' && emit LOOSENED_ASSERT "$l"
      # Tolerances and thresholds
      printf '%s' "$l" | grep -qE '(approx\(|abs=|rel=|tolerance|delta=|toBeCloseTo|--cov-fail-under|fail_under|min_score|threshold|baseline|hit@k|>= *0\.[0-9])' && emit THRESHOLD_TOUCHED "$l"
      # Timeouts raised or retries added
      printf '%s' "$l" | grep -qE '(timeout\s*[=:]\s*[0-9]{3,}|retries?\s*[=:]\s*[2-9]|flaky|reruns)' && emit TIMEOUT_OR_RETRY "$l"
      # Gates mocked out
      printf '%s' "$l" | grep -qE '(mock\.patch|MagicMock\(|monkeypatch\.setattr|jest\.mock\(|vi\.mock\(|sinon\.stub)' && emit MOCK_ADDED "$l"
      # Assertions wrapped or made conditional
      printf '%s' "$l" | grep -qE '^\s*(try:|except\b.*:\s*(pass)?$|if .*(CI|env|os\.environ).*:)' && emit ASSERT_GUARDED "$l"
      # Certificate rounding (kit repos)
      printf '%s' "$l" | grep -qiE '(enforced:\s*true|status:\s*CERTIFIED)' && emit CERT_ROUNDED "$l"
      # Golden set edits without a human author line nearby is judged in the skill; flag the file
      case "$file" in *golden*|*fixtures*|*baseline*) emit GOLDEN_EDITED "$l" ;; esac
      continue ;;
    *) line=$((line+1)) ;;
  esac
done <<< "$DIFF"

if [ "$found" -eq 0 ]; then
  echo "weakened-tests: test-side changes vs $BASE, no suspicious patterns"
  exit 0
fi
echo "weakened-tests: findings above need a stated reason in the diff or commit message"
exit 1
