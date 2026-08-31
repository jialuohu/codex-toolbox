#!/usr/bin/env bash
set -euo pipefail

TOOLBOX_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIFY_SCRIPTS="$TOOLBOX_ROOT/plugins/diagram-tools/skills/archify/scripts"
ARCHIFY_CLI="$ARCHIFY_SCRIPTS/archify.mjs"
RUNTIME_MANAGER="$ARCHIFY_SCRIPTS/runtime-manager.mjs"
LOCAL_BIN_DIR="${CODEX_LOCAL_BIN_DIR:-$HOME/.local/bin}"
ARCHIFY_LAUNCHER="$LOCAL_BIN_DIR/archify"

usage() {
  cat <<'EOF'
Usage: scripts/setup-archify-tools.sh --check|--install|--rollback

  --check      Verify the active pinned runtime and owned launcher offline.
  --install    Download, verify, smoke-test, and atomically promote v2.16.0.
  --rollback   Validate and reactivate the previous runtime release.
EOF
}

fail() {
  echo "$*" >&2
  exit 3
}

if ! command -v node >/dev/null 2>&1; then
  fail "Archify setup requires Node.js 20 or newer"
fi

NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
if [ "$NODE_MAJOR" -lt 20 ]; then
  fail "Archify setup requires Node.js 20 or newer; found $(node --version)"
fi

launcher_preflight() {
  local existing_target=""
  if [ -e "$LOCAL_BIN_DIR" ] || [ -L "$LOCAL_BIN_DIR" ]; then
    if [ -L "$LOCAL_BIN_DIR" ] || [ ! -d "$LOCAL_BIN_DIR" ]; then
      fail "Archify launcher directory is unsafe: $LOCAL_BIN_DIR"
    fi
  fi
  if [ -e "$ARCHIFY_LAUNCHER" ] || [ -L "$ARCHIFY_LAUNCHER" ]; then
    if [ ! -L "$ARCHIFY_LAUNCHER" ]; then
      fail "Refusing to replace non-symlink launcher: $ARCHIFY_LAUNCHER"
    fi
    existing_target="$(readlink "$ARCHIFY_LAUNCHER")"
    case "$existing_target" in
      "$ARCHIFY_CLI"|*/plugins/diagram-tools/skills/archify/scripts/archify.mjs) ;;
      *) fail "Refusing to replace launcher not owned by diagram-tools: $ARCHIFY_LAUNCHER" ;;
    esac
  fi
}

check_launcher() {
  launcher_preflight
  if [ ! -L "$ARCHIFY_LAUNCHER" ] || [ "$(readlink "$ARCHIFY_LAUNCHER")" != "$ARCHIFY_CLI" ]; then
    fail "Archify launcher is not installed: $ARCHIFY_LAUNCHER"
  fi
}

install_launcher() {
  local temporary_launcher="$LOCAL_BIN_DIR/.archify.installing.$$"
  launcher_preflight
  mkdir -p "$LOCAL_BIN_DIR"
  if [ -e "$temporary_launcher" ] || [ -L "$temporary_launcher" ]; then
    fail "Temporary Archify launcher already exists: $temporary_launcher"
  fi
  ln -s "$ARCHIFY_CLI" "$temporary_launcher"
  launcher_preflight
  if ! mv -f -- "$temporary_launcher" "$ARCHIFY_LAUNCHER"; then
    rm -f -- "$temporary_launcher"
    fail "Unable to install Archify launcher: $ARCHIFY_LAUNCHER"
  fi
}

ACTION="${1:---check}"
shift || true
if [ "$#" -ne 0 ]; then
  usage >&2
  exit 2
fi

case "$ACTION" in
  --check)
    check_launcher
    exec node "$RUNTIME_MANAGER" check
    ;;
  --install)
    launcher_preflight
    node "$RUNTIME_MANAGER" install
    install_launcher
    exec node "$ARCHIFY_CLI" runtime-info --json
    ;;
  --rollback)
    launcher_preflight
    node "$RUNTIME_MANAGER" rollback
    install_launcher
    exec node "$ARCHIFY_CLI" runtime-info --json
    ;;
  --help|-h)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
