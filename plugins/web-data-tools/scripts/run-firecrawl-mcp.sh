#!/bin/sh
set -eu

operation=${1:-serve}
if [ "$operation" != "serve" ] && [ "$operation" != "status" ]; then
  echo "Usage: run-firecrawl-mcp.sh [serve|status]" >&2
  exit 64
fi

codex_home=${CODEX_HOME:-"$HOME/.codex"}
secrets_dir=${CODEX_SECRETS_DIR:-"$codex_home/secrets"}
secret_file="$secrets_dir/firecrawl.env"

if [ ! -f "$secret_file" ] || [ -L "$secret_file" ]; then
  echo "firecrawl.env must be a regular, non-symlinked file" >&2
  exit 1
fi

if file_mode=$(stat -f '%Lp' "$secret_file" 2>/dev/null); then
  :
elif file_mode=$(stat -c '%a' "$secret_file" 2>/dev/null); then
  :
else
  echo "Unable to inspect firecrawl.env permissions" >&2
  exit 1
fi
if [ "$file_mode" != "600" ]; then
  echo "firecrawl.env must have mode 600" >&2
  exit 1
fi

if file_owner=$(stat -f '%u' "$secret_file" 2>/dev/null); then
  :
elif file_owner=$(stat -c '%u' "$secret_file" 2>/dev/null); then
  :
else
  echo "Unable to inspect firecrawl.env ownership" >&2
  exit 1
fi
if [ "$file_owner" != "$(id -u)" ]; then
  echo "firecrawl.env must be owned by the current user" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$secret_file"
set +a

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
python_bin=$(command -v python3 || true)
if [ -z "$python_bin" ] && [ -n "${CODEX_LOCAL_BIN_DIR:-}" ] && [ -x "$CODEX_LOCAL_BIN_DIR/python3" ]; then
  python_bin="$CODEX_LOCAL_BIN_DIR/python3"
fi
if [ -z "$python_bin" ]; then
  echo "python3 not found" >&2
  exit 127
fi

if [ "$operation" = "status" ]; then
  exec "$python_bin" "$script_dir/firecrawl_budget_proxy.py" status
fi

npx_bin=$(command -v npx || true)
if [ -z "$npx_bin" ] && [ -n "${CODEX_LOCAL_BIN_DIR:-}" ] && [ -x "$CODEX_LOCAL_BIN_DIR/npx" ]; then
  npx_bin="$CODEX_LOCAL_BIN_DIR/npx"
fi
if [ -z "$npx_bin" ]; then
  echo "npx not found" >&2
  exit 127
fi

exec "$python_bin" "$script_dir/firecrawl_budget_proxy.py" serve -- "$npx_bin" -y firecrawl-mcp
