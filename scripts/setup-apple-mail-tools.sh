#!/usr/bin/env bash
# Install and inspect immutable Apple Mail MCP runtime generations.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="${APPLE_MAIL_SERVER_DIR:-$ROOT/plugins/apple-mail-tools/server}"
APPLE_MAIL_CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
CODEX_SECRETS_DIR="${CODEX_SECRETS_DIR:-$APPLE_MAIL_CODEX_ROOT/secrets}"
STATE_ROOT="$CODEX_SECRETS_DIR/apple-mail-tools"
RUNTIME_PARENT="$APPLE_MAIL_CODEX_ROOT/runtime"
GENERATION_ROOT="$RUNTIME_PARENT/apple-mail-tools-generations"
GENERATION_ENVS="$GENERATION_ROOT/envs"
GENERATION_LOCKS="$GENERATION_ROOT/locks"
LEGACY_RUNTIME="$RUNTIME_PARENT/apple-mail-tools"
MCP_WRAPPER_SOURCE="$SERVER_DIR/scripts/apple-mail-mcp"
RUNTIME_LOCK_SOURCE="$SERVER_DIR/src/apple_mail_tools/runtime_lock.py"
RUNTIME_STAMP_SOURCE="$SERVER_DIR/src/apple_mail_tools/runtime_stamp.py"
SYSTEM_PYTHON="$(command -v python3 || true)"
BUSY_EXIT=75
export CODEX_SECRETS_DIR APPLE_MAIL_SERVER_DIR
readonly ROOT SERVER_DIR APPLE_MAIL_CODEX_ROOT CODEX_SECRETS_DIR STATE_ROOT
readonly RUNTIME_PARENT GENERATION_ROOT GENERATION_ENVS GENERATION_LOCKS LEGACY_RUNTIME
readonly MCP_WRAPPER_SOURCE RUNTIME_LOCK_SOURCE RUNTIME_STAMP_SOURCE SYSTEM_PYTHON BUSY_EXIT

usage() {
  cat >&2 <<'EOF'
Usage: scripts/setup-apple-mail-tools.sh --check|--install|--status|--init-config|--prune

--check        Validate source, private state, and the matching immutable runtime.
--install      Install the immutable runtime generation matching the selected source.
--status       Run a bounded Mail/TCC health check without reading messages.
--init-config  Create missing private configuration and signing state without replacement.
--prune        Remove only unlocked runtime generations no installed plugin references.
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

require_source_inputs() {
  [ -n "$SYSTEM_PYTHON" ] || fail "python3 not found; install Python and rerun --install"
  [ -d "$SERVER_DIR" ] && [ ! -L "$SERVER_DIR" ] || \
    fail "Apple Mail server source is missing or unsafe"
  for source in \
    "$SERVER_DIR/pyproject.toml" \
    "$SERVER_DIR/uv.lock" \
    "$MCP_WRAPPER_SOURCE" \
    "$SERVER_DIR/scripts/mail_bridge.applescript" \
    "$RUNTIME_LOCK_SOURCE" \
    "$RUNTIME_STAMP_SOURCE"
  do
    [ -f "$source" ] && [ ! -L "$source" ] || \
      fail "Apple Mail runtime source inputs are missing or unsafe"
  done
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

run_uv() {
  local uv
  uv="$(resolve_uv)"
  "$uv" "$@"
}

require_fresh_dependency_lock() {
  run_uv lock --check --directory "$SERVER_DIR" >/dev/null 2>&1 || \
    fail "Apple Mail dependency lock is stale; refresh and review server/uv.lock"
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
  ensure_directory "$RUNTIME_PARENT" "Apple Mail runtime parent must be a safe directory"
  ensure_directory "$GENERATION_ROOT" "Apple Mail generation root must be a safe directory"
  ensure_directory "$GENERATION_ENVS" "Apple Mail generation environments must be safe"
  ensure_directory "$GENERATION_LOCKS" "Apple Mail generation locks must be safe"
}

require_runtime_roots() {
  [ -d "$RUNTIME_PARENT" ] && [ ! -L "$RUNTIME_PARENT" ] || \
    fail "Apple Mail runtime is missing; rerun --install"
  [ -d "$GENERATION_ROOT" ] && [ ! -L "$GENERATION_ROOT" ] || \
    fail "Apple Mail generation root is missing or unsafe; rerun --install"
  [ -d "$GENERATION_ENVS" ] && [ ! -L "$GENERATION_ENVS" ] || \
    fail "Apple Mail generation environments are missing or unsafe; rerun --install"
  [ -d "$GENERATION_LOCKS" ] && [ ! -L "$GENERATION_LOCKS" ] || \
    fail "Apple Mail generation locks are missing or unsafe; rerun --install"
}

ensure_private_state_root() {
  ensure_directory "$CODEX_SECRETS_DIR" "Apple Mail secrets root must be a safe directory"
  ensure_directory "$STATE_ROOT" "Apple Mail private state root must be a safe directory"
  chmod 700 "$STATE_ROOT"
}

require_private_state_root() {
  [ -d "$STATE_ROOT" ] && [ ! -L "$STATE_ROOT" ] || \
    fail "Apple Mail private configuration is missing; rerun --install"
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
  value="$(source_fingerprint_for "$SERVER_DIR")" || \
    fail "Unable to fingerprint Apple Mail runtime source"
  printf '%s\n' "$value"
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
    /bin/bash "$ROOT/scripts/setup-apple-mail-tools.sh" "$hidden_command"
}

run_generation_locked() {
  local mode="$1"
  local hidden_command="$2"
  shift 2
  exec "$SYSTEM_PYTHON" "$RUNTIME_LOCK_SOURCE" \
    --kind generation --mode "$mode" --root "$GENERATION_ROOT" \
    --generation "$FINGERPRINT" -- \
    /bin/bash "$ROOT/scripts/setup-apple-mail-tools.sh" "$hidden_command" "$@"
}

require_generation_path() {
  case "$GENERATION_RUNTIME" in
    ("$GENERATION_ENVS/$FINGERPRINT") ;;
    (*) fail "Apple Mail runtime generation path is invalid" ;;
  esac
  [ ! -L "$GENERATION_RUNTIME" ] || fail "Apple Mail runtime generation is unsafe"
}

generation_is_current() {
  require_generation_path
  [ -d "$GENERATION_RUNTIME" ] || return 1
  "$SYSTEM_PYTHON" "$RUNTIME_STAMP_SOURCE" \
    check "$SERVER_DIR" "$RUNTIME_STAMP" >/dev/null 2>&1 || return 1
  [ -x "$GENERATION_RUNTIME/bin/apple-mail-mcp" ] && \
    [ ! -L "$GENERATION_RUNTIME/bin/apple-mail-mcp" ] || return 1
  [ -x "$GENERATION_RUNTIME/bin/apple-mail-runtime-stamp" ] && \
    [ ! -L "$GENERATION_RUNTIME/bin/apple-mail-runtime-stamp" ] || return 1
}

require_current_runtime() {
  generation_is_current || fail "Apple Mail runtime is stale; rerun --install"
}

ensure_runtime_private_state() {
  "$GENERATION_RUNTIME/bin/python" -c \
    'from apple_mail_tools.config import RuntimePaths; RuntimePaths.from_environment().ensure()'
}

install_generation_locked() {
  validate_lock setup exclusive --root "$GENERATION_ROOT" || \
    fail "Apple Mail runtime installation requires the held setup lock"
  validate_lock generation exclusive --root "$GENERATION_ROOT" \
    --generation "$FINGERPRINT" || \
    fail "Apple Mail runtime installation requires the held exclusive generation lock"
  require_macos
  require_source_inputs
  require_fresh_dependency_lock
  ensure_private_state_root
  require_generation_path
  if [ -e "$GENERATION_RUNTIME" ]; then
    [ -d "$GENERATION_RUNTIME" ] && [ ! -L "$GENERATION_RUNTIME" ] || \
      fail "Apple Mail runtime generation is unsafe"
    rm -rf -- "$GENERATION_RUNTIME"
  fi
  mkdir -p "$GENERATION_RUNTIME"
  UV_PROJECT_ENVIRONMENT="$GENERATION_RUNTIME" run_uv sync \
    --python 3.12 --frozen --no-dev --no-editable \
    --reinstall-package apple-mail-tools --directory "$SERVER_DIR"
  ensure_runtime_private_state
  "$SYSTEM_PYTHON" "$RUNTIME_STAMP_SOURCE" write \
    "$SERVER_DIR" "$RUNTIME_STAMP" --expected "$FINGERPRINT" || \
    fail "Apple Mail source changed during runtime installation; rerun --install"
  echo "Apple Mail runtime generation: installed"
}

install_setup_locked() {
  validate_lock setup exclusive --root "$GENERATION_ROOT" || \
    fail "Apple Mail runtime installation requires the held setup lock"
  require_macos
  require_source_inputs
  require_fresh_dependency_lock
  ensure_private_state_root
  if generation_is_current; then
    ensure_runtime_private_state
    echo "Apple Mail runtime generation: ready"
    return 0
  fi
  run_generation_locked exclusive --install-generation-locked
}

check_locked() {
  validate_lock generation shared --root "$GENERATION_ROOT" \
    --generation "$FINGERPRINT" || \
    fail "Apple Mail check requires the held shared generation lock"
  require_macos
  require_source_inputs
  require_fresh_dependency_lock
  require_private_state_root
  require_current_runtime
  UV_PROJECT_ENVIRONMENT="$GENERATION_RUNTIME" run_uv sync \
    --frozen --check --no-dev --no-editable --directory "$SERVER_DIR" >/dev/null 2>&1 || \
    fail "Apple Mail runtime is stale or incomplete; rerun --install"
  "$GENERATION_RUNTIME/bin/python" -c '
from apple_mail_tools.config import RuntimePaths
paths = RuntimePaths.from_environment()
paths.ensure()
paths.load_settings()
' >/dev/null
  echo "Apple Mail runtime: ready"
}

status_locked() {
  validate_lock generation shared --root "$GENERATION_ROOT" \
    --generation "$FINGERPRINT" || \
    fail "Apple Mail status requires the held shared generation lock"
  require_macos
  require_private_state_root
  require_current_runtime
  "$GENERATION_RUNTIME/bin/python" -c '
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

init_config_locked() {
  validate_lock generation shared --root "$GENERATION_ROOT" \
    --generation "$FINGERPRINT" || \
    fail "Apple Mail config initialization requires the held shared generation lock"
  require_macos
  require_current_runtime
  ensure_private_state_root
  ensure_runtime_private_state
  echo "Apple Mail private configuration: ready"
}

protected_generation_ids() {
  printf '%s\n' "$FINGERPRINT"
  local candidate_server candidate_fingerprint
  for candidate_server in "$APPLE_MAIL_CODEX_ROOT"/plugins/cache/*/apple-mail-tools/*/server; do
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
    fail "Apple Mail prune requires the held setup lock"
  validate_lock generation exclusive --root "$GENERATION_ROOT" \
    --generation "$generation" || \
    fail "Apple Mail prune requires the held exclusive generation lock"
  case "$generation" in
    (*[!0-9a-f]*|'') fail "Apple Mail prune generation is invalid" ;;
  esac
  [ "${#generation}" -eq 64 ] || fail "Apple Mail prune generation is invalid"
  [ "$generation" != "$FINGERPRINT" ] || \
    fail "Apple Mail current runtime generation is protected"
  generation_is_protected "$generation" && \
    fail "Apple Mail installed runtime generation is protected"
  local target="$GENERATION_ENVS/$generation"
  case "$target" in
    ("$GENERATION_ENVS/$generation") ;;
    (*) fail "Apple Mail prune target is invalid" ;;
  esac
  if [ -e "$target" ]; then
    [ -d "$target" ] && [ ! -L "$target" ] || fail "Apple Mail prune target is unsafe"
    rm -rf -- "$target"
  fi
  echo "removed"
}

prune_setup_locked() {
  validate_lock setup exclusive --root "$GENERATION_ROOT" || \
    fail "Apple Mail prune requires the held setup lock"
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
    generation_is_protected "$generation" && continue
    set +e
    result="$("$SYSTEM_PYTHON" "$RUNTIME_LOCK_SOURCE" \
      --kind generation --mode exclusive --root "$GENERATION_ROOT" \
      --generation "$generation" -- \
      /bin/bash "$ROOT/scripts/setup-apple-mail-tools.sh" \
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
  echo "Apple Mail runtime generations: pruned=$removed busy=$busy unsafe=$unsafe legacy_retained=$([ -d "$LEGACY_RUNTIME" ] && echo 1 || echo 0)"
  [ "$unsafe" -eq 0 ] || return 1
  [ "$busy" -eq 0 ] || return "$BUSY_EXIT"
}

require_source_inputs
FINGERPRINT="$(source_fingerprint)"
GENERATION_RUNTIME="$GENERATION_ENVS/$FINGERPRINT"
RUNTIME_STAMP="$GENERATION_RUNTIME/.apple-mail-tools-source.sha256"
readonly FINGERPRINT GENERATION_RUNTIME RUNTIME_STAMP

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
    ensure_runtime_roots
    run_setup_locked --install-setup-locked
    ;;
  --status)
    [ "$#" -eq 1 ] || { usage; exit 2; }
    require_runtime_roots
    require_current_runtime
    run_generation_locked shared --status-locked
    ;;
  --init-config)
    [ "$#" -eq 1 ] || { usage; exit 2; }
    require_runtime_roots
    require_current_runtime
    run_generation_locked shared --init-config-locked
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
  --init-config-locked)
    [ "$#" -eq 1 ] || exit 2
    init_config_locked
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
