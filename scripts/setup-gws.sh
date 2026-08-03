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
TX_RESERVATION=""
TX_LOCK=""
TX_CLIENT_CANDIDATE=""
TX_ACTIVATED=0
TX_COMMITTED=0
SECRETS_ROOT_ENTRIES=()
PROFILE_ENTRIES=()

cleanup_install_tmp() {
  if [ -n "${INSTALL_TMP:-}" ] && [ -d "$INSTALL_TMP" ]; then
    rm -rf "$INSTALL_TMP"
  fi
}

cleanup_profile_transaction() {
  local failed=0 rollback_failed=0
  if [ -n "${TX_CLIENT_CANDIDATE:-}" ] && { [ -e "$TX_CLIENT_CANDIDATE" ] || [ -L "$TX_CLIENT_CANDIDATE" ]; }; then
    if ! /bin/rm -- "$TX_CLIENT_CANDIDATE"; then
      printf 'warning: failed to clean OAuth client candidate\n' >&2
      failed=1
    fi
  fi
  if [ "${TX_ACTIVATED:-0}" -eq 1 ] && [ "${TX_COMMITTED:-0}" -eq 0 ]; then
    if [ -n "${TX_LIVE:-}" ] && { [ -e "$TX_LIVE" ] || [ -L "$TX_LIVE" ]; } \
      && [ -n "${TX_CANDIDATE:-}" ] && [ ! -e "$TX_CANDIDATE" ] && [ ! -L "$TX_CANDIDATE" ]; then
      if ! rename_path "$TX_LIVE" "$TX_CANDIDATE"; then
        printf 'critical: failed to quarantine uncommitted live profile\n' >&2
        failed=1
        rollback_failed=1
      fi
    fi
  fi
  if [ -n "${TX_BACKUP:-}" ] && { [ -e "$TX_BACKUP" ] || [ -L "$TX_BACKUP" ]; }; then
    if [ "${TX_COMMITTED:-0}" -eq 0 ] && [ -n "${TX_LIVE:-}" ] \
      && [ ! -e "$TX_LIVE" ] && [ ! -L "$TX_LIVE" ]; then
      if rename_path "$TX_BACKUP" "$TX_LIVE"; then
        TX_BACKUP=""
      else
        printf 'critical: failed to restore preserved live profile\n' >&2
        failed=1
        rollback_failed=1
      fi
    else
      printf 'warning: preserved profile backup requires manual review\n' >&2
      if [ "${TX_COMMITTED:-0}" -eq 0 ]; then
        failed=1
        rollback_failed=1
      fi
    fi
  fi
  if [ -n "${TX_CANDIDATE:-}" ] && { [ -e "$TX_CANDIDATE" ] || [ -L "$TX_CANDIDATE" ]; }; then
    if [ "$rollback_failed" -eq 0 ]; then
      if ! /bin/rm -rf -- "$TX_CANDIDATE"; then
        printf 'warning: failed to clean candidate profile\n' >&2
        failed=1
      fi
    else
      printf 'critical: preserved candidate profile requires manual review\n' >&2
    fi
  fi
  if [ -n "${TX_RESERVATION:-}" ] && [ -d "$TX_RESERVATION" ] && [ ! -L "$TX_RESERVATION" ]; then
    if ! /bin/rmdir -- "$TX_RESERVATION"; then
      printf 'warning: failed to clean reserved profile path\n' >&2
      failed=1
    fi
  fi
  if [ -n "${TX_LOCK:-}" ] && [ -d "$TX_LOCK" ] && [ ! -L "$TX_LOCK" ]; then
    if [ "$rollback_failed" -ne 0 ]; then
      printf 'critical: preserved alias lock requires manual review\n' >&2
      failed=1
    elif ! /bin/rmdir -- "$TX_LOCK"; then
      printf 'warning: failed to release account lock\n' >&2
      failed=1
    fi
  fi
  return "$failed"
}

cleanup_all() {
  local failed=0
  cleanup_profile_transaction || failed=1
  cleanup_install_tmp || failed=1
  return "$failed"
}

cleanup_on_exit() {
  local status="$?"
  trap - EXIT HUP INT TERM
  if ! cleanup_all; then
    status=1
  fi
  exit "$status"
}
trap cleanup_on_exit EXIT
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
  setup-gws.sh --import-account FILE --email EMAIL --alias ALIAS [--replace]
  setup-gws.sh --migrate-account ALIAS
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
  local version_output first_line
  runtime_path_is_trusted 0 || return 1
  [ "$(file_sha256 "$GWS_BIN")" = "$BINARY_SHA256" ] || return 1
  version_output="$("$GWS_BIN" --version 2>/dev/null)" || return 1
  first_line="${version_output%%$'\n'*}"
  [ "$first_line" = "gws $VERSION" ]
}

runtime_path_is_trusted() {
  RUNTIME_DIR_PATH="$RUNTIME_DIR" \
  RUNTIME_BINARY_PATH="$GWS_BIN" \
  ALLOW_MISSING_RUNTIME="$1" \
    /usr/bin/python3 -I - <<'PY'
import os
import stat
import sys

try:
    runtime_dir = os.environ["RUNTIME_DIR_PATH"]
    binary = os.environ["RUNTIME_BINARY_PATH"]
    allow_missing = os.environ["ALLOW_MISSING_RUNTIME"] == "1"
    if (
        not os.path.isabs(runtime_dir)
        or os.path.normpath(runtime_dir) != runtime_dir
        or binary != os.path.join(runtime_dir, "gws")
    ):
        raise ValueError("non-canonical runtime path")

    trusted_owners = {0, os.getuid()}
    current = os.path.sep
    components = [current]
    for component in runtime_dir.split(os.path.sep)[1:]:
        current = os.path.join(current, component)
        components.append(current)

    missing = False
    for component in components:
        try:
            metadata = os.lstat(component)
        except FileNotFoundError:
            if not allow_missing:
                raise
            missing = True
            continue
        if missing:
            raise ValueError("runtime path exists below a missing ancestor")
        mode = stat.S_IMODE(metadata.st_mode)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid not in trusted_owners
            or mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise ValueError("unsafe runtime directory")

    if not allow_missing:
        metadata = os.lstat(binary)
        mode = stat.S_IMODE(metadata.st_mode)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid not in trusted_owners
            or mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        ):
            raise ValueError("unsafe runtime binary")
except (KeyError, OSError, ValueError):
    sys.exit(1)
PY
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

ensure_runtime_dir() {
  runtime_path_is_trusted 1 || die "unsafe gws runtime path"
  mkdir -p "$RUNTIME_DIR" || die "unable to create gws runtime path"
  chmod 755 "$RUNTIME_DIR" || die "unable to protect gws runtime path"
  runtime_path_is_trusted 1 || die "unsafe gws runtime path"
}

file_sha256() {
  local output
  [ -f "$1" ] && [ ! -L "$1" ] || return 1
  output="$(/usr/bin/shasum -a 256 "$1" 2>/dev/null)" || return 1
  printf '%s\n' "${output%% *}"
}

private_regular_file() {
  FILE_PATH="$1" /usr/bin/python3 -I - <<'PY'
import os
import stat
import sys
try:
    metadata = os.lstat(os.environ["FILE_PATH"])
    valid = (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
    )
except OSError:
    valid = False
sys.exit(0 if valid else 1)
PY
}

secrets_base_is_private() {
  local base
  [ -d "$SECRETS_BASE" ] && [ ! -L "$SECRETS_BASE" ] || return 1
  profile_state_is_private_shallow "$SECRETS_BASE" || return 1
  base="$(canonical_dir "$SECRETS_BASE")" || return 1
  [ "$base" = "$SECRETS_BASE" ]
}

secrets_root_is_private() {
  local root
  secrets_base_is_private || return 1
  [ -d "$SECRETS_ROOT" ] && [ ! -L "$SECRETS_ROOT" ] || return 1
  profile_state_is_private_shallow "$SECRETS_ROOT" || return 1
  root="$(canonical_dir "$SECRETS_ROOT")" || return 1
  [ "$root" = "$SECRETS_ROOT" ]
}

accounts_root_is_private() {
  local root
  secrets_root_is_private || return 1
  [ -d "$ACCOUNTS_ROOT" ] && [ ! -L "$ACCOUNTS_ROOT" ] || return 1
  profile_state_is_private_shallow "$ACCOUNTS_ROOT" || return 1
  root="$(canonical_dir "$ACCOUNTS_ROOT")" || return 1
  [ "$root" = "$SECRETS_ROOT/accounts" ] && [ "$root" = "$ACCOUNTS_ROOT" ]
}

profile_state_is_private_shallow() {
  PROFILE_DIR="$1" /usr/bin/python3 -I - <<'PY'
import os
import stat
import sys
try:
    metadata = os.lstat(os.environ["PROFILE_DIR"])
    valid = (
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )
except OSError:
    valid = False
sys.exit(0 if valid else 1)
PY
}

registered_client_is_private() {
  local parent
  secrets_root_is_private || return 1
  [ -f "$CLIENT_PATH" ] && [ ! -L "$CLIENT_PATH" ] || return 1
  validate_registered_client_json "$CLIENT_PATH" || return 1
  private_regular_file "$CLIENT_PATH" || return 1
  parent="$(canonical_dir "${CLIENT_PATH%/*}")" || return 1
  [ "$parent" = "$SECRETS_ROOT" ]
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
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != expected_mode:
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

validate_registered_client_json() {
  [ -f "$1" ] && [ ! -L "$1" ] || return 1
  CLIENT_FILE="$1" /usr/bin/python3 -I - <<'PY'
import json
import os
import sys

try:
    with open(os.environ["CLIENT_FILE"], encoding="utf-8") as source:
        document = json.load(source)
    installed = document["installed"]
    required = ("client_id", "client_secret", "project_id", "auth_uri", "token_uri")
    valid = (
        isinstance(document, dict)
        and isinstance(installed, dict)
        and all(isinstance(installed.get(key), str) and installed[key] for key in required)
        and installed["auth_uri"] == "https://accounts.google.com/o/oauth2/auth"
        and installed["token_uri"] == "https://oauth2.googleapis.com/token"
    )
except (OSError, ValueError, KeyError, TypeError):
    valid = False
sys.exit(0 if valid else 1)
PY
}

validate_runtime_client_json() {
  [ -f "$1" ] && [ ! -L "$1" ] || return 1
  CLIENT_FILE="$1" /usr/bin/python3 -I - <<'PY'
import json
import os
import sys

try:
    with open(os.environ["CLIENT_FILE"], encoding="utf-8") as source:
        document = json.load(source)
    installed = document["installed"]
    required = ("client_id", "client_secret", "project_id", "auth_uri", "token_uri")
    valid = (
        isinstance(document, dict)
        and isinstance(installed, dict)
        and all(isinstance(installed.get(key), str) for key in required)
        and all(installed[key] for key in required if key != "project_id")
        and installed["project_id"] == ""
        and installed["auth_uri"] == "https://accounts.google.com/o/oauth2/auth"
        and installed["token_uri"] == "https://oauth2.googleapis.com/token"
    )
except (OSError, ValueError, KeyError, TypeError):
    valid = False
sys.exit(0 if valid else 1)
PY
}

runtime_client_matches_registered() {
  RUNTIME_FILE="$1" REGISTERED_FILE="$CLIENT_PATH" /usr/bin/python3 -I - <<'PY'
import json
import os
import sys

def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result

try:
    with open(os.environ["REGISTERED_FILE"], encoding="utf-8") as source:
        registered = json.load(source, object_pairs_hook=reject_duplicates)
    with open(os.environ["RUNTIME_FILE"], encoding="utf-8") as source:
        runtime = json.load(source, object_pairs_hook=reject_duplicates)
    expected = json.loads(json.dumps(registered))
    expected["installed"]["project_id"] = ""
    valid = runtime == expected
except (OSError, ValueError, KeyError, TypeError):
    valid = False
sys.exit(0 if valid else 1)
PY
}

legacy_runtime_client_matches_registered() {
  RUNTIME_FILE="$1" REGISTERED_FILE="$CLIENT_PATH" /usr/bin/python3 -I - <<'PY'
import json
import os
import sys

def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result

try:
    with open(os.environ["REGISTERED_FILE"], encoding="utf-8") as source:
        registered = json.load(source, object_pairs_hook=reject_duplicates)
    with open(os.environ["RUNTIME_FILE"], encoding="utf-8") as source:
        runtime = json.load(source, object_pairs_hook=reject_duplicates)
    valid = runtime == registered
except (OSError, ValueError, KeyError, TypeError):
    valid = False
sys.exit(0 if valid else 1)
PY
}

write_runtime_client() {
  REGISTERED_FILE="$CLIENT_PATH" RUNTIME_FILE="$1" /usr/bin/python3 -I - <<'PY'
import json
import os
import sys

try:
    with open(os.environ["REGISTERED_FILE"], encoding="utf-8") as source:
        client = json.load(source)
    client["installed"]["project_id"] = ""
    encoded = (json.dumps(client, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(os.environ["RUNTIME_FILE"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
except (OSError, ValueError, KeyError, TypeError):
    try:
        os.unlink(os.environ["RUNTIME_FILE"])
    except OSError:
        pass
    sys.exit(1)
PY
}

validate_imported_profile_state() {
  PROFILE_DIR="$1" /usr/bin/python3 -I - <<'PY'
import hashlib
import json
import os
import stat
import sys

def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result

def safe_imported_credentials(metadata):
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == 1
    )

def identity(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_uid,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        getattr(metadata, "st_mtime_ns", int(metadata.st_mtime * 1000000000)),
        getattr(metadata, "st_ctime_ns", int(metadata.st_ctime * 1000000000)),
    )

credential_fd = None
try:
    root = os.environ["PROFILE_DIR"]
    with open(os.path.join(root, "profile.json"), encoding="utf-8") as source:
        metadata = json.load(source)
    credential_path = os.path.join(root, "credentials.json")
    before = os.lstat(credential_path)
    if not safe_imported_credentials(before):
        raise ValueError("unsafe imported credentials")
    credential_fd = os.open(
        credential_path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    opened = os.fstat(credential_fd)
    if not safe_imported_credentials(opened) or identity(opened) != identity(before):
        raise ValueError("imported credentials changed before read")
    with os.fdopen(credential_fd, "rb") as source:
        credential_fd = None
        credential_bytes = source.read()
        after_fd = os.fstat(source.fileno())
    after_path = os.lstat(credential_path)
    if identity(after_fd) != identity(opened) or identity(after_path) != identity(before):
        raise ValueError("imported credentials changed during read")
    credentials = json.loads(credential_bytes.decode("utf-8"), object_pairs_hook=reject_duplicates)
    with open(os.path.join(root, "client_secret.json"), encoding="utf-8") as source:
        client = json.load(source)["installed"]
    expected_keys = {"type", "client_id", "client_secret", "refresh_token"}
    valid = (
        isinstance(credentials, dict)
        and set(credentials) == expected_keys
        and credentials.get("type") == "authorized_user"
        and all(isinstance(credentials.get(key), str) and credentials[key] for key in ("client_id", "client_secret", "refresh_token"))
        and credentials["client_id"] == client.get("client_id")
        and credentials["client_secret"] == client.get("client_secret")
        and metadata.get("source_sha256") == hashlib.sha256(credential_bytes).hexdigest()
    )
except (OSError, UnicodeError, ValueError, KeyError, TypeError):
    valid = False
finally:
    if credential_fd is not None:
        os.close(credential_fd)
sys.exit(0 if valid else 1)
PY
}

copy_imported_credentials() {
  local source="$1" destination="$2"
  SOURCE_PATH="$source" DESTINATION_PATH="$destination" IMPORT_ROOT="$SECRETS_BASE/gws-import" CLIENT_FILE="$CLIENT_PATH" /usr/bin/python3 -I - <<'PY'
import hashlib
import json
import os
import stat
import sys

def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result

def safe_import_root(path):
    metadata = os.lstat(path)
    return (
        os.path.isabs(path)
        and os.path.normpath(path) == path
        and os.path.realpath(path) == path
        and stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )

def safe_source(metadata):
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == 1
    )

def identity(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_uid,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        getattr(metadata, "st_mtime_ns", int(metadata.st_mtime * 1000000000)),
        getattr(metadata, "st_ctime_ns", int(metadata.st_ctime * 1000000000)),
    )

source_path = os.environ["SOURCE_PATH"]
destination_path = os.environ["DESTINATION_PATH"]
root = os.environ["IMPORT_ROOT"]
source_fd = None
destination_fd = None
try:
    if not safe_import_root(root):
        raise ValueError("unsafe import root")
    root = os.path.realpath(root)
    if (
        not os.path.isabs(source_path)
        or os.path.normpath(source_path) != source_path
        or os.path.dirname(source_path) != root
        or os.path.realpath(source_path) != source_path
    ):
        raise ValueError("source must be a canonical direct child")
    before = os.lstat(source_path)
    if not safe_source(before):
        raise ValueError("unsafe source")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    source_fd = os.open(source_path, flags)
    opened = os.fstat(source_fd)
    if not safe_source(opened) or identity(opened) != identity(before):
        raise ValueError("source changed before read")
    credential_bytes = b""
    while True:
        chunk = os.read(source_fd, 65536)
        if not chunk:
            break
        credential_bytes += chunk
    credentials = json.loads(credential_bytes.decode("utf-8"), object_pairs_hook=reject_duplicates)
    with open(os.environ["CLIENT_FILE"], encoding="utf-8") as source:
        client = json.load(source)["installed"]
    expected_keys = {"type", "client_id", "client_secret", "refresh_token"}
    if not (
        isinstance(credentials, dict)
        and set(credentials) == expected_keys
        and credentials.get("type") == "authorized_user"
        and all(isinstance(credentials.get(key), str) and credentials[key] for key in ("client_id", "client_secret", "refresh_token"))
        and credentials["client_id"] == client.get("client_id")
        and credentials["client_secret"] == client.get("client_secret")
    ):
        raise ValueError("invalid authorized user")
    digest = hashlib.sha256(credential_bytes).hexdigest()
    destination_fd = os.open(destination_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    view = memoryview(credential_bytes)
    while view:
        written = os.write(destination_fd, view)
        view = view[written:]
    os.fsync(destination_fd)
    destination_metadata = os.fstat(destination_fd)
    if not safe_source(destination_metadata):
        raise ValueError("unsafe destination")
    os.close(destination_fd)
    destination_fd = None
    with open(destination_path, "rb") as copied:
        if hashlib.sha256(copied.read()).hexdigest() != digest:
            raise ValueError("candidate digest mismatch")
    os.lseek(source_fd, 0, os.SEEK_SET)
    reread = b""
    while True:
        chunk = os.read(source_fd, 65536)
        if not chunk:
            break
        reread += chunk
    after_fd = os.fstat(source_fd)
    after_path = os.lstat(source_path)
    if (
        identity(after_fd) != identity(opened)
        or identity(after_path) != identity(before)
        or hashlib.sha256(reread).hexdigest() != digest
    ):
        raise ValueError("source changed during copy")
    print(digest)
except (OSError, UnicodeError, ValueError, KeyError, TypeError):
    try:
        os.unlink(destination_path)
    except OSError:
        pass
    sys.exit(1)
finally:
    if source_fd is not None:
        os.close(source_fd)
    if destination_fd is not None:
        os.close(destination_fd)
PY
}

ensure_secrets_root() {
  local parent
  if [ -e "$SECRETS_BASE" ] || [ -L "$SECRETS_BASE" ]; then
    secrets_base_is_private || die "secrets base is unsafe"
  else
    parent="${SECRETS_BASE%/*}"
    [ "$parent" != "$SECRETS_BASE" ] || die "secrets base must be an absolute canonical path"
    [ ! -L "$parent" ] || die "refusing symlinked secrets base parent"
    /bin/mkdir -p "$parent" || die "unable to create secrets base parent"
    [ "$(canonical_dir "$parent")" = "$parent" ] || die "secrets base parent is not canonical"
    /bin/mkdir "$SECRETS_BASE" || die "unable to create secrets base"
    chmod 700 "$SECRETS_BASE" || die "unable to protect secrets base"
    secrets_base_is_private || die "secrets base is unsafe"
  fi
  if [ -e "$SECRETS_ROOT" ] || [ -L "$SECRETS_ROOT" ]; then
    secrets_root_is_private || die "secrets root is unsafe"
    return 0
  fi
  /bin/mkdir "$SECRETS_ROOT" || die "unable to create secrets root"
  chmod 700 "$SECRETS_ROOT" || die "unable to protect secrets root"
  secrets_root_is_private || die "secrets root is unsafe"
}

ensure_accounts_root() {
  secrets_root_is_private || die "secrets root is unsafe"
  if [ -e "$ACCOUNTS_ROOT" ] || [ -L "$ACCOUNTS_ROOT" ]; then
    accounts_root_is_private || die "accounts root is unsafe"
    return 0
  fi
  /bin/mkdir "$ACCOUNTS_ROOT" || die "unable to create accounts root"
  chmod 700 "$ACCOUNTS_ROOT" || die "unable to protect accounts root"
  accounts_root_is_private || die "accounts root is unsafe"
}

acquire_alias_lock() {
  local alias="$1" lock
  accounts_root_is_private || die "accounts root is unsafe"
  lock="$ACCOUNTS_ROOT/.${alias}.lock"
  /bin/mkdir "$lock" 2>/dev/null || die "account operation is already in progress or has a stale lock"
  TX_LOCK="$lock"
  chmod 700 "$lock" || die "unable to protect account lock"
}

release_alias_lock() {
  [ -n "${TX_LOCK:-}" ] || return 0
  /bin/rmdir -- "$TX_LOCK" || die "unable to release account lock"
  TX_LOCK=""
}

begin_profile_activation() {
  TX_LIVE="$1"
  TX_ACTIVATED=1
  TX_COMMITTED=0
}

commit_profile_activation() {
  TX_COMMITTED=1
}

clear_profile_activation() {
  TX_CANDIDATE=""
  TX_BACKUP=""
  TX_LIVE=""
  TX_ACTIVATED=0
  TX_COMMITTED=0
}

rename_path() {
  SOURCE_PATH="$1" DESTINATION_PATH="$2" /usr/bin/python3 -I - <<'PY'
import os
import sys

try:
    os.rename(os.environ["SOURCE_PATH"], os.environ["DESTINATION_PATH"])
except OSError:
    sys.exit(1)
PY
}

unlink_destination_if_same_file() {
  SOURCE_PATH="$1" DESTINATION_PATH="$2" /usr/bin/python3 -I - <<'PY'
import os
import stat
import sys

try:
    source = os.lstat(os.environ["SOURCE_PATH"])
    destination = os.lstat(os.environ["DESTINATION_PATH"])
    same = (
        stat.S_ISREG(source.st_mode)
        and stat.S_ISREG(destination.st_mode)
        and source.st_dev == destination.st_dev
        and source.st_ino == destination.st_ino
    )
    if not same:
        raise ValueError("destination changed")
    os.unlink(os.environ["DESTINATION_PATH"])
except (OSError, ValueError):
    sys.exit(1)
PY
}

collect_profile_entries() {
  local had_dotglob=0 had_nullglob=0
  shopt -q dotglob && had_dotglob=1
  shopt -q nullglob && had_nullglob=1
  shopt -s dotglob nullglob
  PROFILE_ENTRIES=("$ACCOUNTS_ROOT"/*)
  [ "$had_dotglob" -eq 1 ] || shopt -u dotglob
  [ "$had_nullglob" -eq 1 ] || shopt -u nullglob
}

secrets_root_inventory_is_clean() {
  local had_dotglob=0 had_nullglob=0 entry name
  shopt -q dotglob && had_dotglob=1
  shopt -q nullglob && had_nullglob=1
  shopt -s dotglob nullglob
  SECRETS_ROOT_ENTRIES=("$SECRETS_ROOT"/*)
  [ "$had_dotglob" -eq 1 ] || shopt -u dotglob
  [ "$had_nullglob" -eq 1 ] || shopt -u nullglob
  for entry in "${SECRETS_ROOT_ENTRIES[@]}"; do
    name="${entry##*/}"
    case "$name" in
      client_secret.json|accounts) ;;
      *) return 1 ;;
    esac
  done
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

profile_metadata_field() {
  PROFILE_FILE="$1/profile.json" PROFILE_FIELD="$2" /usr/bin/python3 -I - <<'PY'
import json
import os
import re
import sys

try:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    with open(os.environ["PROFILE_FILE"], encoding="utf-8") as source:
        profile = json.load(source, object_pairs_hook=reject_duplicates)
    if (
        not isinstance(profile, dict)
        or type(profile.get("schema_version")) is not int
        or profile["schema_version"] != 1
    ):
        raise ValueError("invalid profile")
    email = profile.get("expected_email")
    if not isinstance(email, str) or not email:
        raise ValueError("invalid profile")
    legacy_keys = {"schema_version", "expected_email"}
    mode_keys = {"credential_mode", "scope_policy", "source_sha256"}
    imported_keys = legacy_keys | mode_keys
    if not mode_keys.intersection(profile):
        values = {
            "expected_email": email,
            "credential_mode": "encrypted_oauth",
            "scope_policy": "exact_required",
            "source_sha256": "",
        }
    elif (
        set(profile) == imported_keys
        and profile.get("credential_mode") == "imported_authorized_user"
        and profile.get("scope_policy") == "existing_grant"
        and isinstance(profile.get("source_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", profile["source_sha256"])
    ):
        values = {
            "expected_email": email,
            "credential_mode": profile["credential_mode"],
            "scope_policy": profile["scope_policy"],
            "source_sha256": profile["source_sha256"],
        }
    else:
        raise ValueError("invalid profile")
    value = values[os.environ["PROFILE_FIELD"]]
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(1)
print(value)
PY
}

profile_expected_email() {
  profile_metadata_field "$1" expected_email
}

profile_credential_mode() {
  profile_metadata_field "$1" credential_mode
}

run_isolated() {
  local profile="$1" mode="$2"
  shift 2
  cd / || return 1
  if [ "$mode" = "imported_authorized_user" ]; then
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
      GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE="$profile/credentials.json" \
      GOOGLE_APPLICATION_CREDENTIALS="$profile/missing-adc.json" \
      "$GWS_BIN" "$@"
    return
  fi
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
  local expected="$1" status="$2" mode="$3" profile="$4"
  EXPECTED_EMAIL="$expected" STATUS_JSON="$status" CREDENTIAL_MODE="$mode" PROFILE_PATH="$profile" /usr/bin/python3 -I - <<'PY'
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
    common = (
        isinstance(status.get("user"), str)
        and status["user"].casefold() == os.environ["EXPECTED_EMAIL"].casefold()
        and status.get("token_valid") is True
        and status.get("keyring_backend") == "file"
        and isinstance(scopes, list)
    )
    if os.environ["CREDENTIAL_MODE"] == "encrypted_oauth":
        healthy = (
            common
            and status.get("storage") == "encrypted"
            and status.get("encrypted_credentials_exists") is True
            and status.get("encryption_valid") is True
            and status.get("plain_credentials_exists") is False
            and len(scopes) == len(required_scopes)
            and set(scopes) == required_scopes
        )
    elif os.environ["CREDENTIAL_MODE"] == "imported_authorized_user":
        profile = os.environ["PROFILE_PATH"]
        healthy = (
            common
            and status.get("storage") == "plaintext"
            and status.get("plain_credentials_exists") is True
            and status.get("encrypted_credentials_exists") is False
            and status.get("has_refresh_token") is True
            and status.get("plain_credentials") == os.path.join(profile, "credentials.json")
            and status.get("client_config") == os.path.join(profile, "client_secret.json")
            and len(scopes) == len(set(scopes))
            and all(isinstance(scope, str) for scope in scopes)
            and required_scopes.issubset(set(scopes))
            and "https://mail.google.com/" not in scopes
        )
    else:
        healthy = False
except (ValueError, TypeError, KeyError):
    healthy = False
sys.exit(0 if healthy else 1)
PY
}

live_identity_matches_expected() {
  local expected="$1" profile_json="$2"
  EXPECTED_EMAIL="$expected" PROFILE_JSON="$profile_json" /usr/bin/python3 -I - <<'PY'
import json
import os
import sys

try:
    profile = json.loads(os.environ["PROFILE_JSON"])
    email = profile["emailAddress"]
    valid = isinstance(email, str) and email.casefold() == os.environ["EXPECTED_EMAIL"].casefold()
except (ValueError, KeyError, TypeError):
    valid = False
sys.exit(0 if valid else 1)
PY
}

credential_state_is_complete() {
  local profile="$1" mode="$2"
  private_regular_file "$profile/profile.json" || return 1
  private_regular_file "$profile/client_secret.json" || return 1
  if [ "$mode" = "encrypted_oauth" ]; then
    private_regular_file "$profile/credentials.enc" || return 1
    private_regular_file "$profile/.encryption_key" || return 1
    [ ! -e "$profile/credentials.json" ] && [ ! -L "$profile/credentials.json" ]
    return
  fi
  [ "$mode" = "imported_authorized_user" ] || return 1
  private_regular_file "$profile/credentials.json" || return 1
  [ ! -e "$profile/credentials.enc" ] && [ ! -L "$profile/credentials.enc" ] || return 1
  validate_imported_profile_state "$profile"
}

check_profile_health() {
  local profile="$1" expected="$2" alias="$3" mode="$4" status identity
  profile_state_is_private "$profile" || { printf '%s: private permissions check failed\n' "$alias" >&2; return 1; }
  validate_runtime_client_json "$profile/client_secret.json" || { printf '%s: invalid runtime client\n' "$alias" >&2; return 1; }
  runtime_client_matches_registered "$profile/client_secret.json" || { printf '%s: runtime client does not match registration\n' "$alias" >&2; return 1; }
  credential_state_is_complete "$profile" "$mode" || { printf '%s: incomplete or invalid credential state\n' "$alias" >&2; return 1; }
  runtime_ready || { printf '%s: gws runtime unavailable\n' "$alias" >&2; return 1; }
  status="$(run_isolated "$profile" "$mode" auth status 2>/dev/null)" || { printf '%s: credentials unavailable\n' "$alias" >&2; return 1; }
  status_is_healthy "$expected" "$status" "$mode" "$profile" || { printf '%s: identity, token, credential mode, or scope check failed\n' "$alias" >&2; return 1; }
  identity="$(run_isolated "$profile" "$mode" gmail users getProfile --params '{"userId":"me"}' --format json 2>/dev/null)" || { printf '%s: live identity check failed\n' "$alias" >&2; return 1; }
  live_identity_matches_expected "$expected" "$identity" || { printf '%s: live identity check failed\n' "$alias" >&2; return 1; }
  printf '%s: ready\n' "$alias"
}

check_account() {
  local alias="$1"
  local profile expected mode
  profile="$(profile_for_alias "$alias")" || { printf '%s: invalid profile\n' "$alias" >&2; return 1; }
  private_regular_file "$profile/profile.json" || { printf '%s: invalid profile\n' "$alias" >&2; return 1; }
  expected="$(profile_expected_email "$profile")" || { printf '%s: invalid profile\n' "$alias" >&2; return 1; }
  mode="$(profile_credential_mode "$profile")" || { printf '%s: invalid profile\n' "$alias" >&2; return 1; }
  check_profile_health "$profile" "$expected" "$alias" "$mode"
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
  ensure_runtime_dir
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
  local candidate
  validate_registered_client_json "$1" || die "invalid Desktop OAuth client JSON"
  [ ! -e "$CLIENT_PATH" ] && [ ! -L "$CLIENT_PATH" ] || die "OAuth client already registered; refusing replacement"
  ensure_secrets_root
  [ ! -e "$CLIENT_PATH" ] && [ ! -L "$CLIENT_PATH" ] || die "OAuth client already registered; refusing replacement"
  candidate="$(mktemp "$SECRETS_ROOT/.client_secret.json.XXXXXX")" || die "unable to create OAuth client candidate"
  TX_CLIENT_CANDIDATE="$candidate"
  /bin/cp "$1" "$candidate" || die "unable to copy OAuth client candidate"
  chmod 600 "$candidate" || die "unable to protect OAuth client candidate"
  validate_registered_client_json "$candidate" || die "copied OAuth client candidate is invalid"
  private_regular_file "$candidate" || die "copied OAuth client candidate is unsafe"
  /bin/ln "$candidate" "$CLIENT_PATH" || die "OAuth client already registered; refusing replacement"
  if ! registered_client_is_private; then
    unlink_destination_if_same_file "$candidate" "$CLIENT_PATH" || die "stored OAuth client failed readback and rollback"
    die "stored OAuth client failed readback"
  fi
  /bin/rm -- "$candidate" || die "unable to clean OAuth client candidate"
  TX_CLIENT_CANDIDATE=""
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
  ensure_accounts_root
  acquire_alias_lock "$alias"
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
  /bin/mkdir "$profile" || die "unable to reserve account profile path"
  TX_RESERVATION="$profile"
  chmod 700 "$profile" || die "unable to protect reserved account profile path"
  candidate="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.add.XXXXXX")" || die "unable to create candidate account profile"
  chmod 700 "$candidate" || die "unable to protect candidate account profile"
  TX_CANDIDATE="$candidate"
  if ! write_runtime_client "$candidate/client_secret.json"; then
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
  if ! run_isolated "$candidate" encrypted_oauth auth login --scopes "$GMAIL_SCOPE"; then
    die "OAuth login failed; candidate profile will be removed"
  fi
  if ! check_profile_health "$candidate" "$email" "$alias" encrypted_oauth; then
    die "OAuth login identity check failed; candidate profile will be removed"
  fi
  begin_profile_activation "$profile"
  rename_path "$candidate" "$profile" || die "unable to activate candidate account profile"
  TX_RESERVATION=""
  if ! check_account "$alias"; then
    die "activated account profile failed live readback; transaction will roll back"
  fi
  commit_profile_activation
  clear_profile_activation
  release_alias_lock
  printf 'Account %s added\n' "$alias"
}

emails_match() {
  LEFT_EMAIL="$1" RIGHT_EMAIL="$2" /usr/bin/python3 -I - <<'PY'
import os
import sys
sys.exit(0 if os.environ["LEFT_EMAIL"].casefold() == os.environ["RIGHT_EMAIL"].casefold() else 1)
PY
}

import_account() {
  local source="" email="" alias="" replace=0 seen_source=0 seen_email=0 seen_alias=0 seen_replace=0
  local profile existing expected existing_mode candidate digest backup
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --email)
        [ "$seen_email" -eq 0 ] && [ "$#" -ge 2 ] || usage
        email="$2"; seen_email=1; shift 2
        ;;
      --alias)
        [ "$seen_alias" -eq 0 ] && [ "$#" -ge 2 ] || usage
        alias="$2"; seen_alias=1; shift 2
        ;;
      --replace)
        [ "$seen_replace" -eq 0 ] || usage
        replace=1; seen_replace=1; shift
        ;;
      --*) usage ;;
      *)
        [ "$seen_source" -eq 0 ] || usage
        source="$1"; seen_source=1; shift
        ;;
    esac
  done
  [ "$seen_source" -eq 1 ] && [ -n "$source" ] && [ "$seen_email" -eq 1 ] && [ -n "$email" ] && [ "$seen_alias" -eq 1 ] && [ -n "$alias" ] || usage
  validate_alias "$alias" || die "invalid account alias"
  registered_client_is_private || die "a valid protected registered OAuth client is required"
  runtime_ready || die "gws runtime is unavailable or untrusted"
  ensure_accounts_root
  acquire_alias_lock "$alias"
  profile="$ACCOUNTS_ROOT/$alias"
  [ ! -L "$profile" ] || die "refusing symlinked account profile"
  if [ -e "$profile" ]; then
    [ "$replace" -eq 1 ] || die "account alias already exists"
    existing="$(profile_for_alias "$alias")" || die "invalid existing account profile"
    private_regular_file "$existing/profile.json" || die "invalid existing account profile"
    expected="$(profile_expected_email "$existing")" || die "invalid existing account profile"
    existing_mode="$(profile_credential_mode "$existing")" || die "invalid existing account profile"
    [ "$existing_mode" = "imported_authorized_user" ] || die "--replace is only supported for imported account profiles"
    emails_match "$expected" "$email" || die "account alias belongs to another expected email"
  else
    [ "$replace" -eq 0 ] || die "--replace requires an existing imported account profile"
    /bin/mkdir "$profile" || die "unable to reserve account profile path"
    TX_RESERVATION="$profile"
    chmod 700 "$profile" || die "unable to protect reserved account profile path"
  fi
  candidate="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.import.XXXXXX")" || die "unable to create imported account candidate"
  chmod 700 "$candidate" || die "unable to protect imported account candidate"
  TX_CANDIDATE="$candidate"
  if ! write_runtime_client "$candidate/client_secret.json"; then
    die "unable to copy registered OAuth client"
  fi
  validate_runtime_client_json "$candidate/client_secret.json" || die "copied OAuth client is invalid"
  private_regular_file "$candidate/client_secret.json" || die "copied OAuth client is unsafe"
  runtime_client_matches_registered "$candidate/client_secret.json" || die "copied OAuth client mismatch"
  digest="$(copy_imported_credentials "$source" "$candidate/credentials.json")" || die "invalid or unsafe imported authorized-user credentials"
  EMAIL="$email" DIGEST="$digest" PROFILE_FILE="$candidate/profile.json" /usr/bin/python3 -I - <<'PY' || die "unable to write imported account metadata"
import json
import os
with open(os.environ["PROFILE_FILE"], "w", encoding="utf-8") as destination:
    json.dump({
        "schema_version": 1,
        "expected_email": os.environ["EMAIL"],
        "credential_mode": "imported_authorized_user",
        "scope_policy": "existing_grant",
        "source_sha256": os.environ["DIGEST"],
    }, destination)
    destination.write("\n")
PY
  chmod 600 "$candidate/profile.json" || die "unable to protect imported account metadata"
  if ! check_profile_health "$candidate" "$email" "$alias" imported_authorized_user >/dev/null; then
    die "imported credential identity or health check failed; live profile remains unchanged"
  fi
  if [ "$replace" -eq 0 ]; then
    begin_profile_activation "$profile"
    rename_path "$candidate" "$profile" || die "unable to activate imported account profile"
    TX_RESERVATION=""
    if ! check_account "$alias" >/dev/null; then
      die "activated imported account profile failed live readback; transaction will roll back"
    fi
    commit_profile_activation
  else
    backup="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.backup.XXXXXX")" || die "unable to reserve profile backup"
    /bin/rmdir -- "$backup" || die "unable to reserve profile backup"
    TX_BACKUP="$backup"
    TX_LIVE="$profile"
    if ! rename_path "$profile" "$backup"; then
      TX_BACKUP=""
      die "unable to stage live profile; live profile remains unchanged"
    fi
    begin_profile_activation "$profile"
    rename_path "$candidate" "$profile" || die "unable to activate imported replacement; transaction will roll back"
    if ! check_account "$alias" >/dev/null; then
      die "imported replacement failed live readback; transaction will roll back"
    fi
    commit_profile_activation
    if ! /bin/rm -rf -- "$backup"; then
      die "imported replacement activated but backup cleanup failed"
    fi
  fi
  clear_profile_activation
  release_alias_lock
  printf 'Account %s imported\n' "$alias"
}

migrate_account() {
  [ "$#" -eq 1 ] || usage
  local alias="$1" profile expected mode candidate backup
  validate_alias "$alias" || die "invalid profile"
  registered_client_is_private || die "a valid protected registered OAuth client is required"
  accounts_root_is_private || die "invalid profile"
  acquire_alias_lock "$alias"
  profile="$(profile_for_alias "$alias")" || die "invalid profile"
  private_regular_file "$profile/profile.json" || die "invalid profile"
  expected="$(profile_expected_email "$profile")" || die "invalid profile"
  mode="$(profile_credential_mode "$profile")" || die "invalid profile"
  profile_state_is_private "$profile" || die "existing profile has unsafe permissions"
  credential_state_is_complete "$profile" "$mode" || die "existing profile has incomplete or invalid credential state"
  if runtime_client_matches_registered "$profile/client_secret.json"; then
    check_account "$alias" >/dev/null || die "already-migrated profile failed health check"
    release_alias_lock
    printf 'Account %s already migrated\n' "$alias"
    return 0
  fi
  legacy_runtime_client_matches_registered "$profile/client_secret.json" || die "legacy profile client does not match registration"
  runtime_ready || die "gws runtime is unavailable or untrusted"
  candidate="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.migrate.XXXXXX")" || die "unable to create migration candidate"
  chmod 700 "$candidate" || die "unable to protect migration candidate"
  TX_CANDIDATE="$candidate"
  cp -pR "$profile/." "$candidate" || die "unable to stage migration candidate"
  /bin/rm -- "$candidate/client_secret.json" || die "unable to prepare migration runtime client"
  write_runtime_client "$candidate/client_secret.json" || die "unable to write migration runtime client"
  private_regular_file "$candidate/client_secret.json" || die "migration runtime client is unsafe"
  runtime_client_matches_registered "$candidate/client_secret.json" || die "migration runtime client does not match registration"
  if ! check_profile_health "$candidate" "$expected" "$alias" "$mode" >/dev/null; then
    die "migration candidate identity or health check failed; live profile remains unchanged"
  fi
  backup="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.backup.XXXXXX")" || die "unable to reserve profile backup"
  /bin/rmdir -- "$backup" || die "unable to reserve profile backup"
  TX_BACKUP="$backup"
  TX_LIVE="$profile"
  if ! rename_path "$profile" "$backup"; then
    TX_BACKUP=""
    die "unable to stage live profile; live profile remains unchanged"
  fi
  begin_profile_activation "$profile"
  rename_path "$candidate" "$profile" || die "unable to activate migrated profile; transaction will roll back"
  if ! check_account "$alias" >/dev/null; then
    die "migrated profile failed live readback; transaction will roll back"
  fi
  commit_profile_activation
  if ! /bin/rm -rf -- "$backup"; then
    die "migrated profile activated but backup cleanup failed"
  fi
  clear_profile_activation
  release_alias_lock
  printf 'Account %s migrated\n' "$alias"
}

reauth_account() {
  [ "$#" -eq 1 ] || usage
  local alias="$1" profile expected mode candidate backup
  validate_alias "$alias" || die "invalid profile"
  accounts_root_is_private || die "invalid profile"
  acquire_alias_lock "$alias"
  profile="$(profile_for_alias "$alias")" || die "invalid profile"
  private_regular_file "$profile/profile.json" || die "invalid profile"
  expected="$(profile_expected_email "$profile")" || die "invalid profile"
  mode="$(profile_credential_mode "$profile")" || die "invalid profile"
  [ "$mode" = "encrypted_oauth" ] || die "imported profiles cannot be reauthenticated; use --import-account FILE --email EMAIL --alias $alias --replace"
  validate_runtime_client_json "$profile/client_secret.json" || die "invalid profile client"
  runtime_client_matches_registered "$profile/client_secret.json" || die "profile client does not match registration"
  profile_state_is_private "$profile" || die "existing profile has unsafe permissions"
  runtime_ready || die "gws runtime is unavailable or untrusted"
  candidate="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.reauth.XXXXXX")" || die "unable to create reauthentication candidate"
  chmod 700 "$candidate" || die "unable to protect reauthentication candidate"
  TX_CANDIDATE="$candidate"
  cp -pR "$profile/." "$candidate" || die "unable to stage reauthentication candidate"
  if ! run_isolated "$candidate" encrypted_oauth auth login --scopes "$GMAIL_SCOPE"; then
    die "OAuth login failed; live profile remains unchanged"
  fi
  if ! check_profile_health "$candidate" "$expected" "$alias" encrypted_oauth; then
    die "OAuth login identity check failed; live profile remains unchanged"
  fi
  backup="$(mktemp -d "$ACCOUNTS_ROOT/.${alias}.backup.XXXXXX")" || die "unable to reserve profile backup"
  /bin/rmdir -- "$backup" || die "unable to reserve profile backup"
  TX_BACKUP="$backup"
  TX_LIVE="$profile"
  if ! rename_path "$profile" "$backup"; then
    TX_BACKUP=""
    die "unable to stage live profile; live profile remains unchanged"
  fi
  begin_profile_activation "$profile"
  rename_path "$candidate" "$profile" || die "unable to activate reauthenticated profile; transaction will roll back"
  if ! check_account "$alias"; then
    die "reauthenticated profile failed live readback; transaction will roll back"
  fi
  commit_profile_activation
  if ! /bin/rm -rf -- "$backup"; then
    die "reauthenticated profile activated but backup cleanup failed"
  fi
  clear_profile_activation
  release_alias_lock
  printf 'Account %s reauthenticated\n' "$alias"
}

check_all() {
  local failed=0 alias alias_path
  if platform_ready; then printf 'Platform: ready (macOS arm64)\n'; else printf 'Platform: unsupported (requires macOS arm64)\n'; failed=1; fi
  if runtime_ready; then printf 'gws runtime: ready (%s)\n' "$VERSION"; else printf 'gws runtime: missing (expected %s)\n' "$VERSION"; failed=1; fi
  if [ ! -e "$SECRETS_BASE" ] && [ ! -L "$SECRETS_BASE" ]; then
    printf 'OAuth client: missing\n'
    printf 'Profiles: none\n'
    failed=1
  elif ! secrets_base_is_private; then
    printf 'OAuth client: unsafe\n'
    printf 'Profiles: unsafe\n'
    failed=1
  elif [ ! -e "$SECRETS_ROOT" ] && [ ! -L "$SECRETS_ROOT" ]; then
    printf 'OAuth client: missing\n'
    printf 'Profiles: none\n'
    failed=1
  else
    if ! secrets_root_is_private; then
      printf 'OAuth client: unsafe\n'
      printf 'Profiles: unsafe\n'
      failed=1
    elif ! secrets_root_inventory_is_clean; then
      printf 'OAuth client: unsafe\n'
      printf 'Profiles: unsafe\n'
      failed=1
    else
      if [ ! -e "$CLIENT_PATH" ] && [ ! -L "$CLIENT_PATH" ]; then
        printf 'OAuth client: missing\n'
        failed=1
      elif registered_client_is_private; then
        printf 'OAuth client: ready\n'
      else
        printf 'OAuth client: unsafe\n'
        failed=1
      fi
      if [ ! -e "$ACCOUNTS_ROOT" ] && [ ! -L "$ACCOUNTS_ROOT" ]; then
        printf 'Profiles: none\n'
        failed=1
      elif ! accounts_root_is_private; then
        printf 'Profiles: unsafe\n'
        failed=1
      else
        collect_profile_entries
        if [ "${#PROFILE_ENTRIES[@]}" -eq 0 ]; then
          printf 'Profiles: none\n'
          failed=1
        else
          for alias_path in "${PROFILE_ENTRIES[@]}"; do
            alias="${alias_path##*/}"
            if ! validate_alias "$alias"; then
              printf 'Profiles: unsafe entry\n'
              failed=1
            elif check_account "$alias"; then
              :
            else
              failed=1
            fi
          done
        fi
      fi
    fi
  fi
  [ "$failed" -eq 0 ] && printf 'Overall: ready\n'
  return "$failed"
}

list_accounts() {
  [ "$#" -eq 0 ] || usage
  if [ ! -e "$SECRETS_BASE" ] && [ ! -L "$SECRETS_BASE" ]; then
    printf 'Profiles: none\n'
    return 0
  fi
  if ! secrets_base_is_private; then
    printf 'Profiles: unsafe\n'
    return 1
  fi
  if [ ! -e "$SECRETS_ROOT" ] && [ ! -L "$SECRETS_ROOT" ]; then
    printf 'Profiles: none\n'
    return 0
  fi
  if ! secrets_root_is_private; then
    printf 'Profiles: unsafe\n'
    return 1
  fi
  if ! secrets_root_inventory_is_clean; then
    printf 'Profiles: unsafe\n'
    return 1
  fi
  if [ ! -e "$ACCOUNTS_ROOT" ] && [ ! -L "$ACCOUNTS_ROOT" ]; then
    printf 'Profiles: none\n'
    return 0
  fi
  if ! accounts_root_is_private; then
    printf 'Profiles: unsafe\n'
    return 1
  fi
  local alias_path alias failed=0
  collect_profile_entries
  if [ "${#PROFILE_ENTRIES[@]}" -eq 0 ]; then
    printf 'Profiles: none\n'
    return 0
  fi
  for alias_path in "${PROFILE_ENTRIES[@]}"; do
    alias="${alias_path##*/}"
    if ! validate_alias "$alias"; then
      printf 'Profiles: unsafe entry\n'
      failed=1
    elif check_account "$alias"; then
      :
    else
      failed=1
    fi
  done
  return "$failed"
}

case "${1:-}" in
  --check) [ "$#" -eq 1 ] || usage; check_all ;;
  --install) [ "$#" -eq 1 ] || usage; install_gws ;;
  --register-client) shift; register_client "$@" ;;
  --add-account) shift; [ "$#" -ge 1 ] || usage; add_account "$@" ;;
  --import-account) shift; import_account "$@" ;;
  --migrate-account) shift; migrate_account "$@" ;;
  --reauth-account) shift; reauth_account "$@" ;;
  --check-account) shift; [ "$#" -eq 1 ] || usage; check_account "$1" ;;
  --list-accounts) shift; list_accounts "$@" ;;
  *) usage ;;
esac
