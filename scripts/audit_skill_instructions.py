#!/usr/bin/env python3
"""Offline skill discovery/reference audit. Install instruction-audit-requirements.txt."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXPLICIT_ONLY = {"ship-toolbox", "pick-ui-library", "prototype", "review-animations"}
IMPORTED = {"chronicle", "defuddle", "playwright", "json-canvas", "obsidian-bases", "obsidian-cli", "obsidian-markdown"}


class UniqueLoader(yaml.SafeLoader):
    """Reject ambiguous duplicate YAML keys, including nested invocation policy."""


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def read_yaml(text: str):
    return yaml.load(text, Loader=UniqueLoader)


def frontmatter(text: str) -> dict:
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
    if not match:
        raise ValueError("missing YAML frontmatter")
    data = read_yaml(match[1])
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a mapping")
    for field in ("name", "description"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"{field} must be a nonempty string")
    return data


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_links(path: Path, root: Path) -> tuple[list[Path], list[str]]:
    path, root = path.resolve(), root.resolve()
    text = path.read_text(encoding="utf-8")
    # Examples inside fences are not live reference edges.
    text = re.sub(r"(?ms)^\s*(`{3,}|~{3,}).*?^\s*\1\s*$", "", text)
    named_refs = re.findall(r"`((?:references|assets)/[^`\n]*\.(?:md|json|yaml|yml))`", text)
    text = re.sub(r"(`+)[^\n]*?\1", "", text)
    links, errors = [], []
    for raw in re.findall(r"!?\[[^\]\n]*\]\(([^)\n]+)\)", text) + named_refs:
        target = raw.strip().split(' "', 1)[0].strip("<>")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        if any(c in target for c in ("$", "{", "}", "*")):
            continue
        resolved = (path.parent / unquote(parsed.path)).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            errors.append(f"{path.relative_to(root)}: reference escapes repository: {target}")
            continue
        if not resolved.exists():
            errors.append(f"{path.relative_to(root)}: missing reference: {target}")
        else:
            links.append(resolved)
    return links, errors


def reference_graph(entry: Path, root: Path) -> tuple[list[str], list[str]]:
    entry, root = entry.resolve(), root.resolve()
    pending, seen, errors = [entry], set(), []
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        if path.suffix != ".md":
            continue
        links, failures = local_links(path, root)
        errors.extend(failures)
        pending.extend(links)
    return sorted(str(p.relative_to(root)) for p in seen if p != entry), errors


def inventory(root: Path) -> dict:
    root = root.resolve()
    rows, errors = [], []
    for path in sorted(root.glob("plugins/*/skills/*/SKILL.md")):
        rel = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            meta = frontmatter(text)
            agent = path.parent / "agents/openai.yaml"
            invocation = True
            if agent.exists():
                agent_meta = read_yaml(agent.read_text(encoding="utf-8"))
                invocation = agent_meta.get("policy", {}).get("allow_implicit_invocation", True)
                if type(invocation) is not bool:
                    raise ValueError("allow_implicit_invocation must be boolean")
            refs, failures = reference_graph(path, root)
            errors.extend(failures)
            name = meta["name"]
            if name != path.parent.name:
                raise ValueError("skill name and directory differ")
            ownership = "preserved-import" if name in IMPORTED else "toolbox"
            if "design-engineering-tools" in path.parts:
                ownership = "toolbox-adaptation"
            rows.append({"name": name, "path": rel, "description": meta["description"].strip(),
                         "description_chars": len(meta["description"].strip()),
                         "entry_bytes": len(raw), "entry_words": len(text.split()),
                         "implicit": invocation, "ownership": ownership,
                         "sha256": digest(raw), "references": refs})
        except (ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
            errors.append(f"{rel}: {exc}")
    names = [row["name"] for row in rows]
    if len(names) != len(set(names)):
        errors.append("duplicate skill names")
    if not rows:
        errors.append("no skills discovered")
    instructions = {p: len((root / p).read_bytes()) for p in ("AGENTS.md", "config/codex/AGENTS.global.md") if (root / p).exists()}
    source_files = set(instructions)
    for row in rows:
        source_files.add(row["path"])
        source_files.update(row["references"])
        agent = str(Path(row["path"]).parent / "agents/openai.yaml")
        if (root / agent).exists():
            source_files.add(agent)
    hashes = {p: digest((root / p).read_bytes()) for p in sorted(source_files) if (root / p).is_file()}
    return {"schema_version": 1, "skill_count": len(rows),
            "description_chars": sum(row["description_chars"] for row in rows),
            "instruction_bytes": instructions, "source_sha256": digest(json.dumps(hashes, sort_keys=True).encode()),
            "file_hashes": hashes, "skills": rows, "errors": sorted(set(errors))}


def check(report: dict, policy: dict, baseline: dict | None = None) -> tuple[list[str], list[str]]:
    errors = list(report["errors"])
    warnings = []
    exceptions = policy.get("description_exceptions", {})
    actual_explicit = {r["name"] for r in report["skills"] if not r["implicit"]}
    if actual_explicit != EXPLICIT_ONLY:
        errors.append(f"explicit-only policy changed: {sorted(actual_explicit)}")
    by_name = {r["name"]: r for r in report["skills"]}
    for row in report["skills"]:
        if row["description_chars"] > 240:
            warnings.append(f"{row['name']}: description exceeds 240 characters")
            reason = exceptions.get(row["name"])
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{row['name']}: long description needs a documented exception")
    for name in exceptions:
        if name not in by_name or by_name[name]["description_chars"] <= 240:
            errors.append(f"stale description exception: {name}")
    sizes = report["instruction_bytes"]
    if sizes.get("config/codex/AGENTS.global.md", 0) > 8192 or sum(sizes.values()) > 16384:
        errors.append("global/combined instruction budget exceeded")
    if "wechat-digest" in by_name and by_name["wechat-digest"]["entry_words"] > 500:
        errors.append("wechat-digest: entry exceeds 500 words")
    if baseline:
        if {(r["name"], r["path"]) for r in report["skills"]} != {(r["name"], r["path"]) for r in baseline["skills"]}:
            errors.append("skill names or entry paths changed")
        reduction = 1 - report["description_chars"] / baseline["description_chars"]
        report["description_reduction_percent"] = round(100 * reduction, 2)
        if reduction < 0.25:
            errors.append("aggregate descriptions have not decreased by 25 percent")
    return sorted(set(errors)), warnings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--policy", type=Path, default=ROOT / "tests/fixtures/instruction-policy.json")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inventory(args.root)
    warnings = []
    if args.check:
        policy = json.loads(args.policy.read_text())
        baseline = json.loads(args.baseline.read_text()) if args.baseline else None
        report["errors"], warnings = check(report, policy, baseline)
    report["warnings"] = warnings
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"{report['skill_count']} skills; {report['description_chars']} description characters")
        for message in warnings + report["errors"]:
            print(message)
    return int(bool(report["errors"]))


if __name__ == "__main__":
    sys.exit(main())
