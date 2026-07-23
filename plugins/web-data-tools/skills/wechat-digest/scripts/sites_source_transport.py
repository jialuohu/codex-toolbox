#!/usr/bin/env python3
"""Pinned, credential-safe Git transport for one owner-only Sites source."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import termios
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, TextIO


PROJECT_ROOT = Path("/workspace/info-site")
PROJECT_ID = "sites-project-id"
REMOTE_URL = (
    "https://git.chatgpt-team.site/repository-id/"
    "sites-project-id.git"
)
REMOTE_NAME = "sites"
BRANCH = "main"
PROVIDER = "cloudflare_artifact"
AUTH_MODE = "http_extra_header"
GIT_EXECUTABLE = "/usr/bin/git"
MAX_CREDENTIAL_BYTES = 16_384
MAX_TOKEN_CHARS = 4_096
EXPIRY_SAFETY_MARGIN = timedelta(minutes=2)
GIT_TIMEOUT_SECONDS = 60

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HEAD_REF_RE = re.compile(r"^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
APP_REPOSITORY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
CREDENTIAL_ENV_NAME_RE = re.compile(
    r"(?:^|_)(?:AUTH|OAUTH|CRED|CREDENTIALS?|PASS|PASSWORD|PASSWD|JWT|"
    r"COOKIE|SESSION|TOKEN|SECRET|PAT|APIKEY|API_KEY|ACCESS_KEY|"
    r"PRIVATE_KEY|CLIENT_SECRET|AUTHORIZATION|BEARER|SIGNING_KEY|KEY)"
    r"(?:$|_)",
    re.IGNORECASE,
)
SAFE_AMBIENT_ENV_NAMES = frozenset(
    {
        "CODEX_SECRETS_DIR",
        "NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S",
        "SSH_AUTH_SOCK",
        "TOKENIZERS_PARALLELISM",
    }
)
READINESS_LINE = '{"event":"credential_input_ready"}\n'


ERROR_MESSAGES = {
    "INVALID_ARGUMENTS": "Expected exactly one operation argument.",
    "INVALID_OPERATION": "Operation must be push or readback.",
    "CREDENTIAL_ENV_FORBIDDEN": "Credential environment variables are forbidden.",
    "ROOT_PATH_UNSAFE": "The pinned project root is not a real direct path.",
    "WORKING_DIRECTORY_MISMATCH": "Run the transport only from the pinned project root.",
    "GIT_UNAVAILABLE": "The pinned Git executable is unavailable.",
    "GIT_PREFLIGHT_FAILED": "Git preflight failed safely.",
    "GIT_TOPLEVEL_MISMATCH": "Git top level does not match the pinned project root.",
    "NOT_A_WORKTREE": "The pinned project root is not a working tree.",
    "DETACHED_HEAD": "Detached HEAD is not allowed.",
    "MALFORMED_HEAD_REF": "The local branch reference is malformed.",
    "LOCAL_BRANCH_MISMATCH": "Local branch must be refs/heads/main.",
    "MALFORMED_LOCAL_SHA": "Local HEAD is not a 40-hex commit.",
    "REMOTE_MISSING": "The pinned Sites remote is missing.",
    "REMOTE_AMBIGUOUS": "The pinned Sites remote is ambiguous.",
    "REMOTE_MISMATCH": "The Sites remote does not match the pinned repository.",
    "DIRTY_WORKTREE": "Push requires a clean working tree.",
    "STDIN_TTY_REQUIRED": "Credential input requires a non-echoed terminal.",
    "STDIN_CONTROL_FAILED": "Credential input could not be protected.",
    "CREDENTIAL_INPUT_MISSING": "One credential JSON line is required.",
    "CREDENTIAL_INPUT_TOO_LARGE": "Credential input exceeds the safe size limit.",
    "INVALID_CREDENTIAL_JSON": "Credential input is not valid JSON.",
    "INVALID_CREDENTIAL_OBJECT": "Credential JSON must be an object.",
    "INVALID_REPOSITORY_ID": "Credential repository identity is invalid.",
    "PROJECT_ID_MISMATCH": "Credential project identity does not match.",
    "PROVIDER_MISMATCH": "Credential provider does not match.",
    "BRANCH_MISMATCH": "Credential branch does not match.",
    "AUTH_MODE_MISMATCH": "Credential authentication mode does not match.",
    "INVALID_TOKEN": "Credential token is invalid.",
    "INVALID_EXPIRY": "Credential expiry is invalid.",
    "CREDENTIAL_EXPIRED": "Credential has expired.",
    "CREDENTIAL_EXPIRING": "Credential expires too soon for a safe operation.",
    "LOCAL_STATE_CHANGED": "Local Git state changed during the operation.",
    "GIT_PUSH_FAILED": "Sites source push failed safely.",
    "GIT_READBACK_FAILED": "Sites source readback failed safely.",
    "REMOTE_READBACK_EMPTY": "Sites source readback returned no branch.",
    "REMOTE_READBACK_AMBIGUOUS": "Sites source readback returned multiple branches.",
    "REMOTE_READBACK_MALFORMED": "Sites source readback was malformed.",
    "REMOTE_SHA_MISMATCH": "Remote branch does not equal local HEAD.",
    "INTERNAL_ERROR": "Sites source transport failed safely.",
}


class TransportError(Exception):
    def __init__(self, code: str, *, exit_code: int = 2):
        super().__init__(code)
        self.code = code
        self.message = ERROR_MESSAGES[code]
        self.exit_code = exit_code


@dataclass(frozen=True)
class Runtime:
    root: Path = PROJECT_ROOT
    git_executable: str = GIT_EXECUTABLE


@dataclass(frozen=True)
class Credential:
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class LocalState:
    sha: str


def _raise(code: str, *, exit_code: int = 2) -> None:
    raise TransportError(code, exit_code=exit_code)


def _base_git_environment() -> Dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/var/empty",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def _network_git_environment(token: str) -> Dict[str, str]:
    env = _base_git_environment()
    values = (
        ("http.extraHeader", "Authorization: Bearer " + token),
        ("core.hooksPath", "/dev/null"),
        ("credential.helper", ""),
        ("http.proxy", ""),
    )
    env["GIT_CONFIG_COUNT"] = str(len(values))
    for index, (key, value) in enumerate(values):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


def _run_git(
    runtime: Runtime,
    args: Sequence[str],
    *,
    token: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    env = _network_git_environment(token) if token is not None else _base_git_environment()
    try:
        return subprocess.run(
            [runtime.git_executable, *args],
            cwd=str(runtime.root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        _raise("GIT_UNAVAILABLE", exit_code=3)
    raise AssertionError("unreachable")


def _require_git_output(
    runtime: Runtime,
    args: Sequence[str],
    *,
    failure_code: str = "GIT_PREFLIGHT_FAILED",
) -> str:
    result = _run_git(runtime, args)
    if result.returncode != 0:
        _raise(failure_code, exit_code=3)
    return result.stdout


def _validate_runtime(runtime: Runtime) -> None:
    root = runtime.root
    if not root.is_absolute():
        _raise("ROOT_PATH_UNSAFE")
    try:
        if root.resolve(strict=True) != root:
            _raise("ROOT_PATH_UNSAFE")
        current = Path(os.getcwd())
        if current != root or current.resolve(strict=True) != root:
            _raise("WORKING_DIRECTORY_MISMATCH")
    except (OSError, RuntimeError):
        _raise("ROOT_PATH_UNSAFE")


def _validate_head_ref(value: str) -> None:
    if (
        not HEAD_REF_RE.fullmatch(value)
        or ".." in value
        or "//" in value
        or "@{" in value
        or value.endswith(("/", ".", ".lock"))
    ):
        _raise("MALFORMED_HEAD_REF")


def _read_local_sha(runtime: Runtime) -> str:
    output = _require_git_output(
        runtime,
        ["rev-parse", "--verify", "HEAD^{commit}"],
    ).strip()
    if not SHA_RE.fullmatch(output):
        _raise("MALFORMED_LOCAL_SHA")
    return output


def _validate_remote_output(output: str) -> None:
    lines = [line for line in output.splitlines() if line]
    if not lines:
        _raise("REMOTE_MISSING")
    if len(lines) != 1:
        _raise("REMOTE_AMBIGUOUS")
    if lines[0] != REMOTE_URL:
        _raise("REMOTE_MISMATCH")


def _read_local_state(runtime: Runtime, operation: str) -> LocalState:
    top_level = _require_git_output(
        runtime,
        ["rev-parse", "--show-toplevel"],
    ).strip()
    if top_level != str(runtime.root):
        _raise("GIT_TOPLEVEL_MISMATCH")
    try:
        if Path(top_level).resolve(strict=True) != runtime.root:
            _raise("GIT_TOPLEVEL_MISMATCH")
    except (OSError, RuntimeError):
        _raise("GIT_TOPLEVEL_MISMATCH")

    inside = _require_git_output(
        runtime,
        ["rev-parse", "--is-inside-work-tree"],
    ).strip()
    if inside != "true":
        _raise("NOT_A_WORKTREE")

    symbolic = _run_git(runtime, ["symbolic-ref", "-q", "HEAD"])
    if symbolic.returncode != 0:
        _raise("DETACHED_HEAD")
    head_ref = symbolic.stdout.strip()
    _validate_head_ref(head_ref)
    if head_ref != "refs/heads/main":
        _raise("LOCAL_BRANCH_MISMATCH")

    sha = _read_local_sha(runtime)
    fetch_remote = _run_git(runtime, ["remote", "get-url", "--all", REMOTE_NAME])
    if fetch_remote.returncode != 0:
        _raise("REMOTE_MISSING")
    _validate_remote_output(fetch_remote.stdout)
    push_remote = _run_git(
        runtime,
        ["remote", "get-url", "--push", "--all", REMOTE_NAME],
    )
    if push_remote.returncode != 0:
        _raise("REMOTE_MISSING")
    _validate_remote_output(push_remote.stdout)

    if operation == "push":
        status = _require_git_output(
            runtime,
            ["status", "--porcelain=v1", "--untracked-files=normal"],
        )
        if status:
            _raise("DIRTY_WORKTREE")
    return LocalState(sha=sha)


def _validate_no_credential_environment(environment: Mapping[str, str]) -> None:
    for name in environment:
        if name in SAFE_AMBIENT_ENV_NAMES:
            continue
        if CREDENTIAL_ENV_NAME_RE.search(name):
            _raise("CREDENTIAL_ENV_FORBIDDEN")


def _validate_credential_not_in_environment(
    token: str,
    environment: Mapping[str, str],
) -> None:
    if any(token in value for value in environment.values()):
        _raise("CREDENTIAL_ENV_FORBIDDEN")


def _read_credential_line(stream: TextIO, readiness_output: TextIO) -> str:
    if not stream.isatty():
        _raise("STDIN_TTY_REQUIRED")
    try:
        descriptor = stream.fileno()
        original = termios.tcgetattr(descriptor)
        protected = list(original)
        protected[3] &= ~(termios.ECHO | termios.ECHONL)
        termios.tcsetattr(descriptor, termios.TCSANOW, protected)
    except (AttributeError, OSError, termios.error, ValueError):
        _raise("STDIN_CONTROL_FAILED")

    try:
        try:
            active = termios.tcgetattr(descriptor)
        except (OSError, termios.error):
            _raise("STDIN_CONTROL_FAILED")
        if active[3] & (termios.ECHO | termios.ECHONL):
            _raise("STDIN_CONTROL_FAILED")
        readiness_output.write(READINESS_LINE)
        readiness_output.flush()
        line = stream.readline(MAX_CREDENTIAL_BYTES + 2)
    finally:
        try:
            termios.tcsetattr(descriptor, termios.TCSANOW, original)
        except (OSError, termios.error):
            pass

    if not line:
        _raise("CREDENTIAL_INPUT_MISSING")
    if len(line.encode("utf-8")) > MAX_CREDENTIAL_BYTES:
        _raise("CREDENTIAL_INPUT_TOO_LARGE")
    return line


def _parse_expiry(value: object) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        _raise("INVALID_EXPIRY")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        _raise("INVALID_EXPIRY")
    if parsed.tzinfo is None:
        _raise("INVALID_EXPIRY")
    return parsed.astimezone(timezone.utc)


def _parse_credential(line: str, now: datetime) -> Credential:
    try:
        value = json.loads(line)
    except (json.JSONDecodeError, UnicodeError):
        _raise("INVALID_CREDENTIAL_JSON")
    if not isinstance(value, dict):
        _raise("INVALID_CREDENTIAL_OBJECT")

    app_repository_id = value.get("app_repository_id")
    if (
        not isinstance(app_repository_id, str)
        or not APP_REPOSITORY_ID_RE.fullmatch(app_repository_id)
    ):
        _raise("INVALID_REPOSITORY_ID")
    if value.get("repository") != PROJECT_ID:
        _raise("PROJECT_ID_MISMATCH")
    if value.get("provider") != PROVIDER:
        _raise("PROVIDER_MISMATCH")
    if value.get("branch") != BRANCH:
        _raise("BRANCH_MISMATCH")
    if value.get("remote_url") != REMOTE_URL:
        _raise("REMOTE_MISMATCH")
    if value.get("auth_mode") != AUTH_MODE:
        _raise("AUTH_MODE_MISMATCH")

    token = value.get("token")
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= MAX_TOKEN_CHARS
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in token)
    ):
        _raise("INVALID_TOKEN")

    expires_at = _parse_expiry(value.get("token_expires_at"))
    if expires_at <= now:
        _raise("CREDENTIAL_EXPIRED")
    if expires_at < now + EXPIRY_SAFETY_MARGIN:
        _raise("CREDENTIAL_EXPIRING")
    return Credential(token=token, expires_at=expires_at)


def _read_remote_sha(runtime: Runtime, token: str) -> str:
    result = _run_git(
        runtime,
        [
            "ls-remote",
            "--heads",
            "--exit-code",
            REMOTE_URL,
            "refs/heads/main",
        ],
        token=token,
    )
    if result.returncode != 0:
        _raise("GIT_READBACK_FAILED", exit_code=3)
    lines = [line for line in result.stdout.splitlines() if line]
    if not lines:
        _raise("REMOTE_READBACK_EMPTY", exit_code=3)
    if len(lines) != 1:
        _raise("REMOTE_READBACK_AMBIGUOUS", exit_code=3)
    match = re.fullmatch(r"([0-9a-f]{40})[ \t]+refs/heads/main", lines[0])
    if not match:
        _raise("REMOTE_READBACK_MALFORMED", exit_code=3)
    return match.group(1)


def _require_stable_local_state(runtime: Runtime, expected_sha: str, operation: str) -> None:
    symbolic = _run_git(runtime, ["symbolic-ref", "-q", "HEAD"])
    if symbolic.returncode != 0 or symbolic.stdout.strip() != "refs/heads/main":
        _raise("LOCAL_STATE_CHANGED", exit_code=3)
    if _read_local_sha(runtime) != expected_sha:
        _raise("LOCAL_STATE_CHANGED", exit_code=3)
    if operation == "push":
        status = _require_git_output(
            runtime,
            ["status", "--porcelain=v1", "--untracked-files=normal"],
        )
        if status:
            _raise("LOCAL_STATE_CHANGED", exit_code=3)


def _perform(operation: str, runtime: Runtime, credential: Credential, local: LocalState) -> dict:
    _require_stable_local_state(runtime, local.sha, operation)
    if operation == "push":
        result = _run_git(
            runtime,
            [
                "push",
                "--porcelain",
                "--no-verify",
                REMOTE_URL,
                "HEAD:refs/heads/main",
            ],
            token=credential.token,
        )
        if result.returncode != 0:
            _raise("GIT_PUSH_FAILED", exit_code=3)

    remote_sha = _read_remote_sha(runtime, credential.token)
    _require_stable_local_state(runtime, local.sha, operation)
    if remote_sha != local.sha:
        _raise("REMOTE_SHA_MISMATCH", exit_code=3)
    return {
        "operation": operation,
        "local_sha": local.sha,
        "remote_sha": remote_sha,
        "exact": True,
    }


def _transport(
    argv: Sequence[str],
    runtime: Runtime,
    stdin: TextIO,
    stdout: TextIO,
    environment: Mapping[str, str],
) -> dict:
    if len(argv) != 2:
        _raise("INVALID_ARGUMENTS")
    operation = argv[1]
    if operation not in {"push", "readback"}:
        _raise("INVALID_OPERATION")
    _validate_no_credential_environment(environment)
    _validate_runtime(runtime)
    local = _read_local_state(runtime, operation)
    line = _read_credential_line(stdin, stdout)
    credential = _parse_credential(line, datetime.now(timezone.utc))
    _validate_credential_not_in_environment(credential.token, environment)
    return _perform(operation, runtime, credential, local)


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    runtime: Optional[Runtime] = None,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
    environment: Optional[Mapping[str, str]] = None,
) -> int:
    argv = list(sys.argv if argv is None else argv)
    runtime = Runtime() if runtime is None else runtime
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    environment = os.environ if environment is None else environment
    try:
        receipt = _transport(argv, runtime, stdin, stdout, environment)
    except TransportError as error:
        json.dump(
            {"error": error.code, "message": error.message},
            stderr,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        stderr.write("\n")
        stderr.flush()
        return error.exit_code
    except Exception:
        json.dump(
            {"error": "INTERNAL_ERROR", "message": ERROR_MESSAGES["INTERNAL_ERROR"]},
            stderr,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        stderr.write("\n")
        stderr.flush()
        return 3

    json.dump(receipt, stdout, ensure_ascii=True, separators=(",", ":"))
    stdout.write("\n")
    stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
