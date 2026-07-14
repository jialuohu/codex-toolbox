#!/usr/bin/env python3
"""Run MinerU on one local document and emit a stable extraction manifest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Sequence


MANIFEST_NAME = "mineru-run.json"
MINERU_VERSION = "3.4.4"
STDOUT_LOG = "mineru-stdout.log"
STDERR_LOG = "mineru-stderr.log"
SUPPORTED_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff",
    ".bmp", ".gif", ".docx", ".pptx", ".xlsx",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
CONTENT_LIST_V2_TYPES = {
    "algorithm",
    "chart",
    "code",
    "equation_interline",
    "image",
    "index",
    "list",
    "page_aside_text",
    "page_footer",
    "page_footnote",
    "page_header",
    "page_number",
    "paragraph",
    "table",
    "title",
}
CONTENT_LIST_V2_REQUIRED_KEYS = {
    "algorithm": "algorithm_content",
    "chart": "image_source",
    "code": "code_content",
    "equation_interline": "math_content",
    "image": "image_source",
    "index": "list_items",
    "list": "list_items",
    "page_aside_text": "page_aside_text_content",
    "page_footer": "page_footer_content",
    "page_footnote": "page_footnote_content",
    "page_header": "page_header_content",
    "page_number": "page_number_content",
    "paragraph": "paragraph_content",
    "table": "html",
    "title": "title_content",
}
CONTENT_LIST_V2_REQUIRED_VALUE_TYPES = {
    "algorithm": list,
    "chart": dict,
    "code": list,
    "equation_interline": str,
    "image": dict,
    "index": list,
    "list": list,
    "page_aside_text": list,
    "page_footer": list,
    "page_footnote": list,
    "page_header": list,
    "page_number": list,
    "paragraph": list,
    "table": str,
    "title": list,
}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract one local document with MinerU and write mineru-run.json.",
        allow_abbrev=False,
    )
    parser.add_argument("--input", required=True, help="One supported local input file.")
    parser.add_argument("--output", required=True, help="Explicit output directory.")
    parser.add_argument("--backend", choices=("hybrid-engine", "pipeline"), default="hybrid-engine")
    parser.add_argument("--effort", choices=("high", "medium"), default="high")
    parser.add_argument("--method", choices=("auto", "txt", "ocr"), default="auto")
    parser.add_argument("--start", type=int, help="Zero-based first page.")
    parser.add_argument("--end", type=int, help="Zero-based last page.")
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def empty_artifacts() -> Dict[str, List[str]]:
    return {"markdown": [], "content_list_v2": [], "layout_pdf": [], "images": [], "logs": []}


def relative_files(output: Path) -> List[Path]:
    return sorted(
        (path for path in output.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(output).as_posix(),
    )


def discover_artifacts(output: Path) -> Dict[str, List[str]]:
    artifacts = empty_artifacts()
    for path in relative_files(output):
        relative_path = path.relative_to(output)
        relative = relative_path.as_posix()
        lower_name = path.name.lower()
        lower_parts = {part.lower() for part in relative_path.parts}
        if path.suffix.lower() == ".md":
            artifacts["markdown"].append(relative)
        if "content_list_v2" in lower_name and path.suffix.lower() == ".json":
            artifacts["content_list_v2"].append(relative)
        if path.suffix.lower() == ".pdf" and "layout" in path.stem.lower():
            artifacts["layout_pdf"].append(relative)
        if "images" in lower_parts and path.suffix.lower() in IMAGE_SUFFIXES:
            artifacts["images"].append(relative)
        if path.suffix.lower() == ".log":
            artifacts["logs"].append(relative)
    return artifacts


def artifact_tree_error(output: Path) -> Optional[str]:
    root = output.resolve()
    for path in output.rglob("*"):
        if path.is_symlink():
            return f"Artifact must not be a symbolic link: {path.relative_to(output)}"
        try:
            resolved = path.resolve()
        except OSError:
            return f"Artifact path could not be resolved: {path.relative_to(output)}"
        if not is_within(resolved, root):
            return f"Artifact escaped the output directory: {path.relative_to(output)}"
    return None


def write_manifest(output: Path, manifest: Dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    destination = output / MANIFEST_NAME
    temporary = output / f".{MANIFEST_NAME}.tmp"
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def finish_timing(manifest: Dict[str, Any]) -> None:
    finished = datetime.now(timezone.utc)
    started_text = manifest["timing"]["started_at"]
    started = datetime.fromisoformat(started_text.replace("Z", "+00:00"))
    manifest["timing"]["finished_at"] = finished.isoformat().replace("+00:00", "Z")
    manifest["timing"]["duration_seconds"] = round(
        max(0.0, (finished - started).total_seconds()), 3
    )


def probe_mineru_version(runtime: str) -> Optional[str]:
    try:
        result = subprocess.run(
            [runtime, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    match = re.search(
        r"\b(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\b",
        result.stdout + result.stderr,
    )
    return match.group(1) if match else None


def observed_device_engine(log_paths: Sequence[Path]) -> Optional[str]:
    engines = set()
    for path in log_paths:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as log:
                for line in log:
                    lowered = line.lower()
                    if "mlx-engine" in lowered or "mlx engine" in lowered:
                        engines.add("mlx-engine")
                    for engine in ("mps", "cuda", "cpu"):
                        if re.search(rf"\b{engine}\b", lowered):
                            engines.add(engine)
        except OSError:
            continue
    if "mlx-engine" in engines:
        return "mlx-engine"
    for engine in ("mps", "cuda", "cpu"):
        if engine in engines:
            return engine
    return None


def resolve_mineru_runtime() -> Optional[str]:
    override = os.environ.get("MINERU_EXECUTABLE", "").strip()
    if override:
        candidate = Path(override).expanduser().resolve()
    else:
        data_home = Path(
            os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        )
        tool_root_value = os.environ.get("MINERU_UV_TOOL_DIR")
        if not tool_root_value:
            tool_root_value = os.environ.get("UV_TOOL_DIR", str(data_home / "uv" / "tools"))
        tool_root = Path(tool_root_value).expanduser()
        candidate = (tool_root / "mineru" / "bin" / "mineru").resolve()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def protected_location_error(path: Path) -> Optional[str]:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return "location is inside a Git checkout"
        if (candidate / ".obsidian").exists():
            return "location is inside an Obsidian vault"

    vault_value = os.environ.get("CODEX_OBSIDIAN_VAULT", "").strip()
    if vault_value:
        vault = Path(vault_value).expanduser().resolve()
        if is_within(path, vault):
            return "location is inside the configured Obsidian vault"
    return None


def output_target_error(output: Path) -> Optional[str]:
    protected_error = protected_location_error(output)
    if protected_error:
        if "Git checkout" in protected_error:
            return "Output must be outside every Git checkout."
        return "Output must be outside every Obsidian vault."

    if output.exists() and not output.is_dir():
        return "Output must be a directory path, not an existing file."
    if output.is_dir():
        try:
            if any(output.iterdir()):
                return "Output directory must be empty; use a fresh directory for each attempt."
        except OSError as error:
            return f"Output directory could not be inspected: {error}."
    return None


def contains_enabled_config(value: Any) -> bool:
    if isinstance(value, dict):
        if bool(value.get("enable", False)):
            return True
        return any(contains_enabled_config(child) for child in value.values())
    if isinstance(value, list):
        return any(contains_enabled_config(child) for child in value)
    return False


def model_configuration_error() -> Optional[tuple[str, str]]:
    config_value = os.environ.get("MINERU_TOOLS_CONFIG_JSON", "mineru.json")
    config_path = Path(config_value).expanduser()
    if not config_path.is_absolute():
        config_path = Path.home() / config_path
    config_path = config_path.resolve()

    protected_error = protected_location_error(config_path)
    if protected_error:
        return "model_config_unsafe", f"MinerU config {protected_error}."
    if not config_path.is_file():
        return (
            "model_config_not_ready",
            "MinerU local model config is missing; run the setup doctor.",
        )
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "model_config_not_ready", "MinerU local model config is not valid UTF-8 JSON."
    if not isinstance(config, dict):
        return "model_config_not_ready", "MinerU local model config must contain a JSON object."

    if contains_enabled_config(config.get("llm-aided-config")):
        return (
            "model_config_remote_features",
            "MinerU llm-aided-config must be disabled for local-only extraction.",
        )

    models = config.get("models-dir")
    if not isinstance(models, dict):
        return "model_config_not_ready", "MinerU local model config is missing models-dir."
    for model_type in ("pipeline", "vlm"):
        raw_path = models.get(model_type)
        if not isinstance(raw_path, str) or not raw_path.strip():
            return (
                "model_config_not_ready",
                f"MinerU local model config is missing {model_type}.",
            )
        model_path = Path(raw_path).expanduser().resolve()
        protected_error = protected_location_error(model_path)
        if protected_error:
            return "model_config_unsafe", f"MinerU {model_type} model {protected_error}."
        try:
            populated = model_path.is_dir() and next(model_path.iterdir(), None) is not None
        except OSError:
            populated = False
        if not populated:
            return (
                "model_config_not_ready",
                f"MinerU {model_type} model directory is not ready.",
            )

    for variable in (
        "HF_HOME",
        "MODELSCOPE_CACHE",
        "XDG_CACHE_HOME",
        "MINERU_MODEL_CACHE_DIR",
        "TORCH_HOME",
        "PADDLE_HOME",
        "HF_HUB_CACHE",
        "HF_ASSETS_CACHE",
        "HUGGINGFACE_HUB_CACHE",
        "HUGGINGFACE_ASSETS_CACHE",
        "TRANSFORMERS_CACHE",
        "PYTORCH_PRETRAINED_BERT_CACHE",
        "PYTORCH_TRANSFORMERS_CACHE",
        "HF_MODULES_CACHE",
        "FTLANG_CACHE",
    ):
        value = os.environ.get(variable, "").strip()
        if value:
            protected_error = protected_location_error(Path(value).expanduser().resolve())
            if protected_error:
                return "model_config_unsafe", f"{variable} {protected_error}."
    return None


def base_manifest(args: argparse.Namespace, output: Path) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "failure",
        "source": {
            "path": args.input,
            "name": Path(args.input).name,
            "size_bytes": None,
            "sha256": None,
            "sha256_after": None,
            "verified_unchanged": None,
            "staged_copy_used": False,
            "staged_copy_verified_unchanged": None,
        },
        "output_directory": str(output),
        "request": {
            "backend": args.backend,
            "effort": args.effort,
            "method": args.method,
            "pages": {"start": args.start, "end": args.end},
            "concurrency": 1,
            "local_only": True,
        },
        "mineru": {
            "version": None,
            "observed_device_engine": None,
        },
        "process": {"exit_code": None},
        "timing": {
            "started_at": utc_now(),
            "finished_at": None,
            "duration_seconds": None,
        },
        "artifacts": empty_artifacts(),
        "error": None,
    }


def fail(
    output: Path,
    manifest: Dict[str, Any],
    code: str,
    message: str,
    exit_code: int = 2,
) -> int:
    manifest["status"] = "failure"
    manifest["error"] = {"code": code, "message": message}
    manifest["artifacts"] = discover_artifacts(output)
    finish_timing(manifest)
    write_manifest(output, manifest)
    print(message, file=sys.stderr)
    return exit_code


def validate_content_lists(
    output: Path, paths: Sequence[str], expected_pages: Optional[int]
) -> Optional[str]:
    for relative in paths:
        try:
            content = json.loads((output / relative).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return f"Content list is not valid UTF-8 JSON: {relative}"
        if not isinstance(content, list) or not content:
            return f"Content list must use a non-empty page-grouped nested list: {relative}"
        if not all(isinstance(page, list) for page in content):
            return f"Content list must use a page-grouped nested list: {relative}"
        if expected_pages is not None and len(content) != expected_pages:
            return (
                f"Content list page coverage is {len(content)}; "
                f"expected {expected_pages}: {relative}"
            )
        block_count = 0
        for page in content:
            for block in page:
                block_count += 1
                if not isinstance(block, dict):
                    return f"Content list contains an invalid structured block: {relative}"
                block_type = block.get("type")
                block_content = block.get("content")
                if block_type not in CONTENT_LIST_V2_TYPES:
                    return f"Content list contains an unknown block type: {relative}"
                if not isinstance(block_content, dict) or not block_content:
                    return f"Content list contains an empty block content object: {relative}"
                required_key = CONTENT_LIST_V2_REQUIRED_KEYS[block_type]
                if required_key not in block_content:
                    return (
                        f"Content list block {block_type} is missing {required_key}: "
                        f"{relative}"
                    )
                required_type = CONTENT_LIST_V2_REQUIRED_VALUE_TYPES[block_type]
                if not isinstance(block_content[required_key], required_type):
                    return (
                        f"Content list block {block_type}.{required_key} must be a "
                        f"{required_type.__name__}: {relative}"
                    )
                if "bbox" in block:
                    bbox = block["bbox"]
                    if not (
                        isinstance(bbox, list)
                        and len(bbox) == 4
                        and all(isinstance(value, (int, float)) for value in bbox)
                    ):
                        return f"Content list contains an invalid bbox: {relative}"
        if block_count == 0:
            return f"Content list contains no structured blocks: {relative}"
    return None


def validate_markdown(output: Path, paths: Sequence[str]) -> Optional[str]:
    for relative in paths:
        try:
            markdown = (output / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return f"Markdown is not readable UTF-8: {relative}"
        if not markdown.strip():
            return f"Markdown is empty: {relative}"
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    os.umask(0o077)
    args = parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    target_error = output_target_error(output)
    if target_error:
        print(target_error, file=sys.stderr)
        return 2
    manifest = base_manifest(args, output)

    if "://" in args.input:
        return fail(output, manifest, "input_url", "URLs are not supported; provide one local file.")

    source = Path(args.input).expanduser()
    if not source.is_file():
        return fail(output, manifest, "input_not_file", "Input must be one existing local file.")

    source = source.resolve()
    manifest["source"]["path"] = str(source)
    manifest["source"]["name"] = source.name

    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        return fail(
            output,
            manifest,
            "input_unsupported",
            f"Unsupported input type {source.suffix or '<none>'}; supported extensions: {supported}.",
        )
    if (args.start is None) != (args.end is None):
        return fail(
            output,
            manifest,
            "invalid_pages",
            "--start and --end must be supplied together for auditable page coverage.",
        )
    if source.suffix.lower() != ".pdf" and args.start is not None:
        return fail(
            output,
            manifest,
            "invalid_pages",
            "Page ranges are supported only for PDF inputs.",
        )
    if output == source:
        return fail(output.parent, manifest, "output_overwrites_source", "Output must not be the source file.")
    if args.start is not None and args.start < 0:
        return fail(output, manifest, "invalid_pages", "--start must be zero or greater.")
    if args.end is not None and args.end < 0:
        return fail(output, manifest, "invalid_pages", "--end must be zero or greater.")
    if args.start is not None and args.end is not None and args.end < args.start:
        return fail(output, manifest, "invalid_pages", "--end must be greater than or equal to --start.")

    try:
        source_hash = sha256_file(source)
        source_size = source.stat().st_size
    except OSError as error:
        return fail(output, manifest, "input_unreadable", f"Could not read input: {error}.")

    manifest["source"].update(
        {
            "size_bytes": source_size,
            "sha256": source_hash,
            "sha256_after": source_hash,
            "verified_unchanged": True,
        }
    )
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)

    runtime = resolve_mineru_runtime()
    if runtime is None:
        return fail(
            output,
            manifest,
            "runtime_missing",
            "The managed MinerU runtime was not found; run the setup doctor.",
            exit_code=127,
        )
    manifest["mineru"]["version"] = probe_mineru_version(runtime)
    if manifest["mineru"]["version"] is None:
        return fail(
            output,
            manifest,
            "runtime_version_unavailable",
            "MinerU was found, but its version could not be determined.",
            exit_code=127,
        )
    if manifest["mineru"]["version"] != MINERU_VERSION:
        return fail(
            output,
            manifest,
            "runtime_version_mismatch",
            f"MinerU {MINERU_VERSION} is required; found {manifest['mineru']['version']}.",
            exit_code=127,
        )
    model_error = model_configuration_error()
    if model_error:
        error_code, error_message = model_error
        return fail(output, manifest, error_code, error_message)

    environment = os.environ.copy()
    environment["MINERU_API_MAX_CONCURRENT_REQUESTS"] = "1"
    environment["MINERU_PDF_RENDER_THREADS"] = "1"
    environment["MINERU_MODEL_SOURCE"] = "local"
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    for proxy_variable in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        environment.pop(proxy_variable, None)
    environment["NO_PROXY"] = "127.0.0.1,localhost,::1"
    environment["no_proxy"] = "127.0.0.1,localhost,::1"

    stdout_path = output / STDOUT_LOG
    stderr_path = output / STDERR_LOG
    staged_hash_after = None
    result = None
    staging_failure = None
    runtime_failure = None
    try:
        with tempfile.TemporaryDirectory(prefix=".mineru-source-", dir=output) as staging_dir:
            staged_source = Path(staging_dir) / source.name
            runtime_temp = Path(staging_dir) / "runtime-tmp"
            try:
                runtime_temp.mkdir(mode=0o700)
                shutil.copyfile(source, staged_source)
                staged_source.chmod(0o400)
                if sha256_file(staged_source) != source_hash:
                    staging_failure = "The private staged input did not match the source checksum."
            except OSError as error:
                staging_failure = f"Could not create the private staged input: {error}."

            if staging_failure is None:
                manifest["source"]["staged_copy_used"] = True
                for temp_variable in ("TMPDIR", "TEMP", "TMP"):
                    environment[temp_variable] = str(runtime_temp)
                command = [
                    runtime,
                    "--path", str(staged_source),
                    "--output", str(output),
                    "--backend", args.backend,
                    "--effort", args.effort,
                    "--method", args.method,
                ]
                if args.start is not None:
                    command.extend(("--start", str(args.start)))
                if args.end is not None:
                    command.extend(("--end", str(args.end)))

                try:
                    with stdout_path.open("wb") as stdout_log, stderr_path.open("wb") as stderr_log:
                        result = subprocess.run(
                            command,
                            stdout=stdout_log,
                            stderr=stderr_log,
                            env=environment,
                            check=False,
                        )
                except OSError as error:
                    runtime_failure = f"Could not run MinerU: {error}."
                try:
                    staged_hash_after = sha256_file(staged_source)
                except OSError:
                    staged_hash_after = None
    except OSError as error:
        staging_failure = f"Could not manage the private staged input: {error}."

    manifest["process"]["exit_code"] = result.returncode if result is not None else None
    manifest["mineru"]["observed_device_engine"] = observed_device_engine(
        (stdout_path, stderr_path)
    )
    manifest["source"]["staged_copy_verified_unchanged"] = staged_hash_after == source_hash

    try:
        source_hash_after = sha256_file(source)
    except OSError:
        source_hash_after = None
    manifest["source"]["sha256_after"] = source_hash_after
    manifest["source"]["verified_unchanged"] = source_hash_after == source_hash

    if source_hash_after != source_hash:
        return fail(
            output,
            manifest,
            "source_mutated",
            "The source checksum changed during extraction; outputs are untrusted.",
        )
    if staging_failure is not None:
        return fail(output, manifest, "staging_failed", staging_failure)
    if manifest["source"]["staged_copy_used"] and staged_hash_after != source_hash:
        return fail(
            output,
            manifest,
            "staged_input_mutated",
            "MinerU changed the private staged input; outputs are untrusted.",
        )
    if runtime_failure is not None:
        return fail(output, manifest, "runtime_error", runtime_failure)
    if result is None:
        return fail(output, manifest, "runtime_error", "MinerU did not return a process result.")
    if result.returncode != 0:
        return fail(
            output,
            manifest,
            "parse_failed",
            f"MinerU exited with code {result.returncode}.",
            exit_code=result.returncode if result.returncode > 0 else 1,
        )

    tree_error = artifact_tree_error(output)
    if tree_error:
        return fail(output, manifest, "unsafe_artifact", tree_error)
    manifest["artifacts"] = discover_artifacts(output)

    artifacts = manifest["artifacts"]
    missing = []
    if not artifacts["markdown"]:
        missing.append("Markdown")
    if not artifacts["content_list_v2"]:
        missing.append("content_list_v2 JSON")
    if missing:
        return fail(
            output,
            manifest,
            "malformed_output",
            "MinerU completed without required artifacts: " + ", ".join(missing) + ".",
        )
    markdown_error = validate_markdown(output, artifacts["markdown"])
    if markdown_error:
        return fail(output, manifest, "malformed_output", markdown_error)
    expected_pages = None
    if args.start is not None and args.end is not None:
        expected_pages = args.end - args.start + 1
    content_error = validate_content_lists(
        output, artifacts["content_list_v2"], expected_pages
    )
    if content_error:
        return fail(output, manifest, "malformed_output", content_error)

    manifest["status"] = "success"
    manifest["error"] = None
    finish_timing(manifest)
    write_manifest(output, manifest)
    print(output / MANIFEST_NAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
