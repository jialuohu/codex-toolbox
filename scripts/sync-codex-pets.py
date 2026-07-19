#!/usr/bin/env python3
"""Validate and install repository-owned Codex pet bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import tempfile
from datetime import datetime, timezone
from typing import Dict, Iterable, Tuple


SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXPECTED_FILES = frozenset(("pet.json", "spritesheet.webp"))
WIDTH = 1536
HEIGHT = 2288


class PetError(ValueError):
    """A pet bundle is malformed or differs from its installed copy."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_webp_dimensions(path: Path) -> Tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise PetError("not a RIFF WebP")
    if struct.unpack_from("<I", data, 4)[0] + 8 != len(data):
        raise PetError("WebP RIFF length is invalid")

    offset = 12
    canvas_dimensions = None
    image_dimensions = None
    while offset < len(data):
        if offset + 8 > len(data):
            raise PetError("truncated WebP chunk")
        chunk_type = data[offset : offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        start = offset + 8
        end = start + size
        if end > len(data):
            raise PetError("truncated WebP chunk payload")
        chunk = data[start:end]
        if chunk_type in (b"EXIF", b"XMP "):
            raise PetError("WebP must not contain EXIF or XMP metadata")
        if chunk_type in (b"ANIM", b"ANMF"):
            raise PetError("animated WebP is not allowed for a pet atlas")
        if chunk_type == b"VP8X":
            if offset != 12:
                raise PetError("VP8X must be the first WebP chunk")
            if canvas_dimensions is not None:
                raise PetError("WebP must not contain duplicate VP8X chunks")
            if len(chunk) != 10:
                raise PetError("invalid VP8X header")
            if chunk[0] & 0xC1:
                raise PetError("VP8X reserved flag bits must be zero")
            if chunk[1:4] != b"\0\0\0":
                raise PetError("VP8X reserved bytes must be zero")
            if chunk[0] & 0x02:
                raise PetError("animated WebP is not allowed for a pet atlas")
            if chunk[0] & 0x0C:
                raise PetError("WebP must not advertise EXIF or XMP metadata")
            canvas_dimensions = (
                int.from_bytes(chunk[4:7], "little") + 1,
                int.from_bytes(chunk[7:10], "little") + 1,
            )
        elif chunk_type == b"VP8 ":
            if image_dimensions is not None:
                raise PetError("WebP must contain exactly one image payload")
            if len(chunk) <= 10 or chunk[3:6] != b"\x9d\x01\x2a":
                raise PetError("invalid VP8 header")
            image_dimensions = (
                struct.unpack_from("<H", chunk, 6)[0] & 0x3FFF,
                struct.unpack_from("<H", chunk, 8)[0] & 0x3FFF,
            )
        elif chunk_type == b"VP8L":
            if image_dimensions is not None:
                raise PetError("WebP must contain exactly one image payload")
            if len(chunk) <= 5 or chunk[0] != 0x2F:
                raise PetError("invalid VP8L header")
            bits = int.from_bytes(chunk[1:5], "little")
            if bits >> 29:
                raise PetError("invalid VP8L version")
            image_dimensions = ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        padded_end = end + (size % 2)
        if padded_end > len(data):
            raise PetError("truncated WebP chunk padding")
        if size % 2 and data[end] != 0:
            raise PetError("WebP chunk padding must be zero")
        offset = padded_end

    if offset != len(data) or image_dimensions is None:
        raise PetError("WebP has no substantive VP8 or VP8L image payload")
    if canvas_dimensions is not None and canvas_dimensions != image_dimensions:
        raise PetError("VP8X canvas dimensions do not match the image payload")
    return canvas_dimensions or image_dimensions


def ensure_regular(path: Path, name: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise PetError("%s must be a regular non-symlink file" % name)


def validate_pet(pet_dir: Path) -> Dict[str, str]:
    if pet_dir.is_symlink() or not pet_dir.is_dir():
        raise PetError("pet directory must be a real directory")
    slug = pet_dir.name
    if not SLUG.fullmatch(slug):
        raise PetError("pet directory %r is not a lowercase slug" % slug)
    entries = {entry.name for entry in pet_dir.iterdir()}
    if entries != EXPECTED_FILES:
        raise PetError("%s must contain exactly pet.json and spritesheet.webp" % slug)

    manifest_path = pet_dir / "pet.json"
    sprite_path = pet_dir / "spritesheet.webp"
    ensure_regular(manifest_path, "pet.json")
    ensure_regular(sprite_path, "spritesheet.webp")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PetError("pet.json is not valid JSON: %s" % error) from error
    if not isinstance(manifest, dict):
        raise PetError("pet.json must be a JSON object")
    if manifest.get("id") != slug or not isinstance(manifest.get("id"), str):
        raise PetError("manifest id must exactly match its directory")
    for key in ("displayName", "description"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise PetError("%s must be a nonempty string" % key)
    if type(manifest.get("spriteVersionNumber")) is not int or manifest["spriteVersionNumber"] != 2:
        raise PetError("spriteVersionNumber must be 2")
    if manifest.get("spritesheetPath") != "spritesheet.webp":
        raise PetError("spritesheetPath must be exactly spritesheet.webp")
    dimensions = read_webp_dimensions(sprite_path)
    if dimensions != (WIDTH, HEIGHT):
        raise PetError("spritesheet dimensions must be 1536x2288, got %dx%d" % dimensions)
    return {"pet.json": sha256(manifest_path), "spritesheet.webp": sha256(sprite_path)}


def discover(source_root: Path) -> Dict[str, Tuple[Path, Dict[str, str]]]:
    if source_root.is_symlink():
        raise PetError("pet source root must not be a symlink")
    if source_root.exists() and not source_root.is_dir():
        raise PetError("pet source root must be a real directory")
    if not source_root.exists():
        return {}
    pets: Dict[str, Tuple[Path, Dict[str, str]]] = {}
    for entry in sorted(source_root.iterdir(), key=lambda path: path.name):
        try:
            pets[entry.name] = (entry, validate_pet(entry))
        except PetError as error:
            raise PetError("invalid source pet %s: %s" % (entry.name, error)) from error
    return pets


def has_mode(path: Path, expected: int = 0o644) -> bool:
    try:
        return stat.S_IMODE(os.lstat(path).st_mode) == expected
    except OSError:
        return False


def target_content_matches(target: Path, expected: Dict[str, str]) -> bool:
    try:
        if target.is_symlink() or not target.is_dir() or {item.name for item in target.iterdir()} != EXPECTED_FILES:
            return False
        return all(
            not (target / name).is_symlink()
            and (target / name).is_file()
            and sha256(target / name) == digest
            for name, digest in expected.items()
        )
    except OSError:
        return False


def target_matches(target: Path, expected: Dict[str, str]) -> bool:
    return target_content_matches(target, expected) and all(has_mode(target / name) for name in EXPECTED_FILES)


def marker_payload(pets: Dict[str, Tuple[Path, Dict[str, str]]]) -> Dict[str, object]:
    return {
        "version": 1,
        "pets": {slug: {"files": hashes} for slug, (_, hashes) in pets.items()},
    }


def marker_bytes(payload: Dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def marker_matches(path: Path, payload: Dict[str, object]) -> bool:
    try:
        return not path.is_symlink() and path.is_file() and path.read_bytes() == marker_bytes(payload) and has_mode(path)
    except OSError:
        return False


def ensure_safe_directory(path: Path, label: str) -> None:
    if path.is_symlink():
        raise PetError("%s must not be a symlink" % label)
    if path.exists() and not path.is_dir():
        raise PetError("%s must be a directory" % label)


def ensure_safe_file(path: Path, label: str) -> None:
    if path.is_symlink():
        raise PetError("%s must not be a symlink" % label)
    if path.exists() and not path.is_file():
        raise PetError("%s must be a regular file" % label)


def validate_destination_base(codex_home: Path) -> None:
    ensure_safe_directory(codex_home, "CODEX_HOME")
    ensure_safe_directory(codex_home / "pets", "CODEX_HOME/pets")
    managed = codex_home / ".codex-toolbox"
    ensure_safe_directory(managed, "managed root")
    ensure_safe_file(managed / "pets-sync.json", "pet sync marker")


def validate_staging_roots(managed: Path) -> None:
    ensure_safe_directory(managed / "staging", "staging parent")
    ensure_safe_directory(managed / "staging" / "pets", "pet staging root")


def validate_backup_roots(managed: Path) -> None:
    ensure_safe_directory(managed / "backups", "backup parent")
    ensure_safe_directory(managed / "backups" / "pets", "pet backup root")


def write_marker(path: Path, payload: Dict[str, object]) -> None:
    ensure_safe_file(path, "pet sync marker")
    encoded = marker_bytes(payload)
    if path.is_file() and not path.is_symlink() and path.read_bytes() == encoded:
        if not has_mode(path):
            os.chmod(path, 0o644)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-%d" % os.getpid())
    try:
        temporary.write_bytes(encoded)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def copy_bundle(source: Path, staging: Path) -> None:
    staging.mkdir()
    for name in sorted(EXPECTED_FILES):
        destination = staging / name
        shutil.copyfile(source / name, destination)
        os.chmod(destination, 0o644)


def install(pets: Dict[str, Tuple[Path, Dict[str, str]]], codex_home: Path) -> None:
    targets = codex_home / "pets"
    managed = codex_home / ".codex-toolbox"
    validate_destination_base(codex_home)
    changed = {slug: bundle for slug, bundle in pets.items() if not target_content_matches(targets / slug, bundle[1])}
    mode_repairs = {
        slug: bundle
        for slug, bundle in pets.items()
        if slug not in changed and not target_matches(targets / slug, bundle[1])
    }
    conflicts = {
        slug
        for slug in changed
        if (targets / slug).exists() or (targets / slug).is_symlink()
    }
    if changed:
        validate_staging_roots(managed)
    if conflicts:
        validate_backup_roots(managed)

    if changed or mode_repairs or not marker_matches(managed / "pets-sync.json", marker_payload(pets)):
        codex_home.mkdir(parents=True, exist_ok=True)
    for slug in mode_repairs:
        for name in EXPECTED_FILES:
            os.chmod(targets / slug / name, 0o644)

    if changed:
        targets.mkdir(parents=True, exist_ok=True)
        staging_root = managed / "staging" / "pets"
        staging_root.mkdir(parents=True, exist_ok=True)
        run_staging = Path(tempfile.mkdtemp(prefix="sync-", dir=str(staging_root)))
        try:
            for slug, (source, _) in changed.items():
                staged = run_staging / slug
                copy_bundle(source, staged)
                target = targets / slug
                if target.exists() or target.is_symlink():
                    backup_root = managed / "backups" / "pets"
                    backup_root.mkdir(parents=True, exist_ok=True)
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                    backup = backup_root / (slug + "-" + stamp)
                    os.replace(target, backup)
                os.replace(staged, target)
        finally:
            if run_staging.exists():
                shutil.rmtree(run_staging)
            if staging_root.exists():
                try:
                    staging_root.rmdir()
                except OSError:
                    pass
            staging_parent = staging_root.parent
            if staging_parent.exists():
                try:
                    staging_parent.rmdir()
                except OSError:
                    pass
    write_marker(managed / "pets-sync.json", marker_payload(pets))


def check(pets: Dict[str, Tuple[Path, Dict[str, str]]], codex_home: Path) -> None:
    validate_destination_base(codex_home)
    drift = [slug for slug, (_, hashes) in pets.items() if not target_matches(codex_home / "pets" / slug, hashes)]
    if not marker_matches(codex_home / ".codex-toolbox" / "pets-sync.json", marker_payload(pets)):
        drift.append("sync marker")
    if drift:
        raise PetError("installed pet drift: " + ", ".join(drift))


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="validate sources and installed parity")
    group.add_argument("--install", action="store_true", help="validate then atomically install source pets")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    root = Path(os.environ.get("CODEX_TOOLBOX_ROOT", Path(__file__).resolve().parents[1])).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    try:
        pets = discover(root / "config" / "codex" / "pets")
        if args.check:
            check(pets, codex_home)
            print("Codex pets: ready")
        else:
            install(pets, codex_home)
            print("Codex pets: installed")
    except (OSError, PetError) as error:
        print("Codex pets: invalid: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
