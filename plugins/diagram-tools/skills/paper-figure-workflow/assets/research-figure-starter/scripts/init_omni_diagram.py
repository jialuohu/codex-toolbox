#!/usr/bin/env python3
"""Initialize one editable OmniGraffle source without replacing existing work."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import uuid


PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = PROJECT / "scripts/omnigraffle-tools/skills/omnigraffle-workflow/scripts"
SOURCES = PROJECT / "figures_src/diagrams"


def run(command: list[str]) -> dict:
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[:1200])
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError("OmniGraffle helper returned invalid JSON") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", choices=("architecture", "timeline", "mechanism"), required=True)
    parser.add_argument("--prepare-only", action="store_true",
                        help="Write a new seed and guarded create request without dispatching to the app")
    parser.add_argument("--request-out", type=Path,
                        help="New absolute request path; defaults to private local state")
    widths = parser.add_mutually_exclusive_group()
    widths.add_argument("--width", choices=("single", "double"), default="double")
    widths.add_argument("--width-in", type=float)
    args = parser.parse_args()
    if args.width_in is not None and (not math.isfinite(args.width_in) or args.width_in <= 0):
        parser.error("--width-in must be positive and finite")
    selected = PROJECT / "figures_src/diagram-owner.json"
    try:
        owner = json.loads(selected.read_text(encoding="utf-8"))["owner"]
    except (OSError, ValueError, KeyError) as error:
        parser.error(f"recorded diagram owner is missing or invalid: {error}")
    if owner != "omnigraffle":
        parser.error(f"recorded diagram owner is {owner}; OmniGraffle initialization requires omnigraffle")
    generator, cli = RUNTIME / "research_workflow.py", RUNTIME / "omnigraffle.py"
    if not generator.is_file() or not cli.is_file():
        parser.error("project-local OmniGraffle runtime is incomplete")
    width_args = (["--width-in", str(args.width_in)] if args.width_in is not None
                  else ["--width", args.width])
    label = (f"{args.width_in:g}".replace(".", "p") + "in" if args.width_in is not None
             else args.width)
    name = f"{args.template}-{label}"
    native = SOURCES / f"{name}.graffle"
    seeds = SOURCES / "seeds"
    seeds.mkdir(parents=True, exist_ok=True)
    source = seeds / f"{name}.json"
    palette = seeds / f"{name}.palette.json"
    if native.exists() or source.exists() or palette.exists() or any(
            path.is_symlink() for path in (native, source, palette)):
        parser.error(f"refusing to overwrite existing native source or seed for {name}")
    if args.request_out is not None:
        request = args.request_out.expanduser()
        if not request.is_absolute() or request.exists() or request.is_symlink() or not request.parent.is_dir():
            parser.error("--request-out must be a new absolute path in an existing directory")
    else:
        request_dir = Path.home() / ".local/state/codex-toolbox/omnigraffle/project-requests"
        request_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        request = request_dir / f"{name}-{uuid.uuid4()}.json"
    try:
        run([sys.executable, str(generator), "--template", args.template, *width_args,
             "source", "--out", str(source)])
        run([sys.executable, str(generator), "--spec", str(source),
             "prepare", "--output", str(native), "--request-out", str(request)])
        if not palette.is_file():
            raise RuntimeError(f"template palette provenance is missing: {palette}")
        create_request = json.loads(request.read_text(encoding="utf-8"))
        create_request["palette"] = {"catalog_path": str(palette)}
        request.write_text(json.dumps(create_request, indent=2) + "\n", encoding="utf-8")
        if args.prepare_only:
            print(f"prepared source seed and palette: {source}, {palette}")
            print(f"guarded create request: {request}")
            print(f"create with: {sys.executable} {cli} create --request {request}")
            return
        receipt = run([sys.executable, str(cli), "create", "--request", str(request)])
        if receipt.get("status") not in ("completed", "committed") or not native.is_file():
            raise RuntimeError(f"native creation did not verify: {receipt.get('status')}")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"OmniGraffle initialization failed: {error}\n"
                         f"Seed: {source}\nRequest: {request}\n"
                         "If the operation outcome is unknown, reconcile its operation ID before any retry.") from error
    print(f"created editable source: {native}")
    print(f"source seed and palette: {source}, {palette}")
    print("Subsequent make diagrams exports the saved .graffle and preserves native edits.")


if __name__ == "__main__":
    main()
