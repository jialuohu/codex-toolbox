#!/usr/bin/env bash
set -euo pipefail

skill_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
secrets_dir="${CODEX_SECRETS_DIR:-${CODEX_HOME:-$HOME/.codex}/secrets}"
secret_file="$secrets_dir/bestblogs.env"

if [[ ! -f "$secret_file" ]]; then
  echo "Missing bestblogs.env in the configured secrets directory." >&2
  exit 2
fi

set -a
# shellcheck source=/dev/null
source "$secret_file"
set +a

if [[ -z "${BESTBLOGS_API_KEY:-}" ]]; then
  echo "BESTBLOGS_API_KEY is required in bestblogs.env." >&2
  exit 2
fi

exec python3 "$skill_dir/scripts/wechat_digest.py" "$@"
