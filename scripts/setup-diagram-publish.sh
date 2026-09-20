#!/usr/bin/env bash
# Launcher installation is local only. Runtime/account setup is a separate command.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$ROOT/plugins/diagram-tools/skills/diagram-publish/scripts/diagram_publish.py"
BIN_DIR="${CODEX_LOCAL_BIN_DIR:-$HOME/.local/bin}"
LAUNCHER="$BIN_DIR/diagram-publish"
ACTION="${1:---install-launcher}"
[ "$#" -le 1 ] || { echo 'Expected one setup action' >&2; exit 2; }
case "$ACTION" in
  --check) exec python3 "$CLI" status ;;
  --install-launcher)
    mkdir -p "$BIN_DIR"
    [ -d "$BIN_DIR" ] && [ ! -L "$BIN_DIR" ] || { echo 'Unsafe launcher directory' >&2; exit 1; }
    if [ -e "$LAUNCHER" ] || [ -L "$LAUNCHER" ]; then
      [ -L "$LAUNCHER" ] || { echo 'Refusing to replace unrelated launcher' >&2; exit 1; }
      case "$(readlink "$LAUNCHER")" in
        */plugins/diagram-tools/skills/diagram-publish/scripts/diagram_publish.py) ;;
        *) echo 'Refusing to replace unrelated launcher' >&2; exit 1 ;;
      esac
    fi
    TEMP_LAUNCHER="$BIN_DIR/.diagram-publish.installing.$$"
    trap 'rm -f -- "$TEMP_LAUNCHER"' EXIT
    ln -s "$CLI" "$TEMP_LAUNCHER"
    mv -f -- "$TEMP_LAUNCHER" "$LAUNCHER"
    exec python3 "$CLI" status
    ;;
  --help|-h) echo 'Usage: setup-diagram-publish.sh [--install-launcher|--check]' ;;
  *) echo 'Unknown setup action' >&2; exit 2 ;;
esac
