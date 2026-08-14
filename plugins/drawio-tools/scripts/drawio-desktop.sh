#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  drawio-desktop.sh --doctor
  drawio-desktop.sh --open INPUT.drawio
  drawio-desktop.sh --export png|svg|pdf INPUT.drawio OUTPUT

Set DRAWIO_DESKTOP_BIN to override executable discovery.
EOF
}

resolve_drawio() {
  local candidate=""

  if [ -n "${DRAWIO_DESKTOP_BIN:-}" ]; then
    candidate="$DRAWIO_DESKTOP_BIN"
  elif command -v drawio >/dev/null 2>&1; then
    candidate="$(command -v drawio)"
  elif command -v draw.io >/dev/null 2>&1; then
    candidate="$(command -v draw.io)"
  elif [ -x "/Applications/draw.io.app/Contents/MacOS/draw.io" ]; then
    candidate="/Applications/draw.io.app/Contents/MacOS/draw.io"
  elif [ -x "/mnt/c/Program Files/draw.io/draw.io.exe" ]; then
    candidate="/mnt/c/Program Files/draw.io/draw.io.exe"
  fi

  if [ -z "$candidate" ] || [ ! -x "$candidate" ]; then
    echo "draw.io Desktop CLI not found; set DRAWIO_DESKTOP_BIN or run setup-drawio-tools.sh --install --with-desktop" >&2
    return 1
  fi
  case "$candidate" in
    /*) ;;
    *) echo "draw.io Desktop executable must resolve to an absolute path: $candidate" >&2; return 1 ;;
  esac

  printf '%s\n' "$candidate"
}

require_absolute() {
  case "$1" in
    /*) ;;
    *) echo "draw.io helper paths must be absolute: $1" >&2; exit 2 ;;
  esac
}

command_name="${1:-}"
case "$command_name" in
  --doctor)
    [ "$#" -eq 1 ] || { usage >&2; exit 2; }
    drawio_bin="$(resolve_drawio)"
    version="$("$drawio_bin" --version 2>&1)"
    version="${version%%$'\n'*}"
    printf 'drawio_desktop_bin=%s\n' "$drawio_bin"
    printf 'drawio_desktop_version=%s\n' "$version"
    ;;
  --open)
    [ "$#" -eq 2 ] || { usage >&2; exit 2; }
    input="$2"
    require_absolute "$input"
    [ -f "$input" ] || { echo "draw.io source not found: $input" >&2; exit 1; }
    drawio_bin="$(resolve_drawio)"
    "$drawio_bin" "$input" >/dev/null 2>&1 &
    ;;
  --export)
    [ "$#" -eq 4 ] || { usage >&2; exit 2; }
    format="$2"
    input="$3"
    output="$4"
    case "$format" in png|svg|pdf) ;; *) echo "unsupported draw.io export format: $format" >&2; exit 2 ;; esac
    require_absolute "$input"
    require_absolute "$output"
    [ -f "$input" ] || { echo "draw.io source not found: $input" >&2; exit 1; }
    [ -d "$(dirname "$output")" ] || { echo "draw.io output directory does not exist: $(dirname "$output")" >&2; exit 1; }
    [ ! -L "$output" ] || { echo "refusing symlink draw.io export target: $output" >&2; exit 1; }
    drawio_bin="$(resolve_drawio)"
    "$drawio_bin" -x -f "$format" -e -b 10 -o "$output" "$input"
    [ -s "$output" ] || { echo "draw.io Desktop did not create a non-empty export: $output" >&2; exit 1; }
    printf '%s\n' "$output"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
