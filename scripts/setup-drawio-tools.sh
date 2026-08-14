#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_ROOT="$ROOT/plugins/drawio-tools"
BOOTSTRAP="$PLUGIN_ROOT/runtime/bootstrap"
VERIFY_SCRIPT="$PLUGIN_ROOT/scripts/verify-drawio-runtime.mjs"
DESKTOP_HELPER="$PLUGIN_ROOT/scripts/drawio-desktop.sh"
DESKTOP_FIXTURE="$PLUGIN_ROOT/assets/fixtures/basic.drawio"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
RUNTIME_PARENT="$CODEX_ROOT/runtime"
RUNTIME_ROOT="$RUNTIME_PARENT/drawio-tools"
ACTIVE_DIR="$RUNTIME_ROOT/active"
PACKAGE_VERSION="1.4.0"
PACKAGE_INTEGRITY="sha512-DRg8oveMZSN5rgH6TAtkfaGSm364GzJV53uqJE9ug4EYCORjCgEpapFr0XLi037kq2OXdM2Z/vgAyj7N6vbjiA=="
PACKAGE_TREE_SHA256="9b8fed587fd1bc61041c4a57ec536ad653673e8f413141d7ff6ef0b03754ac6d"
SHAPE_INDEX_COMMIT="9ce8dc19caa8861315337ec91f3ac7c0df8e0978"
SHAPE_INDEX_URL="https://raw.githubusercontent.com/jgraph/drawio-mcp/${SHAPE_INDEX_COMMIT}/shape-search/search-index.json"
SHAPE_INDEX_SHA256="09b84516025e46238e5dd47465cc96ecfd96134ea853ace1063e1ca19dd34601"
SHAPE_INDEX_BYTES="4776086"
SHAPE_INDEX_ENTRIES="10446"

usage() {
  cat <<'EOF'
Usage: scripts/setup-drawio-tools.sh --check|--install [--with-desktop]

  --check          Verify the installed MCP runtime without network access.
  --install        Install or refresh the exact lockfile-approved MCP runtime.
  --with-desktop   Also require/install draw.io Desktop and smoke-test exports.
EOF
}

fail() {
  echo "$*" >&2
  exit 1
}

hash_file() {
  local path="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  else
    fail "Neither shasum nor sha256sum is available"
  fi
}

resolve_node() {
  local node_bin=""
  node_bin="$(command -v node || true)"
  if [ -z "$node_bin" ] && [ -n "${CODEX_LOCAL_BIN_DIR:-}" ] && [ -x "$CODEX_LOCAL_BIN_DIR/node" ]; then
    node_bin="$CODEX_LOCAL_BIN_DIR/node"
  fi
  [ -n "$node_bin" ] || fail "Node.js 20 or newer is required"
  local node_major
  node_major="$($node_bin -p 'Number(process.versions.node.split(".")[0])')"
  [ "$node_major" -ge 20 ] || fail "Node.js 20 or newer is required; found $($node_bin --version)"
  printf '%s\n' "$node_bin"
}

resolve_npm() {
  local npm_bin=""
  npm_bin="$(command -v npm || true)"
  if [ -z "$npm_bin" ] && [ -n "${CODEX_LOCAL_BIN_DIR:-}" ] && [ -x "$CODEX_LOCAL_BIN_DIR/npm" ]; then
    npm_bin="$CODEX_LOCAL_BIN_DIR/npm"
  fi
  [ -n "$npm_bin" ] || fail "npm is required to install the Draw.io MCP runtime"
  printf '%s\n' "$npm_bin"
}

ensure_safe_runtime_root() {
  local requested_mode="$1"
  case "$CODEX_ROOT" in
    /*) ;;
    *) fail "CODEX_HOME must resolve to an absolute path" ;;
  esac
  if [ "$requested_mode" = "--check" ] && [ ! -e "$RUNTIME_PARENT" ]; then
    return
  fi
  mkdir -p "$RUNTIME_PARENT"
  [ ! -L "$RUNTIME_PARENT" ] || fail "Refusing symlink runtime parent: $RUNTIME_PARENT"
  if [ -e "$RUNTIME_ROOT" ]; then
    [ -d "$RUNTIME_ROOT" ] && [ ! -L "$RUNTIME_ROOT" ] || fail "Draw.io runtime root is not a safe directory: $RUNTIME_ROOT"
  elif [ "$requested_mode" = "--install" ]; then
    mkdir -m 700 "$RUNTIME_ROOT"
  fi
}

check_runtime() {
  local node_bin="$1"
  "$node_bin" "$VERIFY_SCRIPT" "$ACTIVE_DIR" "$BOOTSTRAP/package-lock.json"
  local observed_version
  observed_version="$($node_bin "$ACTIVE_DIR/node_modules/@drawio/mcp/src/index.js" --version)"
  [ "$observed_version" = "$PACKAGE_VERSION" ] || fail "Draw.io MCP reported unexpected version: $observed_version"
}

runtime_is_current() {
  local node_bin="$1"
  "$node_bin" "$VERIFY_SCRIPT" "$ACTIVE_DIR" "$BOOTSTRAP/package-lock.json" >/dev/null 2>&1 || return 1
  [ "$($node_bin "$ACTIVE_DIR/node_modules/@drawio/mcp/src/index.js" --version 2>/dev/null)" = "$PACKAGE_VERSION" ]
}

candidate=""
cleanup_candidate() {
  if [ -n "$candidate" ]; then
    case "$candidate" in
      "$RUNTIME_ROOT"/.candidate.*) rm -rf -- "$candidate" ;;
      *) echo "Refusing unsafe candidate cleanup path: $candidate" >&2 ;;
    esac
  fi
}
trap cleanup_candidate EXIT

install_runtime() {
  local node_bin="$1"
  local npm_bin="$2"
  local curl_bin
  curl_bin="$(command -v curl || true)"
  [ -n "$curl_bin" ] || fail "curl is required to install the offline Draw.io shape index"

  if runtime_is_current "$node_bin"; then
    echo "Draw.io MCP runtime is already current: $ACTIVE_DIR"
    check_runtime "$node_bin"
    return
  fi

  candidate="$(mktemp -d "$RUNTIME_ROOT/.candidate.XXXXXXXX")"
  cp "$BOOTSTRAP/package.json" "$candidate/package.json"
  cp "$BOOTSTRAP/package-lock.json" "$candidate/package-lock.json"

  "$npm_bin" ci \
    --prefix "$candidate" \
    --ignore-scripts \
    --omit=dev \
    --no-audit \
    --no-fund
  "$npm_bin" audit \
    --prefix "$candidate" \
    --omit=dev \
    --audit-level=high

  local shape_index
  shape_index="$candidate/node_modules/@drawio/mcp/src/search-index.json"
  "$curl_bin" \
    --proto '=https' \
    --tlsv1.2 \
    --fail \
    --location \
    --silent \
    --show-error \
    "$SHAPE_INDEX_URL" \
    --output "$shape_index"

  [ "$(hash_file "$shape_index")" = "$SHAPE_INDEX_SHA256" ] || fail "Downloaded Draw.io shape index failed SHA-256 verification"
  [ "$(wc -c < "$shape_index" | tr -d ' ')" = "$SHAPE_INDEX_BYTES" ] || fail "Downloaded Draw.io shape index has an unexpected size"
  [ "$("$node_bin" "$VERIFY_SCRIPT" --package-tree-sha256 "$candidate/node_modules/@drawio/mcp")" = "$PACKAGE_TREE_SHA256" ] || fail "Installed @drawio/mcp package tree failed SHA-256 verification"

  local lock_sha256
  lock_sha256="$(hash_file "$BOOTSTRAP/package-lock.json")"
  RECEIPT_PATH="$candidate/.drawio-tools-runtime.json" \
  PACKAGE_VERSION="$PACKAGE_VERSION" \
  PACKAGE_INTEGRITY="$PACKAGE_INTEGRITY" \
  PACKAGE_TREE_SHA256="$PACKAGE_TREE_SHA256" \
  LOCK_SHA256="$lock_sha256" \
  SHAPE_INDEX_COMMIT="$SHAPE_INDEX_COMMIT" \
  SHAPE_INDEX_SHA256="$SHAPE_INDEX_SHA256" \
  SHAPE_INDEX_BYTES="$SHAPE_INDEX_BYTES" \
  SHAPE_INDEX_ENTRIES="$SHAPE_INDEX_ENTRIES" \
    "$node_bin" <<'NODE'
import { writeFileSync } from "node:fs";

const receipt = {
  schemaVersion: 1,
  packageVersion: process.env.PACKAGE_VERSION,
  packageIntegrity: process.env.PACKAGE_INTEGRITY,
  packageTreeSha256: process.env.PACKAGE_TREE_SHA256,
  lockSha256: process.env.LOCK_SHA256,
  shapeIndexCommit: process.env.SHAPE_INDEX_COMMIT,
  shapeIndexSha256: process.env.SHAPE_INDEX_SHA256,
  shapeIndexBytes: Number(process.env.SHAPE_INDEX_BYTES),
  shapeIndexEntries: Number(process.env.SHAPE_INDEX_ENTRIES),
  installedAt: new Date().toISOString(),
};

writeFileSync(process.env.RECEIPT_PATH, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o600 });
NODE

  "$node_bin" "$VERIFY_SCRIPT" "$candidate" "$BOOTSTRAP/package-lock.json" >/dev/null
  [ "$($node_bin "$candidate/node_modules/@drawio/mcp/src/index.js" --version)" = "$PACKAGE_VERSION" ] || fail "Candidate Draw.io MCP version check failed"

  local previous="$RUNTIME_ROOT/previous"
  local archived_previous="$RUNTIME_ROOT/previous.$(date -u +%Y%m%dT%H%M%SZ).$$"
  if [ -e "$previous" ]; then
    mv "$previous" "$archived_previous"
  fi
  if [ -e "$ACTIVE_DIR" ]; then
    [ -d "$ACTIVE_DIR" ] && [ ! -L "$ACTIVE_DIR" ] || fail "Refusing unsafe active runtime: $ACTIVE_DIR"
    mv "$ACTIVE_DIR" "$previous"
  fi
  if ! mv "$candidate" "$ACTIVE_DIR"; then
    if [ -d "$previous" ] && [ ! -e "$ACTIVE_DIR" ]; then
      mv "$previous" "$ACTIVE_DIR"
    fi
    fail "Could not promote the verified Draw.io runtime"
  fi
  candidate=""

  check_runtime "$node_bin"
  echo "Promoted verified Draw.io MCP runtime: $ACTIVE_DIR"
}

ensure_desktop() {
  local requested_mode="$1"
  if "$DESKTOP_HELPER" --doctor; then
    return
  fi

  if [ "$requested_mode" != "--install" ]; then
    fail "draw.io Desktop is unavailable; --check never installs software"
  fi

  if [ "$(uname -s)" != "Darwin" ]; then
    fail "draw.io Desktop is not installed; install it for this platform or set DRAWIO_DESKTOP_BIN"
  fi

  local brew_bin
  brew_bin="$(command -v brew || true)"
  [ -n "$brew_bin" ] || fail "Homebrew is required for opt-in draw.io Desktop installation on macOS"
  "$brew_bin" install --cask drawio
  "$DESKTOP_HELPER" --doctor
}

smoke_desktop() {
  local smoke_dir
  smoke_dir="$(mktemp -d)"
  local source="$smoke_dir/basic.drawio"
  cp "$DESKTOP_FIXTURE" "$source"

  "$DESKTOP_HELPER" --export png "$source" "$smoke_dir/basic.png" >/dev/null
  "$DESKTOP_HELPER" --export svg "$source" "$smoke_dir/basic.svg" >/dev/null
  "$DESKTOP_HELPER" --export pdf "$source" "$smoke_dir/basic.pdf" >/dev/null

  python3 - "$smoke_dir" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
png = (root / "basic.png").read_bytes()
svg = (root / "basic.svg").read_bytes()
pdf = (root / "basic.pdf").read_bytes()
if not png.startswith(b"\x89PNG\r\n\x1a\n"):
    raise SystemExit("draw.io Desktop PNG smoke export has an invalid signature")
if b"<svg" not in svg[:4096]:
    raise SystemExit("draw.io Desktop SVG smoke export has an invalid signature")
if not pdf.startswith(b"%PDF"):
    raise SystemExit("draw.io Desktop PDF smoke export has an invalid signature")
PY

  case "$smoke_dir" in
    /tmp/*|/private/tmp/*|/var/folders/*) rm -rf -- "$smoke_dir" ;;
    *) echo "Leaving unexpected Desktop smoke directory in place: $smoke_dir" >&2 ;;
  esac
  echo "draw.io Desktop PNG, SVG, and PDF exports passed"
}

mode=""
with_desktop=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --check|--install)
      [ -z "$mode" ] || { usage >&2; exit 2; }
      mode="$1"
      ;;
    --with-desktop)
      with_desktop=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
  shift
done

[ -n "$mode" ] || { usage >&2; exit 2; }
[ -f "$BOOTSTRAP/package-lock.json" ] || fail "Draw.io runtime lockfile is missing"
ensure_safe_runtime_root "$mode"
NODE_BIN="$(resolve_node)"

if [ "$mode" = "--check" ]; then
  check_runtime "$NODE_BIN"
else
  NPM_BIN="$(resolve_npm)"
  install_runtime "$NODE_BIN" "$NPM_BIN"
fi

if [ "$with_desktop" -eq 1 ]; then
  ensure_desktop "$mode"
  smoke_desktop
fi
