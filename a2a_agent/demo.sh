#!/usr/bin/env bash
# One-command, offline, $0 two-agent A2A demo (ADR-0013).
#
#   make a2a-demo PROFILE=rail      # or PROFILE=hotel
#
# Starts the Interchange knowledge agent, then runs the `requester` agent
# against it: verify the signed Agent Card, hand over the profile's sample
# question as a task, stream the states, print the answer and the audit row.
#
# Key material: a *fresh clone has no private key* (it is never committed), so
# this script mints an ephemeral ES256 pair per run, signs with it, and pins the
# matching public key for the requester via A2A_PINNED_PUBLIC_KEY_PEM. The
# committed keys/*.pub.pem stays the pin for the deployed agent.
#
# Engine: `stub` — the point of the demo is the governed handoff, not the model,
# and it has to run at $0 with no network.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
PROFILE="${PROFILE:-rail}"
PORT="${A2A_DEMO_PORT:-8765}"

TMPDIR_DEMO="$(mktemp -d)"
SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$SERVER_PID" 2>/dev/null || break
      sleep 0.3
    done
    kill -9 "$SERVER_PID" 2>/dev/null
  fi
  wait "$SERVER_PID" 2>/dev/null
  rm -rf "$TMPDIR_DEMO"
}
trap cleanup EXIT INT TERM

# --- profile -> corpus -----------------------------------------------------
read -r COLLECTION DOCS <<EOF
$($PY -c "
from a2a_agent.profiles import load_profile
p = load_profile('$PROFILE')
print(p['collection'], p['docs_dir'])
")
EOF
if [ -z "${COLLECTION:-}" ]; then
  echo "demo: could not read profile '$PROFILE' from a2a_agent/profiles.yaml" >&2
  exit 1
fi
echo "profile: $PROFILE (collection=$COLLECTION docs=$DOCS)"

# --- ephemeral key pair (never written into the repo) ----------------------
$PY -c "
import pathlib, sys
from a2a_agent.keys import generate_keypair
priv, pub = generate_keypair()
d = pathlib.Path(sys.argv[1])
(d / 'signing.pem').write_text(priv); (d / 'signing.pub.pem').write_text(pub)
" "$TMPDIR_DEMO" || exit 1
chmod 600 "$TMPDIR_DEMO/signing.pem"

export A2A_SIGNING_KEY_PEM="$(cat "$TMPDIR_DEMO/signing.pem")"
export A2A_PINNED_PUBLIC_KEY_PEM="$(cat "$TMPDIR_DEMO/signing.pub.pem")"
export A2A_API_KEYS="demo-key:requester"
export A2A_PUBLIC_URL="http://127.0.0.1:${PORT}"
export INTERCHANGE_ENGINE=stub
export INTERCHANGE_COLLECTION="$COLLECTION"
export INTERCHANGE_DOCS_DIR="$DOCS"
export DEMO_PROFILE="$PROFILE"

# --- index the profile's corpus if it isn't there yet ----------------------
if ! $PY -c "
import chromadb, interchange
chromadb.PersistentClient(path=interchange.CHROMA_DIR).get_collection('$COLLECTION')
" >/dev/null 2>&1; then
  echo "index: building the '$COLLECTION' collection from $DOCS/ ..."
  $PY interchange.py --reindex || exit 1
fi

# --- start the knowledge agent --------------------------------------------
# The command line must contain "uvicorn app:app" — the acceptance gate greps
# for it to prove this script stops what it starts.
$PY -m uvicorn app:app --host 127.0.0.1 --port "$PORT" --log-level warning \
  >"$TMPDIR_DEMO/server.log" 2>&1 &
SERVER_PID=$!

ready=0
for _ in $(seq 1 100); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then break; fi
  if $PY -c "
import sys, urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:${PORT}/health', timeout=1).read()
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; then ready=1; break; fi
  sleep 0.3
done
if [ "$ready" -ne 1 ]; then
  echo "demo: server did not become ready on port $PORT" >&2
  sed -n '1,40p' "$TMPDIR_DEMO/server.log" >&2
  exit 1
fi
echo "agent: listening on http://127.0.0.1:${PORT} (engine=stub, \$0)"

# --- run the requester -----------------------------------------------------
$PY -m a2a_agent.requester \
  --url "http://127.0.0.1:${PORT}" \
  --profile "$PROFILE" \
  --api-key demo-key
exit $?
