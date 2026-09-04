#!/bin/sh
set -eu

case "${1:-}" in
  ""|--test|--config) ;;
  *)
    echo "Usage: run-canvas-mcp.sh [--test|--config]" >&2
    exit 64
    ;;
esac

codex_home=${CODEX_HOME:-"$HOME/.codex"}
secrets_dir=${CODEX_SECRETS_DIR:-"$codex_home/secrets"}
secret_file="$secrets_dir/canvas-tools/canvas.env"

if [ ! -f "$secret_file" ] || [ -L "$secret_file" ]; then
  echo "Canvas configuration must be a regular, non-symlinked file at $secret_file" >&2
  exit 1
fi

if file_mode=$(stat -f '%Lp' "$secret_file" 2>/dev/null); then
  :
elif file_mode=$(stat -c '%a' "$secret_file" 2>/dev/null); then
  :
else
  echo "Unable to inspect Canvas configuration permissions" >&2
  exit 1
fi
if [ "$file_mode" != "600" ]; then
  echo "Canvas configuration must have mode 600" >&2
  exit 1
fi

if file_owner=$(stat -f '%u' "$secret_file" 2>/dev/null); then
  :
elif file_owner=$(stat -c '%u' "$secret_file" 2>/dev/null); then
  :
else
  echo "Unable to inspect Canvas configuration ownership" >&2
  exit 1
fi
if [ "$file_owner" != "$(id -u)" ]; then
  echo "Canvas configuration must be owned by the current user" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$secret_file"
set +a

if [ -z "${CANVAS_API_URL:-}" ] || [ -z "${CANVAS_API_TOKEN:-}" ]; then
  echo "Canvas configuration must define CANVAS_API_URL and CANVAS_API_TOKEN" >&2
  exit 1
fi

case "$CANVAS_API_URL" in
  https://*/api/v1|https://*/api/v1/) ;;
  *)
    echo "CANVAS_API_URL must be an HTTPS URL ending in /api/v1" >&2
    exit 1
    ;;
esac

# These values are policy, not user configuration. Set them after loading the
# secret file so a copied upstream template cannot widen the installed plugin.
export CANVAS_ROLE=student
export STUDENT_WRITE_TOOLS=submit_assignment,comment_on_my_submission
export COURSE_AGENT_POLICY_ENABLED=false
export EXECUTE_TYPESCRIPT_ENABLED=false
export LOG_API_REQUESTS=false
export LOG_REDACT_PII=true

uvx_bin=$(command -v uvx || true)
if [ -z "$uvx_bin" ] && [ -n "${CODEX_LOCAL_BIN_DIR:-}" ] && [ -x "$CODEX_LOCAL_BIN_DIR/uvx" ]; then
  uvx_bin="$CODEX_LOCAL_BIN_DIR/uvx"
fi
if [ -z "$uvx_bin" ]; then
  echo "uvx not found; rerun the codex-toolbox prerequisite setup" >&2
  exit 127
fi

if [ -n "${1:-}" ]; then
  exec "$uvx_bin" --from canvas-mcp==1.12.0 canvas-mcp-server "$1" --role student
fi
exec "$uvx_bin" --from canvas-mcp==1.12.0 canvas-mcp-server --role student
