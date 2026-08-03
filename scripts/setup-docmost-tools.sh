#!/usr/bin/env bash
# Bootstrap and check the isolated Docmost MCP runtime. It never prints secrets.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="${DOCMOST_SERVER_DIR:-$ROOT/plugins/docmost-tools/server}"
DOCMOST_CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
CODEX_SECRETS_DIR="${CODEX_SECRETS_DIR:-$DOCMOST_CODEX_ROOT/secrets}"
UV_PROJECT_ENVIRONMENT="$DOCMOST_CODEX_ROOT/runtime/docmost-tools"
export CODEX_SECRETS_DIR UV_PROJECT_ENVIRONMENT
RUNTIME_PARENT="$DOCMOST_CODEX_ROOT/runtime"
ENV_FILE="$CODEX_SECRETS_DIR/docmost.env"
PROFILE_DIR="$CODEX_SECRETS_DIR/docmost"
BROWSER_PROFILE_DIR="$PROFILE_DIR/browser-profile"
RUNTIME_STAMP="$UV_PROJECT_ENVIRONMENT/.docmost-tools-source.sha256"
AUTH_WRAPPER_SOURCE="$SERVER_DIR/scripts/docmost-auth"
RUNTIME_LOCK_SOURCE="$SERVER_DIR/src/docmost_tools/runtime_lock.py"
AUTH_WRAPPER="$UV_PROJECT_ENVIRONMENT/bin/docmost-auth"
RUNTIME_LOCK_HELPER="$UV_PROJECT_ENVIRONMENT/libexec/runtime_lock.py"
SMOKE_TOOL="$UV_PROJECT_ENVIRONMENT/bin/docmost-smoke"
LOGIN_COMMAND='CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" "$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login'
AUTH_REQUIRED_SENTENCE='Authentication required. Close the active task, run `CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" "$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login`, then start a fresh task or reconnect Docmost.'
AUTH_REQUIRED=3
readonly ROOT SERVER_DIR DOCMOST_CODEX_ROOT CODEX_SECRETS_DIR UV_PROJECT_ENVIRONMENT
readonly RUNTIME_PARENT ENV_FILE PROFILE_DIR BROWSER_PROFILE_DIR RUNTIME_STAMP
readonly AUTH_WRAPPER_SOURCE RUNTIME_LOCK_SOURCE AUTH_WRAPPER RUNTIME_LOCK_HELPER SMOKE_TOOL
readonly LOGIN_COMMAND AUTH_REQUIRED_SENTENCE AUTH_REQUIRED

usage() {
  cat >&2 <<'EOF'
Usage: scripts/setup-docmost-tools.sh --check|--install|--login|--status|--logout

--check    Check files and the locked Python runtime without changing anything.
--install  Create the private profile root and install locked Python/Chromium dependencies.
--login    Open the interactive browser login for the isolated Docmost profile.
--status   Run a bounded headless current-user and list-spaces smoke check.
--logout   Remove the isolated browser profile after confirmation from the auth CLI.
EOF
}

fail() {
  echo "$*" >&2
  exit 1
}

file_mode() {
  local mode
  if mode="$(stat -f '%Lp' "$1" 2>/dev/null)"; then
    printf '%s\n' "$mode"
    return 0
  fi
  stat -c '%a' "$1" 2>/dev/null
}

require_private_env() {
  [ -f "$ENV_FILE" ] || fail "Missing CODEX_SECRETS_DIR/docmost.env"
  [ ! -L "$ENV_FILE" ] || fail "docmost.env must not be a symlink"
  local mode
  mode="$(file_mode "$ENV_FILE")" || fail "Unable to inspect docmost.env permissions"
  [ "$mode" = "600" ] || fail "docmost.env must have mode 600"
}

ensure_private_profile_root() {
  [ ! -L "$PROFILE_DIR" ] || fail "Docmost profile directory must not be a symlink"
  if [ -e "$PROFILE_DIR" ] && [ ! -d "$PROFILE_DIR" ]; then
    fail "Docmost profile directory must be a directory"
  fi
  mkdir -p "$PROFILE_DIR"
  chmod 700 "$PROFILE_DIR"
  local mode
  mode="$(file_mode "$PROFILE_DIR")" || fail "Unable to inspect Docmost profile permissions"
  [ "$mode" = "700" ] || fail "Docmost profile directory must have mode 700"
}

require_private_browser_profile() {
  [ -d "$BROWSER_PROFILE_DIR" ] || fail "Docmost browser profile is missing; run --login"
  [ ! -L "$BROWSER_PROFILE_DIR" ] || fail "Docmost browser profile must not be a symlink"
  local mode
  mode="$(file_mode "$BROWSER_PROFILE_DIR")" || \
    fail "Unable to inspect Docmost browser profile permissions"
  [ "$mode" = "700" ] || fail "Docmost browser profile directory must have mode 700"
}

require_private_profile_root() {
  [ -d "$PROFILE_DIR" ] || fail "Docmost profile directory is missing; run --install"
  [ ! -L "$PROFILE_DIR" ] || fail "Docmost profile directory must not be a symlink"
  local mode
  mode="$(file_mode "$PROFILE_DIR")" || fail "Unable to inspect Docmost profile permissions"
  [ "$mode" = "700" ] || fail "Docmost profile directory must have mode 700"
}

resolve_uv() {
  local resolved
  resolved="$(command -v uv || true)"
  if [ -z "$resolved" ] && [ -n "${CODEX_LOCAL_BIN_DIR:-}" ] && \
    [ -x "$CODEX_LOCAL_BIN_DIR/uv" ]; then
    resolved="$CODEX_LOCAL_BIN_DIR/uv"
  fi
  [ -n "$resolved" ] || fail "uv not found; install uv and rerun --install"
  printf '%s\n' "$resolved"
}

load_docmost_env() {
  require_private_env
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

run_uv() {
  local uv
  uv="$(resolve_uv)"
  "$uv" "$@"
}

require_fresh_dependency_lock() {
  if ! run_uv lock --check --directory "$SERVER_DIR" >/dev/null 2>&1; then
    fail "Docmost dependency lock is stale; refresh and review server/uv.lock before setup"
  fi
}

ensure_runtime_root() {
  [ ! -L "$RUNTIME_PARENT" ] || fail "Docmost runtime parent must not be a symlink"
  if [ -e "$RUNTIME_PARENT" ] && [ ! -d "$RUNTIME_PARENT" ]; then
    fail "Docmost runtime parent must be a directory"
  fi
  mkdir -p "$RUNTIME_PARENT"
  [ ! -L "$UV_PROJECT_ENVIRONMENT" ] || fail "Docmost runtime directory must not be a symlink"
  if [ -e "$UV_PROJECT_ENVIRONMENT" ] && [ ! -d "$UV_PROJECT_ENVIRONMENT" ]; then
    fail "Docmost runtime directory must be a directory"
  fi
  mkdir -p "$UV_PROJECT_ENVIRONMENT"
  [ ! -L "$UV_PROJECT_ENVIRONMENT" ] || fail "Docmost runtime directory must not be a symlink"
}

require_runtime_root() {
  [ -d "$RUNTIME_PARENT" ] || \
    fail "Docmost runtime is missing; rerun the full codex-toolbox setup from its checkout"
  [ ! -L "$RUNTIME_PARENT" ] || fail "Docmost runtime parent must not be a symlink"
  [ -d "$UV_PROJECT_ENVIRONMENT" ] || \
    fail "Docmost runtime is missing; rerun the full codex-toolbox setup from its checkout"
  [ ! -L "$UV_PROJECT_ENVIRONMENT" ] || \
    fail "Docmost runtime directory must not be a symlink"
}

require_runtime_lock_source() {
  [ -f "$RUNTIME_LOCK_SOURCE" ] && [ ! -L "$RUNTIME_LOCK_SOURCE" ] || \
    fail "Docmost runtime lock helper is missing or unsafe"
}

validate_runtime_lock() {
  local expected_mode="$1"
  require_runtime_lock_source
  [ "${DOCMOST_RUNTIME_LOCK_MODE:-}" = "$expected_mode" ] || return 1
  python3 "$RUNTIME_LOCK_SOURCE" --validate-fd --mode "$expected_mode" \
    --root "$RUNTIME_PARENT"
}

run_locked() {
  local mode="$1"
  local hidden_command="$2"
  require_runtime_lock_source
  export DOCMOST_SERVER_DIR="$SERVER_DIR"
  exec python3 "$RUNTIME_LOCK_SOURCE" --mode "$mode" \
    --root "$RUNTIME_PARENT" -- \
    bash "$ROOT/scripts/setup-docmost-tools.sh" "$hidden_command"
}

require_current_runtime() {
  local stamp_tool="$UV_PROJECT_ENVIRONMENT/bin/docmost-runtime-stamp"
  [ -x "$stamp_tool" ] || \
    fail "Docmost runtime is missing; rerun the full codex-toolbox setup from its checkout"
  [ -x "$AUTH_WRAPPER" ] || \
    fail "Docmost auth runtime is missing; rerun the full codex-toolbox setup from its checkout"
  [ -f "$RUNTIME_LOCK_HELPER" ] && [ ! -L "$RUNTIME_LOCK_HELPER" ] || \
    fail "Docmost runtime lock helper is missing or unsafe; rerun the full codex-toolbox setup from its checkout"
  "$stamp_tool" check "$SERVER_DIR" "$RUNTIME_STAMP" >/dev/null 2>&1 || \
    fail "Docmost runtime is stale; rerun the full codex-toolbox setup from its checkout"
}

invalidate_runtime_stamp() {
  if [ -d "$RUNTIME_STAMP" ] && [ ! -L "$RUNTIME_STAMP" ]; then
    fail "Docmost runtime stamp must not be a directory"
  fi
  if [ -e "$RUNTIME_STAMP" ] || [ -L "$RUNTIME_STAMP" ]; then
    rm -f -- "$RUNTIME_STAMP"
  fi
}

install_runtime_support() {
  [ -f "$AUTH_WRAPPER_SOURCE" ] && [ ! -L "$AUTH_WRAPPER_SOURCE" ] || \
    fail "Docmost auth wrapper source is missing or unsafe"
  [ -f "$RUNTIME_LOCK_SOURCE" ] && [ ! -L "$RUNTIME_LOCK_SOURCE" ] || \
    fail "Docmost runtime lock helper source is missing or unsafe"
  [ -x "$UV_PROJECT_ENVIRONMENT/bin/docmost-auth-internal" ] || \
    fail "Docmost auth runtime is incomplete after sync"
  [ ! -L "$AUTH_WRAPPER" ] || fail "Docmost auth runtime path must not be a symlink"
  if [ -e "$UV_PROJECT_ENVIRONMENT/libexec" ]; then
    [ -d "$UV_PROJECT_ENVIRONMENT/libexec" ] && \
      [ ! -L "$UV_PROJECT_ENVIRONMENT/libexec" ] || \
      fail "Docmost runtime support directory is unsafe"
  else
    mkdir -m 755 "$UV_PROJECT_ENVIRONMENT/libexec"
  fi
  [ ! -L "$RUNTIME_LOCK_HELPER" ] || fail "Docmost runtime lock helper path must not be a symlink"
  local temporary_wrapper
  local temporary_lock_helper
  temporary_wrapper="$(mktemp "$AUTH_WRAPPER.installing.XXXXXX")"
  temporary_lock_helper="$(mktemp "$RUNTIME_LOCK_HELPER.installing.XXXXXX")"
  command install -m 755 "$AUTH_WRAPPER_SOURCE" "$temporary_wrapper"
  command install -m 644 "$RUNTIME_LOCK_SOURCE" "$temporary_lock_helper"
  mv -f -- "$temporary_wrapper" "$AUTH_WRAPPER"
  mv -f -- "$temporary_lock_helper" "$RUNTIME_LOCK_HELPER"
}

is_auth_required() {
  local output="$1"
  python3 -c '
import json
import sys
try:
    value = json.loads(sys.stdin.read())
except json.JSONDecodeError:
    raise SystemExit(1)
error = value.get("error") if isinstance(value, dict) else None
code = error.get("code") if isinstance(error, dict) else None
raise SystemExit(0 if isinstance(code, str) and code.casefold() == "auth_required" else 1)
' <<<"$output"
}

sanitized_status_code() {
  local output="$1"
  python3 -c '
import json
import sys
try:
    value = json.loads(sys.stdin.read())
except json.JSONDecodeError:
    raise SystemExit(1)
error = value.get("error") if isinstance(value, dict) else None
code = error.get("code") if isinstance(error, dict) else None
allowed = {"configuration_invalid", "profile_busy", "upstream_error", "internal_error"}
if isinstance(code, str) and code in allowed:
    print(code)
    raise SystemExit(0)
raise SystemExit(1)
' <<<"$output"
}

status() {
  validate_runtime_lock shared || fail "Docmost status requires the held shared runtime lock"
  require_private_env
  require_private_profile_root
  require_current_runtime
  if [ ! -d "$BROWSER_PROFILE_DIR" ]; then
    echo "Docmost status: $AUTH_REQUIRED_SENTENCE"
    return "$AUTH_REQUIRED"
  fi
  require_private_browser_profile
  load_docmost_env
  local output result
  set +e
  [ -x "$SMOKE_TOOL" ] || \
    fail "Docmost smoke runtime is missing; rerun the full codex-toolbox setup from its checkout"
  output="$("$SMOKE_TOOL")"
  result=$?
  set -e
  if [ "$result" -eq 0 ]; then
    echo "Docmost status: ready (current user and spaces)"
    return 0
  fi
  if is_auth_required "$output"; then
    echo "Docmost status: $AUTH_REQUIRED_SENTENCE"
    return "$AUTH_REQUIRED"
  fi
  local error_code
  error_code="$(sanitized_status_code "$output" || true)"
  case "$error_code" in
    profile_busy)
      echo "Docmost status failed: PROFILE_BUSY; close the other Docmost MCP/auth process, then run --status" >&2
      ;;
    configuration_invalid)
      echo "Docmost status failed: configuration_invalid; check docmost.env and profile permissions, then run --status" >&2
      ;;
    upstream_error)
      echo "Docmost status failed: upstream_error; check the Docmost URL, network, and CA bundle, then run --status" >&2
      ;;
    internal_error)
      echo "Docmost status failed: internal_error; rerun --check, then run --status" >&2
      ;;
    *)
      echo "Docmost status failed: unavailable; rerun --check or inspect the local Docmost service" >&2
      ;;
  esac
  return "$result"
}

check() {
  validate_runtime_lock shared || fail "Docmost check requires the held shared runtime lock"
  require_private_env
  require_private_profile_root
  require_private_browser_profile
  load_docmost_env
  [ -f "$SERVER_DIR/uv.lock" ] || fail "Docmost lock file is missing"
  require_fresh_dependency_lock
  if ! run_uv sync --frozen --check --no-dev --no-editable \
    --directory "$SERVER_DIR" >/dev/null 2>&1; then
    fail "Docmost runtime is stale or incomplete; rerun the full codex-toolbox setup from its checkout"
  fi
  require_current_runtime
  if ! run_uv run --frozen --no-sync --directory "$SERVER_DIR" python -c \
    'from docmost_tools.config import DocmostSettings; DocmostSettings.model_validate({})' \
    >/dev/null 2>&1; then
    fail "Docmost configuration is invalid"
  fi
  run_uv run --frozen --no-sync --directory "$SERVER_DIR" python -c '
from pathlib import Path
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    executable = Path(playwright.chromium.executable_path)
raise SystemExit(0 if executable.is_file() else "Docmost Chromium executable is missing; run --install")
' >/dev/null
  echo "Docmost runtime: ready"
}

install_locked() {
  validate_runtime_lock exclusive || \
    fail "Docmost runtime installation requires the held exclusive runtime lock"
  require_private_env
  ensure_private_profile_root
  [ -f "$SERVER_DIR/uv.lock" ] || fail "Docmost lock file is missing"
  [ -f "$SERVER_DIR/src/docmost_tools/runtime_stamp.py" ] || \
    fail "Docmost runtime fingerprint tool is missing"
  require_fresh_dependency_lock
  local expected_fingerprint
  expected_fingerprint="$(
    python3 "$SERVER_DIR/src/docmost_tools/runtime_stamp.py" fingerprint "$SERVER_DIR"
  )" || fail "Unable to fingerprint Docmost runtime source"
  case "$expected_fingerprint" in
    (*[!0-9a-f]*|'') fail "Unable to fingerprint Docmost runtime source" ;;
  esac
  [ "${#expected_fingerprint}" -eq 64 ] || fail "Unable to fingerprint Docmost runtime source"
  invalidate_runtime_stamp
  run_uv sync --frozen --no-dev --no-editable --reinstall-package docmost-tools \
    --directory "$SERVER_DIR"
  install_runtime_support
  run_uv run --frozen --no-sync --directory "$SERVER_DIR" playwright install chromium
  "$UV_PROJECT_ENVIRONMENT/bin/docmost-runtime-stamp" write \
    "$SERVER_DIR" "$RUNTIME_STAMP" --expected "$expected_fingerprint" || \
    fail "Docmost source changed during runtime installation; rerun --install"
  echo "Docmost runtime: installed"
}

install() {
  require_private_env
  ensure_private_profile_root
  ensure_runtime_root
  run_locked exclusive --install-locked
}

login() {
  validate_runtime_lock exclusive || fail "Docmost login requires the held exclusive runtime lock"
  require_private_env
  ensure_private_profile_root
  require_current_runtime
  "$AUTH_WRAPPER" login
}

logout() {
  validate_runtime_lock exclusive || fail "Docmost logout requires the held exclusive runtime lock"
  require_private_profile_root
  [ -x "$AUTH_WRAPPER" ] || \
    fail "Docmost auth runtime is missing; rerun the full codex-toolbox setup from its checkout"
  "$AUTH_WRAPPER" logout
}

[ "$#" -eq 1 ] || { usage; exit 2; }
case "$1" in
  --check) require_runtime_root; run_locked shared --check-locked ;;
  --install) install ;;
  --login) require_runtime_root; run_locked exclusive --login-locked ;;
  --status) require_runtime_root; run_locked shared --status-locked ;;
  --logout) require_runtime_root; run_locked exclusive --logout-locked ;;
  --check-locked) check ;;
  --install-locked) install_locked ;;
  --login-locked) login ;;
  --status-locked) status ;;
  --logout-locked) logout ;;
  *) usage; exit 2 ;;
esac
