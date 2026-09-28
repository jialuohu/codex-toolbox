#!/bin/bash
# Runtime isolation only. The owning Gmail skill determines permitted operations.
usage() {
  printf '%s\n' 'Usage: gws-account.sh check --alias ALIAS' \
    '       gws-account.sh run --alias ALIAS --expected-email EMAIL -- GWS_ARGUMENTS...' >&2
  exit 2
}

mode="${1-}"
[ "$#" -gt 0 ] || usage
shift
[ "$#" -ge 2 ] && [ "$1" = "--alias" ] || usage
alias="$2"
shift 2
case "$mode" in
  check) [ "$#" -eq 0 ] || usage ;;
  run)
    [ "$#" -ge 4 ] && [ "$1" = "--expected-email" ] && [ -n "$2" ] || usage
    requested_email="$2"
    shift 2
    [ "$1" = "--" ] || usage
    shift
    case "$1" in gmail|schema) ;; *) usage ;; esac
    ;;
  *) usage ;;
esac

case "$alias" in
  ''|.|..|*/*|*'\'*) exit 1 ;;
esac
[[ "$alias" =~ ^[a-z0-9][a-z0-9._-]{0,62}$ ]] || exit 1

secrets_root_path="${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}"
[ -d "$secrets_root_path" ] && [ ! -L "$secrets_root_path" ] || exit 1
secrets_root="$(cd -P "$secrets_root_path" && pwd)" || exit 1
[ "$secrets_root" = "$secrets_root_path" ] || exit 1

gws_root_path="$secrets_root/gws"
[ -d "$gws_root_path" ] && [ ! -L "$gws_root_path" ] || exit 1
gws_root="$(cd -P "$gws_root_path" && pwd)" || exit 1
[ "$gws_root" = "$gws_root_path" ] || exit 1

accounts_root_path="$gws_root/accounts"
[ -d "$accounts_root_path" ] && [ ! -L "$accounts_root_path" ] || exit 1
accounts_root="$(cd -P "$accounts_root_path" && pwd)" || exit 1
[ "$accounts_root" = "$accounts_root_path" ] || exit 1
profile="$accounts_root/$alias"

expected_email="$(
  SECRETS_ROOT="$secrets_root" GWS_ROOT="$gws_root" \
    ACCOUNTS_ROOT="$accounts_root" PROFILE_DIR="$profile" PROFILE_ALIAS="$alias" \
    /usr/bin/python3 -I - <<'PY'
import json
import os
import stat
import sys

secrets_root = os.environ["SECRETS_ROOT"]
gws_root = os.environ["GWS_ROOT"]
root = os.environ["ACCOUNTS_ROOT"]
profile = os.environ["PROFILE_DIR"]
alias = os.environ["PROFILE_ALIAS"]

def reject(error):
    raise error

def check(path, kind, mode):
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not kind(metadata.st_mode):
        raise ValueError("unsafe profile object")
    if stat.S_IMODE(metadata.st_mode) != mode:
        raise ValueError("unsafe profile mode")

try:
    secrets_real = os.path.realpath(secrets_root)
    gws_real = os.path.realpath(gws_root)
    root_real = os.path.realpath(root)
    profile_real = os.path.realpath(profile)
    if secrets_root != secrets_real:
        raise ValueError("secrets root is not canonical")
    if gws_root != gws_real or os.path.dirname(gws_real) != secrets_real:
        raise ValueError("gws root is not a canonical direct child")
    if os.path.basename(gws_real) != "gws":
        raise ValueError("gws root name mismatch")
    if root != root_real or os.path.dirname(root_real) != gws_real:
        raise ValueError("accounts root is not a canonical direct child")
    if os.path.basename(root_real) != "accounts":
        raise ValueError("accounts root name mismatch")
    if os.path.dirname(profile_real) != root_real:
        raise ValueError("profile is not a canonical direct child")
    if os.path.basename(profile_real) != alias or profile != os.path.join(root, alias):
        raise ValueError("profile alias mismatch")

    check(secrets_root, stat.S_ISDIR, 0o700)
    check(gws_root, stat.S_ISDIR, 0o700)
    check(root, stat.S_ISDIR, 0o700)
    check(profile, stat.S_ISDIR, 0o700)
    for current, directories, files in os.walk(
        profile, topdown=True, followlinks=False, onerror=reject
    ):
        for name in directories:
            check(os.path.join(current, name), stat.S_ISDIR, 0o700)
        for name in files:
            check(os.path.join(current, name), stat.S_ISREG, 0o600)

    if os.path.lexists(os.path.join(profile, "credentials.json")):
        raise ValueError("plaintext profile credentials are forbidden")

    for name in (
        "profile.json",
        "client_secret.json",
        "credentials.enc",
        ".encryption_key",
    ):
        check(os.path.join(profile, name), stat.S_ISREG, 0o600)

    with open(os.path.join(profile, "profile.json"), encoding="utf-8") as source:
        metadata = json.load(source)
    email = metadata["expected_email"]
    if metadata["schema_version"] != 1 or not isinstance(email, str) or not email:
        raise ValueError("invalid profile metadata")
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(1)

print(email)
PY
)" || exit 1

gws_runtime_path="${XDG_DATA_HOME:-$HOME/.local/share}/codex-toolbox/gws/0.22.5/gws"
gws_runtime_dir="${gws_runtime_path%/gws}"
RUNTIME_DIR_PATH="$gws_runtime_dir" RUNTIME_BINARY_PATH="$gws_runtime_path" \
  /usr/bin/python3 -I - <<'PY' || exit 1
import os
import stat
import sys

try:
    runtime_dir = os.environ["RUNTIME_DIR_PATH"]
    binary = os.environ["RUNTIME_BINARY_PATH"]
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
    for component in components:
        metadata = os.lstat(component)
        mode = stat.S_IMODE(metadata.st_mode)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid not in trusted_owners
            or mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise ValueError("unsafe runtime directory")
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
gws_bin="$gws_runtime_path"
gws_sha_output="$(/usr/bin/shasum -a 256 "$gws_bin" 2>/dev/null)" || exit 1
gws_sha256="${gws_sha_output%% *}"
[ "$gws_sha256" = "0f27b8b0815bf09cdf95da48d3c604f05ceb8f16bf5c9f0ba355b1f957cdd47e" ] || exit 1
version_output="$("$gws_bin" --version 2>/dev/null)" || exit 1
first_line="${version_output%%$'\n'*}"
[ "$first_line" = "gws 0.22.5" ] || exit 1

isolated_gws() (
  cd / || exit 1
  /usr/bin/env -u GOOGLE_WORKSPACE_CLI_TOKEN \
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
    "$gws_bin" "$@"
)

status_json="$(isolated_gws auth status)" || exit 1

EXPECTED_EMAIL="$expected_email" STATUS_JSON="$status_json" \
  /usr/bin/python3 -I - <<'PY' || exit 1
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
    accepted_scope_sets = (
        required_scopes,
        required_scopes | {"email", "profile"},
    )
    scope_set = set(scopes) if isinstance(scopes, list) else set()
    healthy = (
        isinstance(status.get("user"), str)
        and status["user"].casefold() == os.environ["EXPECTED_EMAIL"].casefold()
        and status.get("token_valid") is True
        and status.get("storage") == "encrypted"
        and status.get("keyring_backend") == "file"
        and status.get("encrypted_credentials_exists") is True
        and status.get("plain_credentials_exists") is False
        and status.get("encryption_valid") is True
        and isinstance(scopes, list)
        and len(scopes) == len(scope_set)
        and any(scope_set == accepted for accepted in accepted_scope_sets)
    )
except (ValueError, TypeError, KeyError):
    healthy = False
sys.exit(0 if healthy else 1)
PY

if [ "$mode" = "check" ]; then
  PROFILE_ALIAS="$alias" EXPECTED_EMAIL="$expected_email" /usr/bin/python3 -I - <<'PY'
import json
import os
print(json.dumps({"alias": os.environ["PROFILE_ALIAS"],
                  "expected_email": os.environ["EXPECTED_EMAIL"]},
                 separators=(",", ":")))
PY
  exit "$?"
fi

EXPECTED_EMAIL="$expected_email" REQUESTED_EMAIL="$requested_email" \
  /usr/bin/python3 -I - <<'PY' || exit 1
import os
import sys
sys.exit(0 if os.environ["EXPECTED_EMAIL"].casefold()
         == os.environ["REQUESTED_EMAIL"].casefold() else 1)
PY
isolated_gws "$@"
