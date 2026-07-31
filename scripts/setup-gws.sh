#!/usr/bin/env bash
# Opt-in installer and isolated per-account OAuth profile manager for gws.
set -u
set -o pipefail
umask 077

VERSION="0.22.5"
ASSET="google-workspace-cli-aarch64-apple-darwin.tar.gz"
SHA256="1d2a9ffd5bc9b2c2c4b48630daf082fad13d9e57d741988a2c248eed562f7dac"
BINARY_SHA256="0f27b8b0815bf09cdf95da48d3c604f05ceb8f16bf5c9f0ba355b1f957cdd47e"
RELEASE_URL="https://github.com/googleworkspace/cli/releases/download/v${VERSION}/${ASSET}"
GMAIL_SCOPE="https://www.googleapis.com/auth/gmail.modify"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
RUNTIME_DIR="${DATA_HOME}/codex-toolbox/gws/${VERSION}"
GWS_BIN="${RUNTIME_DIR}/gws"
LOCAL_BIN_DIR="${CODEX_LOCAL_BIN_DIR:-$HOME/.local/bin}"
LOCAL_GWS="${LOCAL_BIN_DIR}/gws"
SECRETS_BASE="${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}"
SECRETS_ROOT="${SECRETS_BASE}/gws"
CLIENT_PATH="${SECRETS_ROOT}/client_secret.json"
ACCOUNTS_ROOT="${SECRETS_ROOT}/accounts"
INSTALL_TMP=""
TX_CANDIDATE=""
TX_BACKUP=""
TX_LIVE=""

cleanup_install_tmp() {
  if [ -n "${INSTALL_TMP:-}" ] && [ -d "$INSTALL_TMP" ]; then
    rm -rf "$INSTALL_TMP"
  fi
}

cleanup_profile_transaction() {
  if [ -n "${TX_CANDIDATE:-}" ] && [ -e "$TX_CANDIDATE" ]; then
    /bin/rm -rf -- "$TX_CANDIDATE" || printf 'warning: failed to clean candidate profile\n' >&2
  fi
  if [ -n "${TX_BACKUP:-}" ] && [ -e "$TX_BACKUP" ]; then
    if [ -n "${TX_LIVE:-}" ] && [ ! -e "$TX_LIVE" ]; then
      /bin/mv -- "$TX_BACKUP" "$TX_LIVE" || printf 'critical: failed to restore preserved live profile\n' >&2
    else
      printf 'warning: preserved profile backup requires manual review\n' >&2
    fi
  fi
}

cleanup_all() {
  cleanup_profile_transaction
  cleanup_install_tmp
}
trap cleanup_all EXIT
trap 'exit 130' HUP INT TERM

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

usage() {
  cat >&2 <<'EOF'
Usage:
  setup-gws.sh --check
  setup-gws.sh --install
  setup-gws.sh --register-client FILE
  setup-gws.sh --add-account EMAIL [--alias ALIAS]
  setup-gws.sh --reauth-account ALIAS
  setup-gws.sh --check-account ALIAS
  setup-gws.sh --list-accounts
EOF
  exit 2
}

platform_ready() {
  [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]
}

runtime_ready() {
  local version_output first_line runtime_root canonical_binary
  [ -f "$GWS_BIN" ] && [ ! -L "$GWS_BIN" ] && [ -x "$GWS_BIN" ] || return 1
  runtime_root="$(canonical_dir "$RUNTIME_DIR")" || return 1
  canonical_binary="$(cd -P "$RUNTIME_DIR" && printf '%s/gws\n' "$PWD")" || return 1
  [ "$canonical_binary" = "$runtime_root/gws" ] || return 1
  [ "$(file_sha256 "$GWS_BIN")" = "$BINARY_SHA256" ] || return 1
  version_output="$("$GWS_BIN" --version 2>/dev/null)" || return 1
  first_line="${version_output%%$'\n'*}"
  [ "$first_line" = "gws $VERSION" ]
}

canonical_dir() {
  [ -d "$1" ] && [ ! -L "$1" ] || return 1
  (cd -P "$1" && pwd)
}

ensure_private_dir() {
  if [ -L "$1" ]; then
    die "refusing symlinked private directory"
  fi
  mkdir -p "$1" || die "unable to create private directory"
  chmod 700 "$1" || die "unable to protect private directory"
}

ensure_executable_dir() {
  if [ -L "$1" ]; then
    die "refusing symlinked executable directory"
  fi
  if [ -e "$1" ]; then
    [ -d "$1" ] || die "executable directory path is not a directory"
    return 0
  fi
  mkdir -p "$1" || die "unable to create executable directory"
  chmod 755 "$1" || die "unable to set executable directory permissions"
}

file_sha256() {
  local output
  [ -f "$1" ] && [ ! -L "$1" ] || return 1
  output="$(/usr/bin/shasum -a 256 "$1" 2>/dev/null)" || return 1
  printf '%s\n' "${output%% *}"
}

accounts_root_is_private() {
  [ -d "$ACCOUNTS_ROOT" ] && [ ! -L "$ACCOUNTS_ROOT" ] || return 1
  profile_state_is_private_shallow "$ACCOUNTS_ROOT"
}

profile_state_is_private_shallow() {
  PROFILE_DIR="$1" /usr/bin/python3 -I - <<'PY'
import os
import stat
import sys
try:
    metadata = os.lstat(os.environ["PROFILE_DIR"])
    valid = stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode) and stat.S_IMODE(metadata.st_mode) == 0o700
except OSError:
    valid = False
sys.exit(0 if valid else 1)
PY
}

registered_client_is_private() {
  [ -f "$CLIENT_PATH" ] && [ ! -L "$CLIENT_PATH" ] || return 1
  validate_client_json "$CLIENT_PATH" || return 1
  FILE_PATH="$CLIENT_PATH" /usr/bin/python3 -I - <<'PY'
import os
import stat
import sys
try:
    metadata = os.lstat(os.environ["FILE_PATH"])
    valid = stat.S_ISREG(metadata.st_mode) and stat.S_IMODE(metadata.st_mode) == 0o600
except OSError:
    valid = False
sys.exit(0 if valid else 1)
PY
}

profile_state_is_private() {
  PROFILE_DIR="$1" /usr/bin/python3 -I - <<'PY'
import os
import stat
import sys

def fail_if_unsafe(path, expected_mode, expected_kind):
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not expected_kind(metadata.st_mode):
        raise ValueError("unsafe profile state")
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise ValueError("unsafe profile permissions")

def rethrow(error):
    raise error

try:
    root = os.environ["PROFILE_DIR"]
    fail_if_unsafe(root, 0o700, stat.S_ISDIR)
    for current, directories, files in os.walk(root, topdown=True, followlinks=False, onerror=rethrow):
        for name in directories:
            fail_if_unsafe(os.path.join(current, name), 0o700, stat.S_ISDIR)
        for name in files:
            fail_if_unsafe(os.path.join(current, name), 0o600, stat.S_ISREG)
except (OSError, ValueError):
    sys.exit(1)
PY
}

validate_client_json() {
  [ -f "$1" ] && [ ! -L "$1" ] || return 1
  CLIENT_FILE="$1" /usr/bin/python3 -I - <<'PY'
import json
import os
import sys

try:
    with open(os.environ["CLIENT_FILE"], encoding="utf-8") as source:
        installed = json.load(source)["installed"]
    valid = all(isinstance(installed.get(key), str) and installed[key] for key in ("client_id", "client_secret", "project_id"))
except (OSError, ValueError, KeyError, TypeError):
    valid = False
sys.exit(0 if valid else 1)
PY
}

default_alias() {
  local local_part
  local_part="${1%%@*}"
  printf '%s' "$local_part" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9._-]+/-/g; s/^[._-]+//; s/[._-]+$//'
}

validate_alias() {
  case "$1" in
    ''|.|..|*/*|*'\\'* ) return 1 ;;
  esac
  [[ "$1" =~ ^[a-z0-9][a-z0-9._-]{0,62}$ ]]
}

profile_for_alias() {
  local alias="$1"
  validate_alias "$alias" || return 1
  accounts_root_is_private || return 1
  local root profile
  root="$(canonical_dir "$ACCOUNTS_ROOT")" || return 1
  profile="${ACCOUNTS_ROOT}/${alias}"
  [ -d "$profile" ] && [ ! -L "$profile" ] || return 1
  profile="$(canonical_dir "$profile")" || return 1
  case "$profile" in
    "$root"/*) printf '%s\n' "$profile" ;;
    *) return 1 ;;
  esac
}

profile_expected_email() {
  PROFILE_FILE="$1/profile.json" /usr/bin/python3 -I - <<'PY'
import json
import os
import sys

try:
    with open(os.environ["PROFILE_FILE"], encoding="utf-8") as source:
        profile = json.load(source)
    email = profile["expected_email"]
    if profile["schema_version"] != 1 or not isinstance(email, str) or not email:
        raise ValueError("invalid profile")
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(1)
print(email)
PY
}

run_isolated() {
  local profile="$1"
  shift
  cd / || return 1
  /usr/bin/env \
    -u GOOGLE_WORKSPACE_CLI_TOKEN \
    -u GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE \
    -u GOOGLE_WORKSPACE_CLI_CREDENTIAL_FILE \
    -u GOOGLE_WORKSPACE_CLI_CLIENT_ID \
    -u GOOGLE_WORKSPACE_CLI_CLIENT_SECRET \
    -u GOOGLE_WORKSPACE_CLI_LOG \
    -u GOOGLE_WORKSPACE_CLI_LOG_FILE \
    -u GOOGLE_WORKSPACE_PROJECT_ID \
    -u GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE \
    -u GOOGLE_WORKSPACE_CLI_SANITIZE_MODE \
    -u GOOGLE_APPLICATION_CREDENTIALS \
    GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$profile" \
    GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file \
    GOOGLE_APPLICATION_CREDENTIALS="$profile/missing-adc.json" \
    "$GWS_BIN" "$@"
}

status_is_healthy() {
  local expected="$1"
  local status="$2"
  EXPECTED_EMAIL="$expected" STATUS_JSON="$status" /usr/bin/python3 -I - <<'PY'
import json
import os
import sys

try:
    status = json.loads(os.environ["STATUS_JSON"])
    scopes = status["scopes"]
    required_scopes = {
        "openid",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    }
    healthy = (
        isinstance(status.get("user"), str)
        and status["user"].casefold() == os.environ["EXPECTED_EMAIL"].casefold()
        and status.get("token_valid") is True
        and status.get("storage") == "encrypted"
        and status.get("keyring_backend") == "file"
        and status.get("encrypted_credentials_exists") is True
        and status.get("encryption_valid") is True
        and isinstance(scopes, list)
        and len(scopes) == len(required_scopes)
        and set(scopes) == required_scopes
    )
except (ValueError, TypeError, KeyError):
    healthy = False
sys.exit(0 if healthy else 1)
PY
}

check_profile_health() {
  local profile="$1" expected="$2" alias="$3" status
  validate_client_json "$profile/client_secret.json" || { printf '%s: invalid client\n' "$alias" >&2; return 1; }
  profile_state_is_private "$profile" || { printf '%s: private permissions check failed\n' "$alias" >&2; return 1; }
  runtime_ready || { printf '%s: gws runtime unavailable\n' "$alias" >&2; return 1; }
  status="$(run_isolated "$profile" auth status 2>/dev/null)" || { printf '%s: credentials unavailable\n' "$alias" >&2; return 1; }
  status_is_healthy "$expected" "$status" || { printf '%s: identity, token, keyring, encryption, or scope check failed\n' "$alias" >&2; return 1; }
  printf '%s: ready\n' "$alias"
}

check_account() {
  local alias="$1"
  local profile expected
  profile="$(profile_for_alias "$alias")" || { printf '%s: invalid profile\n' "$alias" >&2; return 1; }
  expected="$(profile_expected_email "$profile")" || { printf '%s: invalid profile\n' "$alias" >&2; return 1; }
  check_profile_health "$profile" "$expected" "$alias"
}

install_gws() {
  platform_ready || die "Platform: unsupported (requires macOS arm64)"
  if [ -e "$LOCAL_GWS" ] || [ -L "$LOCAL_GWS" ]; then
    [ -L "$LOCAL_GWS" ] || die "refusing to overwrite unmanaged local gws binary"
    [ "$(readlink "$LOCAL_GWS")" = "$GWS_BIN" ] || die "refusing to overwrite unmanaged local gws symlink"
  fi
  if runtime_ready; then
    ensure_executable_dir "$LOCAL_BIN_DIR"
    if [ ! -L "$LOCAL_GWS" ]; then
      ln -s "$GWS_BIN" "$LOCAL_GWS" || die "unable to create managed gws symlink"
    fi
    printf 'gws %s already installed\n' "$VERSION"
    return 0
  fi
  ensure_executable_dir "$RUNTIME_DIR"
  ensure_executable_dir "$LOCAL_BIN_DIR"
  local archive stage actual extracted_sha
  INSTALL_TMP="$(mktemp -d "${TMPDIR:-/tmp}/codex-toolbox-gws.XXXXXX")" || die "unable to create temporary directory"
  archive="$INSTALL_TMP/$ASSET"
  curl -fsSL "$RELEASE_URL" -o "$archive" || die "download failed"
  actual="$(file_sha256 "$archive")" || die "unable to hash downloaded gws release"
  [ "$actual" = "$SHA256" ] || die "checksum mismatch for pinned gws release"
  stage="$INSTALL_TMP/stage"
  mkdir "$stage" || die "unable to prepare release extraction"
  tar -xzf "$archive" -C "$stage" || die "archive extraction failed"
  [ -f "$stage/gws" ] && [ ! -L "$stage/gws" ] || die "release archive did not contain gws"
  extracted_sha="$(file_sha256 "$stage/gws")" || die "unable to hash extracted gws binary"
  [ "$extracted_sha" = "$BINARY_SHA256" ] || die "extracted gws checksum mismatch"
  chmod 755 "$stage/gws"
  mv "$stage/gws" "$RUNTIME_DIR/gws.new" || die "unable to stage gws binary"
  mv -f "$RUNTIME_DIR/gws.new" "$GWS_BIN" || die "unable to install gws binary"
  if [ -L "$LOCAL_GWS" ]; then
    rm "$LOCAL_GWS"
  fi
  ln -s "$GWS_BIN" "$LOCAL_GWS" || die "unable to create managed gws symlink"
  runtime_ready || die "installed gws did not report expected version"
  printf 'Installed gws %s\n' "$VERSION"
}

register_client() {
  [ "$#" -eq 1 ] || usage
  validate_client_json "$1" || die "invalid Desktop OAuth client JSON"
  [ ! -e "$CLIENT_PATH" ] && [ ! -L "$CLIENT_PATH" ] || die "OAuth client already registered; refusing replacement"
  ensure_private_dir "$SECRETS_ROOT"
  cp "$1" "$CLIENT_PATH" || die "unable to store OAuth client"
  chmod 600 "$CLIENT_PATH" || die "unable to protect OAuth client"
  printf 'OAuth client registered\n'
}

add_account() {
  local email="$1" alias profile existing candidate
  shift
  [ -n "$email" ] || die "email is required"
  if [ "$#" -eq 0 ]; then
    alias="$(default_alias "$email")"
  elif [ "$#" -eq 2 ] && [ "$1" = "--alias" ]; then
    alias="$2"
  else
    usage
  fi
  validate_alias "$alias" || die "invalid account alias"
  registered_client_is_private || die "a valid protected registered OAuth client is required"
  ensure_private_dir "$SECRETS_ROOT"
  ensure_private_dir "$ACCOUNTS_ROOT"
  profile="$ACCOUNTS_ROOT/$alias"
  if [ -L "$profile" ]; then
    die "refusing symlinked account profile"
  fi
  if [ -e "$profile" ]; then
    existing="$(profile_expected_email "$profile" 2>/dev/null || true)"
    if [ -n "$existing" ] && [ "$(printf '%s' "$existing" | tr '[:upper:]' '[:lower:]')" != "$(printf '%s' "$email" | tr '[:upper:]' '[:lower:]')" ]; then
      die "account alias belongs to another expected email"
    fi
    die "account alias already exists"
  fi
  runtime_ready || die "gws runtime is unavailable or untrusted"
  candidate="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.add.XXXXXX")" || die "unable to create candidate account profile"
  chmod 700 "$candidate" || die "unable to protect candidate account profile"
  TX_CANDIDATE="$candidate"
  if ! cp "$CLIENT_PATH" "$candidate/client_secret.json" || ! chmod 600 "$candidate/client_secret.json"; then
    die "unable to create candidate account profile"
  fi
  EMAIL="$email" PROFILE_FILE="$candidate/profile.json" /usr/bin/python3 -I - <<'PY' || die "unable to write candidate account profile"
import json
import os
with open(os.environ["PROFILE_FILE"], "w", encoding="utf-8") as destination:
    json.dump({"schema_version": 1, "expected_email": os.environ["EMAIL"]}, destination)
    destination.write("\n")
PY
  chmod 600 "$candidate/profile.json" || die "unable to protect candidate account metadata"
  if ! run_isolated "$candidate" auth login --scopes "$GMAIL_SCOPE"; then
    die "OAuth login failed; candidate profile will be removed"
  fi
  if ! check_profile_health "$candidate" "$email" "$alias"; then
    die "OAuth login identity check failed; candidate profile will be removed"
  fi
  /bin/mv -- "$candidate" "$profile" || die "unable to activate candidate account profile"
  TX_CANDIDATE=""
  printf 'Account %s added\n' "$alias"
}

reauth_account() {
  [ "$#" -eq 1 ] || usage
  local alias="$1" profile expected candidate backup
  profile="$(profile_for_alias "$alias")" || die "invalid profile"
  expected="$(profile_expected_email "$profile")" || die "invalid profile"
  validate_client_json "$profile/client_secret.json" || die "invalid profile client"
  profile_state_is_private "$profile" || die "existing profile has unsafe permissions"
  runtime_ready || die "gws runtime is unavailable or untrusted"
  candidate="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.reauth.XXXXXX")" || die "unable to create reauthentication candidate"
  chmod 700 "$candidate" || die "unable to protect reauthentication candidate"
  TX_CANDIDATE="$candidate"
  cp -pR "$profile/." "$candidate" || die "unable to stage reauthentication candidate"
  if ! run_isolated "$candidate" auth login --scopes "$GMAIL_SCOPE"; then
    die "OAuth login failed; live profile remains unchanged"
  fi
  if ! check_profile_health "$candidate" "$expected" "$alias"; then
    die "OAuth login identity check failed; live profile remains unchanged"
  fi
  backup="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.backup.XXXXXX")" || die "unable to reserve profile backup"
  /bin/rmdir -- "$backup" || die "unable to reserve profile backup"
  TX_BACKUP="$backup"
  TX_LIVE="$profile"
  if ! /bin/mv -- "$profile" "$backup"; then
    TX_BACKUP=""
    die "unable to stage live profile; live profile remains unchanged"
  fi
  if ! /bin/mv -- "$candidate" "$profile"; then
    if /bin/mv -- "$backup" "$profile"; then
      TX_BACKUP=""
      die "unable to activate reauthenticated profile; live profile restored"
    fi
    die "unable to activate reauthenticated profile; preserved backup could not be restored"
  fi
  TX_CANDIDATE=""
  if ! /bin/rm -rf -- "$backup"; then
    die "reauthenticated profile activated but backup cleanup failed"
  fi
  TX_BACKUP=""
  TX_LIVE=""
  printf 'Account %s reauthenticated\n' "$alias"
}

check_all() {
  local failed=0 alias found=0
  if platform_ready; then printf 'Platform: ready (macOS arm64)\n'; else printf 'Platform: unsupported (requires macOS arm64)\n'; failed=1; fi
  if runtime_ready; then printf 'gws runtime: ready (%s)\n' "$VERSION"; else printf 'gws runtime: missing (expected %s)\n' "$VERSION"; failed=1; fi
  if [ ! -e "$CLIENT_PATH" ]; then
    printf 'OAuth client: missing\n'
    failed=1
  elif registered_client_is_private; then
    printf 'OAuth client: ready\n'
  else
    printf 'OAuth client: unsafe\n'
    failed=1
  fi
  if [ ! -e "$ACCOUNTS_ROOT" ]; then
    printf 'Profiles: none\n'
    failed=1
  elif ! accounts_root_is_private; then
    printf 'Profiles: unsafe\n'
    failed=1
  else
    for alias_path in "$ACCOUNTS_ROOT"/*; do
      [ -e "$alias_path" ] || continue
      found=1
      alias="${alias_path##*/}"
      if check_account "$alias"; then :; else failed=1; fi
    done
    if [ "$found" -eq 0 ]; then
      printf 'Profiles: none\n'
      failed=1
    fi
  fi
  [ "$failed" -eq 0 ] && printf 'Overall: ready\n'
  return "$failed"
}

list_accounts() {
  [ "$#" -eq 0 ] || usage
  if [ ! -e "$ACCOUNTS_ROOT" ]; then
    printf 'Profiles: none\n'
    return 0
  fi
  if ! accounts_root_is_private; then
    printf 'Profiles: unsafe\n'
    return 1
  fi
  local alias_path alias failed=0 found=0
  for alias_path in "$ACCOUNTS_ROOT"/*; do
    [ -e "$alias_path" ] || continue
    found=1
    alias="${alias_path##*/}"
    if check_account "$alias"; then :; else failed=1; fi
  done
  [ "$found" -eq 1 ] || printf 'Profiles: none\n'
  return "$failed"
}

case "${1:-}" in
  --check) [ "$#" -eq 1 ] || usage; check_all ;;
  --install) [ "$#" -eq 1 ] || usage; install_gws ;;
  --register-client) shift; register_client "$@" ;;
  --add-account) shift; [ "$#" -ge 1 ] || usage; add_account "$@" ;;
  --reauth-account) shift; reauth_account "$@" ;;
  --check-account) shift; [ "$#" -eq 1 ] || usage; check_account "$1" ;;
  --list-accounts) shift; list_accounts "$@" ;;
  *) usage ;;
esac
