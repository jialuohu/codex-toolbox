#!/usr/bin/env bash
# Bootstrap and check immutable Docmost MCP runtime generations. It never prints secrets.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="${DOCMOST_SERVER_DIR:-$ROOT/plugins/docmost-tools/server}"
DOCMOST_CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
CODEX_SECRETS_DIR="${CODEX_SECRETS_DIR:-$DOCMOST_CODEX_ROOT/secrets}"
RUNTIME_PARENT="$DOCMOST_CODEX_ROOT/runtime"
GENERATION_ROOT="$RUNTIME_PARENT/docmost-tools-generations"
GENERATION_ENVS="$GENERATION_ROOT/envs"
GENERATION_LOCKS="$GENERATION_ROOT/locks"
LEGACY_RUNTIME="$RUNTIME_PARENT/docmost-tools"
ENV_FILE="$CODEX_SECRETS_DIR/docmost.env"
PROFILE_DIR="$CODEX_SECRETS_DIR/docmost"
BROWSER_PROFILE_DIR="$PROFILE_DIR/browser-profile"
AUTH_WRAPPER_SOURCE="$SERVER_DIR/scripts/docmost-auth"
MCP_WRAPPER_SOURCE="$SERVER_DIR/scripts/docmost-mcp"
RUNTIME_LOCK_SOURCE="$SERVER_DIR/src/docmost_tools/runtime_lock.py"
RUNTIME_STAMP_SOURCE="$SERVER_DIR/src/docmost_tools/runtime_stamp.py"
SYSTEM_PYTHON="$(command -v python3 || true)"
LOGIN_COMMAND='CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" "$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login'
AUTH_REQUIRED_SENTENCE='Authentication required. Close the active task, run `CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" "$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login`, then start a fresh task or reconnect Docmost.'
AUTH_REQUIRED=3
BUSY_EXIT=75
export CODEX_SECRETS_DIR DOCMOST_SERVER_DIR
readonly ROOT SERVER_DIR DOCMOST_CODEX_ROOT CODEX_SECRETS_DIR
readonly RUNTIME_PARENT GENERATION_ROOT GENERATION_ENVS GENERATION_LOCKS LEGACY_RUNTIME
readonly ENV_FILE PROFILE_DIR BROWSER_PROFILE_DIR AUTH_WRAPPER_SOURCE MCP_WRAPPER_SOURCE
readonly RUNTIME_LOCK_SOURCE RUNTIME_STAMP_SOURCE SYSTEM_PYTHON
readonly LOGIN_COMMAND AUTH_REQUIRED_SENTENCE AUTH_REQUIRED BUSY_EXIT

usage() {
  cat >&2 <<'EOF'
Usage: scripts/setup-docmost-tools.sh --check|--install|--login|--status|--logout|--prune

--check    Check files and the matching locked Python runtime without changing anything.
--install  Create the private profile root and install the matching immutable runtime.
--login    Open the interactive browser login for the isolated Docmost profile.
--status   Run a bounded headless current-user and list-spaces read check.
--logout   Remove the isolated browser profile after confirmation from the auth CLI.
--prune    Remove only unlocked runtime generations that no installed plugin references.
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

require_source_inputs() {
  [ -n "$SYSTEM_PYTHON" ] || fail "python3 not found; install Python and rerun --install"
  [ -d "$SERVER_DIR" ] && [ ! -L "$SERVER_DIR" ] || \
    fail "Docmost server source is missing or unsafe"
  for source in \
    "$SERVER_DIR/pyproject.toml" \
    "$SERVER_DIR/uv.lock" \
    "$AUTH_WRAPPER_SOURCE" \
    "$MCP_WRAPPER_SOURCE" \
    "$RUNTIME_LOCK_SOURCE" \
    "$RUNTIME_STAMP_SOURCE"
  do
    [ -f "$source" ] && [ ! -L "$source" ] || \
      fail "Docmost runtime source inputs are missing or unsafe"
  done
}

source_fingerprint_for() {
  local source_dir="$1"
  local value
  value="$("$SYSTEM_PYTHON" "$RUNTIME_STAMP_SOURCE" fingerprint "$source_dir")" || return 1
  case "$value" in
    (*[!0-9a-f]*|'') return 1 ;;
  esac
  [ "${#value}" -eq 64 ] || return 1
  printf '%s\n' "$value"
}

source_fingerprint() {
  local value
  value="$(source_fingerprint_for "$SERVER_DIR")" || fail "Unable to fingerprint Docmost runtime source"
  printf '%s\n' "$value"
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

ensure_directory() {
  local path="$1"
  local message="$2"
  [ ! -L "$path" ] || fail "$message"
  if [ -e "$path" ] && [ ! -d "$path" ]; then
    fail "$message"
  fi
  mkdir -p "$path"
  [ -d "$path" ] && [ ! -L "$path" ] || fail "$message"
}

ensure_runtime_roots() {
  ensure_directory "$RUNTIME_PARENT" "Docmost runtime parent must be a safe directory"
  ensure_directory "$GENERATION_ROOT" "Docmost generation root must be a safe directory"
  ensure_directory "$GENERATION_ENVS" "Docmost generation environments must be a safe directory"
  ensure_directory "$GENERATION_LOCKS" "Docmost generation locks must be a safe directory"
}

require_runtime_roots() {
  [ -d "$RUNTIME_PARENT" ] && [ ! -L "$RUNTIME_PARENT" ] || \
    fail "Docmost runtime is missing; rerun the full codex-toolbox setup from its checkout"
  [ -d "$GENERATION_ROOT" ] && [ ! -L "$GENERATION_ROOT" ] || \
    fail "Docmost generation root is missing or unsafe; rerun --install"
  [ -d "$GENERATION_ENVS" ] && [ ! -L "$GENERATION_ENVS" ] || \
    fail "Docmost generation environments are missing or unsafe; rerun --install"
  [ -d "$GENERATION_LOCKS" ] && [ ! -L "$GENERATION_LOCKS" ] || \
    fail "Docmost generation locks are missing or unsafe; rerun --install"
}

validate_lock() {
  local kind="$1"
  local mode="$2"
  shift 2
  "$SYSTEM_PYTHON" "$RUNTIME_LOCK_SOURCE" --validate-fd \
    --kind "$kind" --mode "$mode" "$@"
}

run_setup_locked() {
  local hidden_command="$1"
  exec "$SYSTEM_PYTHON" "$RUNTIME_LOCK_SOURCE" \
    --kind setup --mode exclusive --root "$GENERATION_ROOT" -- \
    /bin/bash "$ROOT/scripts/setup-docmost-tools.sh" "$hidden_command"
}

run_generation_locked() {
  local mode="$1"
  local hidden_command="$2"
  shift 2
  exec "$SYSTEM_PYTHON" "$RUNTIME_LOCK_SOURCE" \
    --kind generation --mode "$mode" --root "$GENERATION_ROOT" \
    --generation "$FINGERPRINT" -- \
    /bin/bash "$ROOT/scripts/setup-docmost-tools.sh" "$hidden_command" "$@"
}

run_session_generation_locked() {
  local session_mode="$1"
  local hidden_command="$2"
  exec "$SYSTEM_PYTHON" "$RUNTIME_LOCK_SOURCE" \
    --kind session --mode "$session_mode" --root "$RUNTIME_PARENT" -- \
    "$SYSTEM_PYTHON" "$RUNTIME_LOCK_SOURCE" \
      --kind generation --mode shared --root "$GENERATION_ROOT" \
      --generation "$FINGERPRINT" -- \
      /bin/bash "$ROOT/scripts/setup-docmost-tools.sh" "$hidden_command"
}

require_generation_path() {
  case "$GENERATION_RUNTIME" in
    ("$GENERATION_ENVS/$FINGERPRINT") ;;
    (*) fail "Docmost runtime generation path is invalid" ;;
  esac
  [ ! -L "$GENERATION_RUNTIME" ] || fail "Docmost runtime generation must not be a symlink"
}

generation_is_current() {
  require_generation_path
  [ -d "$GENERATION_RUNTIME" ] || return 1
  "$SYSTEM_PYTHON" "$RUNTIME_STAMP_SOURCE" \
    check "$SERVER_DIR" "$RUNTIME_STAMP" >/dev/null 2>&1 || return 1
  [ -x "$GENERATION_RUNTIME/bin/docmost-mcp" ] && \
    [ ! -L "$GENERATION_RUNTIME/bin/docmost-mcp" ] || return 1
  [ -x "$GENERATION_RUNTIME/bin/docmost-auth-internal" ] && \
    [ ! -L "$GENERATION_RUNTIME/bin/docmost-auth-internal" ] || return 1
  [ -x "$GENERATION_RUNTIME/bin/docmost-runtime-lock" ] && \
    [ ! -L "$GENERATION_RUNTIME/bin/docmost-runtime-lock" ] || return 1
  [ -x "$GENERATION_RUNTIME/bin/docmost-smoke" ] && \
    [ ! -L "$GENERATION_RUNTIME/bin/docmost-smoke" ] || return 1
  [ -x "$AUTH_WRAPPER" ] && [ ! -L "$AUTH_WRAPPER" ] || return 1
}

require_current_runtime() {
  generation_is_current || \
    fail "Docmost runtime is stale; rerun the full codex-toolbox setup from its checkout"
}

install_runtime_support() {
  [ -x "$GENERATION_RUNTIME/bin/docmost-auth-internal" ] && \
    [ ! -L "$GENERATION_RUNTIME/bin/docmost-auth-internal" ] || \
    fail "Docmost auth runtime is incomplete after sync"
  [ ! -L "$AUTH_WRAPPER" ] || fail "Docmost auth runtime path must not be a symlink"
  local temporary_wrapper
  temporary_wrapper="$(mktemp "$AUTH_WRAPPER.installing.XXXXXX")"
  command install -m 755 "$AUTH_WRAPPER_SOURCE" "$temporary_wrapper"
  mv -f -- "$temporary_wrapper" "$AUTH_WRAPPER"
}

install_chromium() {
  [ -x "$GENERATION_RUNTIME/bin/python" ] || \
    fail "Docmost Python runtime is incomplete after sync"
  "$GENERATION_RUNTIME/bin/python" -m playwright install chromium
}

is_auth_required() {
  local output="$1"
  "$SYSTEM_PYTHON" -c '
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
  "$SYSTEM_PYTHON" -c '
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

install_generation_locked() {
  validate_lock setup exclusive --root "$GENERATION_ROOT" || \
    fail "Docmost runtime installation requires the held setup lock"
  validate_lock generation exclusive --root "$GENERATION_ROOT" \
    --generation "$FINGERPRINT" || \
    fail "Docmost runtime installation requires the held exclusive generation lock"
  require_private_env
  ensure_private_profile_root
  require_fresh_dependency_lock
  require_generation_path
  if [ -e "$GENERATION_RUNTIME" ]; then
    [ -d "$GENERATION_RUNTIME" ] && [ ! -L "$GENERATION_RUNTIME" ] || \
      fail "Docmost runtime generation is unsafe"
    rm -rf -- "$GENERATION_RUNTIME"
  fi
  mkdir -p "$GENERATION_RUNTIME"
  rm -f -- "$RUNTIME_STAMP"
  UV_PROJECT_ENVIRONMENT="$GENERATION_RUNTIME" run_uv sync \
    --frozen --no-dev --no-editable --reinstall-package docmost-tools \
    --directory "$SERVER_DIR"
  install_runtime_support
  install_chromium
  "$SYSTEM_PYTHON" "$RUNTIME_STAMP_SOURCE" write \
    "$SERVER_DIR" "$RUNTIME_STAMP" --expected "$FINGERPRINT" || \
    fail "Docmost source changed during runtime installation; rerun --install"
  echo "Docmost runtime generation: installed"
}

install_setup_locked() {
  validate_lock setup exclusive --root "$GENERATION_ROOT" || \
    fail "Docmost runtime installation requires the held setup lock"
  require_private_env
  ensure_private_profile_root
  require_fresh_dependency_lock
  if generation_is_current; then
    install_chromium
    echo "Docmost runtime generation: ready"
    return 0
  fi
  run_generation_locked exclusive --install-generation-locked
}

check_locked() {
  validate_lock generation shared --root "$GENERATION_ROOT" \
    --generation "$FINGERPRINT" || \
    fail "Docmost check requires the held shared generation lock"
  require_private_env
  require_private_profile_root
  require_private_browser_profile
  require_fresh_dependency_lock
  require_current_runtime
  load_docmost_env
  unset PYTHONPATH VIRTUAL_ENV
  if ! "$GENERATION_RUNTIME/bin/python" -c \
    'from docmost_tools.config import DocmostSettings; DocmostSettings.model_validate({})' \
    >/dev/null 2>&1; then
    fail "Docmost configuration is invalid"
  fi
  "$GENERATION_RUNTIME/bin/python" -c '
from pathlib import Path
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    executable = Path(playwright.chromium.executable_path)
raise SystemExit(0 if executable.is_file() else "Docmost Chromium executable is missing; run --install")
' >/dev/null
  echo "Docmost runtime: ready"
}

status_locked() {
  validate_lock session shared --root "$RUNTIME_PARENT" || \
    fail "Docmost status requires the held shared session lock"
  validate_lock generation shared --root "$GENERATION_ROOT" \
    --generation "$FINGERPRINT" || \
    fail "Docmost status requires the held shared generation lock"
  require_private_env
  require_private_profile_root
  require_current_runtime
  if [ ! -d "$BROWSER_PROFILE_DIR" ]; then
    echo "Docmost status: $AUTH_REQUIRED_SENTENCE"
    return "$AUTH_REQUIRED"
  fi
  require_private_browser_profile
  load_docmost_env
  unset PYTHONPATH VIRTUAL_ENV
  local output result
  set +e
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
      echo "Docmost status failed: PROFILE_BUSY; close the other Docmost auth process, then run --status" >&2
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

login_locked() {
  validate_lock session exclusive --root "$RUNTIME_PARENT" || \
    fail "Docmost login requires the held exclusive session lock"
  validate_lock generation shared --root "$GENERATION_ROOT" \
    --generation "$FINGERPRINT" || \
    fail "Docmost login requires the held shared generation lock"
  require_private_env
  ensure_private_profile_root
  require_current_runtime
  "$AUTH_WRAPPER" login
}

logout_locked() {
  validate_lock session exclusive --root "$RUNTIME_PARENT" || \
    fail "Docmost logout requires the held exclusive session lock"
  validate_lock generation shared --root "$GENERATION_ROOT" \
    --generation "$FINGERPRINT" || \
    fail "Docmost logout requires the held shared generation lock"
  require_private_profile_root
  require_current_runtime
  "$AUTH_WRAPPER" logout
}

protected_generation_ids() {
  printf '%s\n' "$FINGERPRINT"
  local candidate_server candidate_fingerprint
  for candidate_server in "$DOCMOST_CODEX_ROOT"/plugins/cache/*/docmost-tools/*/server; do
    [ -d "$candidate_server" ] && [ ! -L "$candidate_server" ] || continue
    candidate_fingerprint="$(source_fingerprint_for "$candidate_server" || true)"
    [ -n "$candidate_fingerprint" ] && printf '%s\n' "$candidate_fingerprint"
  done
}

generation_is_protected() {
  local generation="$1"
  local protected
  while IFS= read -r protected; do
    [ "$protected" = "$generation" ] && return 0
  done < <(protected_generation_ids)
  return 1
}

prune_generation_locked() {
  local generation="$1"
  validate_lock setup exclusive --root "$GENERATION_ROOT" || \
    fail "Docmost prune requires the held setup lock"
  validate_lock generation exclusive --root "$GENERATION_ROOT" \
    --generation "$generation" || \
    fail "Docmost prune requires the held exclusive generation lock"
  [ "$generation" != "$FINGERPRINT" ] || fail "Docmost current runtime generation is protected"
  if generation_is_protected "$generation"; then
    fail "Docmost installed runtime generation is protected"
  fi
  local target="$GENERATION_ENVS/$generation"
  case "$generation" in
    (*[!0-9a-f]*|'') fail "Docmost prune generation is invalid" ;;
  esac
  [ "${#generation}" -eq 64 ] || fail "Docmost prune generation is invalid"
  case "$target" in
    ("$GENERATION_ENVS/$generation") ;;
    (*) fail "Docmost prune target is invalid" ;;
  esac
  if [ -e "$target" ]; then
    [ -d "$target" ] && [ ! -L "$target" ] || fail "Docmost prune target is unsafe"
    rm -rf -- "$target"
  fi
  echo "removed"
}

prune_setup_locked() {
  validate_lock setup exclusive --root "$GENERATION_ROOT" || \
    fail "Docmost prune requires the held setup lock"
  local candidate generation result prune_status removed=0 busy=0 unsafe=0
  shopt -s nullglob
  for candidate in "$GENERATION_ENVS"/*; do
    if [ ! -d "$candidate" ] || [ -L "$candidate" ]; then
      unsafe=$((unsafe + 1))
      continue
    fi
    generation="$(basename "$candidate")"
    case "$generation" in
      (*[!0-9a-f]*|'') unsafe=$((unsafe + 1)); continue ;;
    esac
    if [ "${#generation}" -ne 64 ]; then
      unsafe=$((unsafe + 1))
      continue
    fi
    if generation_is_protected "$generation"; then
      continue
    fi
    set +e
    result="$("$SYSTEM_PYTHON" "$RUNTIME_LOCK_SOURCE" \
      --kind generation --mode exclusive --root "$GENERATION_ROOT" \
      --generation "$generation" -- \
      /bin/bash "$ROOT/scripts/setup-docmost-tools.sh" \
        --prune-generation-locked "$generation" 2>/dev/null)"
    prune_status=$?
    set -e
    if [ "$prune_status" -eq 0 ] && [ "$result" = "removed" ]; then
      removed=$((removed + 1))
    elif [ "$prune_status" -eq "$BUSY_EXIT" ]; then
      busy=$((busy + 1))
    else
      unsafe=$((unsafe + 1))
    fi
  done
  echo "Docmost runtime generations: pruned=$removed busy=$busy unsafe=$unsafe legacy_retained=$([ -d "$LEGACY_RUNTIME" ] && echo 1 || echo 0)"
  [ "$unsafe" -eq 0 ] || return 1
  [ "$busy" -eq 0 ] || return "$BUSY_EXIT"
}

require_source_inputs
FINGERPRINT="$(source_fingerprint)"
GENERATION_RUNTIME="$GENERATION_ENVS/$FINGERPRINT"
RUNTIME_STAMP="$GENERATION_RUNTIME/.docmost-tools-source.sha256"
AUTH_WRAPPER="$GENERATION_RUNTIME/bin/docmost-auth"
SMOKE_TOOL="$GENERATION_RUNTIME/bin/docmost-smoke"
readonly FINGERPRINT GENERATION_RUNTIME RUNTIME_STAMP AUTH_WRAPPER SMOKE_TOOL

ACTION="${1:-}"
case "$ACTION" in
  --check)
    [ "$#" -eq 1 ] || { usage; exit 2; }
    require_runtime_roots
    require_current_runtime
    run_generation_locked shared --check-locked
    ;;
  --install)
    [ "$#" -eq 1 ] || { usage; exit 2; }
    require_private_env
    ensure_private_profile_root
    ensure_runtime_roots
    run_setup_locked --install-setup-locked
    ;;
  --login)
    [ "$#" -eq 1 ] || { usage; exit 2; }
    require_runtime_roots
    require_current_runtime
    run_session_generation_locked exclusive --login-locked
    ;;
  --status)
    [ "$#" -eq 1 ] || { usage; exit 2; }
    require_runtime_roots
    require_current_runtime
    run_session_generation_locked shared --status-locked
    ;;
  --logout)
    [ "$#" -eq 1 ] || { usage; exit 2; }
    require_runtime_roots
    require_current_runtime
    run_session_generation_locked exclusive --logout-locked
    ;;
  --prune)
    [ "$#" -eq 1 ] || { usage; exit 2; }
    require_runtime_roots
    run_setup_locked --prune-setup-locked
    ;;
  --install-setup-locked)
    [ "$#" -eq 1 ] || exit 2
    install_setup_locked
    ;;
  --install-generation-locked)
    [ "$#" -eq 1 ] || exit 2
    install_generation_locked
    ;;
  --check-locked)
    [ "$#" -eq 1 ] || exit 2
    check_locked
    ;;
  --status-locked)
    [ "$#" -eq 1 ] || exit 2
    status_locked
    ;;
  --login-locked)
    [ "$#" -eq 1 ] || exit 2
    login_locked
    ;;
  --logout-locked)
    [ "$#" -eq 1 ] || exit 2
    logout_locked
    ;;
  --prune-setup-locked)
    [ "$#" -eq 1 ] || exit 2
    prune_setup_locked
    ;;
  --prune-generation-locked)
    [ "$#" -eq 2 ] || exit 2
    prune_generation_locked "$2"
    ;;
  *)
    usage
    exit 2
    ;;
esac
