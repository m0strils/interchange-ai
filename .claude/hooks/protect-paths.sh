#!/usr/bin/env bash
# PreToolUse hook on Edit|Write|MultiEdit|NotebookEdit: refuse edits to files the
# run must not change (its own acceptance gate, the eval baseline). Exit 2 blocks
# and the message goes back to Claude. Fail-open on unparseable input.
set -uo pipefail
INPUT=$(cat 2>/dev/null) || exit 0
[ -z "$INPUT" ] && exit 0
python3 - "$INPUT" <<'PY'
import json, os, sys
try:
    data = json.loads(sys.argv[1])
except Exception:
    sys.exit(0)
path = (data.get("tool_input") or {}).get("file_path") or ""
if not path:
    sys.exit(0)
root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
rel = os.path.relpath(os.path.abspath(path), root)
PROTECTED = ("scripts/a2a-accept.sh", "scripts/workbench-accept.sh", "scripts/workbench_accept.py", "eval/baseline.json", "eval/golden.jsonl", ".claude/verify-gate", ".claude/hooks/", ".claude/settings.json")
if any(rel == p or rel.startswith(p) for p in PROTECTED):
    print(f"protect-paths: {rel} is protected. Do not edit the gate, the baseline, or the hooks; stop and say why the change seems needed.", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
PY
