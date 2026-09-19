"""Read-only, protected configuration and key loading. No network or initialization."""

import json
import os
import stat
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .billing import MODEL, MONTHLY_CAP, NANOUSD
from .errors import EvaluationError
from .schema import _unique


def codex_home() -> Path:
    path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    if not path.is_absolute():
        raise EvaluationError("configuration_invalid")
    return path


def check_components(path: Path) -> None:
    # Reject link components below the configured root, not platform aliases such as /var.
    for part in (path, path.parent):
        if part.is_symlink():
            raise EvaluationError("configuration_invalid")


def protected_read(path: Path, limit: int) -> bytes:
    check_components(path)
    if os.name != "posix":
        raise EvaluationError("configuration_invalid")
    try:
        parent = path.parent.stat()
        if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
            raise EvaluationError("configuration_invalid")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1
                    or info.st_size > limit):
                raise EvaluationError("configuration_invalid")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise EvaluationError("configuration_invalid")
            return data
        finally:
            os.close(fd)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise EvaluationError("configuration_invalid") from exc


@dataclass(frozen=True)
class Settings:
    model: str = MODEL
    monthly_limit: int | None = MONTHLY_CAP
    billing_evidence_id: str = ""
    pilot_evidence_id: str = ""
    automatic_research: bool = False


class ConfigStore:
    def __init__(self, secrets: Path | None = None):
        self.secrets = secrets or Path(os.environ.get(
            "CODEX_SECRETS_DIR", str(codex_home() / "secrets")))
        if not self.secrets.is_absolute():
            raise EvaluationError("configuration_invalid")
        if self.secrets.is_symlink() or ".." in self.secrets.parts:
            raise EvaluationError("configuration_invalid")
        self.root = self.secrets / "typesafe"

    def settings(self) -> Settings:
        try:
            data = protected_read(self.root / "config.json", 4096)
        except FileNotFoundError:
            return Settings()
        try:
            raw = json.loads(data, object_pairs_hook=_unique)
            if not isinstance(raw, dict) or not set(raw) <= {
                "model", "monthly_budget_usd", "billing_evidence_id",
                "pilot_evidence_id", "automatic_research",
            }:
                raise ValueError
            configured_budget = raw.get("monthly_budget_usd", "5")
            budget = (None if configured_budget is None
                      else Decimal(str(configured_budget)) * NANOUSD)
            if budget is not None and (not budget.is_finite()
                    or budget != budget.to_integral_value() or not 0 < budget <= MONTHLY_CAP):
                raise ValueError
            if raw.get("model", MODEL) != MODEL:
                raise ValueError
            for name in ("billing_evidence_id", "pilot_evidence_id"):
                if not isinstance(raw.get(name, ""), str) or len(raw.get(name, "")) > 128:
                    raise ValueError
            if type(raw.get("automatic_research", False)) is not bool:
                raise ValueError
            return Settings(MODEL, None if budget is None else int(budget),
                            raw.get("billing_evidence_id", ""),
                            raw.get("pilot_evidence_id", ""), raw.get("automatic_research", False))
        except (ValueError, TypeError, InvalidOperation, UnicodeError) as exc:
            raise EvaluationError("configuration_invalid") from exc

    def api_key(self) -> str:
        try:
            key = protected_read(self.root / "api-key", 4096).decode("ascii").strip()
        except FileNotFoundError as exc:
            raise EvaluationError("credential_missing") from exc
        except UnicodeError as exc:
            raise EvaluationError("configuration_invalid") from exc
        if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise EvaluationError("configuration_invalid")
        return key
