#!/usr/bin/env python3
"""Bounded local native drawing and stock-LaTeXiT GUI commands.

Mutations take a JSON request file, never executable scripts. Inspect/audit are
portable. Application commands require macOS and a licensed, unlocked session.
Run COMMAND --help for the request entrypoint; references/commands.md documents
the schema. Setup does not install applications, TeX, or permissions.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import sys

from contracts import CommandError, load_json
from document import DocumentError, inspect_document
from engine import Engine
from latexit import LatexitAdapter
from native import NativeAdapter
from preflight import collect
from transactions import Store, canonical


def inspection(command, path, output=None):
    report = inspect_document(path)
    if command == "audit":
        report["audit"] = {
            "status": "findings" if report.get("findings") or any(c.get("warnings") for c in report["canvases"]) else "no_structural_findings",
            "visual_review": "not_performed", "native_editability": "not_verified",
        }
    if output:
        destination = canonical(output, output=True)
        source = Path(report["path"])
        if source == destination or destination.exists():
            raise CommandError("output_alias_or_exists", "Report output must be a new path distinct from the input and its aliases")
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        report["report_output"] = str(destination)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path("/Applications/OmniGraffle.app"))
    parser.add_argument("--latexit-app", type=Path, default=Path("/Applications/LaTeXiT.app"))
    parser.add_argument("--state-dir", type=Path, help="Private receipts directory; the global app lock and quarantine remain shared")
    parser.add_argument("--timeout", type=int, default=45, choices=range(5, 181), metavar="5..180")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Read prerequisites; never grants access or installs dependencies")
    doctor.add_argument("--probe-app", action="store_true")
    for command in ("inspect", "audit"):
        p = commands.add_parser(command, help="Bounded read-only inspection of ZIP/plist .graffle")
        p.add_argument("file", type=Path)
        p.add_argument("--output", type=Path, help="New report path; input/output aliases and existing destinations rejected")
    for command in ("create", "update", "export", "equation-source", "equation-render", "equation-insert", "equation-update"):
        p = commands.add_parser(command, help="Run one journaled data-only request")
        p.add_argument("--request", type=Path, required=True, help="JSON file with canonical UUID operation_id and command data")
    reconcile = commands.add_parser("reconcile", help="Inspect an interrupted operation without retrying its mutation")
    reconcile.add_argument("operation_id")
    args = parser.parse_args(argv)
    try:
        if args.command in ("inspect", "audit"):
            result = inspection(args.command, args.file, args.output)
        elif args.command == "doctor":
            result = collect(args.app, args.probe_app, min(args.timeout, 30), [], "stock-gui", args.latexit_app)
        else:
            if platform.system() != "Darwin":
                raise CommandError("macos_required", "Application commands require macOS")
            store = Store(args.state_dir)
            engine = Engine(NativeAdapter(args.app, timeout=args.timeout),
                            LatexitAdapter(str(args.app), str(args.latexit_app), timeout=args.timeout, runtime_dir=store.guard / "runtime"), store)
            if args.command == "reconcile":
                receipt = engine.reconcile(args.operation_id)
            else:
                receipt = engine.perform(args.command, load_json(args.request))
            result = {k: receipt[k] for k in ("status", "operation_id", "phase", "receipt", "result", "error", "reconciliation", "replayed_receipt") if k in receipt}
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0 if result.get("status") in ("inspected", "completed", "committed", "reconciled_unchanged", "prerequisites_present") else 2
    except (CommandError, DocumentError, OSError, ValueError) as error:
        print(json.dumps({"status": "rejected", "error": {"code": getattr(error, "code", "invalid_request"), "message": str(error),
                                                        "outcome_unknown": getattr(error, "unknown", False)}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
