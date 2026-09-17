#!/usr/bin/env python3
"""Report native prototype prerequisites; this never certifies LinkBack support.

No installation, configuration edits, document writes, or network requests.
Only --probe-app sends non-mutating AppleEvents (which can launch OmniGraffle).
One probe evaluates the fixed JavaScript expression 1+1; no user code is sent.
Reports go to stdout, so this helper cannot overwrite an input document.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
from typing import Any
from xml.parsers.expat import ExpatError


APP_ID = "com.omnigroup.OmniGraffle7"
LATEXIT_APP_ID = "fr.chachatelier.pierre.LaTeXiT"
ISOLATED_LINKBACK_SERVICE = "io.github.jialuohu.codex-toolbox.latexit-automation:LaTeXiTToolboxAutomation"
STOCK_LINKBACK_SERVICE = "fr.chachatelier.pierre.LaTeXiT:LaTeXiT"
PROBE_SCRIPT = Path(__file__).with_name("probe.applescript")
PROBES = ("version", "documents", "professional", "javascript")
# AppKit process inventory only: this does not send an AppleEvent to OmniGraffle.
PROCESS_SCRIPT = """ObjC.import('AppKit');
const apps = $.NSRunningApplication.runningApplicationsWithBundleIdentifier('com.omnigroup.OmniGraffle7');
const result = [];
for (let i = 0; i < apps.count; i++) {
  const app = apps.objectAtIndex(i);
  result.push({pid: Number(app.processIdentifier),
    path: ObjC.unwrap(app.bundleURL.path), bundle_id: ObjC.unwrap(app.bundleIdentifier)});
}
JSON.stringify(result);"""


def run_command(args: list[str], timeout: int = 8, output_limit: int = 2000) -> dict[str, Any]:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "exit_code": None, "output": "", "error": "Command exceeded the configured timeout."}
    except OSError as error:
        return {"status": "unavailable", "exit_code": None, "output": "", "error": str(error)}
    output = result.stdout.strip()
    error = result.stderr.strip()
    status = "ok" if result.returncode == 0 else "error"
    if result.returncode and "(-1712)" in error:
        status = "timeout"
    if result.returncode and "(-1743)" in error:
        status = "permission_denied"
    return {
        "status": status, "exit_code": result.returncode,
        "output": output[:output_limit], "error": error[:2000],
    }


def linkback_sandbox(app: Path, service: str = ISOLATED_LINKBACK_SERVICE) -> dict[str, Any]:
    """Read signed entitlements, without launching or modifying the application.

    An absent exception is a feasibility gate, not a universal assessment of
    sandbox policy. Even a listed exception cannot certify a live callback.
    """
    if service not in (ISOLATED_LINKBACK_SERVICE, STOCK_LINKBACK_SERVICE):
        raise ValueError("Unknown LinkBack service")
    check = run_command(
        ["/usr/bin/codesign", "-d", "--entitlements", "-", "--xml", str(app.resolve())],
        output_limit=65536,
    )
    report = {"status": "unknown", "service": service,
              "live_linkback_verified": False}
    if check["status"] != "ok":
        return {**report, "reason": "entitlements_unavailable"}
    try:
        data = plistlib.loads(check.get("output", "").encode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Entitlements must be a dictionary")
        sandboxed = data.get("com.apple.security.app-sandbox", False)
        names = data.get("com.apple.security.temporary-exception.mach-lookup.global-name", [])
        if type(sandboxed) is not bool or not isinstance(names, list) or any(not isinstance(n, str) for n in names):
            raise ValueError("Unexpected sandbox entitlement types")
    except (ValueError, plistlib.InvalidFileException, ExpatError):
        return {**report, "reason": "entitlements_invalid_or_truncated"}
    present = service in names
    return {
        **report,
        "status": ("sandbox_not_enabled" if not sandboxed else
                   "exception_present" if present else
                   "isolated_service_not_listed" if service == ISOLATED_LINKBACK_SERVICE else "stock_service_not_listed"),
        "sandbox_enabled": sandboxed,
        "selected_service_exception": present,
        "isolated_service_exception": ISOLATED_LINKBACK_SERVICE in names,
        "stock_latexit_service_exception": STOCK_LINKBACK_SERVICE in names,
        "note": "Static entitlement inspection only. Other sandbox mechanisms and callback behavior are not verified.",
    }


def app_info(path: Path, expected_id: str = APP_ID) -> dict[str, Any]:
    try:
        path = path.expanduser().resolve()
        with (path / "Contents" / "Info.plist").open("rb") as handle:
            data = plistlib.load(handle)
        if not isinstance(data, dict):
            raise ValueError("Application Info.plist must be a dictionary")
        if data.get("CFBundleIdentifier") != expected_id:
            raise ValueError("Unexpected application bundle identifier")
    except (OSError, ValueError, plistlib.InvalidFileException, ExpatError) as error:
        return {"status": "unavailable", "error": str(error)}
    return {
        "status": "present", "path": str(path.resolve()),
        "bundle_id": expected_id, "version": data.get("CFBundleShortVersionString"),
        "note": "Bundle metadata is not proof of scripting access or a valid license.",
    }


def running_instances(timeout: int) -> dict[str, Any]:
    check = run_command(["/usr/bin/osascript", "-l", "JavaScript", "-e", PROCESS_SCRIPT], timeout=timeout + 3)
    if check["status"] != "ok":
        return {"status": "unavailable", "instances": [], "check": check}
    try:
        data = json.loads(check.get("output", ""))
        if not isinstance(data, list):
            raise ValueError("Process inventory must be an array")
        instances = []
        pids = set()
        for item in data:
            if (not isinstance(item, dict) or type(item.get("pid")) is not int
                    or item["pid"] <= 0 or item["pid"] in pids
                    or item.get("bundle_id") != APP_ID
                    or not isinstance(item.get("path"), str) or not item["path"]
                    or not Path(item["path"]).is_absolute()):
                raise ValueError("Invalid or duplicate process identity")
            pids.add(item["pid"])
            instances.append({"pid": item["pid"], "path": str(Path(item["path"]).resolve()), "bundle_id": APP_ID})
        return {"status": "ok", "instances": instances}
    except (ValueError, OSError, RuntimeError) as error:
        return {"status": "invalid_response", "instances": [], "error": str(error)}


def probe_app(timeout: int, app: Path) -> dict[str, Any]:
    if not 1 <= timeout <= 30:
        raise ValueError("Probe timeout must be between 1 and 30 seconds")
    checks: dict[str, Any] = {}
    process_checks = []
    selected_path = str(app.resolve())
    selected_pid = None
    for probe in PROBES:
        inventory = running_instances(timeout)
        process_checks.append(inventory)
        instances = inventory.get("instances", [])
        reason = None
        if inventory["status"] != "ok":
            reason = "running_instance_discovery_unavailable"
        elif len(instances) > 1:
            reason = "ambiguous_running_instances"
        elif instances and instances[0]["path"] != selected_path:
            reason = "running_instance_path_mismatch"
        elif not instances and probe != "version":
            reason = "selected_app_not_running_after_launch"
        elif instances:
            if selected_pid is not None and instances[0]["pid"] != selected_pid:
                reason = "running_instance_changed"
            selected_pid = instances[0]["pid"]
        if reason:
            return {"status": "blocked", "reason": reason, "checks": checks, "process_checks": process_checks}
        # With no initial instance, only version may launch the validated app.
        # Inventory is checked again before documents and every later query.
        check = run_command(
            ["/usr/bin/osascript", str(PROBE_SCRIPT), probe, str(timeout), selected_path],
            timeout=timeout + 3,
        )
        if check["status"] == "ok":
            value = check.get("output", "")
            valid = {
                "version": bool(value),
                "documents": value.isdecimal(),
                "professional": value in ("true", "false"),
                "javascript": value in ("2", "2.0"),
            }[probe]
            if not valid:
                check = {**check, "status": "invalid_response"}
        checks[probe] = check
        if check["status"] != "ok":
            # Do not retry or queue more AppleEvents behind an unresponsive app.
            return {"status": "blocked", "checks": checks, "process_checks": process_checks}
    return {
        "status": "responding", "checks": checks, "process_checks": process_checks,
        "note": "Read-only command responses do not prove authoring or export.",
    }


def tex_tools(extra_dirs: list[str]) -> dict[str, Any]:
    # Preserve TeX executable symlinks: argv[0] selects the engine's format.
    dirs = [*extra_dirs, "/Library/TeX/texbin"]
    dirs.extend(str(p) for p in Path("/usr/local/texlive").glob("*/bin/*") if p.is_dir())
    managed = Path.home() / ".cache" / "codex-runtimes" / "codex-texlive"
    dirs.extend(str(p) for p in managed.glob("*/bin/*") if p.is_dir())
    search_path = os.pathsep.join([*dirs, os.environ.get("PATH", "")])
    paths = {name: shutil.which(name, path=search_path) for name in ("pdflatex", "kpsewhich", "gs")}
    return {
        "status": "present" if all(paths.values()) else "missing",
        "paths": paths,
        "note": "Discovered executables are unverified; only file presence and executable permissions were checked. Rendering has not run.",
    }


def stock_helper_tools() -> dict[str, Any]:
    """Discover the compiler and SDK needed by the Cocoa clipboard/AX helper."""
    checks = {name: run_command(command) for name, command in (
        ('clang', ['/usr/bin/xcrun', '--find', 'clang']),
        ('sdk', ['/usr/bin/xcrun', '--show-sdk-path']),
    )}
    compiler_path = checks['clang'].get('output', '')
    sdk_path = checks['sdk'].get('output', '')
    compiler_present = (checks['clang']['status'] == 'ok' and Path(compiler_path).is_absolute()
                        and Path(compiler_path).is_file() and os.access(compiler_path, os.X_OK))
    sdk_present = checks['sdk']['status'] == 'ok' and Path(sdk_path).is_absolute() and Path(sdk_path).is_dir()
    return {'status': 'present' if compiler_present and sdk_present else 'missing',
            'required_for': 'stock_gui_cocoa_helper', 'checks': checks,
            'compiler_present': compiler_present, 'sdk_present': sdk_present,
            'compilation_test': 'not_run',
            'note': 'The stock GUI adapter compiles a local Cocoa helper on first use. This check discovers clang and its SDK; it does not compile, install, or verify a build.'}


def export_capabilities(app: Path, scripting: dict[str, Any]) -> dict[str, Any]:
    """Read installed export terminology; never infer tested support from license."""
    professional = scripting.get('checks', {}).get('professional', {})
    license_report = {'status': 'not_probed', 'professional': None}
    if professional.get('status') == 'ok' and professional.get('output') in ('true', 'false'):
        license_report = {'status': 'reported_by_application', 'professional': professional['output'] == 'true'}
    result = {'status': 'unknown', 'license': license_report,
              'formats': {name: {'advertised': False, 'export_verified': False} for name in ('PDF', 'PNG', 'SVG')},
              'note': 'Installed dictionary declarations and the Professional property are read-only evidence. Each actual export must still verify success, selected canvas and dimensions; no format is assumed available from license tier alone.'}
    try:
        values = []
        for name in ('OmniGraffle.scriptSuite', 'OmniGraffle.scriptTerminology'):
            with (app / 'Contents' / 'Resources' / name).open('rb') as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('Installed dictionary exceeds inspection limit')
            parsed = plistlib.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError('Invalid installed dictionary')
            values.append(parsed)
        command = values[0]['Commands']['Export']
        if command.get('AppleEventCode') != 'OGEx':
            raise ValueError('Unrecognized export command')
        description = values[1]['Commands']['Export']['Arguments']['Format']['Description']
        if not isinstance(description, str):
            raise ValueError('Unrecognized export format description')
        advertised = set(re.findall(r'"([A-Z]+)"', description))
        for name, entry in result['formats'].items():
            entry['advertised'] = name in advertised
        result['status'] = 'dictionary_inspected'
    except (OSError, ValueError, KeyError, TypeError, AttributeError, plistlib.InvalidFileException, ExpatError):
        result['reason'] = 'installed_export_dictionary_unavailable_or_unrecognized'
    return result


def collect(app: Path, active_probe: bool, timeout: int, tex_dirs: list[str],
            equation_backend: str = "isolated", latexit_app: Path = Path("/Applications/LaTeXiT.app")) -> dict[str, Any]:
    if equation_backend not in ("isolated", "stock-gui"):
        raise ValueError("Unknown equation backend")
    result: dict[str, Any] = {
        "schema_version": 1,
        "platform": platform.system(),
        "equation_backend": equation_backend,
        "native_authoring_test": "not_run",
        "equation_persistence_test": "not_run",
        "live_linkback_test": "not_run",
        "release_accepted": False,
        "omnigraffle": {"status": "not_run"},
        "scripting": {"status": "not_run"},
        "linkback_sandbox": {"status": "not_run"},
        "latexit": {"status": "not_run"},
        "build_tools": {"status": "not_run"},
        "tex": {"status": "not_run"},
        "exports": {"status": "not_run"},
    }
    blockers = []
    if result["platform"] != "Darwin":
        result.update(status="blocked", blockers=["macos_required"])
        return result
    result["omnigraffle"] = app_info(app)
    if result["omnigraffle"]["status"] != "present":
        blockers.append("omnigraffle_unavailable")
    else:
        selected_service = STOCK_LINKBACK_SERVICE if equation_backend == "stock-gui" else ISOLATED_LINKBACK_SERVICE
        result["linkback_sandbox"] = linkback_sandbox(Path(result["omnigraffle"]["path"]), selected_service)
        if result["linkback_sandbox"]["status"] == "isolated_service_not_listed":
            blockers.append("isolated_linkback_service_exception_missing")
        elif result["linkback_sandbox"]["status"] == "stock_service_not_listed":
            blockers.append("stock_linkback_service_exception_missing")
        elif result["linkback_sandbox"]["status"] == "unknown":
            blockers.append("linkback_sandbox_not_verified")
    if active_probe and not blockers:
        result["scripting"] = probe_app(timeout, Path(result["omnigraffle"]["path"]))
        if result["scripting"]["status"] != "responding":
            blockers.append("omnigraffle_scripting_unavailable")
    else:
        result["scripting"] = {"status": "not_probed"}
        blockers.append("omnigraffle_scripting_not_verified")
    if result['omnigraffle']['status'] == 'present':
        result['exports'] = export_capabilities(Path(result['omnigraffle']['path']), result['scripting'])
    if equation_backend == "stock-gui":
        result["latexit"] = app_info(latexit_app, LATEXIT_APP_ID)
        if result["latexit"]["status"] != "present":
            blockers.append("stock_latexit_unavailable")
        result["gui"] = {
            "status": "not_probed",
            "note": "Requires an unlocked desktop and GUI access. Application/process identity and GUI controls must be verified before each operation. Stock application state is shared, not isolated.",
        }
        result["build_tools"] = stock_helper_tools()
        if result['build_tools']['status'] != 'present':
            blockers.append('stock_gui_helper_build_tools_unavailable')
    else:
        result["build_tools"] = {
            name: run_command(command) for name, command in (
                ("xcode", ["/usr/bin/xcodebuild", "-version"]),
                ("sdk", ["/usr/bin/xcrun", "--show-sdk-path"]),
                ("momc", ["/usr/bin/xcrun", "--find", "momc"]),
                ("ibtool", ["/usr/bin/xcrun", "--find", "ibtool"]),
            )
        }
        if any(check["status"] != "ok" for check in result["build_tools"].values()):
            blockers.append("latexit_build_tools_unavailable")
    result["tex"] = tex_tools(tex_dirs)
    if result["tex"]["status"] != "present":
        blockers.append("latexit_tex_dependencies_missing")
    result.update(status="blocked" if blockers else "prerequisites_present", blockers=blockers)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path("/Applications/OmniGraffle.app"))
    parser.add_argument("--equation-backend", choices=("isolated", "stock-gui"), default="isolated")
    parser.add_argument("--latexit-app", type=Path, default=Path("/Applications/LaTeXiT.app"))
    parser.add_argument("--probe-app", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=5, choices=range(1, 31), metavar="1..30")
    parser.add_argument("--tex-bin", action="append", default=[], help="Additional existing TeX bin directory")
    args = parser.parse_args()
    result = collect(args.app, args.probe_app, args.timeout_seconds, args.tex_bin,
                     args.equation_backend, args.latexit_app)
    print(json.dumps(result, indent=2))
    return 2 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
