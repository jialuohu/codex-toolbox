#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-all}"

if [ "$MODE" != "all" ] && [ "$MODE" != "current" ] && [ "$MODE" != "history" ]; then
  echo "Usage: scripts/privacy-audit.sh [all|current|history]" >&2
  exit 2
fi

PRIVATE_PATH_RE='(/Users/[[:alnum:]_.-]+/|/home/[[:alnum:]_.-]+/|[.]codex[[:space:]]*/[[:space:]]*secrets|[.]vibe-trading)'
TOKEN_RE='(authorization:[[:space:]]*bearer[[:space:]]+[A-Za-z0-9._=-]{20,}|bearer[[:space:]]+[A-Za-z0-9._=-]{20,}|x-api-key[[:space:]]*[:=]|(api[_-]?key|access[_-]?token|refresh[_-]?token|secret[_-]?key|client[_-]?secret|private[_-]?key|password|passwd|session[_-]?token)[[:space:]]*[:=][[:space:]]*["'\'']?[A-Za-z0-9._/+@=-]{12,})'
KEY_RE='(-----BEGIN (RSA |DSA |EC |OPENSSH |PGP |PRIVATE )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{35}|ya29[.][0-9A-Za-z_-]{20,})'
AUDIT_RE="(${PRIVATE_PATH_RE}|${TOKEN_RE}|${KEY_RE})"
SELF_PATH="scripts/privacy-audit.sh"

fail=0

run_current() {
  if rg --hidden --no-ignore -n -I -e "$AUDIT_RE" -g '!/.git/**' -g "!$SELF_PATH" .; then
    fail=1
  fi
}

run_history() {
  while IFS= read -r rev; do
    if git grep -I -n -E -e "$AUDIT_RE" "$rev" -- . ":(exclude)$SELF_PATH"; then
      fail=1
    fi
  done < <(git rev-list --all)
}

case "$MODE" in
  all)
    run_current
    run_history
    ;;
  current)
    run_current
    ;;
  history)
    run_history
    ;;
esac

if [ "$fail" -ne 0 ]; then
  echo "Privacy audit found matches" >&2
  exit 1
fi

echo "Privacy audit found no matches"
