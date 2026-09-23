#!/usr/bin/env bash
# Install or inspect the toolbox-owned Codex task broker for the active plugin.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_TASK_HOME="${CODEX_HOME:-$HOME/.codex}"
MARKETPLACE_NAME="${CODEX_TASK_MARKETPLACE_NAME:-jialuo-codex-toolbox}"
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

[ "$(uname -s)" = "Darwin" ] || fail "Codex Task Tools v0.1.0 requires macOS"
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
        / "0.1.0"
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
    if (manifest.get("name"), manifest.get("version")) != ("codex-task-tools", "0.1.0"):
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
    if ('name = "codex-task-tools"\nversion = "0.1.0"' not in project_text
        or 'name = "codex-task-tools"\nversion = "0.1.0"' not in lock_text):
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

umask 077
validate_runtime_directory

if [ "$ACTION" = --install ]; then
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
    STATUS_JSON="$("$SERVICE_BIN" status)" || \
      fail "Existing broker status is unavailable; refusing to replace its runtime"
    IS_LOADED="$(
      CODEX_TASK_SERVICE_STATUS="$STATUS_JSON" python3 - <<'PY'
import json
import os
import sys

try:
    status = json.loads(os.environ["CODEX_TASK_SERVICE_STATUS"])
    if status.get("ok") is not True or type(status.get("loaded")) is not bool:
        raise ValueError
    if status["loaded"]:
        broker = status.get("broker")
        if (not isinstance(broker, dict)
            or broker.get("running") is not True
            or type(broker.get("activeTaskCount")) is not int
            or type(broker.get("pendingApprovalCount")) is not int):
            raise ValueError
        if broker["activeTaskCount"] or broker["pendingApprovalCount"]:
            print("Broker has an active task or pending approval", file=sys.stderr)
            raise SystemExit(1)
    print("yes" if status["loaded"] else "no")
except (KeyError, TypeError, ValueError, json.JSONDecodeError):
    print("Existing broker health is unknown", file=sys.stderr)
    raise SystemExit(1)
PY
    )" || fail "Refusing to replace an active or unverified broker runtime"
    if [ "$IS_LOADED" = yes ]; then
      "$SERVICE_BIN" stop || fail "Could not stop the idle toolbox broker"
    fi
  fi
  if [ ! -x "$RUNTIME_VENV/bin/python" ]; then
    "$UV_BIN" venv --python 3.12 "$RUNTIME_VENV"
  fi
  env -u UV_PROJECT_ENVIRONMENT VIRTUAL_ENV="$RUNTIME_VENV" \
    "$UV_BIN" sync --active --locked --no-dev --no-editable --project "$SERVER_DIR"
  [ -x "$SERVICE_BIN" ] || fail "Codex Task Tools service entry point is missing"
  "$SERVICE_BIN" install
  "$SERVICE_BIN" start
fi

[ -x "$SERVICE_BIN" ] || fail "Codex Task Tools runtime is missing; run --install"
if [ "$ACTION" = --status ]; then
  "$SERVICE_BIN" status
  exit
fi

for attempt in 1 2 3; do
  if STATUS_JSON="$("$SERVICE_BIN" status)" && \
     CODEX_TASK_SERVICE_STATUS="$STATUS_JSON" python3 - <<'PY'
import json
import os
import sys

try:
    status = json.loads(os.environ["CODEX_TASK_SERVICE_STATUS"])
    broker = status["broker"]
    if (status.get("ok") is not True
        or status.get("installed") is not True
        or status.get("loaded") is not True
        or not isinstance(broker, dict)
        or broker.get("running") is not True
        or type(broker.get("activeTaskCount")) is not int
        or type(broker.get("pendingApprovalCount")) is not int):
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
