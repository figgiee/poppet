#!/usr/bin/env bash
# Install the Poppet Cascadeur-side command script (macOS / Linux).

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

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$REPO_ROOT/cascadeur_side/poppet"
DST_DIR="$COMMANDS_DIR/poppet"

if [[ ! -d "$SRC_DIR" ]]; then
    echo "Source not found: $SRC_DIR" >&2
    exit 1
fi

if [[ -d "$DST_DIR" ]]; then
    echo "Removing existing install at $DST_DIR"
    rm -rf "$DST_DIR"
fi

echo "Copying $SRC_DIR -> $DST_DIR"
cp -R "$SRC_DIR" "$DST_DIR"

cat <<'EOF'

[OK] Cascadeur-side install complete.

Next steps:
  1. Restart Cascadeur.
  2. Verify QTimer compat: Commands -> Poppet -> POC Tick Loop
     (viewport should stay responsive; re-run to stop)
  3. Start the real server: Commands -> Poppet -> Start Server
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
