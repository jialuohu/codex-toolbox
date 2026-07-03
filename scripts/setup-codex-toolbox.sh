#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_CODEX="/Applications/Codex.app/Contents/Resources/codex"
MARKETPLACE_NAME="jialuo-codex-toolbox"
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
  "trading-tools"
  "vibe-trading-tools"
  "chronicle-tools"
)
THIRD_PARTY_DEFAULT_PLUGINS=(
  "ui-ux-pro-max"
)
CONTEXT7_DEFAULT_PLUGINS=(
  "context7"
)
RETIRED_PLUGINS=(
  "legacy-toolbox"
  "lab-weekly-update"
  "context7-docs"
)
MANAGED_MCP_SERVERS=(
  "alpaca"
  "firecrawl"
  "obsidian_files"
  "paper_search_mcp"
  "context7"
  "vibe_trading"
  "zotero"
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

if "$CODEX_BIN" plugin marketplace list | awk 'NR > 1 {print $NF}' | grep -Fx "$ROOT" >/dev/null; then
  echo "Marketplace already registered: $ROOT"
else
  "$CODEX_BIN" plugin marketplace add "$ROOT"
fi

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

for plugin in "${RETIRED_PLUGINS[@]}"; do
  "$CODEX_BIN" plugin remove "${plugin}@${MARKETPLACE_NAME}" --json >/dev/null 2>&1 || true
  echo "Removed retired plugin if present: ${plugin}@${MARKETPLACE_NAME}"
done

for server in "${MANAGED_MCP_SERVERS[@]}"; do
  if direct_mcp_config_present "$server"; then
    "$CODEX_BIN" mcp remove "$server" >/dev/null
    echo "Removed direct MCP config override: ${server}"
  else
    echo "Direct MCP config override not present: ${server}"
  fi
done

for plugin in "${DEFAULT_PLUGINS[@]}"; do
  install_or_refresh_plugin "$plugin" "$MARKETPLACE_NAME"
done

ensure_ui_ux_marketplace
for plugin in "${THIRD_PARTY_DEFAULT_PLUGINS[@]}"; do
  install_or_refresh_plugin "$plugin" "$UI_UX_MARKETPLACE_NAME"
done

ensure_context7_marketplace
for plugin in "${CONTEXT7_DEFAULT_PLUGINS[@]}"; do
  install_or_refresh_plugin "$plugin" "$CONTEXT7_MARKETPLACE_NAME"
done

"$CODEX_BIN" plugin marketplace list
