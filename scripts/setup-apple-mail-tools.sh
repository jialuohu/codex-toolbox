#!/usr/bin/env bash
# Install and inspect the isolated Apple Mail MCP runtime. It never prints mail content.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="${APPLE_MAIL_SERVER_DIR:-$ROOT/plugins/apple-mail-tools/server}"
APPLE_MAIL_CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
CODEX_SECRETS_DIR="${CODEX_SECRETS_DIR:-$APPLE_MAIL_CODEX_ROOT/secrets}"
STATE_ROOT="$CODEX_SECRETS_DIR/apple-mail-tools"
RUNTIME_PARENT="$APPLE_MAIL_CODEX_ROOT/runtime"
UV_PROJECT_ENVIRONMENT="$RUNTIME_PARENT/apple-mail-tools"
RUNTIME_STAMP="$UV_PROJECT_ENVIRONMENT/.apple-mail-tools-source.sha256"
LOCK_SOURCE="$SERVER_DIR/src/apple_mail_tools/runtime_lock.py"
LOCK_INSTALLED="$UV_PROJECT_ENVIRONMENT/libexec/runtime_lock.py"
export CODEX_SECRETS_DIR UV_PROJECT_ENVIRONMENT
readonly ROOT SERVER_DIR APPLE_MAIL_CODEX_ROOT CODEX_SECRETS_DIR STATE_ROOT
readonly RUNTIME_PARENT UV_PROJECT_ENVIRONMENT RUNTIME_STAMP LOCK_SOURCE LOCK_INSTALLED

usage() {
  cat >&2 <<'EOF'
Usage: scripts/setup-apple-mail-tools.sh --check|--install|--status|--init-config

--check        Validate source, locked runtime, private configuration, and runtime stamp.
--install      Create private state and install the exact locked Python 3.12 runtime.
--status       Run a bounded Mail/TCC health check without reading messages.
--init-config  Create missing private configuration and signing key without replacing either.
EOF
}

fail() {
  echo "$*" >&2
  exit 1
}

require_macos() {
  [ "$(uname -s)" = "Darwin" ] || fail "Apple Mail tools require macOS"
  [ -x /usr/bin/osascript ] || fail "AppleScript is unavailable"
  [ -d /System/Applications/Mail.app ] || fail "Mail.app is unavailable"
}

require_source() {
  [ -d "$SERVER_DIR" ] && [ ! -L "$SERVER_DIR" ] || fail "Apple Mail server source is unsafe"
  [ -f "$SERVER_DIR/pyproject.toml" ] || fail "Apple Mail pyproject.toml is missing"
  [ -f "$SERVER_DIR/uv.lock" ] || fail "Apple Mail uv.lock is missing"
  [ -f "$SERVER_DIR/scripts/mail_bridge.applescript" ] || fail "Apple Mail bridge is missing"
  [ -f "$LOCK_SOURCE" ] && [ ! -L "$LOCK_SOURCE" ] || fail "Apple Mail runtime lock helper is missing"
}

require_uv() {
  command -v uv >/dev/null 2>&1 || fail "uv is required for Apple Mail tools"
}

ensure_runtime_parent() {
  if [ -L "$RUNTIME_PARENT" ]; then
    fail "Apple Mail runtime parent must not be a symlink"
  fi
  if [ -e "$RUNTIME_PARENT" ] && [ ! -d "$RUNTIME_PARENT" ]; then
    fail "Apple Mail runtime parent is unsafe"
  fi
  mkdir -p "$RUNTIME_PARENT"
  chmod 755 "$RUNTIME_PARENT"
}

require_runtime_parent() {
  [ -d "$RUNTIME_PARENT" ] && [ ! -L "$RUNTIME_PARENT" ] || \
    fail "Apple Mail runtime is missing; run --install"
}

run_locked() {
  local mode="$1"
  local hidden_command="$2"
  python3 "$LOCK_SOURCE" --mode "$mode" --root "$RUNTIME_PARENT" -- \
    bash "$ROOT/scripts/setup-apple-mail-tools.sh" "$hidden_command"
}

validate_lock() {
  local mode="$1"
  python3 "$LOCK_SOURCE" --validate-fd --mode "$mode" --root "$RUNTIME_PARENT"
}

require_runtime() {
  [ -d "$UV_PROJECT_ENVIRONMENT" ] && [ ! -L "$UV_PROJECT_ENVIRONMENT" ] || \
    fail "Apple Mail runtime is missing; run --install"
  [ -x "$UV_PROJECT_ENVIRONMENT/bin/python" ] || fail "Apple Mail Python runtime is missing"
  [ -x "$UV_PROJECT_ENVIRONMENT/bin/apple-mail-mcp" ] || fail "Apple Mail MCP launcher is missing"
  [ -x "$UV_PROJECT_ENVIRONMENT/bin/apple-mail-runtime-stamp" ] || \
    fail "Apple Mail runtime stamp tool is missing"
  [ -f "$LOCK_INSTALLED" ] && [ ! -L "$LOCK_INSTALLED" ] || \
    fail "Apple Mail installed lock helper is missing"
}

install_locked() {
  validate_lock exclusive || fail "Apple Mail install requires its exclusive runtime lock"
  require_macos
  require_source
  require_uv
  local expected_fingerprint
  expected_fingerprint="$(python3 "$SERVER_DIR/src/apple_mail_tools/runtime_stamp.py" fingerprint "$SERVER_DIR")" || \
    fail "Unable to fingerprint Apple Mail source"
  case "$expected_fingerprint" in
    (*[!0-9a-f]*|'') fail "Unable to fingerprint Apple Mail source" ;;
  esac
  [ "${#expected_fingerprint}" -eq 64 ] || fail "Unable to fingerprint Apple Mail source"
  uv sync --python 3.12 --frozen --no-dev --no-editable --reinstall-package apple-mail-tools \
    --directory "$SERVER_DIR"
  [ -d "$UV_PROJECT_ENVIRONMENT/libexec" ] && [ ! -L "$UV_PROJECT_ENVIRONMENT/libexec" ] || \
    mkdir -m 755 "$UV_PROJECT_ENVIRONMENT/libexec"
  command install -m 644 "$LOCK_SOURCE" "$LOCK_INSTALLED"
  "$UV_PROJECT_ENVIRONMENT/bin/python" -c \
    'from apple_mail_tools.config import RuntimePaths; RuntimePaths.from_environment().ensure()'
  "$UV_PROJECT_ENVIRONMENT/bin/apple-mail-runtime-stamp" write \
    "$SERVER_DIR" "$RUNTIME_STAMP" --expected "$expected_fingerprint" || \
    fail "Apple Mail source changed during runtime installation"
  echo "Apple Mail runtime: installed"
}

install_runtime() {
  ensure_runtime_parent
  run_locked exclusive --install-locked
}

check_locked() {
  validate_lock shared || fail "Apple Mail check requires its shared runtime lock"
  require_macos
  require_source
  require_uv
  require_runtime
  uv sync --frozen --check --no-dev --no-editable --directory "$SERVER_DIR" >/dev/null 2>&1 || \
    fail "Apple Mail runtime is stale or incomplete; run --install"
  "$UV_PROJECT_ENVIRONMENT/bin/apple-mail-runtime-stamp" check \
    "$SERVER_DIR" "$RUNTIME_STAMP" >/dev/null || \
    fail "Apple Mail runtime source stamp is stale; run --install"
  "$UV_PROJECT_ENVIRONMENT/bin/python" -c '
from apple_mail_tools.config import RuntimePaths
paths = RuntimePaths.from_environment()
paths.ensure()
paths.load_settings()
' >/dev/null
  echo "Apple Mail runtime: ready"
}

check_runtime() {
  require_runtime_parent
  run_locked shared --check-locked
}

status_locked() {
  validate_lock shared || fail "Apple Mail status requires its shared runtime lock"
  require_runtime
  "$UV_PROJECT_ENVIRONMENT/bin/python" -c '
import json
import sys
from apple_mail_tools.models import AppleMailError
from apple_mail_tools.service import AppleMailService
try:
    output = AppleMailService().health_check()
except AppleMailError as error:
    print(f"Apple Mail status failed: {error.code.value}: {error.message}", file=sys.stderr)
    raise SystemExit(1)
print(json.dumps(output.data, sort_keys=True))
'
}

status_runtime() {
  require_runtime_parent
  run_locked shared --status-locked
}

init_config_locked() {
  validate_lock shared || fail "Apple Mail config initialization requires its shared runtime lock"
  require_runtime
  "$UV_PROJECT_ENVIRONMENT/bin/python" -c \
    'from apple_mail_tools.config import RuntimePaths; RuntimePaths.from_environment().ensure()'
  echo "Apple Mail private configuration: ready"
}

init_config() {
  require_runtime_parent
  run_locked shared --init-config-locked
}

[ "$#" -eq 1 ] || { usage; exit 2; }
case "$1" in
  --check) check_runtime ;;
  --install) install_runtime ;;
  --status) status_runtime ;;
  --init-config) init_config ;;
  --check-locked) check_locked ;;
  --install-locked) install_locked ;;
  --status-locked) status_locked ;;
  --init-config-locked) init_config_locked ;;
  *) usage; exit 2 ;;
esac
