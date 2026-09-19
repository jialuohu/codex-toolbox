#!/usr/bin/env python3
"""Offline skill discovery/reference audit. Install instruction-audit-requirements.txt."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXPLICIT_ONLY = {"ship-toolbox", "pick-ui-library", "prototype", "review-animations"}
IMPORTED = {"chronicle", "defuddle", "playwright", "json-canvas", "obsidian-bases", "obsidian-cli", "obsidian-markdown"}


# Format validation is shared with the installed helper; authoring policy stays here.
sys.dont_write_bytecode = True
_validation_path = ROOT / "plugins/workflow-tools/skills/sync-toolbox/scripts/skill_validation.py"
_spec = importlib.util.spec_from_file_location("toolbox_skill_validation", _validation_path)
_validation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_validation)
read_yaml = _validation.read_yaml
frontmatter = _validation.frontmatter
local_links = _validation.local_links
reference_graph = _validation.reference_graph


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
