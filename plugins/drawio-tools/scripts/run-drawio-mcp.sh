#!/bin/sh
set -eu

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
RUNTIME_DIR="$CODEX_ROOT/runtime/drawio-tools/active"
LOCK_FILE="$PLUGIN_ROOT/runtime/bootstrap/package-lock.json"
VERIFY_SCRIPT="$PLUGIN_ROOT/scripts/verify-drawio-runtime.mjs"
NODE_BIN="$(command -v node || true)"

if [ -z "$NODE_BIN" ] && [ -n "${CODEX_LOCAL_BIN_DIR:-}" ] && [ -x "$CODEX_LOCAL_BIN_DIR/node" ]; then
  NODE_BIN="$CODEX_LOCAL_BIN_DIR/node"
fi

if [ -z "$NODE_BIN" ]; then
  printf '%s\n' "Node.js is unavailable; rerun the full codex-toolbox setup" >&2
  exit 127
fi

if ! "$NODE_BIN" "$VERIFY_SCRIPT" "$RUNTIME_DIR" "$LOCK_FILE" >/dev/null; then
  printf '%s\n' "Draw.io runtime is missing or invalid; rerun scripts/setup-drawio-tools.sh --install from the toolbox checkout" >&2
  exit 1
fi

# The verified local index must win. If it disappears after verification, fail
# closed instead of silently downloading a mutable index during MCP use.
export DRAWIO_SHAPE_INDEX_URL="https://invalid.invalid/drawio-tools-offline-index"
exec "$NODE_BIN" "$RUNTIME_DIR/node_modules/@drawio/mcp/src/index.js"
