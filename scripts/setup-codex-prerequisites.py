#!/usr/bin/env python3
"""Safe, testable prerequisites for the Codex toolbox setup script."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence


LEGACY_SKILLS = (
    "chronicle",
    "defuddle",
    "json-canvas",
    "obsidian-bases",
    "obsidian-cli",
    "obsidian-markdown",
    "playwright",
)
CHATGPT_CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
LEGACY_CODEX = Path("/Applications/Codex.app/Contents/Resources/codex")
DEFAULT_BREW_BINARIES = (Path("/opt/homebrew/bin/brew"), Path("/usr/local/bin/brew"))

Runner = Callable[..., subprocess.CompletedProcess[str]]
Which = Callable[[str, Optional[str]], Optional[str]]


def _run(
    args: Sequence[str],
    *,
    capture_output: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=capture_output, text=text, check=False)


def _which(name: str, path: str | None) -> str | None:
    return shutil.which(name, path=path)


def _normal_path(path: Path) -> Path:
    """Normalize spelling without dereferencing any part of the path."""

    return Path(os.path.abspath(os.path.normpath(os.fspath(path))))


def _symlink_destination(link: Path) -> Path:
    destination = Path(os.readlink(link))
    if not destination.is_absolute():
        destination = link.parent / destination
    return _normal_path(destination)


def legacy_skill_paths(env: Mapping[str, str]) -> tuple[Path, Path]:
    home = Path(env.get("HOME", str(Path.home())))
    codex_home = Path(env.get("CODEX_HOME", str(home / ".codex")))
    cc_switch_home = Path(env.get("CC_SWITCH_HOME", str(home / ".cc-switch")))
    return codex_home / "skills", cc_switch_home / "skills"


def migrate_legacy_skills(*, install: bool, env: Mapping[str, str]) -> int:
    codex_skills, cc_switch_skills = legacy_skill_paths(env)
    removable: list[Path] = []
    unexpected: list[str] = []

    # Validate every managed path before unlinking any of them. This prevents a
    # valid legacy link from being removed when another name is user-owned.
    for name in LEGACY_SKILLS:
        link = codex_skills / name
        expected = _normal_path(cc_switch_skills / name)
        if link.is_symlink():
            actual = _symlink_destination(link)
            if actual == expected:
                removable.append(link)
            else:
                unexpected.append(f"{link}: points to {actual}, expected {expected}")
        elif link.exists():
            unexpected.append(f"{link}: exists and is not a symbolic link")

    if unexpected:
        print("Refusing to modify legacy skills; unexpected paths found:", file=sys.stderr)
        for detail in unexpected:
            print(f"  - {detail}", file=sys.stderr)
        return 2

    if not install:
        if removable:
            print("Legacy user-level skill links still require migration:", file=sys.stderr)
            for link in removable:
                print(f"  - {link}", file=sys.stderr)
            return 1
        print("Legacy user-level skill links are clean")
        return 0

    # Revalidate as a group immediately before mutation to keep the operation
    # fail-closed if a path changed after the first scan.
    for link in removable:
        expected = _normal_path(cc_switch_skills / link.name)
        if not link.is_symlink() or _symlink_destination(link) != expected:
            print(f"Refusing to remove changed path: {link}", file=sys.stderr)
            return 2

    for link in removable:
        link.unlink()
        print(f"Removed duplicate user-level skill link: {link}")

    if not removable:
        print("Legacy user-level skill links already clean")
    return 0


def _works(executable: Path, runner: Runner) -> bool:
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return False
    try:
        result = runner([str(executable), "--version"], capture_output=True, text=True)
    except OSError:
        return False
    return result.returncode == 0


def local_bin_dir(env: Mapping[str, str]) -> Path:
    home = Path(env.get("HOME", str(Path.home())))
    return Path(env.get("CODEX_LOCAL_BIN_DIR", str(home / ".local" / "bin")))


def find_working_rg(
    *,
    env: Mapping[str, str],
    runner: Runner = _run,
    which: Which = _which,
) -> Path | None:
    path_candidate = which("rg", env.get("PATH"))
    if path_candidate:
        candidate = Path(path_candidate)
        if _works(candidate, runner):
            return candidate

    candidate = local_bin_dir(env) / "rg"
    if _works(candidate, runner):
        return candidate
    return None


def find_working_brew(
    *,
    env: Mapping[str, str],
    runner: Runner = _run,
    which: Which = _which,
) -> Path | None:
    candidates: list[Path] = []
    path_candidate = which("brew", env.get("PATH"))
    if path_candidate:
        candidates.append(Path(path_candidate))
    candidates.extend(DEFAULT_BREW_BINARIES)

    seen: set[Path] = set()
    for candidate in candidates:
        normalized = _normal_path(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if _works(candidate, runner):
            return candidate
    return None


def _brew_ripgrep_binary(brew: Path, runner: Runner) -> Path | None:
    result = runner([str(brew), "--prefix", "ripgrep"], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()) / "bin" / "rg"


def _expose_rg(source: Path, destination: Path, runner: Runner) -> bool:
    if destination == source:
        return _works(source, runner)
    if destination.is_symlink() or destination.exists():
        print(
            f"Refusing to replace existing non-working ripgrep path: {destination}",
            file=sys.stderr,
        )
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source)
    if not _works(destination, runner):
        destination.unlink(missing_ok=True)
        print(f"Exposed ripgrep failed verification: {destination}", file=sys.stderr)
        return False
    return True


def ensure_rg(
    *,
    install: bool,
    env: Mapping[str, str],
    runner: Runner = _run,
    which: Which = _which,
) -> int:
    existing = find_working_rg(env=env, runner=runner, which=which)
    if existing:
        print(f"Using ripgrep binary: {existing}")
        return 0
    if not install:
        print("No working ripgrep binary found", file=sys.stderr)
        return 1

    brew = find_working_brew(env=env, runner=runner, which=which)
    if not brew:
        print("No working Homebrew binary found; cannot install ripgrep", file=sys.stderr)
        return 1

    print(f"Installing ripgrep with Homebrew: {brew}")
    result = runner([str(brew), "install", "ripgrep"], capture_output=True, text=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout.rstrip(), file=sys.stderr)
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        print("Homebrew failed to install ripgrep", file=sys.stderr)
        return 1

    existing = find_working_rg(env=env, runner=runner, which=which)
    if existing:
        print(f"Using ripgrep binary: {existing}")
        return 0

    brewed_rg = _brew_ripgrep_binary(brew, runner)
    if not brewed_rg or not _works(brewed_rg, runner):
        print("Homebrew completed but no working ripgrep binary was found", file=sys.stderr)
        return 1

    destination = local_bin_dir(env) / "rg"
    if not _expose_rg(brewed_rg, destination, runner):
        return 1
    print(f"Exposed ripgrep through CODEX_LOCAL_BIN_DIR: {destination}")
    return 0


def resolve_codex(
    *,
    env: Mapping[str, str],
    runner: Runner = _run,
    which: Which = _which,
    chatgpt_codex: Path = CHATGPT_CODEX,
    legacy_codex: Path = LEGACY_CODEX,
) -> Path | None:
    path_candidate = which("codex", env.get("PATH"))
    if path_candidate:
        candidate = Path(path_candidate)
        if _works(candidate, runner):
            return candidate
    for candidate in (chatgpt_codex, legacy_codex):
        if _works(candidate, runner):
            return candidate
    return None


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("legacy-skills", "ensure-rg"):
        subparser = subparsers.add_parser(name)
        mode = subparser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--check", action="store_true")
        mode.add_argument("--install", action="store_true")

    subparsers.add_parser("resolve-codex")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.command == "legacy-skills":
        return migrate_legacy_skills(install=args.install, env=os.environ)
    if args.command == "ensure-rg":
        return ensure_rg(install=args.install, env=os.environ)
    if args.command == "resolve-codex":
        codex = resolve_codex(env=os.environ)
        if codex:
            print(codex)
            return 0
        return 1
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
