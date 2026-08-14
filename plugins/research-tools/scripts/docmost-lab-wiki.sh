#!/bin/zsh
set -euo pipefail

LAB_WIKI_CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
LAB_WIKI_SECRETS_ROOT="${CODEX_SECRETS_DIR:-$LAB_WIKI_CODEX_ROOT/secrets}"
LAB_WIKI_RUNTIME="$LAB_WIKI_CODEX_ROOT/runtime/docmost-lab-wiki"
LAB_WIKI_CONFIG="$LAB_WIKI_SECRETS_ROOT/docmost-lab-wiki.env"

if [ ! -f "$LAB_WIKI_CONFIG" ] || [ -L "$LAB_WIKI_CONFIG" ]; then
  echo "Lab Wiki configuration is missing or unsafe; run scripts/setup-docmost-lab-wiki.sh --install" >&2
  exit 1
fi
LAB_WIKI_CONFIG_MODE=""
if LAB_WIKI_CONFIG_MODE="$(stat -f '%Lp' "$LAB_WIKI_CONFIG" 2>/dev/null)"; then
  :
elif LAB_WIKI_CONFIG_MODE="$(stat -c '%a' "$LAB_WIKI_CONFIG" 2>/dev/null)"; then
  :
fi
if [ "$LAB_WIKI_CONFIG_MODE" != "600" ]; then
  echo "Lab Wiki configuration must have mode 600" >&2
  exit 1
fi
if [ ! -x "$LAB_WIKI_RUNTIME/bin/docmost-lab-wiki" ] || [ -L "$LAB_WIKI_RUNTIME" ]; then
  echo "Lab Wiki runtime is missing or unsafe; run scripts/setup-docmost-lab-wiki.sh --install" >&2
  exit 1
fi

readonly LAB_WIKI_CODEX_ROOT LAB_WIKI_SECRETS_ROOT LAB_WIKI_RUNTIME LAB_WIKI_CONFIG
export CODEX_SECRETS_DIR="$LAB_WIKI_SECRETS_ROOT"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
exec "$LAB_WIKI_RUNTIME/bin/docmost-lab-wiki" "$@"
