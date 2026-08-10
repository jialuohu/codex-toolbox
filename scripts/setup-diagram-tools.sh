#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_SCRIPTS="$ROOT/plugins/diagram-tools/skills/pretty-mermaid/scripts"
PRETTY_MERMAID_CLI="$SKILL_SCRIPTS/pretty-mermaid.mjs"
LOCAL_BIN_DIR="${CODEX_LOCAL_BIN_DIR:-$HOME/.local/bin}"
PRETTY_MERMAID_LAUNCHER="$LOCAL_BIN_DIR/pretty-mermaid"

usage() {
  cat <<'EOF'
Usage: scripts/setup-diagram-tools.sh --check|--update|--rollback [--strict]

  --check      Verify the active runtime without network access.
  --update     Stage, test, and promote the newest stable renderer.
  --rollback   Validate and activate the previous runtime release.
  --strict     Fail when the newest candidate is rejected, even if fallback works.
EOF
}

if ! command -v node >/dev/null 2>&1; then
  echo "Pretty Mermaid setup requires Node.js 20 or newer" >&2
  exit 3
fi

NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
if [ "$NODE_MAJOR" -lt 20 ]; then
  echo "Pretty Mermaid setup requires Node.js 20 or newer; found $(node --version)" >&2
  exit 3
fi

install_launcher() {
  local existing_target=""
  local temporary_launcher="$LOCAL_BIN_DIR/.pretty-mermaid.installing.$$"

  mkdir -p "$LOCAL_BIN_DIR"
  if [ -L "$LOCAL_BIN_DIR" ] || [ ! -d "$LOCAL_BIN_DIR" ]; then
    echo "Pretty Mermaid launcher directory is unsafe: $LOCAL_BIN_DIR" >&2
    return 1
  fi

  if [ -e "$PRETTY_MERMAID_LAUNCHER" ] || [ -L "$PRETTY_MERMAID_LAUNCHER" ]; then
    if [ ! -L "$PRETTY_MERMAID_LAUNCHER" ]; then
      echo "Refusing to replace non-symlink launcher: $PRETTY_MERMAID_LAUNCHER" >&2
      return 1
    fi
    existing_target="$(readlink "$PRETTY_MERMAID_LAUNCHER")"
    case "$existing_target" in
      */plugins/diagram-tools/skills/pretty-mermaid/scripts/pretty-mermaid.mjs) ;;
      *)
        echo "Refusing to replace launcher not owned by diagram-tools: $PRETTY_MERMAID_LAUNCHER" >&2
        return 1
        ;;
    esac
  fi

  if [ -e "$temporary_launcher" ] || [ -L "$temporary_launcher" ]; then
    echo "Temporary Pretty Mermaid launcher already exists: $temporary_launcher" >&2
    return 1
  fi
  ln -s "$PRETTY_MERMAID_CLI" "$temporary_launcher"
  if ! mv -f -- "$temporary_launcher" "$PRETTY_MERMAID_LAUNCHER"; then
    rm -f -- "$temporary_launcher"
    return 1
  fi
}

ACTION="${1:---check}"
shift || true

case "$ACTION" in
  --check)
    if [ "$#" -ne 0 ]; then usage >&2; exit 2; fi
    exec node "$SKILL_SCRIPTS/pretty-mermaid.mjs" doctor --json
    ;;
  --update)
    if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && [ "$1" != "--strict" ]; }; then
      usage >&2
      exit 2
    fi
    install_launcher
    if [ "$#" -eq 1 ]; then
      exec node "$SKILL_SCRIPTS/runtime-manager.mjs" update --strict
    fi
    exec node "$SKILL_SCRIPTS/runtime-manager.mjs" update
    ;;
  --rollback)
    if [ "$#" -ne 0 ]; then usage >&2; exit 2; fi
    exec node "$SKILL_SCRIPTS/runtime-manager.mjs" rollback
    ;;
  --help|-h)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
