#!/usr/bin/env python3
"""Plan or migrate the Visual Communication family through supported Codex CLI operations.

No command edits active Codex configuration directly. Plan/check mode never writes
packages, configuration, journals, or recovery snapshots. Apply first rehearses
both upgrade and recovery with captured packages in an isolated, credential-free
Codex home, then verifies each live step before retiring the old figure plugin.
"""

from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

try:
    import tomllib
except ImportError:  # Python < 3.11 must not guess active configuration.
    tomllib = None


MARKETPLACE = "jialuo-codex-toolbox"
FAMILY = ("diagram-tools", "workflow-tools", "paper-figure-tools")
TARGET = {"diagram-tools": "0.6.0", "workflow-tools": "0.19.0"}
PREDECESSOR = {"diagram-tools": "0.5.3", "workflow-tools": "0.18.2", "paper-figure-tools": "0.3.1"}
MOVED = ("explain-clearly", "paper-figure-workflow")
OLD_OWNERS = {"explain-clearly": ["workflow-tools"], "paper-figure-workflow": ["paper-figure-tools"]}
NEW_OWNERS = {name: ["diagram-tools"] for name in MOVED}
STATE_PARTS = ("state", "visual-communication-migration")
IGNORED = {".git", "__pycache__", "node_modules", ".DS_Store"}
_PARSER_PYTHON = None


class Blocked(RuntimeError):
    """A condition for which no active mutation is safe."""


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Blocked(f"invalid_json:{path.name}") from error


def config_document(home: Path) -> dict:
    path = home / "config.toml"
    if not path.exists():
        return {}
    if tomllib is None:
        # The system Python on macOS may be 3.9. Reuse an already installed
        # standard-library TOML parser; never install a runtime during preflight.
        interpreter = parser_python(home)
        code = "import json,pathlib,sys,tomllib;print(json.dumps(tomllib.loads(pathlib.Path(sys.argv[1]).read_text())))"
        result = subprocess.run([interpreter, "-I", "-c", code, str(path)],
                                env=clean_environment(home, home.parent), text=True,
                                capture_output=True, timeout=10, check=False)
        if result.returncode:
            raise Blocked("configuration_unreadable")
        return checked_configuration(json.loads(result.stdout))
    try:
        return checked_configuration(tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        raise Blocked("configuration_unreadable") from error


def checked_configuration(document: Any) -> dict:
    if not isinstance(document, dict):
        raise Blocked("configuration_shape_unknown")
    plugins, skills = document.get("plugins", {}), document.get("skills", {})
    if (not isinstance(plugins, dict) or not all(isinstance(value, dict) for value in plugins.values())
            or not isinstance(skills, dict) or not isinstance(skills.get("config", []), list)
            or not all(isinstance(entry, dict) for entry in skills.get("config", []))):
        raise Blocked("configuration_shape_unknown")
    return document


def parser_python(home: Path) -> str:
    global _PARSER_PYTHON
    if _PARSER_PYTHON:
        return _PARSER_PYTHON
    choices = [shutil.which(name) for name in ("python3.13", "python3.12", "python3.11")]
    choices.extend(str(base / "runtime/toolbox-health/bin/python") for base in
                   (home, Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))), Path.home() / ".codex"))
    for choice in dict.fromkeys(candidate for candidate in choices if candidate):
        if not Path(choice).is_file():
            continue
        try:
            result = subprocess.run([choice, "-I", "-c", "import sys,tomllib;assert sys.version_info >= (3,11)"],
                                    env=clean_environment(home, home.parent), capture_output=True,
                                    timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            _PARSER_PYTHON = choice
            return choice
    raise Blocked("python_3_11_parser_unavailable_no_runtime_installed")


def checked_child(root: Path, *parts: str) -> Path:
    candidate = root.joinpath(*parts)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise Blocked("path_outside_owned_root")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise Blocked("owned_path_is_symlink")
    return candidate


def package_info(path: Path, name: str) -> dict:
    """Inspect a complete immutable package without following symlinks."""
    if not path.is_dir() or path.is_symlink():
        raise Blocked(f"package_unavailable:{name}")
    manifest = read_json(checked_child(path, ".codex-plugin", "plugin.json"))
    if not isinstance(manifest, dict) or manifest.get("name") != name or not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", ""))):
        raise Blocked(f"package_identity_invalid:{name}")
    if manifest.get("mcpServers"):
        raise Blocked(f"unexpected_family_mcp_surface:{name}")
    files = {}
    skills = []
    items = []
    for directory, directories, filenames in os.walk(path, followlinks=False):
        directories[:] = sorted(child for child in directories if child not in IGNORED)
        for child in directories:
            if (Path(directory) / child).is_symlink():
                raise Blocked(f"package_symlink:{name}")
        items.extend(Path(directory) / filename for filename in sorted(filenames)
                     if filename not in IGNORED and Path(filename).suffix not in {".pyc", ".pyo"})
    for item in sorted(items):
        relative = item.relative_to(path)
        if item.is_symlink():
            raise Blocked(f"package_symlink:{name}")
        if not item.is_file():
            raise Blocked(f"package_special_file:{name}")
        files[relative.as_posix()] = [hashlib.sha256(item.read_bytes()).hexdigest(), item.stat().st_mode & 0o777]
        if len(relative.parts) == 3 and relative.parts[0] == "skills" and item.name == "SKILL.md":
            body = item.read_text(encoding="utf-8")
            frontmatter = body.split("---", 2) if body.startswith("---") else []
            match = re.search(r"(?m)^name:\s*['\"]?([a-z0-9-]+)['\"]?\s*$", frontmatter[1] if len(frontmatter) == 3 else "")
            if not match or match.group(1) != relative.parts[1]:
                raise Blocked(f"skill_identity_invalid:{name}")
            skills.append(match.group(1))
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"version": manifest["version"], "sha256": hashlib.sha256(payload).hexdigest(), "skills": sorted(skills)}


def clean_environment(home: Path, user_home: Path | None = None) -> dict[str, str]:
    # Intentionally do not copy os.environ: no API keys, credentials, provider
    # profiles, CODEX_SESSION_ID, CODEX_SECRETS_DIR, or active-home config enter a probe.
    return {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(user_home or Path.home()),
            "CODEX_HOME": str(home), "LANG": "en_US.UTF-8"}


class CodexCLI:
    def __init__(self, binary: str, home: Path, *, isolated: bool = False):
        self.binary = str(Path(binary).resolve()) if "/" in binary else (shutil.which(binary) or binary)
        self.home = home.resolve()
        self.env = clean_environment(self.home, self.home.parent if isolated else None)

    def run(self, *arguments: str, marketplace: Path | None = None) -> dict:
        options = []
        if marketplace is not None:
            options = ["-c", f'marketplaces.{MARKETPLACE}.source_type="local"',
                       "-c", f"marketplaces.{MARKETPLACE}.source={json.dumps(str(marketplace.resolve()))}"]
        try:
            result = subprocess.run([self.binary, *options, *arguments], env=self.env,
                                    text=True, capture_output=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Blocked("cli_unavailable_or_timed_out") from error
        if result.returncode:
            # Tool output can contain configuration secrets; return only the
            # bounded operation and exit code, never raw stdout/stderr.
            raise Blocked(f"cli_operation_failed:{'-'.join(arguments[:3])}:{result.returncode}")
        try:
            value = json.loads(result.stdout)
        except ValueError as error:
            raise Blocked("cli_json_unavailable") from error
        if not isinstance(value, dict):
            raise Blocked("cli_json_invalid")
        return value

    def installed(self) -> list[dict]:
        data = self.run("plugin", "list", "--json")
        if not isinstance(data.get("installed"), list):
            raise Blocked("plugin_inventory_unavailable")
        return data["installed"]

    def add(self, name: str, source: Path) -> None:
        self.run("plugin", "add", f"{name}@{MARKETPLACE}", "--json", marketplace=source)

    def remove(self, name: str) -> None:
        self.run("plugin", "remove", f"{name}@{MARKETPLACE}", "--json")


def stable_row(row: dict) -> dict:
    fields = ("pluginId", "name", "marketplaceName", "version", "installed", "enabled")
    result = {field: row.get(field) for field in fields}
    # Source URLs/paths can contain private data. Preserve their exact semantics
    # without copying them into the transaction receipt.
    result["source_identity_sha256"] = hashlib.sha256(json.dumps(
        row.get("source"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


def family_row(row: dict) -> bool:
    return (row.get("name") in FAMILY and row.get("marketplaceName") == MARKETPLACE
            and row.get("pluginId") == f'{row["name"]}@{MARKETPLACE}')


def preserved_configuration_hash(document: dict) -> str:
    """Hash all non-family semantics, including marketplace registration, without saving secrets."""
    preserved = dict(document)
    configured = document.get("plugins", {})
    if not isinstance(configured, dict):
        raise Blocked("plugin_configuration_unknown")
    unrelated = {key: value for key, value in configured.items()
                 if key not in {f'{name}@{MARKETPLACE}' for name in FAMILY}}
    preserved.pop("plugins", None)
    if unrelated:
        preserved["plugins"] = unrelated
    return hashlib.sha256(json.dumps(preserved, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def unrelated_observation(cli: CodexCLI) -> dict:
    """Recovery can observe unrelated installs even if a family add was interrupted."""
    document = config_document(cli.home)
    configured = document.get("plugins", {})
    if not isinstance(configured, dict):
        raise Blocked("plugin_configuration_unknown")
    rows = cli.installed()
    if any(not isinstance(row, dict) or not isinstance(row.get("name"), str) for row in rows):
        raise Blocked("plugin_inventory_invalid")
    return {"unrelated": sorted((stable_row(row) for row in rows if not family_row(row)),
                                key=lambda row: str(row.get("pluginId"))),
            "opaque_remote_plugins": assert_other_skill_owners(cli, rows, document),
            "unrelated_configuration_sha256": preserved_configuration_hash(document)}


def assert_other_skill_owners(cli: CodexCLI, rows: list[dict], document: dict) -> list[dict]:
    """Reject known competing owners; explicitly retain opaque remote identities.

    An absent remote manifest is not evidence of zero skills. Plan permits these
    unchanged plugins only when the complete family skill-name set is preserved.
    """
    roots = [cli.home / "skills", Path(cli.env["HOME"]) / ".agents/skills"]
    opaque = []
    skill_section = document.get("skills", {})
    if not isinstance(skill_section, dict):
        raise Blocked("skill_configuration_unknown")
    configured_skills = skill_section.get("config", [])
    if not isinstance(configured_skills, list):
        raise Blocked("skill_configuration_unknown")
    for entry in configured_skills:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise Blocked("skill_configuration_unknown")
        path = Path(entry["path"]).expanduser()
        if entry.get("enabled") is False:
            if any(name in path.parts for name in MOVED):
                raise Blocked("moved_skill_disabled_or_unknown")
            continue
        if not path.is_absolute():
            raise Blocked("local_skill_path_unresolved")
        roots.append(path)
    for row in rows:
        if family_row(row) or row.get("enabled") is False:
            continue
        if row["name"] in FAMILY:
            raise Blocked("family_namespace_ambiguous")
        parts = [row.get(key) for key in ("marketplaceName", "name", "version")]
        if not all(isinstance(part, str) and re.fullmatch(r"[a-zA-Z0-9._-]+", part) for part in parts):
            raise Blocked("other_plugin_skill_owner_unknown")
        package = checked_child(cli.home, "plugins", "cache", *parts)
        manifest_path = package / ".codex-plugin/plugin.json"
        if not manifest_path.is_file():
            manifest_path = package / ".claude-plugin/plugin.json"
        if not manifest_path.is_file():
            source = row.get("source")
            if (row.get("installed") is not True or row.get("enabled") is not True
                    or row.get("pluginId") != f'{row["name"]}@{row["marketplaceName"]}'
                    or not isinstance(source, dict) or source.get("source") != "remote"
                    or not isinstance(source.get("id"), str)
                    or not re.fullmatch(r"[a-zA-Z0-9._-]{1,256}", source["id"])):
                raise Blocked("other_plugin_skill_owner_unknown")
            opaque.append({**stable_row(row), "remote_plugin_id": source["id"],
                           "skill_ownership": "unverified"})
            continue
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict):
            raise Blocked("other_plugin_skill_owner_unknown")
        paths = manifest.get("skills", "./skills/")
        if isinstance(paths, str):
            paths = [paths]
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise Blocked("other_plugin_skill_paths_unknown")
        for path in paths:
            selected = (package / path).resolve()
            if not selected.is_relative_to(package.resolve()):
                raise Blocked("other_plugin_skill_path_outside_package")
            roots.append(selected)
    for root in roots:
        files = {root} if root.is_file() else set(root.rglob("SKILL.md")) if root.is_dir() else set()
        if root.is_dir():
            # Path.rglob does not traverse symlinked local skill directories.
            # Inspect their conventional entrypoints without crawling targets.
            files.update(child / "SKILL.md" for child in root.iterdir()
                         if child.is_dir() and (child / "SKILL.md").is_file())
        for file in files:
            text = file.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            frontmatter = text.split("---", 2)
            if len(frontmatter) < 3:
                raise Blocked("local_skill_metadata_unknown")
            match = re.search(r"(?m)^name:\s*(?:\"([A-Za-z0-9_-]+)\"|'([A-Za-z0-9_-]+)'|([A-Za-z0-9_-]+))\s*$", frontmatter[1])
            if not match:
                raise Blocked("local_skill_metadata_unknown")
            name = next(group for group in match.groups() if group is not None)
            if name in MOVED:
                raise Blocked(f"other_skill_owner_collision:{name}")
    return sorted(opaque, key=lambda row: row["pluginId"])


def inventory(cli: CodexCLI) -> dict:
    document = config_document(cli.home)
    configured = document.get("plugins", {})
    if not isinstance(configured, dict):
        raise Blocked("plugin_configuration_unknown")
    rows = cli.installed()
    family = {}
    unrelated = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise Blocked("plugin_inventory_invalid")
        name = row["name"]
        if not family_row(row):
            if name in FAMILY:
                raise Blocked("family_namespace_ambiguous")
            unrelated.append(stable_row(row))
            continue
        if row.get("marketplaceName") != MARKETPLACE or name in family:
            raise Blocked("family_owner_ambiguous")
        family[name] = stable_row(row)
    # Codex 0.159.0 omits installed plugins removed from the marketplace catalog.
    # Reconcile their intent with exactly one cached package; never infer absence
    # from `plugin list` alone or select an arbitrary cached version.
    for name in FAMILY:
        key = f"{name}@{MARKETPLACE}"
        setting = configured.get(key)
        cache = checked_child(cli.home, "plugins", "cache", MARKETPLACE, name)
        versions = sorted(p for p in cache.iterdir() if p.is_dir()) if cache.exists() else []
        if name not in family and setting is not None:
            if not isinstance(setting, dict) or type(setting.get("enabled")) is not bool or len(versions) != 1:
                raise Blocked(f"unlisted_family_state_unknown:{name}")
            info = package_info(versions[0], name)
            family[name] = {"pluginId": key, "name": name, "marketplaceName": MARKETPLACE,
                            "version": info["version"], "installed": True, "enabled": setting["enabled"]}
        elif name not in family and versions:
            raise Blocked(f"orphan_family_cache:{name}")
        if name in family:
            row = family[name]
            if (row.get("installed") is not True or type(row.get("enabled")) is not bool
                    or not isinstance(setting, dict) or setting.get("enabled") is not row["enabled"]):
                raise Blocked(f"family_enabled_state_unknown:{name}")
            if len(versions) != 1 or versions[0].name != row.get("version"):
                raise Blocked(f"family_cache_version_unknown:{name}")
            info = package_info(versions[0], name)
            if info["version"] != row["version"]:
                raise Blocked(f"family_version_mismatch:{name}")
            row.update(info)
    for key in configured:
        if any(key.startswith(name + "@") and key != f"{name}@{MARKETPLACE}" for name in FAMILY):
            raise Blocked("family_configured_from_other_marketplace")
    opaque = assert_other_skill_owners(cli, rows, document)
    unrelated.sort(key=lambda row: str(row.get("pluginId")))
    owners = {skill: sorted(name for name, row in family.items() if skill in row["skills"]) for skill in MOVED}
    return {"family": family, "owners": owners, "unrelated": unrelated,
            "opaque_remote_plugins": opaque,
            "unrelated_configuration_sha256": preserved_configuration_hash(document)}


def classify(current: dict) -> str:
    family = current["family"]
    if not family:
        return "fresh"
    if any(row["enabled"] is not True for row in family.values()):
        raise Blocked("family_disabled")
    versions = {name: row["version"] for name, row in family.items()}
    if (set(versions) == set(TARGET) and current["owners"] == NEW_OWNERS
            and all(version_at_least(versions[name], floor) for name, floor in TARGET.items())):
        return "current"
    if versions == PREDECESSOR and current["owners"] == OLD_OWNERS:
        return "predecessor"
    raise Blocked("mixed_partial_or_unknown_family")


def version_at_least(version: str, floor: str) -> bool:
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return False
    return tuple(map(int, version.split("."))) >= tuple(map(int, floor.split(".")))


def candidates(root: Path, *, exact_migration: bool = False) -> dict:
    result = {name: package_info(root / "plugins" / name, name) for name in TARGET}
    versions = {name: info["version"] for name, info in result.items()}
    if ((exact_migration and versions != TARGET)
            or not all(version_at_least(versions[name], floor) for name, floor in TARGET.items())):
        raise Blocked("candidate_version_mismatch")
    owners = {skill: sorted(name for name, info in result.items() if skill in info["skills"]) for skill in MOVED}
    if owners != NEW_OWNERS:
        raise Blocked("candidate_skill_ownership_invalid")
    return result


def journal_path(home: Path) -> Path:
    return checked_child(home, *STATE_PARTS, "transaction.json")


def open_transaction_file(path: Path, *, lock: bool = False):
    """Do not follow a file symlink, including a swap after checked_child."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise Blocked("transaction_nofollow_unavailable")
    flags = os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_RDWR | os.O_CREAT if lock else os.O_RDONLY)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise Blocked("unsafe_transaction_file") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise Blocked("transaction_file_not_regular")
        return os.fdopen(descriptor, "r+" if lock else "r", encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise


def read_journal(path: Path) -> dict:
    try:
        with open_transaction_file(path) as source:
            value = json.load(source)
    except (OSError, ValueError) as error:
        raise Blocked("recovery_receipt_invalid") from error
    if not isinstance(value, dict):
        raise Blocked("recovery_receipt_invalid")
    return value


def plan(root: Path, cli: CodexCLI) -> dict:
    journal = journal_path(cli.home)
    if journal.exists():
        saved = read_journal(journal)
        if saved.get("phase") not in {"committed", "recovered"}:
            raise Blocked("interrupted_migration_requires_recovery")
    current = inventory(cli)
    state = classify(current)
    target = candidates(root, exact_migration=state == "predecessor")
    old_names = Counter(skill for row in current["family"].values() for skill in row["skills"])
    new_names = Counter(skill for row in target.values() for skill in row["skills"])
    preserved_names = old_names == new_names
    if state == "predecessor" and not preserved_names:
        raise Blocked("migration_family_skill_names_changed")
    if current["opaque_remote_plugins"] and not preserved_names:
        raise Blocked("opaque_remote_plugins_require_unchanged_family_skill_names")
    return {"schema_version": 1, "status": state, "migration": "visual-communication",
            "family": current["family"], "owners": current["owners"], "target": target,
            "ownership_scope": "verified_family_and_local_skills",
            "opaque_remote_plugins": current["opaque_remote_plugins"],
            "family_skill_names_preserved": preserved_names,
            "recoverable_predecessors": state == "predecessor", "live_execution_verified": False,
            "steps": (["capture_packages", "rehearse_upgrade_and_recovery", "add_and_verify_diagram-tools",
                       "add_and_verify_workflow-tools", "remove_paper-figure-tools", "verify_final_owners"]
                      if state == "predecessor" else []),
            "next_action": "explicit_migration" if state == "predecessor" else "standard_setup",
            "_inventory": current}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".receipt-", delete=False) as output:
        temporary = Path(output.name)
        json.dump(data, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    # Persist the rename itself before a caller performs the journaled CLI
    # mutation; syncing only the temporary file does not make its name durable.
    directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def snapshot(destination: Path, packages: dict[str, Path], expected: dict) -> None:
    if destination.exists():
        raise Blocked("snapshot_destination_exists")
    destination.mkdir(parents=True, mode=0o700)
    entries = []
    for name, source in packages.items():
        target = destination / "plugins" / name
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(*IGNORED, "*.pyc", "*.pyo"))
        if package_info(target, name) != expected[name]:
            raise Blocked(f"snapshot_verification_failed:{name}")
        entries.append({"name": name, "source": {"source": "local", "path": f"./plugins/{name}"}})
    write_json(destination / ".agents" / "plugins" / "marketplace.json", {"name": MARKETPLACE, "plugins": entries})


def assert_unrelated(before: dict, after: dict) -> None:
    for key in ("unrelated", "unrelated_configuration_sha256", "opaque_remote_plugins"):
        if before[key] != after[key]:
            raise Blocked("unrelated_installation_changed")


def verify_package(cli: CodexCLI, name: str, expected: dict) -> None:
    # Validate this exact add independently: another family cache may be absent
    # after an interrupted operation and must not prevent supported recovery.
    configured = config_document(cli.home).get("plugins", {}).get(f"{name}@{MARKETPLACE}", {})
    cache = checked_child(cli.home, "plugins", "cache", MARKETPLACE, name)
    versions = list(cache.iterdir()) if cache.is_dir() else []
    if configured.get("enabled") is not True or len(versions) != 1 or versions[0].name != expected["version"]:
        raise Blocked(f"installed_candidate_verification_failed:{name}")
    info = package_info(versions[0], name)
    rows = [row for row in cli.installed() if row.get("name") == name]
    # Successor names remain catalogued and must be discoverable. Only the
    # retired paper plugin may be absent from CLI discovery during recovery.
    if (info != expected or len(rows) > 1 or (name in TARGET and len(rows) != 1)
            or any(row.get("marketplaceName") != MARKETPLACE or row.get("installed") is not True
                   or row.get("version") != expected["version"] or row.get("enabled") is not True for row in rows)):
        raise Blocked(f"installed_candidate_verification_failed:{name}")


def package_readback(root: Path, cli: CodexCLI, name: str) -> dict:
    expected = candidates(root)[name]
    verify_package(cli, name, expected)
    return {"schema_version": 1, "status": "verified", "migration": "visual-communication",
            "scope": "package", "package": name, "version": expected["version"],
            "sha256": expected["sha256"], "skills": expected["skills"],
            "live_execution_verified": True}


def transition(cli: CodexCLI, target_root: Path, expected: dict, record=lambda operation: None) -> None:
    # Both candidate ownership surfaces are checked before the retire operation.
    for name in TARGET:
        record(f"add:{name}")
        cli.add(name, target_root)
        verify_package(cli, name, expected[name])
    record("remove:paper-figure-tools")
    cli.remove("paper-figure-tools")
    if classify(inventory(cli)) != "current":
        raise Blocked("final_family_verification_failed")


def restore(cli: CodexCLI, previous: Path, before: dict, record=lambda operation: None) -> None:
    # Restore the original capability owners before removing the candidate's
    # copies by replacing diagram-tools. All restores use the supported add CLI.
    for name in ("paper-figure-tools", "workflow-tools", "diagram-tools"):
        record(f"restore:{name}")
        cli.add(name, previous)
        verify_package(cli, name, {key: before["family"][name][key] for key in ("version", "sha256", "skills")})
    after = inventory(cli)
    if after != before:
        raise Blocked("recovery_verification_failed")


def rehearse(binary: str, previous: Path, target: Path, expected: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="toolbox-visual-migration-rehearsal-") as directory:
        home = Path(directory) / "codex"
        home.mkdir()
        cli = CodexCLI(binary, home, isolated=True)
        cli.run("plugin", "marketplace", "add", str(previous), "--json")
        for name in FAMILY:
            cli.add(name, previous)
        before = inventory(cli)
        if classify(before) != "predecessor":
            raise Blocked("rehearsal_predecessor_unverified")
        transition(cli, target, expected)
        restore(cli, previous, before)


def recover(cli: CodexCLI, saved: dict, state: Path) -> dict:
    if saved.get("schema_version") != 1 or saved.get("codex_home") != str(cli.home):
        raise Blocked("recovery_receipt_invalid")
    if not re.fullmatch(r"packages-[a-zA-Z0-9_-]+", str(saved.get("snapshot_id", ""))):
        raise Blocked("recovery_snapshot_invalid")
    previous = checked_child(state, saved["snapshot_id"], "previous")
    before = saved["before"]
    if classify(before) != "predecessor":
        raise Blocked("recovery_predecessor_invalid")
    for name, row in before["family"].items():
        expected = {key: row[key] for key in ("version", "sha256", "skills")}
        if package_info(checked_child(previous, "plugins", name), name) != expected:
            raise Blocked("recovery_package_changed")
    assert_unrelated(before, unrelated_observation(cli))
    configuration = config_document(cli.home).get("plugins", {})
    for name in FAMILY:
        key = f"{name}@{MARKETPLACE}"
        if key in configuration and (not isinstance(configuration[key], dict) or configuration[key].get("enabled") is not True):
            raise Blocked("recovery_family_intent_changed")
        cache = checked_child(cli.home, "plugins", "cache", MARKETPLACE, name)
        original = {key: before["family"][name][key] for key in ("version", "sha256", "skills")}
        known = [original]
        if name in saved.get("target", {}):
            known.append(saved["target"][name])
        if cache.exists():
            for path in cache.iterdir():
                if path.name not in {package["version"] for package in known}:
                    raise Blocked("recovery_family_version_changed")
                if package_info(path, name) not in known:
                    raise Blocked("recovery_family_package_changed")
    saved["phase"] = "recovering"
    write_json(state / "transaction.json", saved)
    restore(cli, previous, before)
    saved["phase"] = "recovered"
    saved.pop("pending_operation", None)
    write_json(state / "transaction.json", saved)
    return {"schema_version": 1, "status": "recovered", "migration": "visual-communication",
            "next_action": "review_plan_before_retry", "live_execution_verified": True}


def apply(root: Path, cli: CodexCLI) -> dict:
    state = checked_child(cli.home, *STATE_PARTS)
    # Fresh/current no-ops remain read-only, including no lock/journal creation.
    journal = journal_path(cli.home)
    lock_path = checked_child(state, "lock")
    interrupted = journal.exists() and read_journal(journal).get("phase") not in {"committed", "recovered"}
    if not interrupted:
        initial = plan(root, cli)
        if initial["status"] in {"fresh", "current"}:
            return {key: value for key, value in initial.items() if not key.startswith("_")}
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open_transaction_file(lock_path, lock=True) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Blocked("migration_already_running") from error
        journal = journal_path(cli.home)
        if journal.exists():
            saved = read_journal(journal)
            if saved.get("phase") not in {"committed", "recovered"}:
                return recover(cli, saved, state)
        proposal = plan(root, cli)
        if proposal["status"] in {"fresh", "current"}:
            return {key: value for key, value in proposal.items() if not key.startswith("_")}
        before = proposal["_inventory"]
        # Only task-owned snapshots are created here; user runtime/state/figure
        # directories and active configuration are never copied or rewritten.
        capture = Path(tempfile.mkdtemp(prefix="packages-", dir=state))
        previous, target = capture / "previous", capture / "target"
        old_expected = {name: {key: row[key] for key in ("version", "sha256", "skills")}
                        for name, row in before["family"].items()}
        snapshot(previous, {name: cli.home / "plugins/cache" / MARKETPLACE / name / row["version"]
                            for name, row in before["family"].items()}, old_expected)
        snapshot(target, {name: root / "plugins" / name for name in TARGET}, proposal["target"])
        rehearse(cli.binary, previous, target, proposal["target"])
        if inventory(cli) != before or candidates(root, exact_migration=True) != proposal["target"]:
            raise Blocked("state_changed_during_rehearsal")
        saved = {"schema_version": 1, "phase": "prepared", "codex_home": str(cli.home),
                 "snapshot_id": capture.name, "before": before, "target": proposal["target"],
                 "rehearsal": "upgrade_and_recovery_passed"}
        write_json(journal, saved)

        def record(operation: str) -> None:
            saved["pending_operation"] = operation
            write_json(journal, saved)

        try:
            transition(cli, target, proposal["target"], record)
            after = inventory(cli)
            assert_unrelated(before, after)
            saved["phase"] = "committed"
            saved.pop("pending_operation", None)
            write_json(journal, saved)
            return {"schema_version": 1, "status": "migrated", "migration": "visual-communication",
                    "owners": after["owners"], "versions": TARGET, "recovery_snapshot": str(previous),
                    "ownership_scope": proposal["ownership_scope"],
                    "opaque_remote_plugins": after["opaque_remote_plugins"],
                    "family_skill_names_preserved": proposal["family_skill_names_preserved"],
                    "rehearsal": saved["rehearsal"], "live_execution_verified": True}
        except (Blocked, OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            saved["phase"] = "recovery_required"
            write_json(journal, saved)
            try:
                recover(cli, saved, state)
            except (Blocked, OSError, ValueError, KeyError, TypeError, AttributeError):
                raise Blocked("migration_failed_recovery_required_rerun_explicit_migration") from error
            raise Blocked("migration_failed_predecessors_restored") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check-setup", action="store_true")
    mode.add_argument("--verify-package", choices=tuple(TARGET))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    args = parser.parse_args(argv)
    cli = CodexCLI(args.codex_bin, args.codex_home.expanduser())
    try:
        if tomllib is None:
            interpreter = parser_python(cli.home)
            # Re-execution uses only an installed interpreter and a clean
            # environment; no credentials or active profile enter a probe.
            command = [interpreter, "-I", str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])]
            return subprocess.run(command, env=clean_environment(cli.home), check=False).returncode
        if args.verify_package:
            result = package_readback(args.root.resolve(), cli, args.verify_package)
        else:
            result = apply(args.root.resolve(), cli) if args.apply else plan(args.root.resolve(), cli)
        result = {key: value for key, value in result.items() if not key.startswith("_")}
        if args.check_setup and result["status"] == "predecessor":
            result.update(status="blocked", reason="explicit_family_migration_required",
                          next_action="scripts/setup-codex-toolbox.sh --migrate visual-communication")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2 if result["status"] in {"blocked", "recovered"} else 0
    except (Blocked, OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        reason = str(error) if isinstance(error, Blocked) else "migration_state_unreadable"
        print(json.dumps({"schema_version": 1, "status": "blocked", "migration": "visual-communication",
                          "reason": reason, "live_execution_verified": False}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
