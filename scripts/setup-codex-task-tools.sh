#!/usr/bin/env bash
# Install or inspect the toolbox-owned Codex task broker for the active plugin.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_TASK_HOME="${CODEX_HOME:-$HOME/.codex}"
MARKETPLACE_NAME="${CODEX_TASK_MARKETPLACE_NAME:-jialuo-codex-toolbox}"
PACKAGE_VERSION="0.1.1"
RUNTIME_DIR="$CODEX_TASK_HOME/runtime/codex-task-tools"
RUNTIME_VENV="$RUNTIME_DIR/.venv"

usage() {
  echo "Usage: scripts/setup-codex-task-tools.sh --install|--check|--status" >&2
}

fail() {
  echo "$*" >&2
  exit 1
}

case "${1:-}" in
  --install|--check|--status) [ "$#" -eq 1 ] || { usage; exit 2; }; ACTION="$1" ;;
  --help|-h) [ "$#" -eq 1 ] || { usage; exit 2; }; usage; exit 0 ;;
  *) usage; exit 2 ;;
esac

[ "$(uname -s)" = "Darwin" ] || fail "Codex Task Tools requires macOS"
if [ -n "${CODEX_TASK_MARKETPLACE_NAME:-}" ] && \
   [ -z "${CODEX_TASK_DEV_MARKETPLACE_ROOT:-}" ]; then
  fail "CODEX_TASK_MARKETPLACE_NAME requires CODEX_TASK_DEV_MARKETPLACE_ROOT"
fi

CODEX_BIN="$(python3 "$ROOT/scripts/setup-codex-prerequisites.py" resolve-codex || true)"
[ -n "$CODEX_BIN" ] || fail "Codex CLI is unavailable"

MCP_JSON="$("$CODEX_BIN" mcp get codex_task_tools --json)" || \
  fail "Installed codex_task_tools MCP entry is unavailable"
MARKETPLACES_JSON="$("$CODEX_BIN" plugin marketplace list --json)" || \
  fail "Codex marketplace inventory is unavailable"

SERVER_DIR="$(
  CODEX_TASK_MCP_JSON="$MCP_JSON" \
  CODEX_TASK_HOME="$CODEX_TASK_HOME" \
  CODEX_TASK_SOURCE_ROOT="$ROOT/plugins/codex-task-tools" \
  CODEX_TASK_MARKETPLACE="$MARKETPLACE_NAME" \
  CODEX_TASK_PACKAGE_VERSION="$PACKAGE_VERSION" \
  CODEX_TASK_MARKETPLACES_JSON="$MARKETPLACES_JSON" \
  CODEX_TASK_DEV_MARKETPLACE_ROOT="${CODEX_TASK_DEV_MARKETPLACE_ROOT:-}" \
  python3 - <<'PY'
import json
import os
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


try:
    entry = json.loads(os.environ["CODEX_TASK_MCP_JSON"])
    transport = entry["transport"]
    cwd_raw = transport["cwd"]
    if not isinstance(cwd_raw, str) or not Path(cwd_raw).is_absolute():
        fail("Codex Task Tools MCP root must be absolute")
    plugin_root = Path(cwd_raw).resolve(strict=True)
    source_root = Path(os.environ["CODEX_TASK_SOURCE_ROOT"]).resolve(strict=True)
    cache_root = (
        Path(os.environ["CODEX_TASK_HOME"])
        / "plugins"
        / "cache"
        / os.environ["CODEX_TASK_MARKETPLACE"]
        / "codex-task-tools"
        / os.environ["CODEX_TASK_PACKAGE_VERSION"]
    ).resolve()
    marketplaces = json.loads(os.environ["CODEX_TASK_MARKETPLACES_JSON"])
    matching = [
        row for row in marketplaces.get("marketplaces", [])
        if row.get("name") == os.environ["CODEX_TASK_MARKETPLACE"]
    ]
    if len(matching) != 1:
        fail("Selected Codex Task Tools marketplace is unavailable")
    registration = matching[0].get("marketplaceSource")
    if not isinstance(registration, dict):
        fail("Selected Codex Task Tools marketplace source is missing")
    source_path = registration.get("source")
    local_root = (
        Path(source_path).resolve(strict=True)
        if registration.get("sourceType") == "local"
        and isinstance(source_path, str)
        and Path(source_path).is_absolute()
        else None
    )
    allowed_roots = set()
    dev_source = os.environ["CODEX_TASK_DEV_MARKETPLACE_ROOT"]
    if dev_source:
        dev_root = Path(dev_source).resolve(strict=True)
        if local_root != dev_root:
            fail("Requested development marketplace is not the registered local source")
        dev_plugin = (dev_root / "plugins" / "codex-task-tools").resolve(strict=True)
        allowed_roots.update({dev_plugin, cache_root})
    elif local_root == source_root.parent.parent:
        allowed_roots.update({source_root, cache_root})
    elif registration == {
        "sourceType": "git", "source": "https://github.com/jialuohu/codex-toolbox.git"
    }:
        allowed_roots.add(cache_root)
    else:
        fail("Selected Codex Task Tools marketplace source is unexpected")
    if plugin_root not in allowed_roots:
        fail("Installed Codex Task Tools path is outside the selected marketplace")
    manifest = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text())
    mcp = json.loads((plugin_root / ".mcp.json").read_text())
    declared = mcp["mcpServers"]["codex_task_tools"]
    expected_args = [
        "run", "--frozen", "--no-dev", "--no-editable", "--no-env-file",
        "--project", "server", "codex-task-tools-mcp",
    ]
    expected_version = os.environ["CODEX_TASK_PACKAGE_VERSION"]
    if (manifest.get("name"), manifest.get("version")) != ("codex-task-tools", expected_version):
        fail("Installed Codex Task Tools manifest is unexpected")
    if (manifest.get("mcpServers"), manifest.get("skills")) != ("./.mcp.json", "./skills/"):
        fail("Installed Codex Task Tools layout is unexpected")
    if set(mcp.get("mcpServers", {})) != {"codex_task_tools"}:
        fail("Installed Codex Task Tools MCP declaration is unexpected")
    if (
        transport.get("type") != "stdio"
        or transport.get("command") != "uv"
        or transport.get("args") != expected_args
        or declared.get("command") != "uv"
        or declared.get("args") != expected_args
        or declared.get("cwd") != "."
        or declared.get("env_vars") != ["CODEX_HOME"]
    ):
        fail("Installed Codex Task Tools MCP transport is unexpected")
    if (declared.get("default_tools_approval_mode") != "auto"
        or "tools" in declared):
        fail("Installed Codex Task Tools approval policy is unexpected")
    if not (plugin_root / "server" / "pyproject.toml").is_file():
        fail("Installed Codex Task Tools package is missing")
    if not (plugin_root / "server" / "uv.lock").is_file():
        fail("Installed Codex Task Tools dependency lock is missing")
    project_text = (plugin_root / "server" / "pyproject.toml").read_text()
    lock_text = (plugin_root / "server" / "uv.lock").read_text()
    version_lines = f'name = "codex-task-tools"\nversion = "{expected_version}"'
    if version_lines not in project_text or version_lines not in lock_text:
        fail("Installed Codex Task Tools package version is unexpected")
    print((plugin_root / "server").resolve(strict=True))
except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
    fail("Installed Codex Task Tools configuration is invalid")
PY
)" || fail "Could not verify installed Codex Task Tools source"

SERVICE_BIN="$RUNTIME_VENV/bin/codex-task-tools-service"
SERVICE_PLIST="$HOME/Library/LaunchAgents/com.jialuohu.codex-task-tools.plist"

validate_runtime_directory() {
  CODEX_TASK_HOME="$CODEX_TASK_HOME" \
  CODEX_TASK_RUNTIME_DIR="$RUNTIME_DIR" \
  CODEX_TASK_RUNTIME_VENV="$RUNTIME_VENV" \
  CODEX_TASK_ACTION="$ACTION" \
  CODEX_TASK_REPO_ROOT="$ROOT" \
  python3 - <<'PY'
import os
import stat
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


home = Path(os.environ["CODEX_TASK_HOME"])
runtime = Path(os.environ["CODEX_TASK_RUNTIME_DIR"])
venv = Path(os.environ["CODEX_TASK_RUNTIME_VENV"])
install = os.environ["CODEX_TASK_ACTION"] == "--install"
repo = Path(os.environ["CODEX_TASK_REPO_ROOT"]).resolve(strict=True)
if not home.is_absolute() or home.resolve().is_relative_to(repo):
    fail("Codex Task Tools private runtime must be outside the repository")
for path in (home, home / "runtime", runtime, venv):
    if not path.exists() and not path.is_symlink():
        if install and path != venv:
            path.mkdir(mode=0o700)
        elif path != venv:
            fail("Codex Task Tools runtime is missing; run --install")
        else:
            continue
    meta = path.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid():
        fail("Codex Task Tools runtime path must be an owned directory without symlinks")
    if path == runtime and stat.S_IMODE(meta.st_mode) != 0o700:
        fail("Codex Task Tools runtime directory must have mode 700")
PY
}

refuse_interrupted_install() {
  CODEX_TASK_HOME="$CODEX_TASK_HOME" python3 - <<'PY' || \
    fail "Interrupted Codex Task Tools installation requires reviewed recovery; broker must remain unloaded"
import os
from pathlib import Path

marker = Path(os.environ["CODEX_TASK_HOME"]) / "state/codex-task-tools/upgrade-install.json"
if os.path.lexists(marker):
    raise SystemExit(1)
PY
}

umask 077
if [ "$ACTION" = --install ]; then
  refuse_interrupted_install
fi
validate_runtime_directory

if [ "$ACTION" = --install ]; then
  RUNTIME_SYNCED=no
  UV_BIN="$(command -v uv || true)"
  if [ -z "$UV_BIN" ] && [ -n "${CODEX_LOCAL_BIN_DIR:-}" ] && \
     [ -x "$CODEX_LOCAL_BIN_DIR/uv" ]; then
    UV_BIN="$CODEX_LOCAL_BIN_DIR/uv"
  fi
  [ -n "$UV_BIN" ] || fail "uv is unavailable"
  "$UV_BIN" lock --check --directory "$SERVER_DIR" >/dev/null || \
    fail "Codex Task Tools dependency lock is stale"
  [ ! -L "$SERVICE_PLIST" ] || fail "Toolbox LaunchAgent path must not be a symlink"
  if [ -e "$SERVICE_PLIST" ] && [ ! -x "$SERVICE_BIN" ]; then
    fail "Installed broker service exists without a verifiable status command"
  fi
  if [ -x "$SERVICE_BIN" ]; then
    [ -x "$RUNTIME_VENV/bin/python" ] || fail "Existing broker Python is unavailable"
    RUNTIME_PACKAGE_VERSION="$("$RUNTIME_VENV/bin/python" -I -c \
      'import importlib.metadata; print(importlib.metadata.version("codex-task-tools"))')" || \
      fail "Existing broker package version is unavailable"
    case "$RUNTIME_PACKAGE_VERSION" in
      0.1.0|"$PACKAGE_VERSION") ;;
      *) fail "Existing broker package is not a supported upgrade source" ;;
    esac
    STATUS_JSON="$("$SERVICE_BIN" status)" || \
      fail "Existing broker status is unavailable; refusing to replace its runtime"
    IS_LOADED="$(
      CODEX_TASK_SERVICE_STATUS="$STATUS_JSON" \
      CODEX_TASK_RUNTIME_PACKAGE_VERSION="$RUNTIME_PACKAGE_VERSION" python3 - <<'PY'
import json
import os
import sys

try:
    status = json.loads(os.environ["CODEX_TASK_SERVICE_STATUS"])
    if status.get("ok") is not True or type(status.get("loaded")) is not bool:
        raise ValueError
    broker = status.get("broker")
    if not isinstance(broker, dict):
        raise ValueError
    if status["loaded"]:
        legacy_disconnected = (
            os.environ["CODEX_TASK_RUNTIME_PACKAGE_VERSION"] == "0.1.0"
            and broker.get("running") is True
            and broker.get("backendConnected") is False
            and broker.get("appServerVersion") is None
            and broker.get("backendIdentity") is None
            and broker.get("activeTaskCount") is None
            and broker.get("pendingApprovalCount") is None
            and broker.get("eventProcessingError") is False
            and type(broker.get("quiesced")) is bool
        )
        if legacy_disconnected:
            print("upgrade")
            raise SystemExit(0)
        if (broker.get("running") is not True
            or broker.get("backendConnected") is not True
            or broker.get("eventProcessingError") is not False
            or type(broker.get("activeTaskCount")) is not int
            or type(broker.get("pendingApprovalCount")) is not int):
            raise ValueError
        if broker["activeTaskCount"] or broker["pendingApprovalCount"]:
            print("Broker has an active task or pending approval", file=sys.stderr)
            raise SystemExit(1)
        print("yes")
    else:
        if broker.get("running") is not False:
            raise ValueError
        # A previous guarded upgrade may have stopped the old broker before
        # setup was interrupted. Re-prove its journal rather than skipping it.
        print("upgrade" if os.environ["CODEX_TASK_RUNTIME_PACKAGE_VERSION"] == "0.1.0" else "no")
except (KeyError, TypeError, ValueError, json.JSONDecodeError):
    print("Existing broker health is unknown", file=sys.stderr)
    raise SystemExit(1)
PY
    )" || fail "Refusing to replace an active or unverified broker runtime"
    refuse_interrupted_install
    case "$IS_LOADED" in
      yes) "$SERVICE_BIN" stop || fail "Could not stop the idle toolbox broker" ;;
      upgrade)
        # Build the verified candidate separately. The running stable venv is
        # unchanged until the guarded predecessor shutdown has succeeded. The
        # helper retains the broker lock through its own stable-environment sync.
        HELPER_JSON="$(env -u UV_PROJECT_ENVIRONMENT -u VIRTUAL_ENV "$UV_BIN" run \
          --isolated --frozen --no-dev --no-editable --no-env-file \
          --refresh-package codex-task-tools \
          --project "$SERVER_DIR" python -I -m codex_task_tools.upgrade \
          --from-version 0.1.0 --to-version "$PACKAGE_VERSION" \
          --state-dir "$CODEX_TASK_HOME/state/codex-task-tools" \
          --install-project "$SERVER_DIR" --uv-executable "$UV_BIN")" || \
          fail "Disconnected broker upgrade could not complete a guarded runtime replacement"
        VERIFIED_HELPER_RECEIPT="$(CODEX_TASK_UPGRADE_RECEIPT="$HELPER_JSON" python3 - <<'PY'
import json
import os


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate receipt key")
        result[key] = value
    return result


try:
    receipt = json.loads(os.environ["CODEX_TASK_UPGRADE_RECEIPT"], object_pairs_hook=unique_pairs)
    expected = {"ok", "fromVersion", "toVersion", "appServerVersion", "stopped",
                "runtimeInstalled", "verifiedTerminalTaskCount"}
    if (not isinstance(receipt, dict) or set(receipt) != expected
        or receipt["ok"] is not True or receipt["runtimeInstalled"] is not True
        or receipt["stopped"] is not True or receipt["fromVersion"] != "0.1.0"
        or receipt["toVersion"] != "0.1.1"
        or receipt["appServerVersion"] not in {"0.156.1", "0.159.0"}
        or type(receipt["verifiedTerminalTaskCount"]) is not int
        or receipt["verifiedTerminalTaskCount"] < 0):
        raise ValueError("Upgrade receipt is unverified")
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
except (TypeError, ValueError, KeyError):
    raise SystemExit(1)
PY
        )" || fail "Guarded broker upgrade returned an invalid completion receipt; refusing startup"
        printf '%s\n' "$VERIFIED_HELPER_RECEIPT" >&2
        RUNTIME_SYNCED=yes
        ;;
      no) ;;
      *) fail "Existing broker state is unsupported" ;;
    esac
    STOPPED_STATUS="$("$SERVICE_BIN" status)" || fail "Stopped broker status is unavailable"
    CODEX_TASK_SERVICE_STATUS="$STOPPED_STATUS" python3 - <<'PY' || \
      fail "Broker did not remain stopped before runtime replacement"
import json
import os
import sys

try:
    status = json.loads(os.environ["CODEX_TASK_SERVICE_STATUS"])
    if (status.get("ok") is not True or status.get("loaded") is not False
        or not isinstance(status.get("broker"), dict)
        or status["broker"].get("running") is not False):
        raise ValueError
except (TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
PY
  fi
  refuse_interrupted_install
  if [ "$RUNTIME_SYNCED" != yes ]; then
    if [ ! -x "$RUNTIME_VENV/bin/python" ]; then
      "$UV_BIN" venv --python 3.12 "$RUNTIME_VENV"
    fi
    env -u UV_PROJECT_ENVIRONMENT VIRTUAL_ENV="$RUNTIME_VENV" \
      "$UV_BIN" sync --active --locked --no-dev --no-editable --project "$SERVER_DIR"
  fi
  refuse_interrupted_install
  [ -x "$SERVICE_BIN" ] || fail "Codex Task Tools service entry point is missing"
  "$SERVICE_BIN" install
  refuse_interrupted_install
  "$SERVICE_BIN" start
fi

[ -x "$SERVICE_BIN" ] || fail "Codex Task Tools runtime is missing; run --install"
if [ "$ACTION" = --status ]; then
  "$SERVICE_BIN" status
  exit
fi

if [ "$ACTION" = --check ]; then
  [ -x "$RUNTIME_VENV/bin/python" ] || fail "Existing broker Python is unavailable"
  RUNTIME_PACKAGE_VERSION="$("$RUNTIME_VENV/bin/python" -I -c \
    'import importlib.metadata; print(importlib.metadata.version("codex-task-tools"))')" || \
    fail "Existing broker package version is unavailable"
  case "$RUNTIME_PACKAGE_VERSION" in
    0.1.0) fail "Codex Task Tools runtime 0.1.0 must be upgraded with --install before --check" ;;
    "$PACKAGE_VERSION") ;;
    *) fail "Existing broker package is not a supported runtime version" ;;
  esac
fi

for attempt in 1 2 3; do
  if STATUS_JSON="$("$SERVICE_BIN" status)" && \
     CODEX_TASK_SERVICE_STATUS="$STATUS_JSON" "$RUNTIME_VENV/bin/python" -I - <<'PY'
import json
import os
import sys

from codex_task_tools.compatibility import SUPPORTED_APP_VERSIONS

try:
    status = json.loads(os.environ["CODEX_TASK_SERVICE_STATUS"])
    broker = status["broker"]
    if (status.get("ok") is not True
        or status.get("installed") is not True
        or status.get("loaded") is not True
        or not isinstance(broker, dict)
        or broker.get("running") is not True
        or broker.get("backendConnected") is not True
        or broker.get("appServerVersion") not in SUPPORTED_APP_VERSIONS
        or broker.get("eventProcessingError") is not False
        or type(broker.get("activeTaskCount")) is not int
        or type(broker.get("pendingApprovalCount")) is not int
        or broker["activeTaskCount"] < 0 or broker["pendingApprovalCount"] < 0):
        raise ValueError
except (KeyError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
PY
  then
    echo "$STATUS_JSON"
    exit 0
  fi
  [ "$attempt" -eq 3 ] || sleep 1
done
fail "Codex Task Tools broker did not become healthy"
