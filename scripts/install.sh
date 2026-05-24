#!/usr/bin/env bash
# Install the Poppet Cascadeur-side command + event scripts (macOS / Linux).

set -euo pipefail

COMMANDS_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --commands-dir) COMMANDS_DIR="$2"; shift 2 ;;
        -h|--help) echo "usage: $0 [--commands-dir <path>]"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

find_commands_dir() {
    local candidates=()
    case "$(uname -s)" in
        Darwin)
            candidates+=(
                "/Applications/Cascadeur.app/Contents/MacOS/resources/scripts/python/commands"
                "/Applications/Cascadeur 2025.3.app/Contents/MacOS/resources/scripts/python/commands"
                "$HOME/Applications/Cascadeur.app/Contents/MacOS/resources/scripts/python/commands"
            )
            ;;
        Linux)
            candidates+=(
                "/opt/cascadeur/resources/scripts/python/commands"
                "/opt/Cascadeur/resources/scripts/python/commands"
                "$HOME/Cascadeur/resources/scripts/python/commands"
            )
            ;;
    esac
    for p in "${candidates[@]}"; do
        if [[ -d "$p" ]]; then
            echo "$p"
            return 0
        fi
    done
    return 1
}

if [[ -z "$COMMANDS_DIR" ]]; then
    if ! COMMANDS_DIR="$(find_commands_dir)"; then
        echo "Could not locate Cascadeur commands folder. Re-run with --commands-dir <path>." >&2
        exit 1
    fi
fi

echo "Detected commands folder: $COMMANDS_DIR"

# events/ is a sibling of commands/ inside resources/scripts/python.
EVENTS_DIR="$(dirname "$COMMANDS_DIR")/events"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$REPO_ROOT/cascadeur_side/poppet"
EVENTS_SRC_DIR="$REPO_ROOT/cascadeur_side/poppet_events"
DST_DIR="$COMMANDS_DIR/poppet"

if [[ ! -d "$SRC_DIR" ]]; then
    echo "Source not found: $SRC_DIR" >&2
    exit 1
fi
if [[ ! -d "$EVENTS_SRC_DIR" ]]; then
    echo "Events source not found: $EVENTS_SRC_DIR" >&2
    exit 1
fi

if [[ -d "$DST_DIR" ]]; then
    echo "Removing existing install at $DST_DIR"
    rm -rf "$DST_DIR"
fi

echo "Copying $SRC_DIR -> $DST_DIR"
cp -R "$SRC_DIR" "$DST_DIR"

# Merge event handlers into bundled events/ tree (subpackage-name addressed).
for evt in scene_activated scene_opened; do
    evt_src="$EVENTS_SRC_DIR/$evt/poppet_drain.py"
    if [[ ! -f "$evt_src" ]]; then
        echo "Skipping $evt (no handler)"
        continue
    fi
    evt_dst="$EVENTS_DIR/$evt/poppet_drain.py"
    mkdir -p "$(dirname "$evt_dst")"
    cp "$evt_src" "$evt_dst"
    echo "Installed event handler: $evt_dst"
done

cat <<'EOF'

[OK] Cascadeur-side install complete (commands + auto-drain events).

Next steps:
  1. Restart Cascadeur.
  2. Verify Commands menu: Commands -> Poppet -> Process Pending (manual drain)
  3. Auto-drain is now wired via scene_activated / scene_opened events —
     queued requests should run any time the Cascadeur window regains focus.
  4. (Once) Refresh the introspection schema: Commands -> Poppet -> Refresh Schema
  5. Wire up your MCP client:

     claude_desktop_config.json:
     {
       "mcpServers": {
         "poppet": { "command": "uvx", "args": ["poppet-mcp"] }
       }
     }

     Or Claude Code:
     claude mcp add poppet -- uvx poppet-mcp
EOF
