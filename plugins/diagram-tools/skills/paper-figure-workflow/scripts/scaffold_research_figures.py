#!/usr/bin/env python3
"""Copy editable research-figure sources and record one diagram owner."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
STARTER = HERE.parent / "assets" / "research-figure-starter"
OWNER_FILE = Path("figures_src") / "diagram-owner.json"
# This source-owned release gate is independent of project metadata and doctor.
# Native templates and foreground-Terminal equation/restart acceptance passed.
# Fresh doctor results establish drawing access, not the caller's GUI permissions.
NATIVE_RESEARCH_PREFERENCE_ENABLED = True


def discover_plugin(name: str, required: Path) -> Path | None:
    """Find a sibling source checkout or separately versioned installed plugin."""
    for parent in HERE.parents:
        checkout = parent / "plugins" / name
        if (checkout / required).exists():
            return checkout
        for candidate in sorted((parent / name).glob("*"), reverse=True):
            if (candidate / required).exists():
                return candidate
    return None


def existing_owner(project: Path) -> str | None:
    native = project / "figures_src" / "diagrams"
    owners = {owner for suffix, owner in ((".graffle", "omnigraffle"),
                                            (".drawio", "drawio"))
              if any(native.glob(f"*{suffix}"))}
    if len(owners) > 1:
        raise ValueError("existing .graffle and .drawio sources have different owners; select one explicitly")
    return next(iter(owners), None)


def recorded_owner(project: Path) -> str | None:
    """Honor the previously selected project owner; never use it as acceptance proof."""
    path = project / OWNER_FILE
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 65536:
            raise ValueError("owner record is too large")
        record = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or type(record.get("schema_version")) is not int
                or record["schema_version"] != 1 or record.get("owner") not in ("omnigraffle", "drawio")):
            raise ValueError("unsupported owner record")
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid {OWNER_FILE}: {error}") from error
    return record["owner"]


def native_readiness(plugin: Path | None) -> tuple[bool, str]:
    """Probe current drawing access, without equating discovery with release acceptance."""
    if platform.system() != "Darwin":
        return False, "macos_required"
    if plugin is None:
        return False, "omnigraffle_runtime_unavailable"
    runtime = plugin.expanduser().resolve() / "skills/omnigraffle-workflow/scripts/omnigraffle.py"
    if not runtime.is_file():
        return False, "omnigraffle_runtime_unavailable"
    try:
        result = subprocess.run([sys.executable, str(runtime), "--timeout", "5", "doctor", "--probe-app"],
                                capture_output=True, text=True, timeout=60, check=False)
        report = json.loads(result.stdout)
        if (result.returncode not in (0, 2) or not isinstance(report, dict)
                or type(report.get("schema_version")) is not int or report["schema_version"] != 1
                or report.get("platform") != "Darwin"
                or report.get("status") not in ("blocked", "prerequisites_present")):
            return False, "native_readiness_invalid"
        app = report.get("omnigraffle", {})
        scripting = report.get("scripting", {})
        exports = report.get("exports", {})
        if not all(isinstance(item, dict) for item in (app, scripting, exports)):
            return False, "native_readiness_invalid"
        if app.get("status") != "present":
            return False, "omnigraffle_unavailable"
        if scripting.get("status") != "responding":
            return False, "omnigraffle_scripting_unavailable"
        formats = exports.get("formats", {})
        pdf = formats.get("PDF", {}) if isinstance(formats, dict) else {}
        if (exports.get("status") != "dictionary_inspected" or not isinstance(pdf, dict)
                or pdf.get("advertised") is not True):
            return False, "native_pdf_not_advertised"
    except subprocess.TimeoutExpired:
        return False, "native_readiness_timeout"
    except OSError:
        return False, "native_readiness_unavailable"
    except ValueError:
        return False, "native_readiness_invalid"
    return True, "native_ready"


def resolve_owner(project: Path, requested: str, plugin: Path | None = None) -> tuple[str, str, str]:
    """Resolve once before dispatch; explicit and existing ownership cannot fall back."""
    source = existing_owner(project)
    recorded = recorded_owner(project)
    if source and recorded and source != recorded:
        raise ValueError(f"existing {source} sources conflict with recorded {recorded} owner")
    convention = recorded or source
    if requested != "auto":
        if convention and convention != requested:
            raise ValueError(f"existing {convention} owner conflicts with --diagram-owner {requested}")
        return requested, "explicit", "explicit_request"
    if recorded:
        return recorded, "recorded_project", "recorded_project_owner"
    if source:
        return source, "existing_source", "existing_native_source"
    if not NATIVE_RESEARCH_PREFERENCE_ENABLED:
        return "drawio", "auto", "native_preference_pending_acceptance"
    if plugin is None:
        plugin = discover_plugin("omnigraffle-tools", Path("skills/omnigraffle-workflow/scripts/omnigraffle.py"))
    ready, reason = native_readiness(plugin)
    return ("omnigraffle" if ready else "drawio"), "auto", reason


def files_under(directory: Path, destination: Path) -> list[tuple[Path, Path]]:
    return [(source, destination / source.relative_to(directory))
            for source in directory.rglob("*") if source.is_file()
            and "__pycache__" not in source.parts and source.suffix not in {".pyc", ".pyo"}]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="Target paper project directory")
    parser.add_argument("--diagram-owner", choices=("auto", "omnigraffle", "drawio"), default="auto")
    parser.add_argument("--drawio-templates", type=Path,
                        help="Directory of editable Draw.io templates")
    parser.add_argument("--omnigraffle-plugin", type=Path,
                        help="OmniGraffle plugin root containing assets and guarded runtime")
    parser.add_argument("--plots-only", action="store_true",
                        help="Explicitly scaffold plots without diagrams")
    args = parser.parse_args()
    if args.plots_only and (args.diagram_owner != "auto" or args.drawio_templates or args.omnigraffle_plugin):
        parser.error("--plots-only cannot select a diagram owner or templates")
    project = args.project.expanduser().resolve()
    if project.exists() and not project.is_dir():
        parser.error("--project must be a directory")
    if not STARTER.is_dir():
        parser.error(f"starter assets are missing: {STARTER}")
    source_files = files_under(STARTER, Path())
    owner = None
    selection = "plots_only" if args.plots_only else "explicit"
    reason = "plots_only"
    if not args.plots_only:
        try:
            owner, selection, reason = resolve_owner(project, args.diagram_owner, args.omnigraffle_plugin)
        except ValueError as error:
            parser.error(str(error))
        if owner == "drawio":
            diagram_dir = args.drawio_templates
            if diagram_dir is None:
                plugin = discover_plugin("drawio-tools", Path("assets/research-templates/README.md"))
                diagram_dir = plugin / "assets/research-templates" if plugin else None
            if diagram_dir is None:
                parser.error("Draw.io research templates are unavailable; pass --drawio-templates PATH or --plots-only")
            if not diagram_dir.is_dir():
                parser.error(f"Draw.io template directory is missing: {diagram_dir}")
            diagram_files = sorted(diagram_dir.glob("*.drawio"))
            readme = diagram_dir / "README.md"
            if not diagram_files or not readme.is_file():
                parser.error(f"Draw.io .drawio templates and provenance README are required in {diagram_dir}")
            source_files.extend((source, Path("figures_src/diagrams") / source.name) for source in diagram_files)
            source_files.append((readme, Path("figures_src/diagrams/README.md")))
        else:
            omni_plugin = args.omnigraffle_plugin or discover_plugin(
                "omnigraffle-tools", Path("skills/omnigraffle-workflow/scripts/omnigraffle.py"))
            if omni_plugin is None:
                parser.error("OmniGraffle plugin is unavailable; pass --omnigraffle-plugin PATH")
            omni_plugin = omni_plugin.expanduser().resolve()
            runtime = omni_plugin / "skills/omnigraffle-workflow/scripts"
            templates = omni_plugin / "assets/research-templates"
            if not (runtime / "omnigraffle.py").is_file() or not (templates / "README.md").is_file():
                parser.error(f"OmniGraffle runtime or templates missing under {omni_plugin}")
            local = Path("scripts/omnigraffle-tools")
            source_files.extend(files_under(runtime, local / "skills/omnigraffle-workflow/scripts"))
            source_files.extend(files_under(templates, local / "assets/research-templates"))
            source_files.append((templates / "README.md", Path("figures_src/diagrams/README.md")))
    conflicts = [project / relative for _, relative in source_files if (project / relative).exists()]
    if owner and (project / OWNER_FILE).exists():
        conflicts.append(project / OWNER_FILE)
    if conflicts:
        parser.error("refusing to overwrite existing sources: " + ", ".join(str(path) for path in conflicts))
    for source, relative in source_files:
        destination = project / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    if owner:
        destination = project / OWNER_FILE
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({"schema_version": 1, "owner": owner,
                                           "selection": selection, "reason": reason}, indent=2) + "\n", encoding="utf-8")
    print(f"copied {len(source_files)} editable figure files to {project}")
    if args.plots_only:
        print("plots-only starter: add project-local diagram sources before make diagrams or make figures")
    else:
        print(f"diagram owner: {owner} ({selection}: {reason}); recorded in {OWNER_FILE}")
    print("regeneration uses only project-local sources; see FIGURES_README.md")


if __name__ == "__main__":
    main()
