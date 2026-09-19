#!/usr/bin/env python3
"""Explicit, pinned TypeSafe installation; status performs no network requests."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = "typesafe-tools"
MARKETPLACE = "typesafe-tools-local"
REVISION = "65a39f393687675ce170e6094757de20370365b9"
UPSTREAM = f"https://github.com/typesafe-ai/skills/tree/{REVISION}/skills/typesafe-ai"
CHECKSUMS = {
    "SKILL.md": "71ea90d7906c6554c4f4c460ef7361b2d26f59116ccdae986dc6d997b9389f52",
    "LICENSE": "835f233f1d6ed84a9b9a351aba0689b47644a4137d6316911fc7957bde523b02",
}
IGNORED = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".git", "dist", "build", ".DS_Store"}


class SetupError(RuntimeError):
    pass


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def run(command: list[str], *, timeout: int = 180) -> str:
    env = dict(os.environ, DO_NOT_TRACK="1", DISABLE_TELEMETRY="1")
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True,
                                timeout=timeout, env=env)
    except (subprocess.SubprocessError, OSError) as error:
        # Installer/CLI output may contain private local paths or configuration.
        raise SetupError(f"{command[0]} failed; inspect the command locally") from error
    return result.stdout


def cli_json(command: list[str]) -> dict:
    try:
        value = json.loads(run(command))
    except (ValueError, TypeError) as error:
        raise SetupError("Codex returned invalid JSON") from error
    if not isinstance(value, dict):
        raise SetupError("Codex returned an unexpected response")
    return value


def candidates(home: Path, codex: Path, project: Path) -> list[Path]:
    roots = [home / ".agents/skills", codex / "skills"]
    for parent in [project, *project.parents]:
        roots.extend([parent / ".agents/skills", parent / ".codex/skills"])
    # Active plugin skill copies can shadow the global installation too.
    cache = codex / "plugins/cache"
    if cache.is_dir():
        roots.extend(p.parent for p in cache.glob("*/*/*/skills/typesafe-ai"))
    found: dict[Path, Path] = {}
    for root in roots:
        path = root / "typesafe-ai"
        if path.exists() or path.is_symlink():
            found.setdefault(path.resolve(), path)
    return list(found.values())


def upstream_status(home: Path, codex: Path, project: Path) -> dict:
    copies = candidates(home, codex, project)
    if not copies:
        return {"state": "absent", "revision": REVISION}
    if len(copies) != 1:
        return {"state": "conflict", "copies": len(copies), "revision": REVISION}
    path = copies[0]
    try:
        actual = {name: hashlib.sha256((path / name).read_bytes()).hexdigest()
                  for name in CHECKSUMS}
        # This revision contains exactly two files. Reject injected companions.
        actual_files = {str(p.relative_to(path)) for p in path.rglob("*") if p.is_file()}
    except OSError:
        return {"state": "conflict", "reason": "unreadable upstream skill"}
    global_paths = {(home / ".agents/skills/typesafe-ai").resolve(),
                    (codex / "skills/typesafe-ai").resolve()}
    verified = actual == CHECKSUMS and actual_files == set(CHECKSUMS)
    return {"state": "verified" if verified and path.resolve() in global_paths else "conflict",
            "revision": REVISION, "global_discovery": path.resolve() in global_paths}


def install_upstream(home: Path, codex: Path, project: Path) -> dict:
    before = upstream_status(home, codex, project)
    if before["state"] == "conflict":
        raise SetupError("Conflicting TypeSafe skill installation; no files changed")
    if before["state"] == "verified":
        return {**before, "action": "unchanged"}
    run(["npx", "--yes", "skills@1.7.0", "add", UPSTREAM,
         "--skill", "typesafe-ai", "--agent", "codex", "--global", "--yes"], timeout=300)
    after = upstream_status(home, codex, project)
    if after["state"] != "verified":
        raise SetupError("Installer completed but pinned upstream verification failed; inspect installation")
    return {**after, "action": "installed"}


def source_files(source: Path) -> list[Path]:
    files = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in IGNORED for part in relative.parts):
            continue
        if path.is_symlink():
            raise SetupError("Plugin source contains a symlink; refusing export")
        if not path.is_file():
            continue
        if path.name.startswith(".env") or path.suffix in {".pyc", ".sqlite", ".sqlite3", ".db", ".log"}:
            continue
        files.append(path)
    required = {".codex-plugin/plugin.json", ".mcp.json", "server/pyproject.toml", "server/uv.lock"}
    if not required.issubset({p.relative_to(source).as_posix() for p in files}):
        raise SetupError("Plugin source is incomplete")
    return files


def source_digest(source: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(source).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def safe_path(root: Path, path: Path) -> None:
    """Reject links inside the explicitly selected root, including the root itself."""
    if not root.is_absolute() or not path.is_absolute():
        raise SetupError("Installation paths must be absolute")
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise SetupError("Installation path escapes its root") from error
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            if part == "..":
                raise SetupError("Installation path escapes its root")
            current = current / part
        if current.is_symlink():
            raise SetupError("Installation path contains a symlink; refusing mutation")


def expected_export(source: Path, files: list[Path], digest: str) -> dict[str, bytes]:
    expected = {p.relative_to(source).as_posix(): p.read_bytes() for p in files}
    measured = hashlib.sha256()
    for name, content in expected.items():
        measured.update(name.encode() + b"\0" + content + b"\0")
    if measured.hexdigest() != digest:
        raise SetupError("Plugin source changed during export; retry after edits finish")
    manifest = json.loads(expected[".codex-plugin/plugin.json"])
    manifest["version"] = manifest["version"].split("+", 1)[0] + "+codex." + digest[:12]
    expected[".codex-plugin/plugin.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    return expected


def verify_export(root: Path, expected: dict[str, bytes]) -> None:
    safe_path(root, root)
    if not root.is_dir():
        raise SetupError("Export or installed cache is missing")
    actual = source_files(root)
    names = {p.relative_to(root).as_posix() for p in actual}
    if names != set(expected) or any((root / name).read_bytes() != data for name, data in expected.items()):
        raise SetupError("Export or installed cache content mismatch; refusing overwrite")


def atomic_text(path: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".typesafe-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def export_plugin(source: Path, destination: Path, files: list[Path], digest: str) -> None:
    """Publish immutable source-addressed trees; replace only the catalog pointer."""
    safe_path(destination, destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "exports" / digest
    safe_path(destination, target)
    target.parent.mkdir(exist_ok=True)
    expected = expected_export(source, files, digest)
    if target.exists():
        verify_export(target, expected)
    else:
        staging = Path(tempfile.mkdtemp(prefix=".typesafe-", dir=target.parent))
        try:
            for name, content in expected.items():
                output = staging / name
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(content)
            verify_export(staging, expected)
            # A concurrent same-digest export is verified, never deleted or replaced.
            if target.exists():
                verify_export(target, expected)
            else:
                try:
                    staging.rename(target)
                except OSError:
                    if not target.exists():
                        raise
                    verify_export(target, expected)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    entry = {"name": PLUGIN, "source": {"source": "local", "path": f"./exports/{digest}"},
             "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
             "category": "Productivity"}
    catalog = destination / ".agents/plugins/marketplace.json"
    safe_path(destination, catalog)
    catalog.parent.mkdir(parents=True, exist_ok=True)
    atomic_text(catalog, json.dumps({"name": MARKETPLACE, "interface": {"displayName": "TypeSafe local pilot"},
                                   "plugins": [entry]}, indent=2) + "\n")
    marker = destination / "source-sha256"
    safe_path(destination, marker)
    atomic_text(marker, digest + "\n")


def verify_installed(codex: Path, entry: dict, target: Path, expected: dict[str, bytes]) -> None:
    version = json.loads(expected[".codex-plugin/plugin.json"])["version"]
    if (not entry.get("installed") or entry.get("version") != version
            or entry.get("marketplaceName") != MARKETPLACE
            or entry.get("source", {}).get("source") != "local"
            or Path(entry.get("source", {}).get("path", "")) != target):
        raise SetupError("Installed version or source differs from the verified export")
    cache = codex / "plugins/cache" / MARKETPLACE / PLUGIN / version
    safe_path(codex, cache)
    verify_export(cache, expected)


def install_plugin(codex: Path, source: Path) -> dict:
    listing = cli_json(["codex", "plugin", "list", "--json"])
    installed = [p for p in listing.get("installed", []) if p.get("name") == PLUGIN]
    if len(installed) > 1 or any(p.get("marketplaceName") != MARKETPLACE for p in installed):
        raise SetupError("TypeSafe is already installed from another marketplace; refusing duplicate")
    marketplaces = cli_json(["codex", "plugin", "marketplace", "list", "--json"])
    destination = codex / "local-marketplaces" / MARKETPLACE
    safe_path(codex, destination)
    matching = [m for m in marketplaces.get("marketplaces", []) if m.get("name") == MARKETPLACE]
    if len(matching) > 1 or any(Path(m.get("root", "")).resolve() != destination.resolve() for m in matching):
        raise SetupError("Local TypeSafe marketplace name is already in use")
    files = source_files(source)
    digest = source_digest(source, files)
    expected = expected_export(source, files, digest)
    target = destination / "exports" / digest
    safe_path(codex, target)
    marker = destination / "source-sha256"
    safe_path(codex, marker)
    same = marker.is_file() and marker.read_text().strip() == digest
    if installed and same:
        catalog = destination / ".agents/plugins/marketplace.json"
        safe_path(codex, catalog)
        try:
            document = json.loads(catalog.read_text())
            entries = document["plugins"]
            if document["name"] != MARKETPLACE or len(entries) != 1 or entries[0]["source"] != {
                "source": "local", "path": f"./exports/{digest}"
            }:
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise SetupError("Local marketplace pointer differs from the verified export") from error
        verify_export(target, expected)
        verify_installed(codex, installed[0], target, expected)
        return {"action": "unchanged", "installed": True, "enabled": installed[0].get("enabled", False)}
    if installed and not installed[0].get("enabled", False):
        return {"action": "update_skipped_disabled", "installed": True, "enabled": False}
    if destination.exists() and not marker.is_file():
        raise SetupError("Unrecognized export directory; refusing overwrite")
    export_plugin(source, destination, files, digest)
    if not matching:
        run(["codex", "plugin", "marketplace", "add", str(destination), "--json"])
    result = cli_json(["codex", "plugin", "add", f"{PLUGIN}@{MARKETPLACE}", "--json"])
    verified = cli_json(["codex", "plugin", "list", "--marketplace", MARKETPLACE, "--json"])
    entries = [p for p in verified.get("installed", []) if p.get("name") == PLUGIN]
    if len(entries) != 1 or not entries[0].get("installed"):
        raise SetupError("Plugin install completed but discovery verification failed")
    verify_installed(codex, entries[0], target, expected)
    del result
    return {"action": "installed", "installed": True, "enabled": entries[0].get("enabled", False)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="Offline filesystem verification; no installation")
    parser.add_argument("--install-upstream", action="store_true", help="Install verified external upstream skill")
    parser.add_argument("--install", action="store_true", help="Install this plugin only through an isolated local marketplace")
    args = parser.parse_args()
    if args.status and (args.install or args.install_upstream):
        parser.error("--status cannot be combined with installation")
    home, codex = Path.home(), codex_home()
    result = {"paid_ready": None, "readiness": "Check typesafe_status for runtime readiness and spending mode"}
    try:
        result["upstream"] = (install_upstream(home, codex, ROOT) if args.install_upstream
                              else upstream_status(home, codex, ROOT))
        if args.install:
            result["plugin"] = install_plugin(codex, ROOT / "plugins" / PLUGIN)
        else:
            result["plugin"] = {"local_export_present": (codex / "local-marketplaces" / MARKETPLACE / "source-sha256").is_file(),
                                "discovery": "not checked in offline status"}
    except SetupError as error:
        print(json.dumps({"error": str(error), "paid_ready": None}))
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"error": "Local installation state is invalid or unavailable; runtime readiness was not checked", "paid_ready": None}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
