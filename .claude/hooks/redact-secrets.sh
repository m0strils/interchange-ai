#!/usr/bin/env bash
# PreToolUse hook, matcher "Bash": redact secrets instead of blocking, and
# hand deploy verbs back to the human with "ask".
#
# Returns JSON on exit 0. Three outcomes:
#   - no secret, no deploy verb: no output, exit 0 (allow as-is)
#   - secret shape found: updatedInput with the secret replaced by a placeholder
#     (updatedInput replaces the WHOLE input, so every other field is echoed back)
#   - deploy verb found: permissionDecision "ask" (behaves as deny under dontAsk)
#
# Fail-open: anything unparseable exits 0 with no output.

set -uo pipefail
INPUT=$(cat 2>/dev/null) || exit 0
[ -z "$INPUT" ] && exit 0

python3 - "$INPUT" <<'PY'
import json, re, sys

raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    sys.exit(0)

tool_input = data.get("tool_input") or {}
cmd = tool_input.get("command")
if not isinstance(cmd, str):
    sys.exit(0)

# Secret shapes. Add to this list; never remove without a reason in git log.
SECRETS = [
    (r"sk-ant-[A-Za-z0-9_\-]{8,}", "<REDACTED_ANTHROPIC_KEY>"),
    (r"sk_live_[A-Za-z0-9]{8,}", "<REDACTED_LIVE_KEY>"),
    (r"sk-[A-Za-z0-9]{20,}", "<REDACTED_API_KEY>"),
    (r"AKIA[0-9A-Z]{16}", "<REDACTED_AWS_ACCESS_KEY>"),
    (r"(?i)(aws_secret_access_key\s*=\s*)[A-Za-z0-9/+=]{30,}", r"\1<REDACTED_AWS_SECRET>"),
    (r"(?i)(watsonx[_-]?api[_-]?key\s*=\s*)\S+", r"\1<REDACTED_WATSONX_KEY>"),
    (r"(?i)(fly_api_token\s*=\s*)\S+", r"\1<REDACTED_FLY_TOKEN>"),
    (r"(?i)(rnd_)[A-Za-z0-9]{20,}", r"\1<REDACTED_RENDER_KEY>"),
    (r"ghp_[A-Za-z0-9]{30,}", "<REDACTED_GITHUB_TOKEN>"),
]

# Deploy verbs: the human decides, once, interactively.
DEPLOY = [
    r"\bfly\s+deploy\b",
    r"\bflyctl\s+deploy\b",
    r"\brender\s+(deploy|services)\b",
    r"\bterraform\s+apply\b",
    r"\bcdk\s+deploy\b",
    r"\bsam\s+deploy\b",
    r"\bserverless\s+deploy\b",
    r"\bgit\s+push\b[^|;&]*(--force|-f)\b",
    r"\bkubectl\s+(apply|delete)\b",
    r"\baws\s+\S+\s+(create|delete|update|put)-",
]

def out(obj):
    sys.stdout.write(json.dumps(obj))
    sys.exit(0)

for pat in DEPLOY:
    if re.search(pat, cmd):
        out({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    "redact-secrets: deploy or destructive verb detected. "
                    "Confirm this command should run."
                ),
            }
        })

new_cmd = cmd
for pat, repl in SECRETS:
    new_cmd = re.sub(pat, repl, new_cmd)

if new_cmd != cmd:
    updated = dict(tool_input)          # echo back every field we did not change
    updated["command"] = new_cmd
    out({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "redact-secrets: secret-shaped value replaced with a placeholder.",
            "updatedInput": updated,
        }
    })

sys.exit(0)
PY
