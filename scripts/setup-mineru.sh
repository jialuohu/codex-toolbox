#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly MINERU_VERSION="3.4.4"
readonly REQUIRED_PYTHON="3.12"
readonly DEFAULT_MIN_DISK_GB="20"
readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

UV_TOOL_DIR="${MINERU_UV_TOOL_DIR:-${UV_TOOL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/uv/tools}}"
RUNTIME_DIR="$UV_TOOL_DIR/mineru"
MODEL_CACHE_DIR="${MINERU_MODEL_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/mineru/models-${MINERU_VERSION}}"
CONFIG_NAME="${MINERU_TOOLS_CONFIG_JSON:-mineru.json}"
if [[ "$CONFIG_NAME" = /* ]]; then
  CONFIG_FILE="$CONFIG_NAME"
else
  CONFIG_FILE="$HOME/$CONFIG_NAME"
fi
MIN_DISK_GB="${MINERU_MIN_DISK_GB:-$DEFAULT_MIN_DISK_GB}"
RUNTIME_PYTHON="${MINERU_RUNTIME_PYTHON:-$RUNTIME_DIR/bin/python3}"
RUNTIME_DOWNLOADER="${MINERU_MODELS_DOWNLOADER:-$RUNTIME_DIR/bin/mineru-models-download}"

usage() {
  cat >&2 <<'EOF'
Usage: scripts/setup-mineru.sh --check|--install|--download-models

  --check            Read-only MinerU runtime doctor.
  --install          Create the managed Python 3.12 runtime and install MinerU 3.4.4.
  --download-models  Download models outside every Git checkout and Obsidian vault.
EOF
}

platform_ready() {
  [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]
}

resolve_candidate_path() {
  local candidate="$1"
  local existing=""
  local suffix=""
  local resolved=""

  if [[ "$candidate" != /* ]]; then
    candidate="$PWD/$candidate"
  fi
  existing="$candidate"
  while [ ! -e "$existing" ] && [ "$existing" != "/" ]; do
    suffix="/$(basename "$existing")$suffix"
    existing="$(dirname "$existing")"
  done
  if [ -d "$existing" ]; then
    resolved="$(cd "$existing" 2>/dev/null && pwd -P)"
  else
    resolved="$(realpath -q "$existing" 2>/dev/null || true)"
  fi
  printf '%s\n' "$resolved$suffix"
}

path_has_marker_ancestor() {
  local candidate="$1"
  local marker="$2"
  local cursor=""

  cursor="$(resolve_candidate_path "$candidate")"
  while true; do
    if [ -e "$cursor/$marker" ]; then
      return 0
    fi
    if [ "$cursor" = "/" ]; then
      return 1
    fi
    cursor="$(dirname "$cursor")"
  done
}

path_is_within() {
  local candidate root
  candidate="$(resolve_candidate_path "$1")"
  root="$(resolve_candidate_path "$2")"
  [ "$candidate" = "$root" ] || [[ "$candidate" == "$root/"* ]]
}

path_is_private_destination() {
  local candidate="$1"
  local vault="${CODEX_OBSIDIAN_VAULT:-}"

  path_has_marker_ancestor "$candidate" ".git" && return 0
  path_has_marker_ancestor "$candidate" ".obsidian" && return 0
  if [ -n "$vault" ] && path_is_within "$candidate" "$vault"; then
    return 0
  fi
  return 1
}

runtime_probe() {
  [ -x "$RUNTIME_PYTHON" ] || return 1

  PYTHONDONTWRITEBYTECODE=1 "$RUNTIME_PYTHON" -B - <<'PY'
import importlib.metadata
import importlib.util
import platform
import sys

try:
    mineru_version = importlib.metadata.version("mineru")
except importlib.metadata.PackageNotFoundError:
    mineru_version = "missing"

mps_built = "no"
mps_available = "no"
try:
    import torch
    mps_built = "yes" if torch.backends.mps.is_built() else "no"
    mps_available = "yes" if torch.backends.mps.is_available() else "no"
except (ImportError, AttributeError):
    pass

mlx = "yes" if importlib.util.find_spec("mlx") is not None else "no"
mlx_vlm = "yes" if importlib.util.find_spec("mlx_vlm") is not None else "no"
mlx_gpu = "no"
vlm_engine = "unknown"
if mlx == "yes" and mlx_vlm == "yes":
    try:
        import mlx.core as mx
        mlx_gpu = "yes" if "gpu" in str(mx.default_device()).lower() else "no"
        from mineru.utils.engine_utils import get_vlm_engine
        vlm_engine = get_vlm_engine("auto")
    except Exception:
        pass
python_version = f"{sys.version_info.major}.{sys.version_info.minor}"

print("|".join((
    mineru_version,
    python_version,
    platform.machine(),
    mps_built,
    mps_available,
    mlx,
    mlx_vlm,
    mlx_gpu,
    vlm_engine,
)))
PY
}

model_cache_state() {
  local system_python
  if [ ! -f "$CONFIG_FILE" ]; then
    printf '%s\n' "missing"
    return
  fi
  system_python="$(command -v python3 || true)"
  if [ -z "$system_python" ]; then
    printf '%s\n' "unreadable"
    return
  fi

  PYTHONDONTWRITEBYTECODE=1 "$system_python" -B - "$CONFIG_FILE" "$ROOT" <<'PY'
import json
import os
from pathlib import Path
import sys

config_path = Path(sys.argv[1]).expanduser()
repo_root = Path(sys.argv[2]).resolve()
vault_value = os.environ.get("CODEX_OBSIDIAN_VAULT", "").strip()
vault = Path(vault_value).expanduser().resolve() if vault_value else None

def unsafe_path(path):
    resolved = path.resolve()
    if resolved == repo_root or repo_root in resolved.parents:
        return True
    if any(
        (ancestor / ".git").exists() or (ancestor / ".obsidian").exists()
        for ancestor in (resolved, *resolved.parents)
    ):
        return True
    return vault is not None and (resolved == vault or vault in resolved.parents)

if not config_path.is_file():
    print("missing")
    raise SystemExit
if unsafe_path(config_path):
    print("unsafe")
    raise SystemExit

try:
    config = json.loads(config_path.read_text())
except (OSError, json.JSONDecodeError):
    print("invalid")
    raise SystemExit
if not isinstance(config, dict):
    print("invalid")
    raise SystemExit

def contains_enabled_config(value):
    if isinstance(value, dict):
        if bool(value.get("enable", False)):
            return True
        return any(contains_enabled_config(child) for child in value.values())
    if isinstance(value, list):
        return any(contains_enabled_config(child) for child in value)
    return False

if contains_enabled_config(config.get("llm-aided-config")):
    print("remote-enabled")
    raise SystemExit

models = config.get("models-dir")
if not isinstance(models, dict):
    print("missing")
    raise SystemExit

for model_type in ("pipeline", "vlm"):
    raw_path = models.get(model_type)
    if not isinstance(raw_path, str) or not raw_path.strip():
        print(f"{model_type}-missing")
        raise SystemExit
    model_path = Path(raw_path).expanduser()
    try:
        resolved = model_path.resolve()
    except OSError:
        print(f"{model_type}-missing")
        raise SystemExit
    if unsafe_path(resolved):
        print("unsafe")
        raise SystemExit
    try:
        populated = resolved.is_dir() and next(resolved.iterdir(), None) is not None
    except OSError:
        populated = False
    if not populated:
        print(f"{model_type}-missing")
        raise SystemExit

print("ready")
PY
}

disk_available_kb() {
  local path="$MODEL_CACHE_DIR"
  while [ ! -e "$path" ] && [ "$path" != "/" ]; do
    path="$(dirname "$path")"
  done
  df -Pk "$path" 2>/dev/null | awk 'NR == 2 { print $4 }'
}

doctor() {
  local failures=0
  local probe=""
  local installed_version="missing"
  local python_version="missing"
  local python_machine="missing"
  local mps_built="no"
  local mps_available="no"
  local mlx="no"
  local mlx_vlm="no"
  local mlx_gpu="no"
  local vlm_engine="unknown"
  local available_kb=""
  local available_gb=0
  local required_kb=0
  local cache_state=""

  if platform_ready; then
    echo "Platform: ready (macOS arm64)"
  else
    echo "Platform: unsupported (requires macOS arm64)"
    failures=$((failures + 1))
  fi

  if command -v uv >/dev/null 2>&1; then
    echo "uv: ready"
  else
    echo "uv: missing"
    failures=$((failures + 1))
  fi

  if [ -x "$RUNTIME_PYTHON" ]; then
    echo "MinerU runtime: ready"
    if probe="$(runtime_probe 2>/dev/null)"; then
      IFS='|' read -r installed_version python_version python_machine mps_built mps_available mlx mlx_vlm mlx_gpu vlm_engine <<<"$probe"
    else
      echo "Runtime probe: failed"
      failures=$((failures + 1))
    fi
  else
    echo "MinerU runtime: missing"
    failures=$((failures + 1))
  fi

  if [ "$installed_version" = "$MINERU_VERSION" ]; then
    echo "MinerU version: ready ($MINERU_VERSION)"
  elif [ "$installed_version" = "missing" ]; then
    echo "MinerU version: missing (expected $MINERU_VERSION)"
    failures=$((failures + 1))
  else
    echo "MinerU version: mismatch (found $installed_version; expected $MINERU_VERSION)"
    failures=$((failures + 1))
  fi

  if [ "$python_version" = "$REQUIRED_PYTHON" ] && [ "$python_machine" = "arm64" ]; then
    echo "Python compatibility: ready (CPython $REQUIRED_PYTHON, arm64)"
  elif [ "$python_version" = "missing" ]; then
    echo "Python compatibility: missing (requires CPython $REQUIRED_PYTHON, arm64)"
    failures=$((failures + 1))
  else
    echo "Python compatibility: unsupported (found CPython $python_version, $python_machine; requires CPython $REQUIRED_PYTHON, arm64)"
    failures=$((failures + 1))
  fi

  if [[ "$MIN_DISK_GB" =~ ^[0-9]+$ ]]; then
    available_kb="$(disk_available_kb || true)"
    required_kb=$((MIN_DISK_GB * 1024 * 1024))
    if [[ "$available_kb" =~ ^[0-9]+$ ]]; then
      available_gb=$((available_kb / 1024 / 1024))
      if [ "$available_kb" -ge "$required_kb" ]; then
        echo "Disk capacity: ready (${available_gb} GiB available; ${MIN_DISK_GB} GiB required)"
      else
        echo "Disk capacity: insufficient (${available_gb} GiB available; ${MIN_DISK_GB} GiB required)"
        failures=$((failures + 1))
      fi
    else
      echo "Disk capacity: unknown (${MIN_DISK_GB} GiB required)"
      failures=$((failures + 1))
    fi
  else
    echo "Disk capacity: invalid requirement"
    failures=$((failures + 1))
  fi

  if [ "$mps_built" = "yes" ] && [ "$mps_available" = "yes" ]; then
    echo "MPS: ready (built and available)"
  elif [ "$mps_built" = "yes" ]; then
    echo "MPS: unavailable (built but not available)"
    failures=$((failures + 1))
  else
    echo "MPS: unavailable (not built)"
    failures=$((failures + 1))
  fi

  if [ "$mlx" = "yes" ] && [ "$mlx_vlm" = "yes" ] && [ "$mlx_gpu" = "yes" ] && [ "$vlm_engine" = "mlx-engine" ]; then
    echo "MLX: ready (GPU device and mlx-engine selected)"
  else
    echo "MLX: unavailable (GPU device or mlx-engine not ready)"
    failures=$((failures + 1))
  fi

  cache_state="$(model_cache_state 2>/dev/null || true)"
  case "$cache_state" in
    ready)
      echo "Model cache: ready (pipeline and vlm)"
      ;;
    unsafe|inside-git)
      echo "Model cache: unsafe (configured inside a Git checkout or Obsidian vault)"
      failures=$((failures + 1))
      ;;
    remote-enabled)
      echo "Model cache: unsafe (llm-aided remote features enabled)"
      failures=$((failures + 1))
      ;;
    invalid)
      echo "Model cache: invalid configuration"
      failures=$((failures + 1))
      ;;
    *)
      echo "Model cache: not ready (pipeline and vlm required)"
      failures=$((failures + 1))
      ;;
  esac

  if [ "$failures" -eq 0 ]; then
    echo "Overall: ready"
    return 0
  fi

  echo "Overall: not ready"
  return 1
}

install_runtime() {
  local probe installed_version python_version python_machine ignored
  local repair_existing=0

  if ! platform_ready; then
    echo "Installation requires native macOS arm64." >&2
    return 1
  fi
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required. Install uv, then rerun with --install." >&2
    return 1
  fi

  if probe="$(runtime_probe 2>/dev/null)"; then
    IFS='|' read -r installed_version python_version python_machine ignored <<<"$probe"
    if [ "$installed_version" = "$MINERU_VERSION" ] && [ "$python_version" = "$REQUIRED_PYTHON" ] && [ "$python_machine" = "arm64" ]; then
      echo "MinerU $MINERU_VERSION is already installed in the managed uv tool environment."
      return 0
    fi
    repair_existing=1
  fi

  echo "Installing mineru[all]==$MINERU_VERSION with managed CPython $REQUIRED_PYTHON..."
  if [ "$repair_existing" -eq 1 ]; then
    UV_TOOL_DIR="$UV_TOOL_DIR" uv tool install --force --python "$REQUIRED_PYTHON" "mineru[all]==$MINERU_VERSION"
  else
    UV_TOOL_DIR="$UV_TOOL_DIR" uv tool install --python "$REQUIRED_PYTHON" "mineru[all]==$MINERU_VERSION"
  fi

  if ! probe="$(runtime_probe 2>/dev/null)"; then
    echo "MinerU runtime probe failed after installation." >&2
    return 1
  fi
  IFS='|' read -r installed_version python_version python_machine ignored <<<"$probe"
  if [ "$installed_version" != "$MINERU_VERSION" ] || [ "$python_version" != "$REQUIRED_PYTHON" ] || [ "$python_machine" != "arm64" ]; then
    echo "Installed runtime does not match MinerU $MINERU_VERSION on CPython $REQUIRED_PYTHON arm64." >&2
    return 1
  fi

  echo "MinerU runtime installed. Model downloads remain opt-in via --download-models."
}

download_models() {
  local probe installed_version python_version python_machine ignored
  if ! platform_ready; then
    echo "Model download requires native macOS arm64." >&2
    return 1
  fi
  if ! probe="$(runtime_probe 2>/dev/null)"; then
    echo "MinerU runtime is missing or unreadable. Run --install first." >&2
    return 1
  fi
  IFS='|' read -r installed_version python_version python_machine ignored <<<"$probe"
  if [ "$installed_version" != "$MINERU_VERSION" ] || [ "$python_version" != "$REQUIRED_PYTHON" ] || [ "$python_machine" != "arm64" ]; then
    echo "MinerU $MINERU_VERSION on CPython $REQUIRED_PYTHON arm64 is required. Run --install first." >&2
    return 1
  fi
  if [ ! -x "$RUNTIME_DOWNLOADER" ]; then
    echo "MinerU model downloader is missing. Run --install first." >&2
    return 1
  fi
  if path_is_private_destination "$MODEL_CACHE_DIR" || path_is_private_destination "$CONFIG_FILE"; then
    echo "MinerU model cache and config must be outside every Git checkout and Obsidian vault." >&2
    return 1
  fi

  mkdir -p "$MODEL_CACHE_DIR" "$(dirname "$CONFIG_FILE")"
  chmod 700 "$MODEL_CACHE_DIR"
  if [ -f "$CONFIG_FILE" ]; then
    chmod 600 "$CONFIG_FILE"
  fi
  echo "Downloading pipeline and VLM models to the external model cache..."
  HF_HOME="$MODEL_CACHE_DIR/huggingface" \
    MODELSCOPE_CACHE="$MODEL_CACHE_DIR/modelscope" \
  MINERU_TOOLS_CONFIG_JSON="$CONFIG_FILE" \
    "$RUNTIME_DOWNLOADER" --source auto --model_type all
  if [ -f "$CONFIG_FILE" ]; then
    chmod 600 "$CONFIG_FILE"
  fi
  if [ "$(model_cache_state 2>/dev/null || true)" != "ready" ]; then
    echo "MinerU downloader did not produce a ready pipeline and VLM model cache." >&2
    return 1
  fi
  echo "MinerU model download finished."
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi

case "$1" in
  --check)
    doctor
    ;;
  --install)
    install_runtime
    ;;
  --download-models)
    download_models
    ;;
  *)
    usage
    exit 2
    ;;
esac
