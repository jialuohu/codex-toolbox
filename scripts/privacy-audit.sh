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

record_matches() {
  local match remaining reference before after metadata numbered display
  local kind="${2:-tracked}" context="${3:-}"
  # Accept only separated shell/configuration references and descendants.
  # Similar directory names or token-adjacent text still need inspection.
  local home_reference_re='(^|[[:space:]`"'\''=]|:-)(\$HOME|\$\{HOME\})/[.]codex/secrets($|[[:space:]`"'\''/};])'
  while IFS= read -r match; do
    remaining="$match"
    metadata=""
    display="$match"
    if [ "$kind" = untracked ]; then
      display="$context:$match"
      if [[ "$match" =~ ^([0-9]+):(.*)$ ]]; then
        metadata="$context:${BASH_REMATCH[1]}:"
        remaining="${BASH_REMATCH[2]}"
      fi
    else
      numbered="$match"
      if [ "$kind" = history ]; then
        numbered="${match#"$context:"}"
      fi
      if [[ "$numbered" =~ ^([^:]+):([0-9]+):(.*)$ ]]; then
        metadata="${BASH_REMATCH[1]}:${BASH_REMATCH[2]}:"
        remaining="${BASH_REMATCH[3]}"
        # A second numbered field could belong to a colon-containing filename.
        # Retain the complete candidate rather than exempt ambiguous content.
        if [[ "$remaining" =~ :[0-9]+: ]]; then
          metadata=""
          remaining="$match"
        fi
      fi
    fi
    # Literal HOME-relative configuration references disclose no user's path.
    # Remove only those occurrences, then check the entire remaining line so a
    # nearby absolute path or credential still fails. Never evaluate the text.
    while [[ "$remaining" =~ $home_reference_re ]]; do
      reference="${BASH_REMATCH[0]}"
      before="${BASH_REMATCH[1]}"
      after="${BASH_REMATCH[3]}"
      remaining="${remaining/"$reference"/"$before<configured-secrets-path>$after"}"
    done
    if [[ "$metadata$remaining" =~ $AUDIT_RE ]]; then
      printf '%s\n' "$display"
      fail=1
    fi
  done <<< "$1"
}

run_current() {
  local matches scan_status enumeration_status=""
  if matches="$(git grep -I -n -E -e "$AUDIT_RE" -- . ":(exclude)$SELF_PATH")"; then
    record_matches "$matches"
  else
    scan_status=$?
    if [ "$scan_status" -ne 1 ]; then
      echo "Privacy audit could not scan tracked files" >&2
      return "$scan_status"
    fi
  fi
  while IFS= read -r -d '' path; do
    # Empty filenames cannot occur in Git. The final empty field separates the
    # NUL-delimited paths from the producer's exit status, including on Bash 3
    # where a process-substitution PID cannot reliably be waited on.
    if [ -z "$path" ]; then
      IFS= read -r -d '' enumeration_status || break
      break
    fi
    if matches="$(git grep --no-index -I -n -h -E -e "$AUDIT_RE" -- "$path")"; then
      record_matches "$matches" untracked "$path"
    else
      scan_status=$?
      if [ "$scan_status" -ne 1 ]; then
        echo "Privacy audit could not scan untracked file: $path" >&2
        return "$scan_status"
      fi
    fi
  done < <(
    if git ls-files --others --exclude-standard -z -- .; then
      enumeration_status=0
    else
      enumeration_status=$?
    fi
    printf '\0%s\0' "$enumeration_status"
  )
  if [ "$enumeration_status" != 0 ]; then
    echo "Privacy audit could not enumerate untracked files" >&2
    return "${enumeration_status:-2}"
  fi
}

run_history() {
  local matches scan_status revisions
  if revisions="$(git rev-list --all)"; then
    :
  else
    scan_status=$?
    echo "Privacy audit could not enumerate revisions" >&2
    return "$scan_status"
  fi
  while IFS= read -r rev; do
    [ -n "$rev" ] || continue
    if matches="$(git grep -I -n -E -e "$AUDIT_RE" "$rev" -- . ":(exclude)$SELF_PATH")"; then
      record_matches "$matches" history "$rev"
    else
      scan_status=$?
      if [ "$scan_status" -ne 1 ]; then
        echo "Privacy audit could not scan revision: $rev" >&2
        return "$scan_status"
      fi
    fi
  done <<< "$revisions"
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
