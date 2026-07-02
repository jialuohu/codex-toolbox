#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_CODEX="/Applications/Codex.app/Contents/Resources/codex"
MARKETPLACE_NAME="jialuo-codex-toolbox"
DEFAULT_PLUGINS=("lab-weekly-update" "context7-docs")
RETIRED_PLUGINS=("legacy-toolbox")

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

if "$CODEX_BIN" plugin marketplace list | awk 'NR > 1 {print $NF}' | grep -Fx "$ROOT" >/dev/null; then
  echo "Marketplace already registered: $ROOT"
else
  "$CODEX_BIN" plugin marketplace add "$ROOT"
fi

plugin_installed() {
  local plugin_name="$1"

  PLUGIN_JSON="$("$CODEX_BIN" plugin list --marketplace "$MARKETPLACE_NAME" --available --json)" \
    python3 - "$plugin_name" "$MARKETPLACE_NAME" <<'PY'
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

for plugin in "${RETIRED_PLUGINS[@]}"; do
  if plugin_installed "$plugin"; then
    echo "Removing retired plugin: ${plugin}@${MARKETPLACE_NAME}"
    "$CODEX_BIN" plugin remove "${plugin}@${MARKETPLACE_NAME}" --json >/dev/null
  else
    echo "Retired plugin not installed: ${plugin}@${MARKETPLACE_NAME}"
  fi
done

for plugin in "${DEFAULT_PLUGINS[@]}"; do
  if plugin_installed "$plugin"; then
    echo "Plugin already installed: ${plugin}@${MARKETPLACE_NAME}"
  else
    echo "Installing plugin: ${plugin}@${MARKETPLACE_NAME}"
    "$CODEX_BIN" plugin add "${plugin}@${MARKETPLACE_NAME}" --json >/dev/null
  fi
done

"$CODEX_BIN" plugin marketplace list
