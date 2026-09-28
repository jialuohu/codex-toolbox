"""Build a local capability catalog from active Codex installation evidence.

This module never contacts Jev. A live tool must be supplied by the caller's
current effective tool inventory; installed MCP configuration is insufficient.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_CAPABILITY_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/@-]{0,191}$")
_FIELD = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?:\s*(.*))?$")
_POLICY = re.compile(
    r"^\s*allow_implicit_invocation:\s*(true|false)\s*(?:#.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_CANDIDATE_KEYS = ("id", "name", "description", "owner", "availability", "implicit")
_MAX_METADATA_BYTES = 64 * 1024
_MAX_DESCRIPTION_BYTES = 300
_MAX_NAME_BYTES = 100
_MAX_OWNER_BYTES = 100


def _bounded_description(value: str) -> str:
    return value.encode("utf-8")[:_MAX_DESCRIPTION_BYTES].decode("utf-8", errors="ignore").strip()


def _short_name_and_owner(name: str, owner: str) -> bool:
    return (bool(name.strip()) and bool(owner.strip())
            and len(name.encode("utf-8")) <= _MAX_NAME_BYTES
            and len(owner.encode("utf-8")) <= _MAX_OWNER_BYTES)


def collect_live_tools(tool_metadata: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Adapt the current host tool list without claiming plugin provenance.

    `ALL_TOOLS`-style records have `name` and `description`. Their namespace is
    the honest owner when the host supplies no verified plugin mapping.
    """
    rows = []
    for source in tool_metadata:
        tool_id = source.get("name")
        description = source.get("description")
        if not isinstance(tool_id, str) or not isinstance(description, str):
            raise TypeError("live tool metadata needs name and description")
        parts = tool_id.split("__")
        if len(parts) >= 3 and parts[0] == "mcp":
            owner = f"mcp:{parts[1]}"
            display_name = "__".join(parts[2:])
        elif len(parts) >= 2:
            owner = parts[0]
            display_name = "__".join(parts[1:])
        else:
            owner = "host"
            display_name = tool_id
        rows.append({"id": tool_id, "name": display_name,
                     "description": description, "owner": owner})
    return rows


def _string_value(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _frontmatter(path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    if len(raw) > _MAX_METADATA_BYTES:
        raise ValueError("skill entry too large")
    lines = raw.decode("utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("missing skill front matter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("unterminated skill front matter") from exc
    fields: dict[str, str] = {}
    index = 1
    while index < end:
        match = _FIELD.match(lines[index])
        if not match:
            index += 1
            continue
        key, value = match.group(1), match.group(2) or ""
        if key in ("name", "description", "disable-model-invocation"):
            if value in ("|", ">", "|-", ">-"):
                block: list[str] = []
                index += 1
                while index < end and (not lines[index] or lines[index][0].isspace()):
                    block.append(lines[index].strip())
                    index += 1
                fields[key] = " ".join(part for part in block if part)
                continue
            fields[key] = _string_value(value)
        index += 1
    return fields


def _implicit(skill_dir: Path, metadata: Mapping[str, str]) -> bool:
    if metadata.get("disable-model-invocation", "false").lower() == "true":
        return False
    policy = skill_dir / "agents" / "openai.yaml"
    if policy.is_file():
        if policy.is_symlink() or (skill_dir / "agents").is_symlink():
            raise ValueError("symlinked skill policy")
        raw = policy.read_bytes()
        if len(raw) > _MAX_METADATA_BYTES:
            raise ValueError("skill policy too large")
        text = raw.decode("utf-8")
        if "allow_implicit_invocation" in text:
            match = _POLICY.search(text)
            if not match:
                raise ValueError("invalid implicit invocation policy")
            return match.group(1).lower() == "true"
    return True


def collect_installed_skills(plugin_listing: Mapping[str, Any], cache_root: Path) -> list[dict[str, Any]]:
    """Read skill metadata only for exact enabled entries in `codex plugin list --json`.

    An absent cache entry is omitted rather than substituted with a marketplace
    source or an unrelated checkout. The result is local evidence, not a claim
    that dependent tools are authenticated or connected.
    """
    installed = plugin_listing.get("installed")
    if not isinstance(installed, list):
        raise TypeError("plugin listing must contain installed array")
    rows: list[dict[str, Any]] = []
    root = cache_root.resolve()
    for plugin in installed:
        if not isinstance(plugin, dict) or plugin.get("installed") is not True or plugin.get("enabled") is not True:
            continue
        name, market, version = (plugin.get(key) for key in ("name", "marketplaceName", "version"))
        plugin_id = plugin.get("pluginId")
        if not all(isinstance(item, str) and _COMPONENT.fullmatch(item) for item in (name, market, version)):
            continue
        if plugin_id != f"{name}@{market}":
            continue
        plugin_dir = root / market / name / version
        if (not plugin_dir.is_dir() or plugin_dir.is_symlink()
                or plugin_dir.parent.is_symlink()
                or plugin_dir.parent.parent.is_symlink()
                or not plugin_dir.resolve().is_relative_to(root)):
            continue
        manifest = plugin_dir / ".codex-plugin" / "plugin.json"
        if (not manifest.is_file() or manifest.is_symlink()
                or (plugin_dir / ".codex-plugin").is_symlink()):
            continue
        try:
            raw_manifest = manifest.read_bytes()
            if len(raw_manifest) > _MAX_METADATA_BYTES:
                continue
            metadata_manifest = json.loads(raw_manifest)
        except (OSError, ValueError):
            continue
        if (metadata_manifest.get("name") != name
                or metadata_manifest.get("version") != version
                or metadata_manifest.get("skills") not in ("./skills/", "./skills")):
            continue
        skill_root = plugin_dir / "skills"
        if not skill_root.is_dir() or skill_root.is_symlink():
            continue
        for skill_dir in sorted(skill_root.iterdir()):
            if not skill_dir.is_dir() or skill_dir.is_symlink():
                continue
            entry = skill_dir / "SKILL.md"
            if not entry.is_file() or entry.is_symlink():
                continue
            try:
                metadata = _frontmatter(entry)
                skill_name = metadata.get("name", "")
                description = metadata.get("description", "").strip()
                if skill_name != skill_dir.name or not description or not _COMPONENT.fullmatch(skill_name):
                    continue
                implicit = _implicit(skill_dir, metadata)
            except (OSError, UnicodeError, ValueError):
                continue
            capability_id = f"skill:{plugin_id}/{skill_name}"
            if not _CAPABILITY_ID.fullmatch(capability_id) or not _short_name_and_owner(skill_name, plugin_id):
                continue
            rows.append({
                "id": capability_id,
                "name": skill_name,
                "description": _bounded_description(description),
                "owner": plugin_id,
                "availability": "installed",
                "implicit": implicit,
                "_source_version": version,
            })
    return rows


def build_catalog(installed_skills: Iterable[Mapping[str, Any]],
                  live_tools: Iterable[Mapping[str, Any]] = (),
                  host_skills: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Pure, deterministic normalization of installed skills and live tool evidence.

    `live_tools` must come from the current host's callable tool list. MCP
    configuration, plugin installation, and advertised app metadata do not
    qualify as live tool evidence.
    """
    normalized: list[dict[str, Any]] = []
    source_versions: dict[str, str] = {}
    for source in installed_skills:
        row = {key: source.get(key) for key in _CANDIDATE_KEYS}
        if (not all(isinstance(row[key], str) and row[key] for key in _CANDIDATE_KEYS[:-1])
                or type(row["implicit"]) is not bool
                or row["availability"] != "installed"
                or not row["id"].startswith("skill:")
                or not _CAPABILITY_ID.fullmatch(row["id"])
                or not _short_name_and_owner(row["name"], row["owner"])
                or not row["description"].strip()):
            raise ValueError("invalid installed skill candidate")
        row["description"] = _bounded_description(row["description"])
        normalized.append(row)
        version = source.get("_source_version", "")
        if not isinstance(version, str):
            raise TypeError("invalid source version")
        source_versions[row["id"]] = version
    for source in live_tools:
        tool_id = source.get("id")
        name = source.get("name")
        description = source.get("description")
        owner = source.get("owner")
        if not all(isinstance(item, str) and item for item in (tool_id, name, description, owner)):
            raise ValueError("live tools need id, name, description, and owner")
        capability_id = f"tool:{tool_id}"
        if (not _CAPABILITY_ID.fullmatch(capability_id) or not _short_name_and_owner(name, owner)
                or not description.strip()):
            raise ValueError("invalid live tool id")
        normalized.append({
            "id": capability_id,
            "name": name,
            "description": _bounded_description(description),
            "owner": owner,
            "availability": "available",
            "implicit": True,
        })
    for source in host_skills:
        skill_id = source.get("id")
        name = source.get("name")
        description = source.get("description")
        owner = source.get("owner")
        implicit = source.get("implicit")
        if (not all(isinstance(item, str) and item for item in (skill_id, name, description, owner))
                or type(implicit) is not bool):
            raise ValueError("host skills need id, name, description, owner, and implicit")
        capability_id = skill_id if skill_id.startswith("skill:") else f"skill:{skill_id}"
        if (not _CAPABILITY_ID.fullmatch(capability_id) or not _short_name_and_owner(name, owner)
                or not description.strip()):
            raise ValueError("invalid host skill id")
        existing = next((row for row in normalized if row["id"] == capability_id), None)
        if existing is not None:
            if existing["availability"] != "installed" or existing["name"] != name or existing["owner"] != owner:
                raise ValueError("conflicting host skill identity")
            existing["availability"] = "available"
            existing["implicit"] = existing["implicit"] and implicit
        else:
            normalized.append({
                "id": capability_id,
                "name": name,
                "description": _bounded_description(description),
                "owner": owner,
                "availability": "available",
                "implicit": implicit,
            })
    normalized.sort(key=lambda row: row["id"])
    ids = [row["id"] for row in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate capability id")
    material = {"candidates": normalized, "source_versions": source_versions}
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"catalog_digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "candidates": normalized}


def prepare_route_candidates(catalog: Mapping[str, Any], selected_ids: Iterable[str],
                             verified_ids: Iterable[str], required_ids: Iterable[str] = (),
                             explicit_invocations: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Require fresh host availability before preparing the server's exact shape.

    Selection is intentionally caller-owned. The host must independently verify
    each selected skill/tool is callable in this turn; a catalog entry alone is
    insufficient. IDs retain caller shortlist order and all required entries.
    """
    rows = catalog.get("candidates")
    if not isinstance(rows, list):
        raise TypeError("catalog candidates unavailable")
    if any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
           or not _CAPABILITY_ID.fullmatch(row["id"]) for row in rows):
        raise ValueError("catalog has invalid IDs")
    by_id = {row.get("id"): row for row in rows if isinstance(row, dict)}
    if len(by_id) != len(rows):
        raise ValueError("catalog has duplicate or invalid IDs")
    selected = list(selected_ids)
    if any(not isinstance(capability_id, str) or not _CAPABILITY_ID.fullmatch(capability_id)
           for capability_id in selected):
        raise ValueError("selected candidate has invalid id")
    if len(selected) > 16 or len(selected) != len(set(selected)):
        raise ValueError("selected candidates exceed limit or repeat")
    verified = set(verified_ids)
    required = set(required_ids)
    invoked = set(explicit_invocations)
    if not required.issubset(selected):
        raise ValueError("required candidate omitted")
    if not selected:
        raise ValueError("no selected candidates")
    result = []
    for capability_id in selected:
        row = by_id.get(capability_id)
        if row is None or capability_id not in verified:
            raise ValueError("unknown or unverified candidate")
        if (not all(isinstance(row.get(field), str) and row[field].strip()
                    for field in ("name", "description", "owner"))
                or not _short_name_and_owner(row["name"], row["owner"])
                or len(row["description"].encode("utf-8")) > _MAX_DESCRIPTION_BYTES):
            raise ValueError("invalid candidate metadata")
        if row["implicit"] is False and (capability_id not in invoked or capability_id not in required):
            raise ValueError("explicit-only skill must be invoked and required")
        result.append({
            "id": row["id"], "name": row["name"],
            "description": row["description"], "owner": row["owner"],
            "availability": "available", "implicit": row["implicit"],
            "required": capability_id in required,
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-list-json", type=Path,
                        help="local codex plugin list --json snapshot; otherwise invoke that read-only CLI")
    parser.add_argument("--cache-root", type=Path,
                        default=Path.home() / ".codex" / "plugins" / "cache")
    parser.add_argument("--live-tools-json", type=Path,
                        help="current host callable-tool inventory with id, name, description, owner")
    parser.add_argument("--host-skills-json", type=Path,
                        help="current host skill inventory with id, name, description, owner, implicit")
    args = parser.parse_args()
    if args.plugin_list_json:
        plugin_listing = json.loads(args.plugin_list_json.read_text(encoding="utf-8"))
    else:
        raw = subprocess.run(["codex", "plugin", "list", "--json"], check=True,
                             capture_output=True, text=True, timeout=10)
        plugin_listing = json.loads(raw.stdout)
    live_tools = json.loads(args.live_tools_json.read_text(encoding="utf-8")) if args.live_tools_json else []
    host_skills = json.loads(args.host_skills_json.read_text(encoding="utf-8")) if args.host_skills_json else []
    catalog = build_catalog(collect_installed_skills(plugin_listing, args.cache_root), live_tools,
                            host_skills)
    print(json.dumps(catalog, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
