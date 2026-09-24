#!/usr/bin/env bash
#
# Install (or remove) the nightly reindex launchd agent for one corpus profile.
# ADR-0016 freshness sub-decision: one scheduled `--reindex` per profile, read-only
# against the corpus and $0 (local embeddings, no metered generation).
#
# Usage:
#   scripts/launchd/install.sh PROFILE            # install + load the agent
#   scripts/launchd/install.sh PROFILE --uninstall  # boot out + remove the agent
#
# Env (same knobs the engine reads, ADR-0016):
#   INTERCHANGE_CHROMA_DIR   index location   (default: $HOME/.interchange/chroma)
#   INTERCHANGE_PROFILES     overlay YAML     (default: $HOME/.interchange/profiles.yaml)
#
set -euo pipefail

PROFILE="${1:-}"
MODE="${2:-}"

if [[ -z "$PROFILE" ]]; then
    echo "usage: $(basename "$0") PROFILE [--uninstall]" >&2
    exit 2
fi

# Resolve the repo root from this script's own location (scripts/launchd/ -> repo).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"

CHROMA="${INTERCHANGE_CHROMA_DIR:-$HOME/.interchange/chroma}"
PROFILES="${INTERCHANGE_PROFILES:-$HOME/.interchange/profiles.yaml}"
LOG_DIR="$HOME/.interchange/logs"
LOG="$LOG_DIR/reindex-$PROFILE.log"

LABEL="ai.interchange.reindex-$PROFILE"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

if [[ "$MODE" == "--uninstall" ]]; then
    launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "uninstalled $LABEL (removed $PLIST)"
    exit 0
fi

mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"

TEMPLATE="$SCRIPT_DIR/ai.interchange.reindex.plist.example"
sed \
    -e "s|__REPO__|$REPO|g" \
    -e "s|__PROFILE__|$PROFILE|g" \
    -e "s|__CHROMA__|$CHROMA|g" \
    -e "s|__PROFILES__|$PROFILES|g" \
    -e "s|__LOG__|$LOG|g" \
    "$TEMPLATE" > "$PLIST"

plutil -lint "$PLIST"

launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST"

echo "installed $LABEL -> $PLIST"
echo "run it now: launchctl kickstart -k gui/$UID_NUM/$LABEL"
