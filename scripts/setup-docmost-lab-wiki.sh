#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
SOURCE="$ROOT/plugins/research-tools/runtime/docmost-lab-wiki"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
SECRETS_ROOT="${CODEX_SECRETS_DIR:-$CODEX_ROOT/secrets}"
RUNTIME_PARENT="$CODEX_ROOT/runtime"
RUNTIME="$RUNTIME_PARENT/docmost-lab-wiki"
MODEL_PARENT="$RUNTIME_PARENT/docmost-lab-wiki-model"
MODEL_REVISION="c32e6154d1bb7a0e47c5e745fd895e7700f44385"
MODEL="$MODEL_PARENT/$MODEL_REVISION"
MODEL_REPOSITORY="Qdrant/bge-small-en-v1.5-onnx-Q"
MODEL_FILE="model_optimized.onnx"
MODEL_FILE_SIZE="66465124"
MODEL_FILE_SHA256="51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431"
CONFIG="$SECRETS_ROOT/docmost-lab-wiki.env"
RUNNER="$ROOT/plugins/research-tools/scripts/docmost-lab-wiki.sh"
UV_BIN="$(command -v uv || true)"

usage() {
  echo "Usage: scripts/setup-docmost-lab-wiki.sh --check|--install|--prewarm" >&2
}

require_prerequisites() {
  if [ -z "$UV_BIN" ] || [ ! -d "$SOURCE" ] || [ ! -x "$RUNNER" ]; then
    echo "Lab Wiki setup prerequisites are missing" >&2
    exit 1
  fi
  if [ -L "$RUNTIME_PARENT" ] || [ -L "$SECRETS_ROOT" ]; then
    echo "Lab Wiki runtime or secrets parent is unsafe" >&2
    exit 1
  fi
  mkdir -p "$RUNTIME_PARENT" "$SECRETS_ROOT" "$MODEL_PARENT"
  chmod 700 "$SECRETS_ROOT" "$MODEL_PARENT"
}

verify_model() {
  local candidate="$1"
  MODEL_VERIFY_PATH="$candidate" \
  MODEL_VERIFY_FILE="$MODEL_FILE" \
  MODEL_VERIFY_SIZE="$MODEL_FILE_SIZE" \
  MODEL_VERIFY_SHA256="$MODEL_FILE_SHA256" \
  python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["MODEL_VERIFY_PATH"])
model = root / os.environ["MODEL_VERIFY_FILE"]
required = (
    "config.json",
    "model_optimized.onnx",
    "ort_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
)
if root.is_symlink() or not all((root / name).is_file() for name in required):
    raise SystemExit("Pinned Lab Wiki model is incomplete or unsafe")
if model.stat().st_size != int(os.environ["MODEL_VERIFY_SIZE"]):
    raise SystemExit("Pinned Lab Wiki model size is invalid")
digest = hashlib.sha256()
with model.open("rb") as source:
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
if digest.hexdigest() != os.environ["MODEL_VERIFY_SHA256"]:
    raise SystemExit("Pinned Lab Wiki model checksum is invalid")
receipt = root / "MODEL_RECEIPT.json"
if receipt.exists():
    value = json.loads(receipt.read_text())
    if value.get("sha256") != digest.hexdigest():
        raise SystemExit("Pinned Lab Wiki model receipt is invalid")
PY
}

install_runtime() {
  "$UV_BIN" lock --check --directory "$SOURCE"
  local backup="$RUNTIME_PARENT/.docmost-lab-wiki-runtime.backup"
  cleanup_runtime() {
    rm -rf "$RUNTIME"
    if [ -e "$backup" ]; then
      mv "$backup" "$RUNTIME"
    fi
  }
  trap cleanup_runtime EXIT
  rm -rf "$backup"
  if [ -e "$RUNTIME" ]; then
    mv "$RUNTIME" "$backup"
  fi
  UV_PROJECT_ENVIRONMENT="$RUNTIME" "$UV_BIN" sync \
    --frozen --no-dev --no-editable --reinstall-package docmost-lab-wiki \
    --directory "$SOURCE"
  if [ ! -x "$RUNTIME/bin/docmost-lab-wiki" ]; then
    echo "Lab Wiki runtime installation did not produce its CLI" >&2
    exit 1
  fi
  rm -rf "$backup"
  trap - EXIT
}

prewarm_model() {
  if verify_model "$MODEL" >/dev/null 2>&1; then
    return
  fi
  if [ ! -x "$RUNTIME/bin/python" ]; then
    echo "Install the Lab Wiki runtime before prewarming its model" >&2
    exit 1
  fi
  local candidate
  candidate="$(mktemp -d "$MODEL_PARENT/.model.XXXXXX")"
  local backup="$MODEL_PARENT/.model.backup"
  cleanup_model() {
    rm -rf "$candidate"
  }
  trap cleanup_model EXIT
  MODEL_DOWNLOAD_PATH="$candidate" \
  MODEL_DOWNLOAD_REPOSITORY="$MODEL_REPOSITORY" \
  MODEL_DOWNLOAD_REVISION="$MODEL_REVISION" \
  "$RUNTIME/bin/python" - <<'PY'
import json
import os
from pathlib import Path
from huggingface_hub import snapshot_download

destination = Path(os.environ["MODEL_DOWNLOAD_PATH"])
snapshot_download(
    repo_id=os.environ["MODEL_DOWNLOAD_REPOSITORY"],
    revision=os.environ["MODEL_DOWNLOAD_REVISION"],
    local_dir=destination,
    allow_patterns=[
        "config.json",
        "model_optimized.onnx",
        "ort_config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.txt",
    ],
)
PY
  verify_model "$candidate"
  MODEL_RECEIPT_PATH="$candidate/MODEL_RECEIPT.json" \
  MODEL_RECEIPT_REPOSITORY="$MODEL_REPOSITORY" \
  MODEL_RECEIPT_REVISION="$MODEL_REVISION" \
  MODEL_RECEIPT_SHA256="$MODEL_FILE_SHA256" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["MODEL_RECEIPT_PATH"])
path.write_text(json.dumps({
    "repository": os.environ["MODEL_RECEIPT_REPOSITORY"],
    "revision": os.environ["MODEL_RECEIPT_REVISION"],
    "sha256": os.environ["MODEL_RECEIPT_SHA256"],
}, sort_keys=True) + "\n")
PY
  verify_model "$candidate"
  rm -rf "$backup"
  if [ -e "$MODEL" ]; then
    mv "$MODEL" "$backup"
  fi
  if ! mv "$candidate" "$MODEL"; then
    if [ -e "$backup" ]; then
      mv "$backup" "$MODEL"
    fi
    exit 1
  fi
  rm -rf "$backup"
  trap - EXIT
}

detect_vault() {
  if [ -n "${DOCMOST_LAB_WIKI_VAULT:-}" ]; then
    printf '%s\n' "$DOCMOST_LAB_WIKI_VAULT"
    return
  fi
  python3 - <<'PY'
import json
from pathlib import Path

registry = Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
if not registry.is_file():
    raise SystemExit("Set DOCMOST_LAB_WIKI_VAULT to an absolute Obsidian vault path")
value = json.loads(registry.read_text())
vaults = value.get("vaults", {})
paths = sorted({item.get("path") for item in vaults.values() if isinstance(item, dict) and item.get("path")})
if len(paths) != 1:
    raise SystemExit("Set DOCMOST_LAB_WIKI_VAULT because exactly one vault was not detected")
print(paths[0])
PY
}

ensure_config() {
  if [ -e "$CONFIG" ]; then
    if [ -L "$CONFIG" ]; then
      echo "Lab Wiki configuration must not be a symlink" >&2
      exit 1
    fi
    chmod 600 "$CONFIG"
    return
  fi
  local vault
  vault="$(detect_vault)"
  if [ ! -d "$vault" ] || [ -L "$vault" ]; then
    echo "Detected Obsidian vault is missing or unsafe" >&2
    exit 1
  fi
  LAB_WIKI_CONFIG_PATH="$CONFIG" \
  LAB_WIKI_CONFIG_VAULT="$vault" \
  LAB_WIKI_CONFIG_INDEX="$SECRETS_ROOT/docmost-lab-wiki/index.sqlite3" \
  LAB_WIKI_CONFIG_MODEL="$MODEL" \
  python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["LAB_WIKI_CONFIG_PATH"])
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
descriptor = os.open(path, flags, 0o600)
with os.fdopen(descriptor, "w") as output:
    output.write(f'DOCMOST_LAB_WIKI_VAULT={os.environ["LAB_WIKI_CONFIG_VAULT"]}\n')
    output.write('DOCMOST_LAB_WIKI_ROOT=Research/Lab Wiki\n')
    output.write(f'DOCMOST_LAB_WIKI_INDEX={os.environ["LAB_WIKI_CONFIG_INDEX"]}\n')
    output.write(f'DOCMOST_LAB_WIKI_MODEL_PATH={os.environ["LAB_WIKI_CONFIG_MODEL"]}\n')
PY
}

check() {
  require_prerequisites
  "$UV_BIN" lock --check --directory "$SOURCE"
  if [ ! -x "$RUNTIME/bin/docmost-lab-wiki" ] || [ -L "$RUNTIME" ]; then
    echo "Lab Wiki runtime is missing or unsafe" >&2
    exit 1
  fi
  verify_model "$MODEL"
  if [ ! -f "$CONFIG" ] || [ -L "$CONFIG" ]; then
    echo "Lab Wiki configuration is missing or unsafe" >&2
    exit 1
  fi
  "$RUNNER" model-check >/dev/null
  echo "Lab Wiki runtime, model, and configuration are ready"
}

case "${1:-}" in
  --check)
    check
    ;;
  --install)
    require_prerequisites
    install_runtime
    prewarm_model
    ensure_config
    check
    ;;
  --prewarm)
    require_prerequisites
    prewarm_model
    ;;
  *)
    usage
    exit 2
    ;;
esac
