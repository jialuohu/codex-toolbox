#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/config/codex/AGENTS.global.md"
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
TARGET="$CODEX_DIR/AGENTS.md"
OVERRIDE="$CODEX_DIR/AGENTS.override.md"
MARKER_DIR="$CODEX_DIR/.codex-toolbox"
MARKER="$MARKER_DIR/agents-sync.env"

usage() {
  cat <<EOF
Usage: $(basename "$0") --check|--install

Sync the repo-managed global Codex instructions to:
  $TARGET
EOF
}

require_source() {
  if [ ! -f "$SOURCE" ]; then
    echo "Missing canonical AGENTS source: $SOURCE" >&2
    exit 1
  fi
}

warn_override() {
  if [ -f "$OVERRIDE" ]; then
    cat >&2 <<EOF
Warning: $OVERRIDE exists.
Codex reads AGENTS.override.md before AGENTS.md at the global scope, so this
managed AGENTS.md may not be the active global instruction file until the
override is removed.
EOF
  fi
}

check_agents() {
  require_source
  warn_override

  if [ ! -f "$TARGET" ]; then
    echo "AGENTS.md is not installed: $TARGET" >&2
    return 1
  fi

  if cmp -s "$SOURCE" "$TARGET"; then
    echo "AGENTS.md is in sync: $TARGET"
    return 0
  fi

  echo "AGENTS.md differs from canonical source: $TARGET" >&2
  echo "Run $(basename "$0") --install to update it." >&2
  return 1
}

install_agents() {
  local backup
  local installed_at
  local stamp

  require_source
  mkdir -p "$CODEX_DIR"
  warn_override

  if [ -f "$TARGET" ] && cmp -s "$SOURCE" "$TARGET"; then
    echo "AGENTS.md already in sync: $TARGET"
  else
    if [ -e "$TARGET" ]; then
      stamp="$(date -u +"%Y%m%dT%H%M%SZ")"
      backup="${TARGET}.backup-${stamp}-$$"
      cp -p "$TARGET" "$backup"
      echo "Backed up existing AGENTS.md to: $backup"
    fi

    cp "$SOURCE" "$TARGET"
    echo "Installed global AGENTS.md: $TARGET"
  fi

  mkdir -p "$MARKER_DIR"
  installed_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  {
    printf 'source=%s\n' "$SOURCE"
    printf 'target=%s\n' "$TARGET"
    printf 'installed_at=%s\n' "$installed_at"
  } >"$MARKER"
  echo "Wrote sync marker: $MARKER"
}

case "${1:-}" in
  --check)
    check_agents
    ;;
  --install)
    install_agents
    ;;
  -h | --help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
