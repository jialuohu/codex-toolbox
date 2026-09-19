#!/usr/bin/env bash
# Install only the reviewed parser dependency; --check is strictly offline.
set -euo pipefail

usage() {
  echo "Usage: scripts/setup-toolbox-health.sh --check|--install"
}

case "${1:---check}" in
  --check|--install) ACTION="${1:---check}" ;;
  --help|-h) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || { usage >&2; exit 2; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUIREMENTS="$ROOT/plugins/workflow-tools/skills/sync-toolbox/scripts/requirements.txt"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
RUNTIME_PARENT="$CODEX_ROOT/runtime"
RUNTIME="$RUNTIME_PARENT/toolbox-health"

fail() {
  echo "$*" >&2
  exit 1
}

[ -f "$REQUIREMENTS" ] && [ ! -L "$REQUIREMENTS" ] || \
  fail "Toolbox health parser requirements are missing or unsafe"
[ "$(cat "$REQUIREMENTS")" = "PyYAML==6.0.3" ] || \
  fail "Toolbox health parser requirements differ from the reviewed pin"

for directory in "$CODEX_ROOT" "$RUNTIME_PARENT" "$RUNTIME" "$RUNTIME/bin"; do
  [ ! -L "$directory" ] || fail "Toolbox health runtime directory is unsafe"
  if [ -e "$directory" ]; then
    [ -d "$directory" ] || fail "Toolbox health runtime directory is unsafe"
  fi
done

runtime_ready() {
  [ -x "$RUNTIME/bin/python" ] || return 1
  "$RUNTIME/bin/python" -I -c '
import sys
import importlib.metadata
import yaml
assert sys.version_info >= (3, 11)
assert importlib.metadata.version("PyYAML") == "6.0.3"
assert yaml.__version__ == "6.0.3"
assert yaml.safe_load("ready: true") == {"ready": True}
' >/dev/null 2>&1
}

if runtime_ready; then
  echo "Toolbox health parser runtime: ready"
  exit 0
fi
[ "$ACTION" = --install ] || \
  fail "Toolbox health parser runtime is missing or stale; run setup-toolbox-health.sh --install"

UV="$(command -v uv || true)"
if [ -z "$UV" ] && [ -n "${CODEX_LOCAL_BIN_DIR:-}" ] && [ -x "$CODEX_LOCAL_BIN_DIR/uv" ]; then
  UV="$CODEX_LOCAL_BIN_DIR/uv"
fi
[ -n "$UV" ] || fail "uv not found; install uv and rerun --install"
mkdir -p "$RUNTIME_PARENT"
if [ ! -x "$RUNTIME/bin/python" ]; then
  # Never clear an existing directory, including an interrupted installation.
  "$UV" venv --python 3.12 --allow-existing "$RUNTIME"
fi
"$UV" pip sync --python "$RUNTIME/bin/python" "$REQUIREMENTS"
runtime_ready || fail "Toolbox health parser runtime verification failed"
echo "Toolbox health parser runtime: installed"
