"""Strict skill metadata and local-reference validation; no Toolbox policy."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

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
    if len(text) > 4 * 1024 * 1024:
        raise ValueError("metadata size limit")
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


def local_links(path: Path, root: Path) -> tuple[list[Path], list[str]]:
    path, root = path.resolve(), root.resolve()
    if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("reference size or type limit")
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
        if len(seen) >= 512:
            raise ValueError("reference count limit")
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
