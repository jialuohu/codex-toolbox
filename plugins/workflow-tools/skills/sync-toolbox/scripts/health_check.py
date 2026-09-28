#!/usr/bin/env python3
"""Inventory installed components and render bounded, evidence-scoped health reports.

No setup, login, raw MCP transport, arbitrary command, or repair execution lives
here. Native probes are dispatched by Codex; only reviewed result fields enter
the report. The input files are local observations, not authenticated attestations.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections import Counter

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
VERSION = "0.13.1"
MAX_BYTES = 4 * 1024 * 1024
MAX_ITEMS = 10000
STATUSES = {"passed", "failed", "unverified", "disabled", "not_applicable"}
SCOPES = {"installation", "configuration", "discovery", "runtime", "authentication", "workflow"}
TOOLBOX = "jialuo-codex-toolbox"
NATIVE = {
    "docmost": "mcp__docmost__docmost_get_current_user",
    "overleaf": "mcp__overleaf__overleaf_configuration_status",
    "typesafe": "mcp__typesafe__typesafe_status",
    "apple_mail": "mcp__apple_mail__apple_mail_health_check",
}
# Commands are code-reviewed adapters, never shell strings from manifests/docs.
SHELL = {
    "mermaid": ["scripts/setup-diagram-tools.sh", "--check"],
    "archify": ["scripts/setup-archify-tools.sh", "--check"],
    "drawio": ["scripts/setup-drawio-tools.sh", "--check"],
    "health": ["scripts/setup-toolbox-health.sh", "--check"],
}
REPAIRS = {
    "mermaid-update": ("diagram-tools", "mermaid-runtime", "scripts/setup-diagram-tools.sh --update"),
    "archify-install": ("diagram-tools", "archify-runtime", "scripts/setup-archify-tools.sh --install"),
    "drawio-install": ("drawio-tools", "drawio-runtime", "scripts/setup-drawio-tools.sh --install"),
    "health-install": ("workflow-tools", "health-runtime", "scripts/setup-toolbox-health.sh --install"),
}
# Stable text only: never forward config values, service errors, paths or stderr.
REASONS = {
    "ok": ("none", "Check passed within its stated scope.", "None."),
    "disabled": ("none", "Explicitly disabled; not exercised.", "None unless you intend to enable it."),
    "not_applicable": ("none", "This check does not apply.", "None."),
    "source_unavailable": ("user", "An inventory source could not be read.", "Restore CLI or file access, then rerun health-only."),
    "invalid_inventory": ("maintainer", "Inventory data has an unsupported shape.", "Update the health helper for the installed CLI format."),
    "parser_missing": ("user", "The health parser dependency is unavailable.", "Run an authorized Toolbox sync to install the health runtime."),
    "invalid_metadata": ("maintainer", "Component metadata is invalid.", "Repair the owning plugin or skill metadata, then recheck."),
    "missing_files": ("user", "An installed component has missing required files.", "Repair its installation through its owning installer."),
    "version_mismatch": ("user", "Installed files do not match the listed version.", "Run an authorized managed sync or use the external plugin's updater."),
    "version_unverified": ("coverage", "Installed version evidence is missing.", "Refresh the installed-plugin listing; no version comparison was possible."),
    "remote_files_unavailable": ("coverage", "Remote plugin files are not locally inspectable.", "Use its native discovery surface; file integrity remains unverified."),
    "missing_reference": ("maintainer", "A required local skill reference is missing or outside its package.", "Correct the reference in the owning skill."),
    "reference_scope_unverified": ("coverage", "A skill references files outside its inspected package.", "Validate those references through their owning source; no outside file was read."),
    "workflow_not_exercised": ("coverage", "Skill workflow execution was not tested.", "Validate on a separately authorized real task if needed."),
    "missing_dependency": ("user", "A declared required dependency is unavailable.", "Configure the named dependency through its owning setup."),
    "dependency_unverified": ("coverage", "Dependency readiness is not established.", "Recheck its owning component after resolving its reported issue."),
    "optional_dependency": ("none", "An optional capability was not required.", "None."),
    "session_unavailable": ("coverage", "A fresh complete session catalog was not supplied.", "Provide a current session catalog and rerun health-only."),
    "tool_unavailable": ("coverage", "The reviewed tool is absent from the current session catalog.", "Refresh discovery in a new session and recheck; absence alone does not prove failure."),
    "session_stale": ("user", "Installed skill content changed after the session catalog was observed.", "Start a fresh Codex session, then rerun health-only."),
    "no_safe_probe": ("coverage", "No reviewed safe probe covers this capability.", "Leave this capability unverified; do not improvise a workflow test."),
    "auth_unverified": ("coverage", "Authentication has not been exercised.", "Use a reviewed authenticated read when one becomes available."),
    "auth_required": ("user", "The service explicitly requires authentication.", "Reconnect or sign in through the owning integration, then recheck."),
    "permission_required": ("user", "The service explicitly denied permission.", "Review the integration's required access, then recheck."),
    "permission_probe_deferred": ("coverage", "This probe can trigger an OS permission prompt and was skipped.", "Check application access separately when ready to handle the prompt."),
    "configuration_missing": ("user", "The owning status probe reports incomplete configuration.", "Complete configuration through the owning integration, then recheck."),
    "policy_blocked": ("coverage", "A policy or optional paid capability is blocked.", "No paid test was attempted; review the owning tool's policy if needed."),
    "profile_busy": ("user", "The owning integration reports a busy profile.", "Close its other authentication session normally, then recheck."),
    "provider_unavailable": ("provider", "The service reported an upstream failure.", "Recheck after service or network recovery; do not assume credentials are invalid."),
    "probe_failed": ("user", "The reviewed runtime check failed.", "Use its listed managed repair when authorized, then recheck."),
    "probe_timeout": ("coverage", "The probe exceeded its deadline.", "Recheck later; the cause and authentication state remain unknown."),
    "budget_exhausted": ("coverage", "The run stopped launching checks after its time budget.", "Rerun health-only for unfinished checks."),
    "not_run": ("coverage", "The reviewed probe has not run.", "Run health-only with safe live checks to exercise it."),
    "unsafe_probe_source": ("coverage", "The reviewed command source could not be verified.", "Use a verified Toolbox checkout; no fallback command was executed."),
    "invalid_evidence": ("coverage", "Evidence is missing, stale, ambiguous, or does not match this probe.", "Collect a fresh matching observation; do not infer a pass."),
    "unknown_enabled_state": ("coverage", "The effective enabled state is unknown.", "Resolve configuration discovery before exercising this component."),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def label(value):
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", value):
        return value
    return "redacted-" + digest(value)[:10]


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_json(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError("missing_input")
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("input_limit")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("input_limit")
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate_key")
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=unique)


def run_command(argv, cwd=None, timeout=30):
    """Bound stdout and the whole process group; discard all stderr."""
    process = None

    def terminate_group():
        if process is None:
            return
        try:
            # The parent may have exited while a child still holds its stdout pipe.
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            # Never let cleanup turn a bounded diagnostic into an indefinite wait.
            pass

    try:
        deadline = time.monotonic() + timeout
        process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   start_new_session=True, bufsize=0)
        stdout = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    terminate_group()
                    return None, "probe_timeout"
                for key, _ in selector.select(remaining):
                    # Read at most one byte beyond the limit; never retain it.
                    chunk = os.read(key.fd, min(65536, MAX_BYTES - len(stdout) + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif len(stdout) + len(chunk) > MAX_BYTES:
                        terminate_group()
                        return None, "invalid_inventory"
                    else:
                        stdout.extend(chunk)
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                terminate_group()
                return None, "probe_timeout"
        if process.returncode:
            return process.returncode, "probe_failed"
        return bytes(stdout), "ok"
    except (OSError, ValueError):
        terminate_group()
        return None, "source_unavailable"
    finally:
        if process is not None and process.stdout is not None:
            process.stdout.close()


def load_catalog():
    data = read_json(HERE.parent / "references/health-probes.json")
    if data.get("schema_version") != 1 or not isinstance(data.get("probes"), list):
        raise ValueError("invalid_catalog")
    ids = set()
    keys = {"id", "kind", "target", "plugin", "adapter", "scope", "safety", "timeout_seconds", "repair_id", "result_fields"}
    for row in data["probes"]:
        if (set(row) != keys or row["id"] in ids or row["adapter"] not in NATIVE.keys() | SHELL.keys()
                or row["kind"] not in {"mcp", "plugin"} or row["scope"] not in SCOPES
                or row["safety"] not in {"read_only", "may_prompt"}
                or row["timeout_seconds"] not in {30, 120}
                or row["repair_id"] not in {None, *REPAIRS}
                or not isinstance(row["result_fields"], list)):
            raise ValueError("invalid_catalog")
        ids.add(row["id"])
    return data["probes"]


def check(component, key, scope, status, reason, observed_at, probe_id=None):
    assert status in STATUSES and scope in SCOPES and reason in REASONS
    if component["enabled"] is False:
        status, reason = "disabled", "disabled"
    row = {"id": key, "scope": scope, "status": status, "reason": reason,
           "observed_at": observed_at, "probe_id": probe_id}
    component["checks"] = [c for c in component["checks"] if c["id"] != key] + [row]


def component(kind, name, identity, enabled=None, owner="external", parent=None, version=None):
    return {"id": kind + ":" + digest(identity)[:20], "kind": kind, "name": label(name),
            "source_id": digest(identity)[:20], "enabled": enabled if type(enabled) is bool else None,
            "owner": owner, "parent_id": parent, "version": label(version) if version else None,
            "dependencies": [], "checks": []}


def validator():
    try:
        spec = importlib.util.spec_from_file_location("health_skill_validation", HERE / "skill_validation.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except (ImportError, OSError, SyntaxError):
        return None


def trusted_root(root):
    if root is None:
        return False
    result, reason = run_command(["git", "-C", str(root), "remote", "get-url", "origin"])
    return reason == "ok" and result.decode().strip().removesuffix(".git") in {
        "https://github.com/jialuohu/codex-toolbox", "git@github.com:jialuohu/codex-toolbox"}


class Collector:
    def __init__(self, cwd, home=None, codex_home=None, toolbox_root=None, session=None, clock=time.time):
        self.cwd, self.home = Path(cwd).resolve(), Path(home or Path.home()).resolve()
        self.codex_home = Path(codex_home or os.environ.get("CODEX_HOME", self.home / ".codex")).resolve()
        self.root = Path(toolbox_root).resolve() if toolbox_root else None
        self.clock = clock
        self.now = clock()
        self.report = {"schema_version": 1, "helper_version": VERSION, "run_id": str(uuid.uuid4()),
                       "started_at": self.now, "deadline_at": self.now + 300, "sync_outcome": "not_run",
                       "inventory_sources": [], "components": [], "native_requests": [], "repairs": []}
        self.validation = validator()
        self.session = session or {}
        self.session_fresh = (self.session.get("schema_version") == 1
                              and number(self.session.get("observed_at"))
                              and 0 <= self.now - self.session["observed_at"] <= 120)
        self.tools = set(t for t in self.session.get("tools", []) if isinstance(t, str)) if self.session_fresh else set()
        self.plugin_roots, self.mcp_declarations, self.skill_paths = {}, {}, {}
        self.disabled_skills = set()
        self.dependencies = []

    def source(self, name, status, reason="ok"):
        self.report["inventory_sources"].append({"source": name, "status": status, "reason": reason})

    def add(self, row):
        existing = next((c for c in self.report["components"] if c["id"] == row["id"]), None)
        if existing:
            return existing
        self.report["components"].append(row)
        if row["enabled"] is None:
            check(row, "enabled-state", "configuration", "unverified", "unknown_enabled_state", self.now)
        return row

    def cli_json(self, command, source):
        if self.clock() >= self.report["deadline_at"]:
            self.source(source, "unverified", "budget_exhausted")
            return None
        raw, reason = run_command(["codex", *command, "--json"], cwd=self.cwd)
        if reason == "ok":
            try:
                result = json.loads(raw)
                self.source(source, "passed")
                return result
            except (ValueError, UnicodeError):
                reason = "invalid_inventory"
        self.source(source, "unverified", reason if reason != "probe_failed" else "source_unavailable")
        return None

    def plugins(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("installed"), list):
            self.source("plugin-schema", "unverified", "invalid_inventory")
            return
        for item in data["installed"][:MAX_ITEMS]:
            if not isinstance(item, dict) or not isinstance(item.get("pluginId"), str) or not isinstance(item.get("name"), str):
                self.source("plugin-row", "unverified", "invalid_inventory")
                continue
            if item.get("installed") is False:
                continue
            name, market, version = item["name"], item.get("marketplaceName"), item.get("version")
            owned = market == TOOLBOX
            row = self.add(component("plugin", name, item["pluginId"], item.get("enabled"), "toolbox" if owned else "external", version=version))
            row["marketplace"] = label(market) if market else "unknown"
            root = None
            # CLI source may describe the marketplace checkout, not the installed cache.
            if all(isinstance(s, str) and label(s) == s for s in (market, name, version)):
                cached = self.codex_home / "plugins/cache" / market / name / version
                if cached.is_dir():
                    root = cached.resolve()
            source = item.get("source", {})
            if root is None and isinstance(source, dict) and source.get("source") == "local" and isinstance(source.get("path"), str):
                root = Path(source["path"]).resolve()
            if root is None:
                check(row, "files", "installation", "unverified", "remote_files_unavailable", self.now)
                continue
            self.plugin_roots[row["id"]] = root
            try:
                manifest_path = root / ".codex-plugin/plugin.json"
                if not manifest_path.resolve().is_relative_to(root):
                    raise ValueError("manifest outside package")
                if not manifest_path.exists() and not owned:
                    manifest_path = root / ".claude-plugin/plugin.json"
                if not manifest_path.resolve().is_relative_to(root):
                    raise ValueError("manifest outside package")
                manifest = read_json(manifest_path)
                if not isinstance(manifest, dict) or manifest.get("name") != name:
                    raise ValueError("metadata")
                check(row, "files", "installation", "passed", "ok", self.now)
                if not isinstance(version, str) or not version or not isinstance(manifest.get("version"), str):
                    check(row, "version", "installation", "unverified", "version_unverified", self.now)
                else:
                    mismatch = manifest["version"] != version
                    check(row, "version", "installation", "failed" if mismatch else "passed", "version_mismatch" if mismatch else "ok", self.now)
                skills = manifest.get("skills")
                if isinstance(skills, str):
                    skill_root = (root / skills).resolve()
                    if not skill_root.is_relative_to(root) or not skill_root.is_dir():
                        check(row, "skills", "installation", "failed", "missing_files", self.now)
                    else:
                        self.scan_skills(skill_root, root, row)
                elif skills is not None:
                    check(row, "skills", "installation", "unverified", "invalid_metadata", self.now)
                mcp_path = root / ".mcp.json"
                declared_mcp = manifest.get("mcpServers")
                declarations = None
                if isinstance(declared_mcp, str):
                    candidate = (root / declared_mcp).resolve()
                    if not candidate.is_relative_to(root):
                        raise ValueError("mcp outside package")
                    mcp_path = candidate
                    if not mcp_path.is_file():
                        check(row, "mcp-files", "installation", "failed", "missing_files", self.now)
                elif isinstance(declared_mcp, dict):
                    declarations = declared_mcp.get("mcpServers", declared_mcp)
                elif declared_mcp is not None:
                    check(row, "mcp-files", "installation", "unverified", "invalid_metadata", self.now)
                if declarations is None and mcp_path.is_file():
                    declarations = read_json(mcp_path).get("mcpServers")
                    if not isinstance(declarations, dict):
                        raise ValueError("metadata")
                if declarations is not None:
                    if not isinstance(declarations, dict):
                        raise ValueError("metadata")
                    for server, config in declarations.items():
                        if isinstance(config, dict):
                            self.mcp_declarations.setdefault(server, []).append((row, root, config))
                        else:
                            check(row, "mcp-files", "installation", "failed", "invalid_metadata", self.now)
            except FileNotFoundError:
                check(row, "files", "installation", "failed", "missing_files", self.now)
            except (OSError, ValueError, TypeError, AttributeError):
                check(row, "files", "installation", "failed", "invalid_metadata", self.now)
        if len(data["installed"]) > MAX_ITEMS:
            self.source("plugin-limit", "unverified", "invalid_inventory")

    def skill(self, path, package_root, parent=None, enabled=True):
        path = path.resolve()
        if path in self.skill_paths:
            return self.skill_paths[path]
        enabled = False if self.disabled_skills.intersection({str(path), str(path.parent)}) or (parent and parent["enabled"] is False) else enabled
        row = self.add(component("skill", path.parent.name, str(path), enabled,
                                 parent["owner"] if parent else "external", parent["id"] if parent else None))
        self.skill_paths[path] = row
        check(row, "workflow", "workflow", "unverified", "workflow_not_exercised", self.now)
        if not path.is_file():
            check(row, "files", "installation", "failed", "missing_files", self.now)
            return row
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("size")
            raw = path.read_bytes()
            if len(raw) > MAX_BYTES:
                raise ValueError("size")
            row["content_sha256"] = hashlib.sha256(raw).hexdigest()
            if self.validation is None:
                check(row, "metadata", "installation", "unverified", "parser_missing", self.now)
                return row
            meta = self.validation.frontmatter(raw.decode())
            row["name"] = label(meta["name"])
            check(row, "metadata", "installation", "passed", "ok", self.now)
            _, errors = self.validation.reference_graph(
                path, package_root, external=row["owner"] == "external"
            )
            only_outside = errors and all("reference escapes repository" in error for error in errors)
            check(row, "references", "installation", "unverified" if only_outside else "failed" if errors else "passed",
                  "reference_scope_unverified" if only_outside else "missing_reference" if errors else "ok", self.now)
            agent = path.parent / "agents/openai.yaml"
            if agent.is_file():
                data = self.validation.read_yaml(agent.read_text())
                if not isinstance(data, dict):
                    raise ValueError("agent metadata")
                policy = data.get("policy", {})
                if not isinstance(policy, dict) or type(policy.get("allow_implicit_invocation", True)) is not bool:
                    raise ValueError("policy")
                for dep in data.get("dependencies", {}).get("tools", []):
                    if isinstance(dep, dict):
                        self.dependencies.append((row, dep))
            skill_json = path.parent / "SKILL.json"
            if skill_json.is_file():
                data = read_json(skill_json)
                for dep in data.get("dependencies", {}).get("tools", []):
                    if isinstance(dep, dict):
                        self.dependencies.append((row, dep))
        except Exception:
            # Parser errors may quote private file contents; retain only a reason code.
            check(row, "metadata", "installation", "failed", "invalid_metadata", self.now)
        return row

    def scan_skills(self, directory, package_root, parent=None):
        if not directory.exists():
            return
        try:
            found = 0
            # Bound traversal and avoid symlink cycles while following individual skill symlinks.
            def scan_error(error):
                raise error
            for current, dirs, files in os.walk(directory, followlinks=False, onerror=scan_error):
                dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".venv", "__pycache__"}]
                for d in list(dirs):
                    candidate = Path(current) / d
                    if candidate.is_symlink() and (candidate / "SKILL.md").is_file():
                        self.skill(candidate / "SKILL.md", candidate.resolve(), parent)
                found += len(dirs) + len(files)
                if found > MAX_ITEMS or self.clock() >= self.report["deadline_at"]:
                    self.source("skill-scan-limit", "unverified", "budget_exhausted")
                    return
                if "SKILL.md" in files:
                    self.skill(Path(current) / "SKILL.md", package_root, parent)
        except OSError:
            self.source("skill-root", "unverified", "source_unavailable")

    def config_skills(self):
        roots = [self.home / ".agents/skills", self.codex_home / "skills", Path("/etc/codex/skills")]
        # Current project and ancestors only, never scan other projects or the home tree.
        configs = [self.codex_home / "config.toml"]
        for base in (self.cwd, *self.cwd.parents):
            roots.extend([base / ".agents/skills", base / ".codex/skills"])
            configs.append(base / ".codex/config.toml")
            if (base / ".git").exists() or base == self.home:
                break
        for config in configs:
            if not config.exists():
                continue
            try:
                import tomllib
                if not config.is_file() or config.stat().st_size > MAX_BYTES:
                    raise ValueError("config size")
                data = tomllib.loads(config.read_text())
                for entry in data.get("skills", {}).get("config", []):
                    if isinstance(entry, dict) and entry.get("enabled") is False and isinstance(entry.get("path"), str):
                        self.disabled_skills.add(str(Path(entry["path"]).expanduser().resolve()))
            except (ImportError, OSError, ValueError, TypeError, AttributeError):
                self.source("skill-config", "unverified", "source_unavailable")
        self.source("skill-roots", "passed")
        return list(dict.fromkeys(roots))

    def servers(self, data):
        if not isinstance(data, list):
            self.source("mcp-schema", "unverified", "invalid_inventory")
            return
        seen = set()
        identities = Counter()
        for item in data[:MAX_ITEMS]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                self.source("mcp-row", "unverified", "invalid_inventory")
                continue
            name = item["name"]
            seen.add(name)
            transport = item.get("transport", {})
            identity = [str(self.cwd), name, item.get("source"), transport]
            identity_key = digest(identity)
            identities[identity_key] += 1
            identity.append(identities[identity_key])
            owner = None
            for plugin, root, declared in self.mcp_declarations.get(name, []):
                declared_cwd, effective_cwd = declared.get("cwd"), transport.get("cwd") if isinstance(transport, dict) else None
                cwd_valid = (declared_cwd is None or isinstance(declared_cwd, str)) and (effective_cwd is None or isinstance(effective_cwd, str))
                if (plugin["enabled"] is True and isinstance(transport, dict) and transport.get("command") == declared.get("command")
                        and transport.get("args", []) == declared.get("args", [])
                        and transport.get("url") == declared.get("url")
                        and cwd_valid and (not declared.get("command") or
                             Path(effective_cwd or ".").resolve() == (root / (declared_cwd or ".")).resolve())):
                    owner = plugin
                    break
            row = self.add(component("mcp", name, identity, item.get("enabled"),
                                     owner["owner"] if owner else "external", owner["id"] if owner else None))
            valid = isinstance(transport, dict) and (
                isinstance(transport.get("command"), str) and bool(transport["command"])
                or isinstance(transport.get("url"), str) and transport["url"].startswith(("https://", "http://"))) and (
                transport.get("cwd") is None or isinstance(transport.get("cwd"), str))
            check(row, "configuration", "configuration", "passed" if valid else "failed", "ok" if valid else "invalid_metadata", self.now)
            if isinstance(transport, dict) and isinstance(transport.get("command"), str):
                exists = shutil.which(transport["command"]) is not None
                check(row, "launcher", "installation", "passed" if exists else "failed", "ok" if exists else "missing_dependency", self.now)
            check(row, "runtime", "runtime", "unverified", "no_safe_probe", self.now)
            check(row, "authentication", "authentication", "unverified", "auth_unverified", self.now)
            # unsupported describes the CLI auth reporting mechanism, not service health.
            if self.session_fresh:
                exposed = any(t.startswith("mcp__" + name + "__") for t in self.tools)
                check(row, "tool-discovery", "discovery", "passed" if exposed else "unverified", "ok" if exposed else "tool_unavailable", self.now)
        for name, declarations in self.mcp_declarations.items():
            if name not in seen:
                for plugin, _, _ in declarations:
                    check(plugin, "declared-mcp-" + label(name), "discovery", "unverified", "tool_unavailable", self.now)
        if len(data) > MAX_ITEMS:
            self.source("mcp-limit", "unverified", "invalid_inventory")

    def session_inventory(self):
        complete = self.session.get("complete", {})
        for part in ("skills", "tools"):
            good = self.session_fresh and isinstance(complete, dict) and complete.get(part) is True and isinstance(self.session.get(part), list)
            self.source("session-" + part, "passed" if good else "unverified", "ok" if good else "session_unavailable")
        if not self.session_fresh:
            return
        for entry in self.session.get("skills", [])[:MAX_ITEMS]:
            if not isinstance(entry, dict):
                self.source("session-skill-row", "unverified", "invalid_inventory")
                continue
            if not isinstance(entry.get("path"), str) or not Path(entry["path"]).is_absolute():
                if isinstance(entry.get("name"), str):
                    row = self.add(component("skill", entry["name"], ["session", entry["name"], entry.get("uri")], entry.get("enabled")))
                    check(row, "files", "installation", "unverified", "remote_files_unavailable", self.now)
                    check(row, "workflow", "workflow", "unverified", "workflow_not_exercised", self.now)
                self.source("session-skill-files", "unverified", "source_unavailable")
                continue
            path = Path(entry["path"]).resolve()
            row = self.skill_paths.get(path) or self.skill(path, path.parent, enabled=entry.get("enabled"))
            if type(entry.get("enabled")) is bool and row["enabled"] is not False:
                row["enabled"] = entry["enabled"]
                row["checks"] = [c for c in row["checks"] if c["id"] != "enabled-state"]
                if row["enabled"] is False:
                    for c in row["checks"]:
                        c.update(status="disabled", reason="disabled")
            observed_hash = entry.get("content_sha256")
            if isinstance(observed_hash, str) and row.get("content_sha256") != observed_hash:
                check(row, "session-content", "discovery", "unverified", "session_stale", self.now)
        existing = {c["name"] for c in self.report["components"] if c["kind"] == "mcp"}
        for tool in sorted(self.tools):
            match = re.fullmatch(r"mcp__([A-Za-z0-9_-]+)__[A-Za-z0-9_-]+", tool)
            if match and match[1] not in existing:
                name = match[1]
                row = self.add(component("mcp", name, ["session", name], True))
                check(row, "tool-discovery", "discovery", "passed", "ok", self.now)
                check(row, "runtime", "runtime", "unverified", "no_safe_probe", self.now)
                check(row, "authentication", "authentication", "unverified", "auth_unverified", self.now)
                existing.add(name)

    def resolve_dependencies(self):
        for row, dep in self.dependencies:
            key = "dependency-" + label(dep.get("value", "unknown"))
            if dep.get("optional") is True:
                check(row, key, "configuration", "not_applicable", "optional_dependency", self.now)
            elif dep.get("type") == "mcp":
                matches = [c for c in self.report["components"] if c["kind"] == "mcp" and c["name"] == dep.get("value")]
                row["dependencies"].extend(c["id"] for c in matches)
                check(row, key, "configuration", "unverified" if matches else "failed", "dependency_unverified" if matches else "missing_dependency", self.now)
            elif dep.get("type") == "env_var" and isinstance(dep.get("value"), str):
                present = bool(os.environ.get(dep["value"]))
                check(row, key, "configuration", "passed" if present else "unverified", "ok" if present else "dependency_unverified", self.now)
            else:
                check(row, key, "configuration", "unverified", "dependency_unverified", self.now)

    def probes(self, live):
        by_id = {c["id"]: c for c in self.report["components"]}
        catalog = load_catalog()
        root_ok = trusted_root(self.root) if live and self.root else False
        if root_ok:
            clean, why = run_command(["git", "-C", str(self.root), "status", "--porcelain", "--untracked-files=normal"])
            # A clean wrapper cannot make edited transitive code safe. Dirty health-only
            # still collects all static/native evidence but skips checkout shell probes.
            root_ok = why == "ok" and not clean.strip()
        for row in self.report["components"]:
            matches = [p for p in catalog if p["kind"] == row["kind"] and p["target"] == row["name"]]
            parent = by_id.get(row["parent_id"])
            for probe in matches:
                # Names alone are not provenance. External overrides never inherit a managed probe.
                if row["owner"] != "toolbox" or (row["kind"] == "mcp" and (not parent or parent["name"] != probe["plugin"])):
                    continue
                reason = "not_run"
                if row["enabled"] is None:
                    reason = "unknown_enabled_state"
                elif probe["safety"] == "may_prompt":
                    reason = "permission_probe_deferred"
                elif self.clock() >= self.report["deadline_at"]:
                    reason = "budget_exhausted"
                elif row["enabled"] is True and live:
                    adapter = probe["adapter"]
                    if adapter in NATIVE:
                        if NATIVE[adapter] in self.tools:
                            self.report["native_requests"].append({"component_id": row["id"], "probe_id": probe["id"], "tool": NATIVE[adapter], "arguments": {}})
                        else:
                            reason = "tool_unavailable"
                    elif root_ok:
                        script, argument = SHELL[adapter]
                        tracked, tracked_reason = run_command(["git", "-C", str(self.root), "ls-files", "--error-unmatch", script])
                        if tracked_reason != "ok":
                            reason = "unsafe_probe_source"
                        elif self.clock() >= self.report["deadline_at"]:
                            reason = "budget_exhausted"
                        else:
                            _, reason = run_command(["/bin/bash", str(self.root / script), argument], cwd=self.root, timeout=probe["timeout_seconds"])
                    else:
                        reason = "unsafe_probe_source"
                check(row, "probe-" + probe["id"], probe["scope"], "passed" if reason == "ok" else "failed" if reason == "probe_failed" else "unverified", reason, self.clock(), probe["id"])
            if row["kind"] == "plugin" and not matches:
                check(row, "runtime", "runtime", "unverified", "no_safe_probe", self.now)
        self.report["components"].sort(key=lambda c: (c["kind"], c["name"], c["id"]))

    def collect(self, live=False, plugin_data=None, mcp_data=None):
        roots = self.config_skills()
        self.plugins(plugin_data if plugin_data is not None else self.cli_json(["plugin", "list"], "plugins"))
        self.servers(mcp_data if mcp_data is not None else self.cli_json(["mcp", "list"], "mcp"))
        for root in roots:
            self.scan_skills(root, root)
        self.session_inventory()
        self.resolve_dependencies()
        self.probes(live)
        return summarize(self.report)


def native_result(adapter, result):
    """Parse only status fields; no service body/error text is ever returned."""
    if not isinstance(result, dict):
        return "unverified", "invalid_evidence"
    if result.get("ok") is False:
        error = result.get("error", {})
        code = error.get("code") if isinstance(error, dict) else None
        reasons = {"auth_required": "auth_required", "forbidden": "permission_required", "profile_busy": "profile_busy",
                   "configuration_invalid": "configuration_missing", "upstream_error": "provider_unavailable"}
        reason = reasons.get(code, "invalid_evidence")
        return ("failed" if reason not in {"invalid_evidence", "profile_busy"} else "unverified"), reason
    if result.get("ok") is not True:
        return "unverified", "invalid_evidence"
    if result.get("error"):
        return "unverified", "invalid_evidence"
    if adapter == "docmost":
        return "passed", "ok"
    if adapter == "overleaf":
        data = result.get("data", {})
        if isinstance(data, dict) and type(data.get("configured")) is bool:
            if data["configured"] is False:
                return "failed", "configuration_missing"
            projects, tokens = data.get("projectCount"), data.get("configuredTokenCount")
            if type(projects) is int and type(tokens) is int and 0 <= tokens <= projects:
                return ("passed", "ok") if projects > 0 and projects == tokens else ("failed", "configuration_missing")
    if adapter == "typesafe":
        if result.get("credential_configured") is False:
            return "failed", "configuration_missing"
        if result.get("status") == "ready" and result.get("credential_configured") is True and result.get("block_reasons") == []:
            return "passed", "ok"
        if result.get("status") == "blocked" and isinstance(result.get("block_reasons"), list):
            return "unverified", "policy_blocked"
    return "unverified", "invalid_evidence"


def apply_evidence(snapshot, evidence, before=None, now=None):
    report = validate_snapshot(snapshot)
    now = time.time() if now is None else now
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1 or evidence.get("run_id") != report["run_id"]:
        raise ValueError("invalid_evidence")
    requests = {(r["component_id"], r["probe_id"]): r for r in report["native_requests"]}
    catalog = {p["id"]: p for p in load_catalog()}
    components = {c["id"]: c for c in report["components"]}
    observations = evidence.get("observations", [])
    if not isinstance(observations, list) or len(observations) > MAX_ITEMS:
        raise ValueError("invalid_evidence")
    counts = Counter((e.get("component_id"), e.get("probe_id")) for e in observations if isinstance(e, dict))
    for entry in observations:
        if not isinstance(entry, dict):
            raise ValueError("invalid_evidence")
        pair = entry.get("component_id"), entry.get("probe_id")
        if pair not in requests:
            raise ValueError("invalid_evidence")
        request, probe, row = requests[pair], catalog[pair[1]], components[pair[0]]
        started, observed = entry.get("started_at"), entry.get("observed_at")
        valid = (counts[pair] == 1 and probe["safety"] == "read_only" and row["enabled"] is True
                 and entry.get("tool") == request["tool"] and number(started) and number(observed)
                 and report["started_at"] <= started <= report["deadline_at"]
                 and started <= observed <= now + 5 and now - observed <= 900)
        status, reason = native_result(probe["adapter"], entry.get("result")) if valid else ("unverified", "invalid_evidence")
        check(row, "probe-" + probe["id"], probe["scope"], status, reason, observed if valid else now, probe["id"])
        if valid and reason != "invalid_evidence":
            # A structured status response proves this tool is callable, not all tools.
            check(row, "runtime", "runtime", "passed", "ok", observed, probe["id"])
            if probe["scope"] == "authentication":
                check(row, "authentication", "authentication", status, reason, observed, probe["id"])
    repair_rows = evidence.get("repairs", [])
    if not isinstance(repair_rows, list):
        raise ValueError("invalid_repair_evidence")
    if repair_rows:
        if before is None:
            raise ValueError("repair_requires_before_snapshot")
        old = validate_snapshot(before)
        seen = set()
        old_plugins = {c["id"]: (c["enabled"], c["version"]) for c in old["components"] if c["kind"] == "plugin"}
        new_plugins = {c["id"]: (c["enabled"], c["version"]) for c in report["components"] if c["kind"] == "plugin"}
        if old_plugins != new_plugins:
            raise ValueError("repair_changed_plugin_selection")
        for entry in repair_rows:
            if not isinstance(entry, dict) or old["sync_outcome"] != "completed" or report["sync_outcome"] != "completed":
                raise ValueError("invalid_repair_evidence")
            cid, rid = entry.get("component_id"), entry.get("repair_id")
            row = components.get(cid)
            if (not row or cid in seen or rid not in REPAIRS or row["owner"] != "toolbox" or row["enabled"] is not True
                    or row["kind"] != "plugin" or row["name"] != REPAIRS[rid][0]
                    or entry.get("before_run_id") != old["run_id"] or entry.get("after_run_id") != report["run_id"]
                    or not number(entry.get("attempted_at")) or not old["started_at"] <= entry["attempted_at"] <= report["started_at"]
                    or type(entry.get("returncode")) is not int):
                raise ValueError("invalid_repair_evidence")
            previous = next((c for c in old["components"] if c["id"] == cid), None)
            if not previous or not any(c["probe_id"] == REPAIRS[rid][1] and c["status"] == "failed" for c in previous["checks"]):
                raise ValueError("repair_requires_failed_check")
            seen.add(cid)
            verified = entry["returncode"] == 0 and any(c["probe_id"] == REPAIRS[rid][1] and c["status"] == "passed" for c in row["checks"])
            report["repairs"].append({"component_id": cid, "repair_id": rid, "status": "passed" if verified else "unverified"})
    for row in report["components"]:
        for item in row["checks"]:
            if item["reason"] == "not_run" and now > report["deadline_at"]:
                item["reason"] = "budget_exhausted"
    return summarize(report)


def validate_snapshot(value):
    """Rebuild an allowlisted report; never echo arbitrary saved JSON fields."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid_snapshot")
    uuid.UUID(value["run_id"])
    if not number(value.get("started_at")) or value.get("deadline_at") != value["started_at"] + 300:
        raise ValueError("invalid_snapshot")
    if value.get("sync_outcome") not in {"not_run", "completed", "failed"}:
        raise ValueError("invalid_snapshot")
    out = {key: value[key] for key in ("schema_version", "run_id", "started_at", "deadline_at", "sync_outcome")}
    out.update(helper_version=VERSION, components=[], inventory_sources=[], native_requests=[], repairs=[])
    for source in value.get("inventory_sources", []):
        if source.get("status") not in STATUSES or source.get("reason") not in REASONS:
            raise ValueError("invalid_snapshot")
        out["inventory_sources"].append({"source": label(source["source"]), "status": source["status"], "reason": source["reason"]})
    ids = set()
    probes = {p["id"]: p for p in load_catalog()}
    for row in value["components"]:
        cid = row["id"]
        if not re.fullmatch(r"(plugin|mcp|skill):[a-f0-9]{20}", cid) or cid in ids or row["kind"] != cid.split(":")[0]:
            raise ValueError("invalid_snapshot")
        if (row.get("owner") not in {"toolbox", "external"} or (row.get("enabled") is not None and type(row.get("enabled")) is not bool)
                or not isinstance(row.get("source_id"), str) or not re.fullmatch(r"[a-f0-9]{20}", row["source_id"])):
            raise ValueError("invalid_snapshot")
        ids.add(cid)
        cleaned = {k: row[k] for k in ("id", "kind", "source_id", "enabled", "owner", "parent_id", "dependencies")}
        cleaned.update(name=label(row["name"]), version=label(row["version"]) if row.get("version") else None, checks=[])
        if row["kind"] == "plugin":
            cleaned["marketplace"] = label(row.get("marketplace", "unknown"))
        if "content_sha256" in row and re.fullmatch(r"[a-f0-9]{64}", row["content_sha256"]):
            cleaned["content_sha256"] = row["content_sha256"]
        for item in row["checks"]:
            if (item.get("status") not in STATUSES or item.get("scope") not in SCOPES or item.get("reason") not in REASONS
                    or not number(item.get("observed_at")) or item.get("probe_id") not in {None, *probes}):
                raise ValueError("invalid_snapshot")
            check(cleaned, label(item["id"]), item["scope"], item["status"], item["reason"], item["observed_at"], item.get("probe_id"))
        out["components"].append(cleaned)
    for row in out["components"]:
        if row["parent_id"] is not None and row["parent_id"] not in ids or not isinstance(row["dependencies"], list) or any(d not in ids for d in row["dependencies"]):
            raise ValueError("invalid_snapshot")
    by_id = {r["id"]: r for r in out["components"]}
    for request in value.get("native_requests", []):
        probe = probes.get(request.get("probe_id"))
        if not probe or probe["adapter"] not in NATIVE or request.get("component_id") not in ids or request.get("tool") != NATIVE[probe["adapter"]] or probe["safety"] != "read_only":
            raise ValueError("invalid_snapshot")
        row = by_id[request["component_id"]]
        parent = by_id.get(row["parent_id"])
        if (row["kind"] != probe["kind"] or row["name"] != probe["target"] or row["owner"] != "toolbox"
                or row["enabled"] is not True or not parent or parent["name"] != probe["plugin"]):
            raise ValueError("invalid_snapshot")
        out["native_requests"].append({"component_id": request["component_id"], "probe_id": probe["id"], "tool": request["tool"], "arguments": {}})
    for entry in value.get("repairs", []):
        if entry.get("component_id") not in ids or entry.get("repair_id") not in REPAIRS or entry.get("status") not in {"passed", "unverified"}:
            raise ValueError("invalid_snapshot")
        out["repairs"].append({k: entry[k] for k in ("component_id", "repair_id", "status")})
    return out


def summarize(report):
    rows = report["components"]
    by_id = {c["id"]: c for c in rows}
    for row in rows:
        for item in row["checks"]:
            if not item["id"].startswith("dependency-") or item["reason"] not in {"dependency_unverified", "missing_dependency", "ok"} or row["enabled"] is False:
                continue
            dependencies = [by_id[d] for d in row["dependencies"] if item["id"] == "dependency-" + by_id[d]["name"]]
            if dependencies:
                required = [c for d in dependencies for c in d["checks"] if c["scope"] in {"configuration", "runtime", "authentication"}]
                if any(d["enabled"] is False for d in dependencies) or any(c["status"] == "failed" for c in required):
                    item.update(status="failed", reason="missing_dependency")
                elif required and all(c["status"] in {"passed", "not_applicable"} for c in required):
                    item.update(status="passed", reason="ok")
                else:
                    item.update(status="unverified", reason="dependency_unverified")
    for row in rows:
        states = {c["status"] for c in row["checks"]}
        row["status"] = "disabled" if row["enabled"] is False else "failed" if "failed" in states else "unverified" if "unverified" in states or row["enabled"] is None else "passed"
    for row in rows:
        for child in rows:
            if child["parent_id"] == row["id"] and child["enabled"] is not False and child["status"] == "failed" and row["enabled"] is not False:
                row["status"] = "failed"
            elif child["parent_id"] == row["id"] and child["enabled"] is not False and child["status"] == "unverified" and row["status"] == "passed":
                row["status"] = "unverified"
    issues = {}
    for row in rows:
        for item in row["checks"]:
            if item["status"] not in {"failed", "unverified"}:
                continue
            reason = item["reason"]
            owner, explanation, action = REASONS[reason]
            recheck = "Run sync-toolbox health-only with safe live checks."
            if reason == "probe_failed":
                repair = next(((rid, spec) for rid, spec in REPAIRS.items() if spec[1] == item["probe_id"]), None)
                if repair:
                    action = "During authorized sync, run " + repair[1][2] + " once from the verified checkout."
                    recheck = "Rerun " + item["probe_id"] + " and its dependent checks."
            dependency = item["id"].removeprefix("dependency-") if item["id"].startswith("dependency-") else None
            related = [by_id[d] for d in row["dependencies"] if dependency == by_id[d]["name"]]
            # The server's concrete error owns the action. Its dependents are
            # attached below, rather than receiving a second generic remedy.
            if dependency and related and any(c["status"] == "failed" for d in related for c in d["checks"]):
                continue
            if dependency and reason == "missing_dependency":
                action = "Restore required dependency " + label(dependency) + " through its owning setup, then recheck."
            # Group required dependency failures by the actual dependency, not skill name.
            shared = ("dependency:" + dependency if dependency and reason == "missing_dependency" else
                      related[0]["id"] if related and reason == "dependency_unverified" else row["id"])
            key = (reason, shared if dependency or owner not in {"coverage", "maintainer"} else reason)
            if key not in issues:
                issues[key] = {"reason": reason, "owner": owner, "problem": explanation, "action": action,
                               "recheck": recheck, "components": [], "scopes": []}
            issue = issues[key]
            issue["components"] = sorted(set(issue["components"] + [row["id"]]))
            issue["scopes"] = sorted(set(issue["scopes"] + [item["scope"]]))
    for issue in issues.values():
        # Include skills that explicitly depend on an affected server.
        affected = set(issue["components"])
        affected.update(row["id"] for row in rows if any(dep in affected for dep in row["dependencies"]))
        issue["components"] = sorted(affected)
    report["issues"] = list(issues.values())
    report["summary"] = {"inventory_complete": bool(report["inventory_sources"]) and all(s["status"] == "passed" for s in report["inventory_sources"]),
                         "components": dict(Counter(c["kind"] for c in rows)),
                         "statuses": dict(Counter(c["status"] for c in rows)),
                         "checks": dict(Counter(c["status"] for row in rows for c in row["checks"])),
                         "live_passed": sum(c["status"] == "passed" and c["probe_id"] is not None for row in rows for c in row["checks"]),
                         "by_scope": {scope: dict(Counter(c["status"] for row in rows for c in row["checks"] if c["scope"] == scope)) for scope in sorted(SCOPES)}}
    return report


def markdown(report):
    summary = report["summary"]
    lines = ["# Toolbox health", "", f"Sync: **{report['sync_outcome']}**. Inventory: **{'complete' if summary['inventory_complete'] else 'incomplete'}**.",
             "Checks prove only their stated scope; skill workflows were not executed.", "",
             "| Component | Discovered |", "|---|---:|"]
    lines += [f"| {kind} | {summary['components'].get(kind, 0)} |" for kind in ("plugin", "mcp", "skill")]
    lines += ["", f"Check results: {json.dumps(summary['checks'], sort_keys=True)}.",
              f"Successful probe checks: {summary['live_passed']}. Verified repairs: {sum(r['status'] == 'passed' for r in report['repairs'])}."]
    lines += ["", "| Evidence scope | Passed | Failed | Unverified | Disabled | Not applicable |", "|---|---:|---:|---:|---:|---:|"]
    for scope, counts in summary["by_scope"].items():
        lines.append("| " + scope + " | " + " | ".join(str(counts.get(status, 0)) for status in ("passed", "failed", "unverified", "disabled", "not_applicable")) + " |")
    names = {c["id"]: c["name"] + ("@" + c["marketplace"] if c.get("marketplace") else "") + " (" + c["id"] + ")" for c in report["components"]}
    for title, user in (("Needs your action", True), ("Other failures and coverage gaps", False)):
        lines += ["", "## " + title, "", "| Components | Problem / affected scope | Next step | Recheck |", "|---|---|---|---|"]
        selected = [i for i in report["issues"] if (i["owner"] == "user") == user]
        for issue in selected:
            listed = issue["components"] if user else issue["components"][:8]
            names_text = ", ".join(names[c] for c in listed)
            if len(listed) < len(issue["components"]):
                names_text += f"; {len(issue['components']) - len(listed)} more (all component IDs are retained in JSON)"
            lines.append(f"| {names_text} | {issue['problem']} ({', '.join(issue['scopes'])}) | {issue['action']} | {issue['recheck']} |")
        if not selected:
            lines.append("| None observed | — | — | — |")
    for source in report["inventory_sources"]:
        if source["status"] != "passed":
            lines += ["", f"Discovery gap: {source['source']} — {REASONS[source['reason']][1]}"]
    return "\n".join(lines) + "\n"


def emit(report, fmt, output=None):
    text = json.dumps(report, indent=2, sort_keys=True) + "\n" if fmt == "json" else markdown(report)
    if output is None:
        print(text, end="")
        return
    path = Path(output).expanduser().resolve()
    # Reject reports inside any Git tree, not just this checkout. Never overwrite.
    if any((parent / ".git").exists() for parent in (path.parent, *path.parent.parents)):
        raise ValueError("output_inside_git")
    root, reason = run_command(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"])
    if reason == "ok":
        raise ValueError("output_inside_git")
    if reason != "probe_failed":
        raise ValueError("output_location_unverified")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--cwd", type=Path, default=Path.cwd())
    collect.add_argument("--toolbox-root", type=Path)
    collect.add_argument("--session", type=Path)
    collect.add_argument("--live", action="store_true")
    collect.add_argument("--sync-outcome", choices=("not_run", "completed", "failed"), default="not_run")
    render = sub.add_parser("report")
    render.add_argument("--snapshot", type=Path, required=True)
    render.add_argument("--evidence", type=Path)
    render.add_argument("--before-snapshot", type=Path)
    for command in (collect, render):
        command.add_argument("--format", choices=("json", "markdown"), default="markdown")
        command.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "collect":
            session = read_json(args.session) if args.session else None
            report = Collector(args.cwd, toolbox_root=args.toolbox_root, session=session).collect(args.live)
            report["sync_outcome"] = args.sync_outcome
        else:
            report = validate_snapshot(read_json(args.snapshot))
            if args.evidence:
                report = apply_evidence(report, read_json(args.evidence), read_json(args.before_snapshot) if args.before_snapshot else None)
            report = summarize(report)
        try:
            emit(report, args.format, args.output)
        except (OSError, ValueError) as error:
            if args.output is None:
                raise
            # Preserve collected evidence without echoing a sensitive file path.
            reason = ("output_exists" if isinstance(error, FileExistsError) else
                      "output_parent_missing" if isinstance(error, FileNotFoundError) else
                      "output_inside_git" if str(error) == "output_inside_git" else "output_unavailable")
            emit(report, args.format)
            print(json.dumps({"schema_version": 1, "error": reason, "report": "stdout"}), file=sys.stderr)
            return 1
        # Nonzero means findings/incomplete checks, not that report generation failed.
        return 1 if report["sync_outcome"] == "failed" or report["issues"] or not report["summary"]["inventory_complete"] else 0
    except Exception:
        print('{"schema_version":1,"error":"health_check_input_or_runtime_unavailable"}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
