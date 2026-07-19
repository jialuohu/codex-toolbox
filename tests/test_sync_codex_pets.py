#!/usr/bin/env python3
"""Behavioral tests for the repository-owned Codex pet synchronizer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync-codex-pets.py"
WIDTH = 1536
HEIGHT = 2288


def riff(*chunks: tuple[bytes, bytes]) -> bytes:
    body = b"WEBP" + b"".join(
        kind + struct.pack("<I", len(data)) + data + (b"\0" if len(data) % 2 else b"")
        for kind, data in chunks
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def webp_payload(
    kind: bytes,
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
    substantive: bool = True,
    flags: int = 0,
    reserved: bytes = b"\0\0\0",
) -> bytes:
    if kind == b"VP8X":
        return bytes((flags,)) + reserved + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    if kind == b"VP8 ":
        header = b"\0\0\0\x9d\x01\x2a" + struct.pack("<HH", width, height)
        return header + (b"\x01" if substantive else b"")
    if kind == b"VP8L":
        bits = (width - 1) | ((height - 1) << 14)
        header = b"\x2f" + bits.to_bytes(4, "little")
        return header + (b"\x01" if substantive else b"")
    raise ValueError(kind)


def webp(kind: bytes = b"VP8L", *, width: int = WIDTH, height: int = HEIGHT, extra: tuple[bytes, bytes] | None = None) -> bytes:
    chunks = [(kind, webp_payload(kind, width=width, height=height))]
    if extra:
        chunks.append(extra)
    return riff(*chunks)


def extended_webp(
    kind: bytes,
    *,
    canvas_width: int = WIDTH,
    canvas_height: int = HEIGHT,
    payload_width: int = WIDTH,
    payload_height: int = HEIGHT,
    flags: int = 0,
    reserved: bytes = b"\0\0\0",
) -> bytes:
    return riff(
        (b"VP8X", webp_payload(b"VP8X", width=canvas_width, height=canvas_height, flags=flags, reserved=reserved)),
        (kind, webp_payload(kind, width=payload_width, height=payload_height)),
    )


class SyncCodexPetsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name) / "toolbox"
        self.source = self.root / "config" / "codex" / "pets"
        self.codex_home = Path(self.tempdir.name) / "codex-home"
        self.source.mkdir(parents=True)
        self.codex_home.mkdir()
        self.env = os.environ.copy()
        self.env.update({"CODEX_TOOLBOX_ROOT": str(self.root), "CODEX_HOME": str(self.codex_home)})

    def manifest(self, **changes: object) -> dict:
        data = {
            "id": "otter",
            "displayName": "Otter",
            "description": "A friendly test pet.",
            "spriteVersionNumber": 2,
            "spritesheetPath": "spritesheet.webp",
        }
        data.update(changes)
        return data

    def write_pet(
        self,
        slug: str = "otter",
        *,
        manifest: dict | None = None,
        image: bytes | None = None,
    ) -> Path:
        pet = self.source / slug
        pet.mkdir()
        data = manifest if manifest is not None else self.manifest(id=slug)
        (pet / "pet.json").write_text(json.dumps(data), encoding="utf-8")
        (pet / "spritesheet.webp").write_bytes(image or webp())
        return pet

    def run_script(self, mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), mode],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def assert_invalid(self, expected: str = "invalid", **kwargs: object) -> None:
        self.write_pet(**kwargs)
        result = self.run_script("--install")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(expected.lower(), (result.stdout + result.stderr).lower())

    def test_check_accepts_simple_vp8_and_vp8l_with_substantive_payloads(self) -> None:
        for index, kind in enumerate((b"VP8 ", b"VP8L")):
            self.write_pet(f"pet{index}", image=webp(kind))
        self.assertEqual(self.run_script("--install").returncode, 0)
        result = self.run_script("--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_accepts_extended_vp8x_plus_vp8(self) -> None:
        self.write_pet(image=extended_webp(b"VP8 "))
        install_result = self.run_script("--install")
        self.assertEqual(install_result.returncode, 0, install_result.stdout + install_result.stderr)
        check_result = self.run_script("--check")
        self.assertEqual(check_result.returncode, 0, check_result.stdout + check_result.stderr)

    def test_check_accepts_extended_vp8x_plus_vp8l(self) -> None:
        self.write_pet(image=extended_webp(b"VP8L"))
        install_result = self.run_script("--install")
        self.assertEqual(install_result.returncode, 0, install_result.stdout + install_result.stderr)
        check_result = self.run_script("--check")
        self.assertEqual(check_result.returncode, 0, check_result.stdout + check_result.stderr)

    def test_check_rejects_missing_manifest(self) -> None:
        pet = self.write_pet()
        (pet / "pet.json").unlink()
        result = self.run_script("--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("pet.json", result.stdout + result.stderr)

    def test_check_rejects_invalid_manifest_json(self) -> None:
        pet = self.write_pet()
        (pet / "pet.json").write_text("not json", encoding="utf-8")
        result = self.run_script("--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("invalid", (result.stdout + result.stderr).lower())

    def test_check_rejects_manifest_id_mismatch_independently(self) -> None:
        self.assert_invalid("manifest id", manifest=self.manifest(id="wrong"))

    def test_check_rejects_non_lowercase_slug_independently(self) -> None:
        self.assert_invalid("lowercase slug", slug="Otter", manifest=self.manifest(id="Otter"))

    def test_check_rejects_empty_display_name_independently(self) -> None:
        self.assert_invalid("displayname", manifest=self.manifest(displayName=""))

    def test_check_rejects_empty_description_independently(self) -> None:
        self.assert_invalid("description", manifest=self.manifest(description="   "))

    def test_check_rejects_sprite_version_independently(self) -> None:
        self.assert_invalid("spriteversionnumber", manifest=self.manifest(spriteVersionNumber=2.0))

    def test_check_rejects_sprite_path_independently(self) -> None:
        self.assert_invalid("spritesheetpath", manifest=self.manifest(spritesheetPath="../spritesheet.webp"))

    def test_check_rejects_unexpected_files_and_symlinks(self) -> None:
        pet = self.write_pet()
        (pet / "extra.txt").write_text("no", encoding="utf-8")
        self.assertEqual(self.run_script("--check").returncode, 1)
        (pet / "extra.txt").unlink()
        (pet / "spritesheet.webp").unlink()
        os.symlink("../nowhere", pet / "spritesheet.webp")
        self.assertEqual(self.run_script("--check").returncode, 1)

    def test_check_rejects_wrong_dimensions(self) -> None:
        self.assert_invalid(image=webp(width=1, height=HEIGHT))

    def test_check_rejects_lone_vp8x_canvas_header(self) -> None:
        image = riff((b"VP8X", webp_payload(b"VP8X")))
        self.assert_invalid(image=image)

    def test_check_rejects_later_webp_header_masking_wrong_canvas(self) -> None:
        image = extended_webp(b"VP8 ", canvas_width=1)
        self.assert_invalid(image=image)

    def test_check_rejects_header_only_and_truncated_image_payloads(self) -> None:
        cases = (
            (b"VP8 ", webp_payload(b"VP8 ", substantive=False)),
            (b"VP8 ", webp_payload(b"VP8 ", substantive=False)[:-1]),
            (b"VP8L", webp_payload(b"VP8L", substantive=False)),
            (b"VP8L", webp_payload(b"VP8L", substantive=False)[:-1]),
        )
        for index, (kind, payload) in enumerate(cases):
            with self.subTest(kind=kind, length=len(payload)):
                if index:
                    shutil.rmtree(self.source)
                    self.source.mkdir()
                self.assert_invalid(image=riff((kind, payload)))

    def test_check_rejects_extended_canvas_payload_dimension_mismatch(self) -> None:
        self.assert_invalid(image=extended_webp(b"VP8L", payload_width=WIDTH - 1))

    def test_check_rejects_duplicate_vp8x_headers(self) -> None:
        image = riff(
            (b"VP8X", webp_payload(b"VP8X")),
            (b"VP8X", webp_payload(b"VP8X")),
            (b"VP8L", webp_payload(b"VP8L")),
        )
        self.assert_invalid(image=image)

    def test_check_rejects_duplicate_image_payloads(self) -> None:
        image = riff(
            (b"VP8 ", webp_payload(b"VP8 ")),
            (b"VP8L", webp_payload(b"VP8L")),
        )
        self.assert_invalid(image=image)

    def test_check_rejects_vp8x_when_not_first_chunk(self) -> None:
        image = riff(
            (b"JUNK", b"safe"),
            (b"VP8X", webp_payload(b"VP8X")),
            (b"VP8L", webp_payload(b"VP8L")),
        )
        self.assert_invalid(image=image)

    def test_check_rejects_animated_vp8x_and_animation_chunks(self) -> None:
        animated = riff(
            (b"VP8X", webp_payload(b"VP8X", flags=0x02)),
            (b"ANIM", b"\0" * 6),
            (b"ANMF", b"\0" * 16),
        )
        self.assert_invalid(image=animated)
        shutil.rmtree(self.source)
        self.source.mkdir()
        chunks_without_flag = riff(
            (b"VP8X", webp_payload(b"VP8X")),
            (b"ANIM", b"\0" * 6),
            (b"VP8L", webp_payload(b"VP8L")),
        )
        self.assert_invalid(image=chunks_without_flag)

    def test_check_rejects_vp8x_reserved_flag_bits_and_bytes(self) -> None:
        cases = (
            extended_webp(b"VP8L", flags=0x01),
            extended_webp(b"VP8L", flags=0x40),
            extended_webp(b"VP8L", reserved=b"\x01\0\0"),
        )
        for index, image in enumerate(cases):
            with self.subTest(index=index):
                if index:
                    shutil.rmtree(self.source)
                    self.source.mkdir()
                self.assert_invalid(image=image)

    def test_check_rejects_nonzero_riff_padding(self) -> None:
        image = bytearray(webp(b"VP8 "))
        self.assertEqual(image[-1], 0)
        image[-1] = 1
        self.assert_invalid(image=bytes(image))

    def test_check_rejects_exif_and_xmp_chunks(self) -> None:
        for extra in ((b"EXIF", b"x"), (b"XMP ", b"x")):
            with self.subTest(extra=extra[0]):
                shutil.rmtree(self.source)
                self.source.mkdir()
                self.assert_invalid(image=webp(extra=extra))

    def test_check_rejects_exif_and_xmp_vp8x_feature_flags(self) -> None:
        for index, flag in enumerate((0x08, 0x04)):
            with self.subTest(flag=flag):
                if index:
                    shutil.rmtree(self.source)
                    self.source.mkdir()
                self.assert_invalid(image=extended_webp(b"VP8L", flags=flag))

    def test_install_creates_exact_pet_and_hash_marker_without_mutating_avatar_config(self) -> None:
        self.write_pet()
        config = self.codex_home / "config.toml"
        config.write_text("[avatars]\ncurrent = 'unchanged'\n", encoding="utf-8")
        before = config.read_bytes()
        result = self.run_script("--install")
        target = self.codex_home / "pets" / "otter"
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(path.name for path in target.iterdir()), ["pet.json", "spritesheet.webp"])
        self.assertEqual(config.read_bytes(), before)
        marker = json.loads((self.codex_home / ".codex-toolbox" / "pets-sync.json").read_text())
        self.assertEqual(marker["pets"]["otter"]["files"].keys(), {"pet.json", "spritesheet.webp"})
        self.assertEqual((target / "pet.json").stat().st_mode & 0o777, 0o644)

    def test_install_is_idempotent_and_exact_target_is_a_noop(self) -> None:
        self.write_pet()
        self.assertEqual(self.run_script("--install").returncode, 0)
        target = self.codex_home / "pets" / "otter"
        original_mtime = target.stat().st_mtime_ns
        result = self.run_script("--install")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(target.stat().st_mtime_ns, original_mtime)
        self.assertFalse((self.codex_home / ".codex-toolbox" / "backups" / "pets").exists())

    def test_check_detects_and_install_repairs_file_mode_drift_without_backup(self) -> None:
        self.write_pet()
        self.assertEqual(self.run_script("--install").returncode, 0)
        target = self.codex_home / "pets" / "otter"
        for name in ("pet.json", "spritesheet.webp"):
            with self.subTest(name=name):
                os.chmod(target / name, 0o600)
                check_result = self.run_script("--check")
                self.assertEqual(check_result.returncode, 1, check_result.stdout + check_result.stderr)
                install_result = self.run_script("--install")
                self.assertEqual(install_result.returncode, 0, install_result.stdout + install_result.stderr)
                self.assertEqual((target / name).stat().st_mode & 0o777, 0o644)
                self.assertFalse((self.codex_home / ".codex-toolbox" / "backups" / "pets").exists())

    def test_check_detects_and_install_repairs_marker_mode_drift_without_backup(self) -> None:
        self.write_pet()
        self.assertEqual(self.run_script("--install").returncode, 0)
        marker = self.codex_home / ".codex-toolbox" / "pets-sync.json"
        os.chmod(marker, 0o600)
        check_result = self.run_script("--check")
        self.assertEqual(check_result.returncode, 1, check_result.stdout + check_result.stderr)
        install_result = self.run_script("--install")
        self.assertEqual(install_result.returncode, 0, install_result.stdout + install_result.stderr)
        self.assertEqual(marker.stat().st_mode & 0o777, 0o644)
        self.assertFalse((self.codex_home / ".codex-toolbox" / "backups" / "pets").exists())

    def test_check_detects_installed_drift(self) -> None:
        self.write_pet()
        self.assertEqual(self.run_script("--install").returncode, 0)
        (self.codex_home / "pets" / "otter" / "pet.json").write_text("{}", encoding="utf-8")
        result = self.run_script("--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("drift", (result.stdout + result.stderr).lower())

    def test_install_backs_up_conflicting_same_id_and_preserves_unrelated_pets(self) -> None:
        self.write_pet()
        target_root = self.codex_home / "pets"
        (target_root / "otter").mkdir(parents=True)
        (target_root / "otter" / "old.txt").write_text("old", encoding="utf-8")
        (target_root / "cat").mkdir()
        (target_root / "cat" / "keep.txt").write_text("keep", encoding="utf-8")
        result = self.run_script("--install")
        backups = list((self.codex_home / ".codex-toolbox" / "backups" / "pets").iterdir())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((target_root / "cat" / "keep.txt").read_text(), "keep")
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "old.txt").read_text(), "old")
        self.assertFalse((self.codex_home / ".codex-toolbox" / "staging" / "pets").exists())

    def test_install_rejects_pets_root_symlink_without_writing_outside(self) -> None:
        self.write_pet()
        outside = Path(self.tempdir.name) / "outside-pets"
        outside.mkdir()
        os.symlink(outside, self.codex_home / "pets")
        result = self.run_script("--install")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("symlink", (result.stdout + result.stderr).lower())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.codex_home / ".codex-toolbox").exists())

    def test_install_rejects_dangling_pets_root_symlink_without_creating_target(self) -> None:
        self.write_pet()
        outside = Path(self.tempdir.name) / "missing-outside-pets"
        os.symlink(outside, self.codex_home / "pets")
        result = self.run_script("--install")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("symlink", (result.stdout + result.stderr).lower())
        self.assertFalse(outside.exists())
        self.assertFalse((self.codex_home / ".codex-toolbox").exists())

    def test_install_rejects_managed_root_symlink_before_any_write(self) -> None:
        self.write_pet()
        outside = Path(self.tempdir.name) / "outside-managed"
        outside.mkdir()
        os.symlink(outside, self.codex_home / ".codex-toolbox")
        result = self.run_script("--install")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("symlink", (result.stdout + result.stderr).lower())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.codex_home / "pets").exists())

    def test_install_rejects_staging_root_symlink_before_any_write(self) -> None:
        self.write_pet()
        outside = Path(self.tempdir.name) / "outside-staging"
        outside.mkdir()
        staging_parent = self.codex_home / ".codex-toolbox" / "staging"
        staging_parent.mkdir(parents=True)
        os.symlink(outside, staging_parent / "pets")
        result = self.run_script("--install")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("symlink", (result.stdout + result.stderr).lower())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.codex_home / "pets").exists())

    def test_install_rejects_backup_root_symlink_before_replacing_conflict(self) -> None:
        self.write_pet()
        target = self.codex_home / "pets" / "otter"
        target.mkdir(parents=True)
        (target / "old.txt").write_text("old", encoding="utf-8")
        outside = Path(self.tempdir.name) / "outside-backups"
        outside.mkdir()
        backup_parent = self.codex_home / ".codex-toolbox" / "backups"
        backup_parent.mkdir(parents=True)
        os.symlink(outside, backup_parent / "pets")
        result = self.run_script("--install")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("symlink", (result.stdout + result.stderr).lower())
        self.assertEqual((target / "old.txt").read_text(), "old")
        self.assertEqual(list(outside.iterdir()), [])

    def test_check_rejects_dangling_source_root_symlink(self) -> None:
        self.source.rmdir()
        os.symlink(self.root / "missing-pets", self.source)
        result = self.run_script("--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("symlink", (result.stdout + result.stderr).lower())


if __name__ == "__main__":
    unittest.main()
