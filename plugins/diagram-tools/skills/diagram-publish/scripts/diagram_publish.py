#!/usr/bin/env python3
"""Publish accepted standalone HTML. Import and default status are offline.

The caller owns content acceptance and conversation authorization. This module
enforces installation opt-in, exact bytes, target identity and upload isolation.
All provider and subprocess output is untrusted and is never echoed verbatim.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


WRANGLER_VERSION = "4.135.0"
MAX_HTML = 25 * 1024 * 1024
API = "https://api.cloudflare.com/client/v4"
HEADERS = b"/*\n  X-Robots-Tag: noindex, nofollow\n  X-Content-Type-Options: nosniff\n"
PLUGIN = Path(__file__).resolve().parents[3]
RUNTIME_SOURCE = PLUGIN / "runtime" / "publisher"


class PublishError(Exception):
    """Only controlled error codes cross the CLI boundary."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PublishError("unsafe_state_directory")


def read_file(path, limit, *, private=False):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise PublishError("unsafe_or_oversized_file")
            if private and (info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1):
                raise PublishError("unsafe_private_file")
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise PublishError("unsafe_or_oversized_file")
            return data
    except OSError as exc:
        raise PublishError("file_unavailable_or_symlink") from exc


def write_json(path, value):
    private_dir(path.parent)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def json_file(path):
    try:
        return json.loads(read_file(path, 8 * 1024 * 1024, private=True))
    except (ValueError, UnicodeError) as exc:
        raise PublishError("invalid_state_json") from exc


class ResourceParser(HTMLParser):
    """Check declarative resources, not arbitrary JavaScript behavior."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.has_html = False
        self.in_style = False
        self.styles = []

    @staticmethod
    def url(value):
        value = value.strip()
        compact = re.sub(r"[\x00-\x20]", "", value).lower()
        if not value or value.startswith("#") or compact.startswith("data:"):
            return
        if compact.startswith(("https://", "http://", "mailto:", "tel:")):
            parsed = urlsplit(compact)
            if parsed.scheme in ("http", "https"):
                host = unquote(parsed.hostname or "").rstrip(".")
                if not host or host == "localhost" or host.endswith((".localhost", ".local", ".localdomain", ".lan", ".internal")):
                    raise PublishError("local_resource_reference")
                try:
                    # inet_aton also normalizes legacy IPv4 spellings (127.1,
                    # hex, octal). It performs no DNS lookup or network I/O.
                    try:
                        address = ipaddress.ip_address(socket.inet_aton(host))
                    except OSError:
                        address = ipaddress.ip_address(host)
                    if not address.is_global:
                        raise PublishError("local_resource_reference")
                except ValueError:
                    if "." not in host:
                        raise PublishError("local_resource_reference") from None
            return
        # Relative/root URLs, file:, drive paths, and protocol-relative resources
        # cannot be assumed to survive publication of a single standalone file.
        raise PublishError("non_standalone_resource_reference")

    def handle_starttag(self, tag, attrs):
        self.has_html |= tag == "html"
        self.in_style |= tag == "style"
        if tag == "meta" and dict(attrs).get("http-equiv", "").lower() == "refresh":
            raise PublishError("unsupported_meta_refresh")
        for key, value in attrs:
            if value is None:
                continue
            if key in ("src", "href", "poster", "data", "action", "formaction", "xlink:href"):
                self.url(value)
            if key in ("srcset", "srcdoc"):
                raise PublishError("unsupported_embedded_resource")
            if key == "style":
                self.styles.append(value)

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)


def accepted_html(path, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise PublishError("invalid_expected_sha256")
    data = read_file(path, MAX_HTML)
    if digest(data) != expected:
        raise PublishError("artifact_hash_changed")
    try:
        source = data.decode("utf-8")
        parser = ResourceParser()
        parser.feed(source)
        parser.close()
        if not parser.has_html:
            raise PublishError("not_html_document")
        for css in parser.styles:
            for match in re.finditer(r"url\(\s*(['\"]?)(.*?)\1\s*\)", css, re.I | re.S):
                parser.url(match.group(2))
            # Quoted CSS imports do not use url().
            for match in re.finditer(r"@import\s+['\"]([^'\"]+)['\"]", css, re.I):
                parser.url(match.group(1))
    except (UnicodeError, ValueError) as exc:
        raise PublishError("invalid_html") from exc
    return data


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_request(method, url, headers, body=None, limit=2 * 1024 * 1024):
    request = Request(url, data=body, headers=headers, method=method)
    try:
        try:
            response = build_opener(NoRedirect()).open(request, timeout=20)
        except HTTPError as exc:
            response = exc
        with response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise PublishError("provider_response_too_large")
            return response.status, {k.lower(): v for k, v in response.headers.items()}, data
    except (URLError, TimeoutError, OSError) as exc:
        raise PublishError("network_unavailable") from exc


class Publisher:
    def __init__(self, *, env=None, transport=http_request, runner=subprocess.run, sleep=time.sleep):
        self.env = dict(os.environ if env is None else env)
        self.home = Path(self.env.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
        self.root = self.home / "diagram-publish"
        self.config_path = self.root / "config.json"
        self.ledger_path = self.root / "publications.json"
        try:
            self.lock_hash = digest(read_file(RUNTIME_SOURCE / "package-lock.json", 2 * 1024 * 1024))
        except PublishError:
            self.lock_hash = "missing"
        self.runtime = self.home / "runtime" / "diagram-tools" / "publisher" / (WRANGLER_VERSION + "-" + self.lock_hash[:16])
        self.secrets_root = Path(self.env.get("CODEX_SECRETS_DIR", str(self.home / "secrets"))).expanduser().resolve()
        self.transport, self.runner, self.sleep = transport, runner, sleep

    @contextlib.contextmanager
    def lock(self):
        private_dir(self.root)
        fd = os.open(self.root / "operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise PublishError("unsafe_lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise PublishError("operation_in_progress") from exc
            yield
        finally:
            os.close(fd)

    def config(self):
        if self.root.exists() or self.root.is_symlink():
            info = self.root.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise PublishError("unsafe_state_directory")
        if not self.config_path.exists() and not self.config_path.is_symlink():
            return None
        value = json_file(self.config_path)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise PublishError("invalid_configuration")
        for key, pattern in (("account_id", r"[a-f0-9]{32}"), ("project_name", r"codex-diagrams-[a-f0-9]{16}"),
                             ("project_id", r"[A-Za-z0-9-]{1,128}")):
            if not isinstance(value.get(key), str) or not re.fullmatch(pattern, value[key]):
                raise PublishError("invalid_configuration")
        if value.get("mode") not in ("off", "auto") or value.get("production_branch") != "main" or not isinstance(value.get("token_file"), str):
            raise PublishError("invalid_configuration")
        return value

    def token(self, path):
        path = Path(path).expanduser().absolute()
        if not path.resolve().is_relative_to(self.secrets_root):
            raise PublishError("token_outside_secrets_directory")
        if any((parent / ".git").exists() for parent in [path.parent, *path.parents]):
            raise PublishError("token_inside_git_worktree")
        for parent in path.parents:
            if parent == self.secrets_root:
                break
            if parent.is_symlink():
                raise PublishError("unsafe_token_path")
        raw = read_file(path, 4096, private=True)
        try:
            token = raw.decode("ascii").strip()
        except UnicodeError as exc:
            raise PublishError("invalid_token_file") from exc
        if not re.fullmatch(r"[A-Za-z0-9_\-]{20,256}", token):
            raise PublishError("invalid_token_file")
        return token

    def api(self, method, suffix, token, payload=None):
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        body = None if payload is None else json.dumps(payload).encode()
        status, _, raw = self.transport(method, API + suffix, headers, body)
        if not 200 <= status < 300:
            raise PublishError(f"provider_http_{status}")
        try:
            value = json.loads(raw)
            if value.get("success") is not True:
                raise PublishError("provider_rejected_request")
            return value["result"]
        except (ValueError, KeyError, AttributeError) as exc:
            raise PublishError("invalid_provider_response") from exc

    @staticmethod
    def project_path(config):
        return f"/accounts/{config['account_id']}/pages/projects/{config['project_name']}"

    def project(self, config, token):
        value = self.api("GET", self.project_path(config), token)
        if not isinstance(value, dict) or value.get("id") != config["project_id"] or value.get("name") != config["project_name"]:
            raise PublishError("project_identity_changed")
        if value.get("production_branch") != config["production_branch"]:
            raise PublishError("production_branch_changed")
        if value.get("source") or value.get("uses_functions"):
            raise PublishError("project_not_static_direct_upload")
        return value

    def runtime_status(self):
        try:
            package = json.loads(read_file(self.runtime / "node_modules/wrangler/package.json", 128 * 1024))
            receipt = json_file(self.runtime / "receipt.json")
            if not isinstance(package, dict) or not isinstance(receipt, dict):
                return "stale"
            if package.get("version") != WRANGLER_VERSION or receipt.get("lock_sha256") != self.lock_hash:
                return "stale"
            if not (self.runtime / "node_modules/wrangler/bin/wrangler.js").is_file():
                return "missing"
            return "ready"
        except (PublishError, ValueError):
            return "missing"

    def node(self):
        executable = shutil.which("node", path=self.env.get("PATH"))
        if not executable:
            raise PublishError("node_22_required")
        try:
            result = self.runner([executable, "--version"], capture_output=True, timeout=10, env={"PATH": self.env.get("PATH", "")})
        except (OSError, subprocess.SubprocessError) as exc:
            raise PublishError("node_22_required") from exc
        try:
            if result.returncode != 0 or int(result.stdout.decode().strip().lstrip("v").split(".")[0]) < 22:
                raise ValueError()
        except (ValueError, AttributeError):
            raise PublishError("node_22_required") from None
        return executable

    def install_runtime(self):
        with self.lock():
            return self._install_runtime()

    def _install_runtime(self):
        self.node()
        if self.runtime_status() == "ready":
            return {"ok": True, "status": "ready", "runtime_version": WRANGLER_VERSION}
        npm = shutil.which("npm", path=self.env.get("PATH"))
        if not npm:
            raise PublishError("npm_required")
        self.runtime.parent.mkdir(parents=True, exist_ok=True)
        if self.runtime.exists() or self.runtime.is_symlink():
            info = self.runtime.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise PublishError("unsafe_runtime_directory")
        stage = Path(tempfile.mkdtemp(prefix=".publisher-install-", dir=self.runtime.parent))
        try:
            for name in ("package.json", "package-lock.json"):
                (stage / name).write_bytes(read_file(RUNTIME_SOURCE / name, 2 * 1024 * 1024))
            (stage / "home").mkdir(mode=0o700)
            child_env = {"PATH": self.env.get("PATH", ""), "HOME": str(stage / "home"), "CI": "true",
                         "npm_config_userconfig": os.devnull, "npm_config_registry": "https://registry.npmjs.org/"}
            result = self.runner([npm, "ci", "--no-audit", "--no-fund"], cwd=stage, env=child_env,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
            if result.returncode:
                raise PublishError("runtime_install_failed")
            package = json.loads((stage / "node_modules/wrangler/package.json").read_text())
            if package.get("version") != WRANGLER_VERSION:
                raise PublishError("runtime_version_mismatch")
            shutil.rmtree(stage / "home")
            write_json(stage / "receipt.json", {"version": WRANGLER_VERSION, "lock_sha256": digest((stage / "package-lock.json").read_bytes())})
            retired = None
            if self.runtime.exists():
                retired = self.runtime.with_name(self.runtime.name + ".retired-" + secrets.token_hex(8))
                os.rename(self.runtime, retired)
            try:
                os.rename(stage, self.runtime)
            except OSError:
                if retired is not None and not self.runtime.exists():
                    os.rename(retired, self.runtime)
                raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return {"ok": True, "status": "ready", "runtime_version": WRANGLER_VERSION}

    def setup(self, account_id, token_file, auto=False):
        if self.blocked():
            raise PublishError("publishing_disabled")
        if not re.fullmatch(r"[a-f0-9]{32}", account_id or ""):
            raise PublishError("invalid_account_id")
        if self.runtime_status() != "ready":
            raise PublishError("publisher_runtime_not_ready")
        self.node()
        token = self.token(token_file)
        with self.lock():
            existing = self.config()
            if existing:
                if existing["account_id"] != account_id or existing["token_file"] != str(Path(token_file).expanduser().absolute()):
                    raise PublishError("already_configured_for_another_target")
                self.project(existing, token)
                existing["mode"] = "auto" if auto else "off"
                write_json(self.config_path, existing)
                return {"ok": True, "status": "configured", "mode": existing["mode"], "project": existing["project_name"]}
            # Persist the project name before POST; retrying setup reconciles it.
            pending_path = self.root / "setup-attempt.json"
            needs_create = False
            had_pending = pending_path.exists()
            if had_pending:
                pending = json_file(pending_path)
                if pending.get("account_id") != account_id:
                    raise PublishError("unresolved_setup_for_another_account")
                name = pending.get("name", "")
                if not re.fullmatch(r"codex-diagrams-[a-f0-9]{16}", name):
                    raise PublishError("invalid_setup_attempt")
                try:
                    project = self.api("GET", f"/accounts/{account_id}/pages/projects/{name}", token)
                except PublishError as exc:
                    if str(exc) != "provider_http_404":
                        raise PublishError("setup_outcome_unknown") from exc
                    # Reuse the exact name after a user repeats setup. Project
                    # names are unique within the account; never mint a second
                    # name while the original create outcome is uncertain.
                    needs_create = True
            else:
                name = "codex-diagrams-" + secrets.token_hex(8)
                # Probe the selected account before any mutation.
                self.api("GET", f"/accounts/{account_id}/pages/projects?page=1&per_page=1", token)
                write_json(pending_path, {"account_id": account_id, "name": name})
                needs_create = True
            if needs_create:
                try:
                    project = self.api("POST", f"/accounts/{account_id}/pages/projects", token,
                                       {"name": name, "production_branch": "main"})
                except PublishError as exc:
                    if not had_pending and str(exc) in {"provider_http_400", "provider_http_401", "provider_http_403", "provider_http_404", "provider_http_405", "provider_http_413", "provider_http_422", "provider_http_429"}:
                        pending_path.unlink()
                        raise
                    raise PublishError("setup_outcome_unknown") from exc
            if not isinstance(project, dict) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", str(project.get("id", ""))):
                raise PublishError("invalid_project_response")
            config = {"schema_version": 1, "account_id": account_id, "project_name": name,
                      "project_id": project["id"], "production_branch": "main",
                      "token_file": str(Path(token_file).expanduser().absolute()), "mode": "auto" if auto else "off"}
            self.project(config, token)
            write_json(self.config_path, config)
            pending_path.unlink()
        return {"ok": True, "status": "configured", "mode": config["mode"], "project": name}

    def blocked(self):
        return self.env.get("CODEX_TOOLBOX_NO_PUBLISH") == "1" or self.env.get("CI", "").lower() not in ("", "0", "false")

    def status(self, online=False):
        try:
            config = self.config()
        except PublishError:
            return {"ok": False, "status": "invalid_configuration", "mode": "off", "runtime": self.runtime_status()}
        result = {"ok": True, "status": "configured" if config else "unconfigured", "mode": config["mode"] if config else "off",
                  "runtime": self.runtime_status(), "suppressed": self.blocked()}
        if online and config:
            self.project(config, self.token(config["token_file"]))
            result["connection"] = "verified"
        return result

    def ledger(self):
        if not self.ledger_path.exists() and not self.ledger_path.is_symlink():
            return []
        value = json_file(self.ledger_path)
        if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("publications"), list):
            raise PublishError("invalid_publication_ledger")
        records = value["publications"]
        for record in records:
            if not isinstance(record, dict) or not re.fullmatch(r"diagram-[a-f0-9]{32}", str(record.get("branch", ""))) or not re.fullmatch(r"[a-f0-9]{64}", str(record.get("sha256", ""))):
                raise PublishError("invalid_publication_ledger")
        return records

    def save(self, records):
        write_json(self.ledger_path, {"schema_version": 1, "publications": records})

    def list_publications(self):
        return {"ok": True, "publications": self.ledger()}

    @staticmethod
    def deployment_url(url, config):
        if not isinstance(url, str):
            raise PublishError("invalid_deployment_url")
        try:
            parsed = urlsplit(url)
            parsed.port
        except ValueError as exc:
            raise PublishError("invalid_deployment_url") from exc
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise PublishError("invalid_deployment_url")
        if not re.fullmatch(r"[a-z0-9]+\." + re.escape(config["project_name"]) + r"\.pages\.dev", parsed.netloc):
            raise PublishError("invalid_deployment_url")
        return url

    @staticmethod
    def deployment_branch(deployment):
        if not isinstance(deployment, dict):
            raise PublishError("invalid_deployment_response")
        trigger = deployment.get("deployment_trigger")
        if not isinstance(trigger, dict) or not isinstance(trigger.get("metadata"), dict):
            raise PublishError("invalid_deployment_response")
        branch = trigger["metadata"].get("branch")
        if not isinstance(branch, str):
            raise PublishError("invalid_deployment_response")
        return branch

    def verify(self, deployment, record, config):
        if not isinstance(deployment, dict) or deployment.get("project_id") != config["project_id"] or deployment.get("project_name") != config["project_name"] or deployment.get("environment") != "preview":
            raise PublishError("deployment_target_mismatch")
        if self.deployment_branch(deployment) != record["branch"] or record["branch"] == config["production_branch"]:
            raise PublishError("deployment_branch_mismatch")
        deployment_id = deployment.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", deployment_id):
            raise PublishError("invalid_deployment_id")
        # Retain the identity of a correctly targeted deployment even when it
        # is not yet public or its response fails verification. It can then be
        # explicitly removed through the normal recorded-deployment interface.
        record["deployment_id"] = deployment_id
        stage = deployment.get("latest_stage")
        if not isinstance(stage, dict):
            raise PublishError("invalid_deployment_response")
        if stage.get("name") != "deploy" or stage.get("status") != "success":
            raise PublishError("deployment_not_ready")
        url = self.deployment_url(deployment.get("url"), config)
        # No cookies or Authorization, and redirects are rejected by transport.
        # Cloudflare can reject urllib's default user agent (error 1010).
        # Identify the verifier explicitly without adding authentication.
        status, headers, body = self.transport("GET", url, {
            "Accept-Encoding": "identity",
            "User-Agent": "codex-toolbox-diagram-publish/0.5.0",
        }, limit=MAX_HTML)
        if status != 200:
            raise PublishError("deployment_not_public")
        if headers.get("content-type", "").split(";")[0].strip().lower() != "text/html":
            raise PublishError("unexpected_content_type")
        if digest(body) != record["sha256"]:
            raise PublishError("published_content_mismatch")
        if "noindex" not in headers.get("x-robots-tag", "").lower():
            raise PublishError("missing_noindex_header")
        return {"deployment_id": deployment_id, "url": url}

    def reconcile(self, config, token, record):
        if record.get("deployment_id") or record.get("hint_deployment_id"):
            deployment_id = record.get("deployment_id") or record["hint_deployment_id"]
            if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", deployment_id):
                raise PublishError("invalid_deployment_id")
            try:
                deployment = self.api("GET", self.project_path(config) + "/deployments/" + deployment_id, token)
            except PublishError as exc:
                if record.get("deployment_id") or str(exc) != "provider_http_404":
                    raise
            else:
                return self.verify(deployment, record, config)
        matches = []
        for page in range(1, 101):
            values = self.api("GET", self.project_path(config) + f"/deployments?env=preview&page={page}&per_page=25", token)
            if not isinstance(values, list):
                raise PublishError("invalid_deployment_list")
            matches.extend(item for item in values if self.deployment_branch(item) == record["branch"])
            if len(values) < 25:
                break
        else:
            raise PublishError("reconciliation_incomplete")
        if len(matches) != 1:
            raise PublishError("outcome_unknown" if not matches else "multiple_deployments_for_attempt")
        deployment_id = matches[0].get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", deployment_id):
            raise PublishError("invalid_deployment_id")
        deployment = self.api("GET", self.project_path(config) + "/deployments/" + deployment_id, token)
        return self.verify(deployment, record, config)

    def run_upload(self, config, token, record, data):
        node = self.node()
        if self.runtime_status() != "ready":
            raise PublishError("publisher_runtime_not_ready")
        with tempfile.TemporaryDirectory(prefix="diagram-publish-") as temporary:
            work = Path(temporary).resolve()
            for parent in (work, *work.parents):
                if any((parent / name).exists() for name in (".git", "wrangler.toml", "wrangler.json", "wrangler.jsonc", ".env", ".dev.vars")):
                    raise PublishError("ambient_project_configuration")
            assets, home = work / "assets", work / "home"
            assets.mkdir(mode=0o700)
            home.mkdir(mode=0o700)
            (assets / "index.html").write_bytes(data)
            (assets / "_headers").write_bytes(HEADERS)
            if digest((assets / "index.html").read_bytes()) != record["sha256"]:
                raise PublishError("staged_hash_changed")
            child_env = {"PATH": str(Path(node).parent) + os.pathsep + "/usr/bin:/bin", "HOME": str(home),
                         "XDG_CONFIG_HOME": str(home / "config"), "XDG_CACHE_HOME": str(home / "cache"),
                         "CLOUDFLARE_API_TOKEN": token, "CLOUDFLARE_ACCOUNT_ID": config["account_id"],
                         "WRANGLER_SEND_METRICS": "false", "WRANGLER_LOG_SANITIZE": "true",
                         "WRANGLER_LOG_PATH": str(work / "wrangler.log"),
                         "WRANGLER_OUTPUT_FILE_PATH": str(work / "output.ndjson"), "CI": "true", "NO_COLOR": "1"}
            args = [node, str(self.runtime / "node_modules/wrangler/bin/wrangler.js"), "pages", "deploy", str(assets),
                    "--project-name", config["project_name"], "--branch", record["branch"], "--commit-message", "Diagram publication"]
            # Exit status/output is not authoritative. Even a timeout may have
            # created a deployment; the API reconciliation below owns success.
            try:
                self.runner(args, cwd=work, env=child_env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
            except subprocess.TimeoutExpired:
                pass
            except OSError as exc:
                raise PublishError("uploader_could_not_start") from exc
            # Structured output is only a lookup hint. Identity, status and
            # public bytes must still pass the independent API/HTTP checks.
            try:
                output = read_file(work / "output.ndjson", 2 * 1024 * 1024).decode("utf-8")
                for line in output.splitlines():
                    event = json.loads(line)
                    if (isinstance(event, dict) and event.get("type") == "pages-deploy"
                            and event.get("version") == 1 and event.get("pages_project") == config["project_name"]
                            and re.fullmatch(r"[A-Za-z0-9-]{1,128}", str(event.get("deployment_id", "")))):
                        return event["deployment_id"]
            except (PublishError, ValueError, UnicodeError):
                pass
            return None

    def publish(self, path, expected, *, reviewed=False, local_only=False):
        if local_only or self.blocked():
            return {"ok": True, "status": "local_only"}
        config = self.config()
        if not config or config["mode"] != "auto":
            return {"ok": True, "status": "publishing_disabled"}
        if not reviewed:
            raise PublishError("visual_review_required")
        data = accepted_html(path, expected)
        token = self.token(config["token_file"])
        if self.runtime_status() != "ready":
            raise PublishError("publisher_runtime_not_ready")
        self.node()
        with self.lock():
            current = self.config()
            if not current or current["mode"] != "auto":
                return {"ok": True, "status": "publishing_disabled"}
            if current != config:
                raise PublishError("configuration_changed")
            self.project(config, token)
            records = self.ledger()
            key = {"account_id": config["account_id"], "project_id": config["project_id"], "sha256": expected}
            record = next((r for r in records if all(r.get(k) == v for k, v in key.items()) and r.get("status") != "removed"), None)
            if record is None:
                record = {**key, "branch": "diagram-" + secrets.token_hex(16), "status": "pending", "created_at": int(time.time())}
                records.append(record)
                self.save(records)
                try:
                    hint = self.run_upload(config, token, record, data)
                    if hint:
                        record["hint_deployment_id"] = hint
                        self.save(records)
                except PublishError as exc:
                    # No subprocess has started when run_upload raises this
                    # controlled preflight error. Keep the receipt actionable.
                    record.update(status="not_uploaded", last_error=str(exc))
                    self.save(records)
                    raise
            elif record.get("status") == "not_uploaded":
                record["status"] = "pending"
                self.save(records)
                try:
                    hint = self.run_upload(config, token, record, data)
                    if hint:
                        record["hint_deployment_id"] = hint
                        self.save(records)
                except PublishError as exc:
                    record.update(status="not_uploaded", last_error=str(exc))
                    self.save(records)
                    raise
            # Any preexisting attempt is read/reconciled, never uploaded again.
            last_error = "outcome_unknown"
            for delay in (0, 1, 2, 4, 8, 15, 30):
                self.sleep(delay)
                try:
                    result = self.reconcile(config, token, record)
                    record.update(result, status="verified", verified_at=int(time.time()))
                    record.pop("last_error", None)
                    self.save(records)
                    return {"ok": True, "status": "verified", "sha256": expected, **result}
                except PublishError as exc:
                    last_error = str(exc)
            record.update(status="unresolved", last_error=last_error)
            self.save(records)
            return {"ok": False, "status": "outcome_unknown", "reason": last_error, "local_artifact_preserved": True}

    def unpublish(self, deployment_id, *, confirm=False):
        if not confirm:
            raise PublishError("explicit_removal_confirmation_required")
        if self.blocked():
            raise PublishError("publishing_disabled")
        config = self.config()
        if not config:
            raise PublishError("not_configured")
        token = self.token(config["token_file"])
        with self.lock():
            self.project(config, token)
            records = self.ledger()
            record = next((r for r in records if r.get("deployment_id") == deployment_id and r.get("account_id") == config["account_id"] and r.get("project_id") == config["project_id"]), None)
            if not record or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", deployment_id or ""):
                raise PublishError("deployment_not_recorded")
            if record.get("status") == "removed":
                return {"ok": True, "status": "removed", "deployment_id": deployment_id}
            endpoint = self.project_path(config) + "/deployments/" + deployment_id
            try:
                deployed = self.api("GET", endpoint, token)
            except PublishError as exc:
                if str(exc) != "provider_http_404":
                    raise
                deployed = None
            if deployed is not None:
                if not isinstance(deployed, dict) or deployed.get("project_id") != config["project_id"] or deployed.get("environment") != "preview" or self.deployment_branch(deployed) != record["branch"]:
                    raise PublishError("removal_target_mismatch")
                record["status"] = "removing"
                self.save(records)
                try:
                    # Every preview has an alias. Force is limited to this
                    # recorded non-production deployment, never the project.
                    self.api("DELETE", endpoint + "?force=true", token)
                except PublishError:
                    pass
                try:
                    self.api("GET", endpoint, token)
                except PublishError as exc:
                    if str(exc) != "provider_http_404":
                        raise PublishError("removal_outcome_unknown") from exc
                else:
                    raise PublishError("removal_outcome_unknown")
            record.update(status="removed", removed_at=int(time.time()))
            self.save(records)
            return {"ok": True, "status": "removed", "deployment_id": deployment_id}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup")
    setup.add_argument("--install-runtime", action="store_true")
    setup.add_argument("--account-id")
    setup.add_argument("--token-file")
    setup.add_argument("--auto", action="store_true")
    status = commands.add_parser("status")
    status.add_argument("--online", action="store_true")
    publish = commands.add_parser("publish-html")
    publish.add_argument("--file", required=True, type=Path)
    publish.add_argument("--expect-sha256", required=True)
    publish.add_argument("--reviewed", action="store_true")
    publish.add_argument("--local-only", action="store_true")
    commands.add_parser("list")
    remove = commands.add_parser("unpublish")
    remove.add_argument("--deployment-id", required=True)
    remove.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    publisher = Publisher()
    try:
        if args.command == "setup":
            if args.install_runtime:
                result = publisher.install_runtime()
            elif args.token_file and args.account_id:
                result = publisher.setup(args.account_id, args.token_file, args.auto)
            else:
                raise PublishError("setup_requires_account_id_and_token_file")
        elif args.command == "status":
            result = publisher.status(args.online)
        elif args.command == "list":
            result = publisher.list_publications()
        elif args.command == "unpublish":
            result = publisher.unpublish(args.deployment_id, confirm=args.confirm)
        else:
            result = publisher.publish(args.file, args.expect_sha256, reviewed=args.reviewed, local_only=args.local_only)
    except PublishError as exc:
        result = {"ok": False, "status": "error", "reason": str(exc)}
    except Exception:
        result = {"ok": False, "status": "error", "reason": "operation_failed"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
