#!/usr/bin/env python3
"""Compile two pinned, unmodified LaTeXiT translation units; never launch apps."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import zipfile


SOURCE_URL = "https://pierre.chachatelier.fr/latexit/downloads/LaTeXiT-source-2_16_6.zip"
SOURCE_SHA256 = "056a3790ec3944b3848664bf6bfff7fb29d03ef10fffa3780382dec26ca82797"
SOURCE_ROOT = "LaTeXiT-mainline"
REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 20000
COMMAND_TIMEOUT = 60
XCRUN = "/usr/bin/xcrun"
LICENSE_PATHS = {
    "latexit": "LaTeXiT-mainline/Resources/documentation/Licence_CeCILL_V2-en.txt",
    "linkback": "LaTeXiT-mainline/Frameworks/LinkBack/LinkBack.framework/Versions/A/Headers/LinkBack.h",
}


class ProbeError(Exception):
    pass


def base_report():
    return {
        "status": "not_started",
        "compiler_only": True,
        "rendering_verified": False,
        "linkback_verified": False,
        "native_acceptance_passed": False,
        "partial_extraction": False,
        "source": {"url": SOURCE_URL, "sha256": SOURCE_SHA256, "version": "2.16.6"},
        "licenses": {
            **LICENSE_PATHS,
            "notice": "Upstream source and copyright notices are retained unmodified.",
        },
        "limitations": [
            "Object compilation does not establish successful linking or application execution.",
            "The upstream app needs bundled Latexit.mom compiled from its Core Data model; this probe does not build it.",
            "The standard application build requires Xcode tools, including momc and ibtool; their availability is not checked here.",
            "TeX dependencies, rendering, isolated application state, and live LinkBack callbacks remain unverified.",
        ],
        "compilations": [],
    }


def validate_output(output, archive):
    requested = Path(output).expanduser()
    if os.path.lexists(requested):
        raise ProbeError("Output must be a new, nonexistent directory.")
    resolved = requested.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise ProbeError("Output must be outside the toolbox repository.")
    if any(part.lower().endswith((".app", ".framework")) for part in resolved.parts):
        raise ProbeError("Output must not be inside an application or framework.")
    if resolved == archive or archive in resolved.parents:
        raise ProbeError("Output must not replace or be inside the source archive.")
    if not resolved.parent.is_dir():
        raise ProbeError("Output parent directory must already exist.")
    return resolved


def verify_archive(archive):
    if not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ProbeError("Source must be a bounded local ZIP file.")
    with archive.open("rb") as source:
        data = source.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ProbeError("Source exceeds the archive size limit.")
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ProbeError("Source SHA-256 does not match the pinned official archive.")
    return data


def archive_members(zipped):
    members = zipped.infolist()
    if len(members) > MAX_MEMBERS:
        raise ProbeError("Archive has too many entries.")
    total = 0
    seen = set()
    links = set()
    for entry in members:
        if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ProbeError("Archive uses a disallowed compression method.")
        name = entry.filename
        parts = PurePosixPath(name).parts
        kind = stat.S_IFMT(entry.external_attr >> 16)
        if (not parts or name.startswith("/") or "\\" in name or ":" in name
                or any(part in (".", "..") for part in name.rstrip("/").split("/"))
                or kind not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK)
                or entry.flag_bits & 1):
            raise ProbeError("Archive contains an unsafe path, link, or entry type.")
        key = name.rstrip("/").casefold()
        if key in seen:
            raise ProbeError("Archive contains duplicate or case-alias paths.")
        seen.add(key)
        if kind == stat.S_IFLNK:
            if entry.file_size > 4096:
                raise ProbeError("Archive link target is too long.")
            target = zipped.read(entry).decode("utf-8")
            if (not target or target.startswith("/") or "\\" in target or ":" in target
                    or "\x00" in target or any(part in ("", ".", "..") for part in target.split("/"))):
                raise ProbeError("Archive link target must stay within its containing directory.")
            links.add(key)
        total += entry.file_size
        if entry.file_size > MAX_MEMBER_BYTES or total > MAX_EXPANDED_BYTES:
            raise ProbeError("Archive exceeds the decompression limit.")
    for key in seen:
        if any(str(parent) in links for parent in PurePosixPath(key).parents):
            raise ProbeError("Archive entry would write through a symbolic link.")
    return members


def run_command(command, cwd, runner):
    environment = {key: os.environ[key] for key in
                   ("HOME", "TMPDIR", "DEVELOPER_DIR", "LANG", "LC_ALL") if key in os.environ}
    environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    try:
        result = runner(command, cwd=cwd, capture_output=True, text=True,
                        check=False, timeout=COMMAND_TIMEOUT, env=environment)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return None, "", "Command timed out; no application was launched."
    except OSError as error:
        return None, "", str(error)


def probe(source_zip, output_dir, runner=subprocess.run):
    report = base_report()
    output = None
    created = False
    try:
        archive = Path(source_zip).expanduser().resolve()
        output = validate_output(output_dir, archive)
        # Extract the exact bytes hashed, even if the archive path is replaced later.
        source_bytes = verify_archive(archive)
        with zipfile.ZipFile(io.BytesIO(source_bytes)) as zipped:
            members = archive_members(zipped)
            required = {f"{SOURCE_ROOT}/{name}" for name in ("LatexitEquation.m", "LaTeXProcessor.m", "LaTeXiT_Prefix.pch")}
            if not required.issubset({entry.filename for entry in members}):
                raise ProbeError("Pinned source entrypoints are absent.")
            if not set(LICENSE_PATHS.values()).issubset({entry.filename for entry in members}):
                raise ProbeError("Required upstream license records are absent.")
            output.mkdir(mode=0o700)
            created = True
            report["partial_extraction"] = True
            # Extract regular files first. Contained framework aliases are created last;
            # no archive entry may have a symbolic-link ancestor.
            for entry in members:
                target = output / "upstream" / entry.filename
                if stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK:
                    continue
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(entry) as src, target.open("xb") as dst:
                        copied = 0
                        while block := src.read(1024 * 1024):
                            copied += len(block)
                            if copied > entry.file_size:
                                raise ProbeError("Archive entry exceeded its declared size.")
                            dst.write(block)
            for entry in members:
                if stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK:
                    target = output / "upstream" / entry.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(zipped.read(entry).decode("utf-8"))
        report["partial_extraction"] = False
        source = output / "upstream" / SOURCE_ROOT
        code, sdk, error = run_command([XCRUN, "--show-sdk-path"], source, runner)
        sdk_path = Path(sdk.strip())
        if code != 0 or not sdk_path.is_absolute() or not sdk_path.is_dir():
            raise ProbeError("Cannot resolve a local macOS SDK with xcrun: " + error[:2000])
        report["sdk_path"] = str(sdk_path)
        for filename in ("LatexitEquation.m", "LaTeXProcessor.m"):
            object_path = output / (Path(filename).stem + ".o")
            command = [XCRUN, "clang", "-c", "-fobjc-exceptions", "-fobjc-weak",
                       "-isysroot", str(sdk_path), "-include", "LaTeXiT_Prefix.pch",
                       "-I.", "-ICommon", "-IFrameworks/RegexKitLite",
                       "-I" + str(sdk_path / "usr/include/libxml2"),
                       "-FFrameworks/LinkBack", "-FFrameworks/Sparkle/10_15+",
                       filename, "-o", str(object_path)]
            code, stdout, stderr = run_command(command, source, runner)
            log = output / (Path(filename).stem + ".log")
            log.write_text((stdout + stderr)[-1024 * 1024:], encoding="utf-8")
            success = code == 0 and object_path.is_file() and object_path.stat().st_size > 0
            report["compilations"].append({"source": filename, "exit_code": code,
                                            "compiled": success, "log": str(log)})
        report["status"] = ("compiled_translation_units" if all(item["compiled"] for item in report["compilations"])
                            else "compiler_failed")
    except (ProbeError, OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        report["status"] = "blocked"
        report["error"] = str(error)
    if created:
        report["output_dir"] = str(output)
        try:
            (output / "evidence.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        except OSError as error:
            report["status"] = "blocked"
            report["evidence_write_error"] = str(error)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    report = probe(args.source_zip, args.output_dir)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "compiled_translation_units" else 1


if __name__ == "__main__":
    raise SystemExit(main())
