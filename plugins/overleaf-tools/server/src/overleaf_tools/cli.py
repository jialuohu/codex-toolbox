"""Interactive, history-safe configuration CLI."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any, cast

from overleaf_tools.config import (
    ConfigStore,
    validate_alias,
    validate_project_id,
    validate_token_name,
)
from overleaf_tools.errors import ErrorCode, OverleafError
from overleaf_tools.permissions import assert_private, is_link_like, reject_link_components


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _init(store: ConfigStore, _args: argparse.Namespace) -> int:
    created = store.initialize()
    _print_json({"ok": True, "created": created, "configPath": str(store.config_path)})
    return 0


def _set_token(store: ConfigStore, args: argparse.Namespace) -> int:
    name = validate_token_name(args.name)
    token = getpass.getpass("Overleaf Git token (input hidden): ")
    path = store.set_token(name, token)
    _print_json({"ok": True, "token": name, "tokenPath": str(path), "valueReported": False})
    return 0


def _add_project(store: ConfigStore, args: argparse.Namespace) -> int:
    store.initialize()
    alias = validate_alias(args.alias)
    project_id = validate_project_id(args.project_id)
    token_name = validate_token_name(args.token)
    token_path = store.root / "tokens" / f"{token_name}.token"
    assert_private(token_path, directory=False)
    raw = store.read_raw()
    projects_value = raw.setdefault("projects", {})
    if not isinstance(projects_value, dict):
        raise OverleafError(ErrorCode.CONFIGURATION_INVALID, "projects is invalid.")
    projects = cast(dict[str, object], projects_value)
    entry: dict[str, str] = {
        "projectId": project_id,
        "tokenFile": f"tokens/{token_name}.token",
    }
    if args.display_name:
        if len(args.display_name) > 200 or any(ord(char) < 32 for char in args.display_name):
            raise ValueError("display name is invalid")
        entry["displayName"] = args.display_name
    projects[alias] = entry
    store.write_raw(raw)
    store.load()
    _print_json({"ok": True, "project": alias, "token": token_name})
    return 0


def _remove_project(store: ConfigStore, args: argparse.Namespace) -> int:
    alias = validate_alias(args.alias)
    store.remove_project(alias)
    _print_json(
        {
            "ok": True,
            "project": alias,
            "removed": True,
            "tokenRetained": True,
        }
    )
    return 0


def _add_import_root(store: ConfigStore, args: argparse.Namespace) -> int:
    store.initialize()
    path = Path(args.path).expanduser()
    if not path.is_absolute() or not path.is_dir() or is_link_like(path):
        raise ValueError("import root must be an existing absolute non-link directory")
    reject_link_components(path)
    canonical = path.resolve(strict=True)
    raw = store.read_raw()
    roots_value = raw.setdefault("allowedImportRoots", [])
    if not isinstance(roots_value, list):
        raise ValueError("allowedImportRoots is invalid")
    roots = cast(list[object], roots_value)
    value = str(canonical)
    if value not in roots:
        roots.append(value)
    store.write_raw(raw)
    store.load()
    _print_json({"ok": True, "allowedImportRoot": value})
    return 0


def _status(store: ConfigStore, args: argparse.Namespace) -> int:
    config = store.load()
    aliases = [args.alias] if args.alias else sorted(config.projects)
    projects: list[dict[str, Any]] = []
    for alias in aliases:
        validate_alias(alias)
        project = config.projects.get(alias)
        if project is None:
            raise ValueError("project alias is not configured")
        token_ready = False
        try:
            assert_private(project.token_path, directory=False)
            token_ready = True
        except OverleafError:
            pass
        projects.append(
            {
                "alias": alias,
                "displayName": project.display_name,
                "tokenConfigured": token_ready,
                "tokenValueReported": False,
            }
        )
    _print_json(
        {
            "ok": True,
            "configPath": str(store.config_path),
            "projects": projects,
            "allowedImportRoots": [str(path) for path in config.allowed_import_roots],
        }
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="overleaf-config",
        description="Configure Overleaf Tools without putting tokens in shell history.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create the private configuration layout.")
    init.set_defaults(handler=_init)
    token = commands.add_parser("set-token", help="Prompt for and store one Git token.")
    token.add_argument("name")
    token.set_defaults(handler=_set_token)
    project = commands.add_parser("add-project", help="Add or update a project alias.")
    project.add_argument("alias")
    project.add_argument("project_id")
    project.add_argument("--token", required=True)
    project.add_argument("--display-name")
    project.set_defaults(handler=_add_project)
    remove_project = commands.add_parser(
        "remove-project",
        help="Remove one project alias while retaining tokens and private caches.",
    )
    remove_project.add_argument("alias")
    remove_project.set_defaults(handler=_remove_project)
    root = commands.add_parser("add-import-root", help="Allow imports from one local directory.")
    root.add_argument("path")
    root.set_defaults(handler=_add_import_root)
    status = commands.add_parser("status", help="Report configuration without token values.")
    status.add_argument("alias", nargs="?")
    status.set_defaults(handler=_status)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        store = ConfigStore()
        return int(args.handler(store, args))
    except (OverleafError, OSError, ValueError) as error:
        message = error.message if isinstance(error, OverleafError) else str(error)
        _print_json({"ok": False, "error": message})
        return 2


if __name__ == "__main__":
    sys.exit(main())
