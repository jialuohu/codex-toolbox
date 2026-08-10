#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_CODEX="/Applications/Codex.app/Contents/Resources/codex"
MARKETPLACE_NAME="jialuo-codex-toolbox"
TOOLBOX_MARKETPLACE_SOURCE="${CODEX_TOOLBOX_MARKETPLACE_SOURCE:-jialuohu/codex-toolbox}"
TOOLBOX_MARKETPLACE_GIT_URL="https://github.com/jialuohu/codex-toolbox.git"
TOOLBOX_MARKETPLACE_REF="${CODEX_TOOLBOX_MARKETPLACE_REF:-main}"
TOOLBOX_MARKETPLACE_MODE="${CODEX_TOOLBOX_MARKETPLACE_MODE:-git}"
declare -a OLD_MARKETPLACE_NAMES=()
UI_UX_MARKETPLACE_NAME="ui-ux-pro-max-skill"
UI_UX_MARKETPLACE_SOURCE="nextlevelbuilder/ui-ux-pro-max-skill"
UI_UX_MARKETPLACE_REF="v2.10.0"
UI_UX_MARKETPLACE_SPARSE_PATHS=(
  ".claude/skills/ui-ux-pro-max"
  ".claude-plugin"
  "LICENSE"
)
CONTEXT7_MARKETPLACE_NAME="context7-marketplace"
CONTEXT7_MARKETPLACE_SOURCE="upstash/context7"
CONTEXT7_MARKETPLACE_GIT_SOURCE="https://github.com/upstash/context7.git"
DEFAULT_PLUGINS=(
  "obsidian-tools"
  "research-tools"
  "web-data-tools"
  "game-asset-tools"
  "design-engineering-tools"
  "workflow-tools"
  "coder-tools"
  "diagram-tools"
  "paper-figure-tools"
  "productivity-tools"
  "trading-tools"
  "vibe-trading-tools"
  "chronicle-tools"
  "google-workspace-tools"
  "docmost-tools"
)
THIRD_PARTY_DEFAULT_PLUGINS=(
  "ui-ux-pro-max"
)
CONTEXT7_DEFAULT_PLUGINS=(
  "context7"
)
RETIRED_PLUGINS=(
  "lab-weekly-update"
  "context7-docs"
  "symphony-tools"
)
MANAGED_MCP_SERVERS=(
  "alpaca"
  "coder"
  "firecrawl"
  "obsidian_files"
  "paper_search_mcp"
  "context7"
  "pixellab"
  "todoist"
  "robinhood-trading"
  "vibe_trading"
  "zotero"
  "docmost"
)
RETIRED_MCP_SERVERS=(
  "symphony"
)

resolve_codex() {
  if command -v codex >/dev/null 2>&1 && codex --version >/dev/null 2>&1; then
    command -v codex
    return 0
  fi

  if [ -x "$APP_CODEX" ] && "$APP_CODEX" --version >/dev/null 2>&1; then
    printf '%s\n' "$APP_CODEX"
    return 0
  fi

  return 1
}

CODEX_BIN="$(resolve_codex || true)"

if [ -z "$CODEX_BIN" ]; then
  cat >&2 <<'EOF'
Could not find a working Codex CLI.

The npm `codex` wrapper may be broken, and the Codex app binary was not usable.
Reinstall or repair Codex, then rerun this script.
EOF
  exit 1
fi

echo "Using Codex binary: $CODEX_BIN"
"$CODEX_BIN" --version
"$ROOT/scripts/sync-agents.sh" --install
python3 "$ROOT/scripts/sync-codex-pets.py" --install

marketplace_registered() {
  local marketplace_name="$1"

  MARKETPLACE_JSON="$("$CODEX_BIN" plugin marketplace list --json)" \
    python3 - "$marketplace_name" <<'PY'
import json
import os
import sys

marketplace_name = sys.argv[1]
data = json.loads(os.environ["MARKETPLACE_JSON"])

for marketplace in data.get("marketplaces", []):
    if marketplace.get("name") == marketplace_name:
        sys.exit(0)

sys.exit(1)
PY
}

ui_ux_marketplace_config_current() {
  local config_file="${CODEX_HOME:-$HOME/.codex}/config.toml"

  [ -f "$config_file" ] || return 1
  grep -Fq "[marketplaces.${UI_UX_MARKETPLACE_NAME}]" "$config_file" || return 1
  grep -Fq 'source = "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git"' "$config_file" || return 1
  grep -Fq "ref = \"${UI_UX_MARKETPLACE_REF}\"" "$config_file" || return 1

  for sparse_path in "${UI_UX_MARKETPLACE_SPARSE_PATHS[@]}"; do
    grep -Fq "\"${sparse_path}\"" "$config_file" || return 1
  done
}

add_ui_ux_marketplace() {
  local add_args=("$UI_UX_MARKETPLACE_SOURCE" "--ref" "$UI_UX_MARKETPLACE_REF")

  for sparse_path in "${UI_UX_MARKETPLACE_SPARSE_PATHS[@]}"; do
    add_args+=("--sparse" "$sparse_path")
  done

  "$CODEX_BIN" plugin marketplace add "${add_args[@]}" --json >/dev/null
}

ensure_ui_ux_marketplace() {
  if ui_ux_marketplace_config_current; then
    echo "Refreshing third-party marketplace: ${UI_UX_MARKETPLACE_NAME}"
    "$CODEX_BIN" plugin marketplace upgrade "$UI_UX_MARKETPLACE_NAME" --json >/dev/null
    return
  fi

  if marketplace_registered "$UI_UX_MARKETPLACE_NAME"; then
    "$CODEX_BIN" plugin marketplace remove "$UI_UX_MARKETPLACE_NAME" --json >/dev/null
    echo "Removed stale third-party marketplace: ${UI_UX_MARKETPLACE_NAME}"
  fi

  echo "Registering third-party marketplace: ${UI_UX_MARKETPLACE_NAME}"
  add_ui_ux_marketplace
}

context7_marketplace_config_current() {
  local config_file="${CODEX_HOME:-$HOME/.codex}/config.toml"

  [ -f "$config_file" ] || return 1
  grep -Fq "[marketplaces.${CONTEXT7_MARKETPLACE_NAME}]" "$config_file" || return 1
  grep -Fq "source = \"${CONTEXT7_MARKETPLACE_GIT_SOURCE}\"" "$config_file" || return 1
}

add_context7_marketplace() {
  "$CODEX_BIN" plugin marketplace add "$CONTEXT7_MARKETPLACE_SOURCE" --json >/dev/null
}

ensure_context7_marketplace() {
  if context7_marketplace_config_current; then
    echo "Refreshing third-party marketplace: ${CONTEXT7_MARKETPLACE_NAME}"
    "$CODEX_BIN" plugin marketplace upgrade "$CONTEXT7_MARKETPLACE_NAME" --json >/dev/null
    return
  fi

  if marketplace_registered "$CONTEXT7_MARKETPLACE_NAME"; then
    "$CODEX_BIN" plugin marketplace remove "$CONTEXT7_MARKETPLACE_NAME" --json >/dev/null
    echo "Removed stale third-party marketplace: ${CONTEXT7_MARKETPLACE_NAME}"
  fi

  echo "Registering third-party marketplace: ${CONTEXT7_MARKETPLACE_NAME}"
  add_context7_marketplace
}

toolbox_git_marketplace_config_current() {
  local config_file="${CODEX_HOME:-$HOME/.codex}/config.toml"

  [ -f "$config_file" ] || return 1
  grep -Fq "[marketplaces.${MARKETPLACE_NAME}]" "$config_file" || return 1
  grep -Fq 'source_type = "git"' "$config_file" || return 1
  grep -Fq "source = \"${TOOLBOX_MARKETPLACE_GIT_URL}\"" "$config_file" || return 1
  grep -Fq "ref = \"${TOOLBOX_MARKETPLACE_REF}\"" "$config_file" || return 1
}

toolbox_local_marketplace_registered() {
  "$CODEX_BIN" plugin marketplace list | awk 'NR > 1 {print $NF}' | grep -Fx "$ROOT" >/dev/null
}

remove_toolbox_marketplace_config_blocks() {
  local source_to_remove="$1"
  local description="$2"
  local config_file="${CODEX_HOME:-$HOME/.codex}/config.toml"

  [ -f "$config_file" ] || return 0

  TOOLBOX_MARKETPLACE_SOURCE_TO_REMOVE="$source_to_remove" \
    TOOLBOX_MARKETPLACE_REMOVE_DESCRIPTION="$description" \
    python3 - "$config_file" <<'PY'
import os
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
source_to_remove = os.environ["TOOLBOX_MARKETPLACE_SOURCE_TO_REMOVE"]
description = os.environ["TOOLBOX_MARKETPLACE_REMOVE_DESCRIPTION"]

original = config_path.read_text()
lines = original.splitlines(keepends=True)
kept_lines = []
removed_headers = []
index = 0

while index < len(lines):
    line = lines[index]
    stripped = line.strip()
    if stripped.startswith("[marketplaces.") and stripped.endswith("]"):
        block = [line]
        index += 1
        while index < len(lines):
            next_stripped = lines[index].strip()
            if next_stripped.startswith("[") and next_stripped.endswith("]"):
                break
            block.append(lines[index])
            index += 1

        if any(entry.strip() == f'source = "{source_to_remove}"' for entry in block):
            removed_headers.append(stripped)
            continue

        kept_lines.extend(block)
        continue

    kept_lines.append(line)
    index += 1

if not removed_headers:
    print(f"{description} config blocks not present")
    raise SystemExit(0)

backup_path = config_path.with_name(
    config_path.name + ".backup-before-toolbox-marketplace-migration"
)
if not backup_path.exists():
    backup_path.write_text(original)

config_path.write_text("".join(kept_lines))
print(f"Removed {description} config blocks: " + ", ".join(removed_headers))
PY
}

remove_toolbox_marketplace_registration() {
  local source_to_remove="$1"
  local description="$2"

  if "$CODEX_BIN" plugin marketplace remove "$MARKETPLACE_NAME" --json >/dev/null 2>&1; then
    echo "Removed ${description}: ${MARKETPLACE_NAME}"
    return
  fi

  remove_toolbox_marketplace_config_blocks "$source_to_remove" "$description"
}

ensure_toolbox_marketplace() {
  case "$TOOLBOX_MARKETPLACE_MODE" in
    git)
      if toolbox_git_marketplace_config_current; then
        echo "Refreshing upgradeable toolbox marketplace: ${MARKETPLACE_NAME}"
        "$CODEX_BIN" plugin marketplace upgrade "$MARKETPLACE_NAME" --json >/dev/null
        return
      fi

      if marketplace_registered "$MARKETPLACE_NAME"; then
        remove_toolbox_marketplace_registration "$ROOT" "stale toolbox marketplace registration"
      fi

      echo "Registering upgradeable toolbox marketplace: ${TOOLBOX_MARKETPLACE_SOURCE} @ ${TOOLBOX_MARKETPLACE_REF}"
      "$CODEX_BIN" plugin marketplace add "$TOOLBOX_MARKETPLACE_SOURCE" --ref "$TOOLBOX_MARKETPLACE_REF" --json >/dev/null
      ;;
    local)
      if toolbox_local_marketplace_registered; then
        echo "Local toolbox marketplace already registered: $ROOT"
        return
      fi

      if marketplace_registered "$MARKETPLACE_NAME"; then
        remove_toolbox_marketplace_registration "$TOOLBOX_MARKETPLACE_GIT_URL" "Git toolbox marketplace for local development"
      fi

      echo "Registering local toolbox marketplace for development: $ROOT"
      "$CODEX_BIN" plugin marketplace add "$ROOT" --json >/dev/null
      ;;
    *)
      echo "Unsupported CODEX_TOOLBOX_MARKETPLACE_MODE=${TOOLBOX_MARKETPLACE_MODE}; use git or local" >&2
      exit 2
      ;;
  esac
}

DOCMOST_SETUP="$ROOT/scripts/setup-docmost-tools.sh"
docmost_setup_command() {
  local server_dir="$1"
  shift
  if [ -n "$server_dir" ]; then
    DOCMOST_SERVER_DIR="$server_dir" "$DOCMOST_SETUP" "$@"
  else
    "$DOCMOST_SETUP" "$@"
  fi
}

ensure_docmost_ready() {
  local server_dir="$1"
  local docmost_status
  docmost_setup_command "$server_dir" --install
  if docmost_setup_command "$server_dir" --status; then
    return 0
  else
    docmost_status=$?
  fi
  if [ "$docmost_status" -eq 3 ]; then
    docmost_setup_command "$server_dir" --login
    docmost_setup_command "$server_dir" --status
    return
  fi
  return "$docmost_status"
}

installed_docmost_server_dir() {
  local mcp_json
  if ! mcp_json="$("$CODEX_BIN" mcp get docmost --json)"; then
    echo "Installed Docmost MCP entry is unavailable" >&2
    return 1
  fi
  DOCMOST_MCP_JSON="$mcp_json" \
    DOCMOST_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}" \
    python3 - "$MARKETPLACE_NAME" <<'PY'
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

marketplace_name = sys.argv[1]
approved_launcher_sha256 = "1e3f754036aaa5d33b1aa21e31f6aeaba068bcbd2b8432335621766bb7f50c8c"


def fail(message: str) -> None:
    raise SystemExit(message)


try:
    data = json.loads(os.environ["DOCMOST_MCP_JSON"])
except (KeyError, json.JSONDecodeError):
    fail("Installed Docmost MCP entry is unavailable")

if not isinstance(data, dict) or data.get("name") != "docmost" or data.get("enabled") is not True:
    fail("Installed Docmost MCP entry is unavailable")
transport = data.get("transport")
if not isinstance(transport, dict):
    fail("Installed Docmost MCP transport is unexpected")
if transport.get("type") != "stdio" or transport.get("command") != "/bin/zsh":
    fail("Installed Docmost MCP transport is unexpected")

raw_cwd = transport.get("cwd")
if (
    not isinstance(raw_cwd, str)
    or not raw_cwd
    or "\n" in raw_cwd
    or "\x00" in raw_cwd
    or not Path(raw_cwd).is_absolute()
):
    fail("Installed Docmost MCP cwd is invalid")

try:
    raw_plugin_root = Path(raw_cwd)
    raw_plugin_metadata = raw_plugin_root.lstat()
except OSError:
    fail("Installed Docmost plugin layout is invalid")
if stat.S_ISLNK(raw_plugin_metadata.st_mode) or not stat.S_ISDIR(raw_plugin_metadata.st_mode):
    fail("Installed Docmost plugin layout is invalid")

try:
    codex_home = Path(os.environ["DOCMOST_CODEX_HOME"]).expanduser().resolve(strict=True)
    plugin_root = raw_plugin_root.resolve(strict=True)
except (KeyError, OSError):
    fail("Installed Docmost plugin layout is invalid")
try:
    relative = plugin_root.relative_to(codex_home)
except ValueError:
    fail("Installed Docmost MCP cwd escapes CODEX_HOME")

parts = relative.parts
if (
    len(parts) != 5
    or parts[:4] != ("plugins", "cache", marketplace_name, "docmost-tools")
    or not parts[4]
):
    fail("Installed Docmost plugin layout is invalid")

version = parts[4]
server = plugin_root / "server"
required_files = (
    plugin_root / ".mcp.json",
    plugin_root / ".codex-plugin" / "plugin.json",
    server / "pyproject.toml",
    server / "uv.lock",
    server / "src" / "docmost_tools" / "server.py",
    server / "src" / "docmost_tools" / "runtime_lock.py",
    server / "src" / "docmost_tools" / "runtime_stamp.py",
)
required_directories = (
    plugin_root,
    plugin_root / ".codex-plugin",
    server,
    server / "src",
    server / "src" / "docmost_tools",
)
if any(not path.is_dir() or path.is_symlink() for path in required_directories):
    fail("Installed Docmost plugin layout is invalid")
if any(not path.is_file() or path.is_symlink() for path in required_files):
    fail("Installed Docmost plugin layout is invalid")

try:
    plugin = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text())
    mcp = json.loads((plugin_root / ".mcp.json").read_text())
except (OSError, json.JSONDecodeError):
    fail("Installed Docmost plugin layout is invalid")
servers = mcp.get("mcpServers") if isinstance(mcp, dict) else None
configured = servers.get("docmost") if isinstance(servers, dict) else None
if (
    not isinstance(plugin, dict)
    or plugin.get("name") != "docmost-tools"
    or plugin.get("version") != version
    or plugin.get("mcpServers") != "./.mcp.json"
    or not isinstance(servers, dict)
    or set(servers) != {"docmost"}
    or not isinstance(configured, dict)
):
    fail("Installed Docmost plugin layout is invalid")
if (
    configured.get("command") != transport.get("command")
    or configured.get("cwd") != "."
    or configured.get("env_vars") != transport.get("env_vars")
):
    fail("Installed Docmost MCP transport is unexpected")
configured_args = configured.get("args")
transport_args = transport.get("args")
if (
    not isinstance(configured_args, list)
    or len(configured_args) != 2
    or configured_args[0] != "-lc"
    or not isinstance(configured_args[1], str)
    or not configured_args[1]
    or hashlib.sha256(configured_args[1].encode()).hexdigest()
    != approved_launcher_sha256
    or not isinstance(transport_args, list)
    or transport_args != configured_args
):
    fail("Installed Docmost MCP launcher is unexpected")
expected_writes = {
    "docmost_create_page",
    "docmost_update_page_title",
    "docmost_create_comment",
}
write_tools = configured.get("tools")
if (
    configured.get("default_tools_approval_mode") != "auto"
    or configured.get("env_vars")
    != ["CODEX_SECRETS_DIR", "CODEX_HOME", "CODEX_LOCAL_BIN_DIR"]
    or not isinstance(write_tools, dict)
    or set(write_tools) != expected_writes
    or any(
        not isinstance(write_tools[name], dict)
        or write_tools[name].get("approval_mode") != "prompt"
        for name in expected_writes
    )
):
    fail("Installed Docmost MCP policy is unexpected")

print(server.resolve(strict=True))
PY
}

ensure_docmost_ready ""

ensure_toolbox_marketplace

plugin_installed() {
  local plugin_name="$1"
  local marketplace_name="$2"

  PLUGIN_JSON="$("$CODEX_BIN" plugin list --marketplace "$marketplace_name" --available --json)" \
    python3 - "$plugin_name" "$marketplace_name" <<'PY'
import json
import os
import sys

plugin_name, marketplace_name = sys.argv[1:]
data = json.loads(os.environ["PLUGIN_JSON"])

for plugin in data.get("installed", []):
    if plugin.get("name") == plugin_name and plugin.get("marketplaceName") == marketplace_name:
        sys.exit(0)

sys.exit(1)
PY
}

install_or_refresh_plugin() {
  local plugin_name="$1"
  local marketplace_name="$2"

  if plugin_installed "$plugin_name" "$marketplace_name"; then
    echo "Refreshing plugin: ${plugin_name}@${marketplace_name}"
    "$CODEX_BIN" plugin remove "${plugin_name}@${marketplace_name}" --json >/dev/null
  else
    echo "Installing plugin: ${plugin_name}@${marketplace_name}"
  fi

  "$CODEX_BIN" plugin add "${plugin_name}@${marketplace_name}" --json >/dev/null
}

direct_mcp_config_present() {
  local server_name="$1"
  local config_file="${CODEX_HOME:-$HOME/.codex}/config.toml"

  [ -f "$config_file" ] && grep -Eq "^\[mcp_servers\.${server_name//./\\.}\]" "$config_file"
}

remove_stale_plugin_config_blocks() {
  local config_file="${CODEX_HOME:-$HOME/.codex}/config.toml"
  local old_marketplaces
  local default_plugins

  [ -f "$config_file" ] || return 0
  if [ "${#OLD_MARKETPLACE_NAMES[@]}" -eq 0 ]; then
    echo "Stale retired-marketplace plugin config blocks not present"
    return 0
  fi

  old_marketplaces="$(printf '%s\n' "${OLD_MARKETPLACE_NAMES[@]}")"
  default_plugins="$(printf '%s\n' "${DEFAULT_PLUGINS[@]}")"

  OLD_MARKETPLACES="$old_marketplaces" DEFAULT_PLUGINS_TEXT="$default_plugins" \
    python3 - "$config_file" <<'PY'
import os
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
old_marketplaces = set(filter(None, os.environ["OLD_MARKETPLACES"].splitlines()))
default_plugins = set(filter(None, os.environ["DEFAULT_PLUGINS_TEXT"].splitlines()))
retired_headers = {
    f'[plugins."{plugin}@{marketplace}"]'
    for plugin in default_plugins
    for marketplace in old_marketplaces
}

original = config_path.read_text()
kept_lines = []
removed_headers = []
skipping = False

for line in original.splitlines(keepends=True):
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        if stripped in retired_headers:
            skipping = True
            removed_headers.append(stripped)
            continue
        skipping = False

    if not skipping:
        kept_lines.append(line)

if not removed_headers:
    print("Stale retired-marketplace plugin config blocks not present")
    raise SystemExit(0)

backup_path = config_path.with_name(
    config_path.name + ".backup-before-toolbox-plugin-migration"
)
if not backup_path.exists():
    backup_path.write_text(original)

config_path.write_text("".join(kept_lines))
print(
    "Removed stale retired-marketplace plugin config blocks: "
    + ", ".join(removed_headers)
)
PY
}

for plugin in "${RETIRED_PLUGINS[@]}"; do
  "$CODEX_BIN" plugin remove "${plugin}@${MARKETPLACE_NAME}" --json >/dev/null 2>&1 || true
  echo "Removed retired plugin if present: ${plugin}@${MARKETPLACE_NAME}"
done

remove_stale_plugin_config_blocks

for server in "${MANAGED_MCP_SERVERS[@]}"; do
  if direct_mcp_config_present "$server"; then
    "$CODEX_BIN" mcp remove "$server" >/dev/null
    echo "Removed direct MCP config override: ${server}"
  else
    echo "Direct MCP config override not present: ${server}"
  fi
done

for server in "${RETIRED_MCP_SERVERS[@]}"; do
  if direct_mcp_config_present "$server"; then
    "$CODEX_BIN" mcp remove "$server" >/dev/null
    echo "Removed retired direct MCP config: ${server}"
  else
    echo "Retired direct MCP config not present: ${server}"
  fi
done

for plugin in "${DEFAULT_PLUGINS[@]}"; do
  install_or_refresh_plugin "$plugin" "$MARKETPLACE_NAME"
done

"$ROOT/scripts/setup-diagram-tools.sh" --update

DOCMOST_INSTALLED_SERVER_DIR="$(installed_docmost_server_dir)"
readonly DOCMOST_INSTALLED_SERVER_DIR
ensure_docmost_ready "$DOCMOST_INSTALLED_SERVER_DIR"

ensure_ui_ux_marketplace
for plugin in "${THIRD_PARTY_DEFAULT_PLUGINS[@]}"; do
  install_or_refresh_plugin "$plugin" "$UI_UX_MARKETPLACE_NAME"
done

ensure_context7_marketplace
for plugin in "${CONTEXT7_DEFAULT_PLUGINS[@]}"; do
  install_or_refresh_plugin "$plugin" "$CONTEXT7_MARKETPLACE_NAME"
done

"$CODEX_BIN" plugin marketplace list
