"""Private write-ahead receipts and staged, fingerprint-checked publication.

The global guard is independent of the optional receipt directory. A timeout
leaves that guard pending. Reconciliation never dispatches a mutation.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
import sys

from contracts import CommandError


DEFAULT_STATE = Path.home() / ".local" / "state" / "codex-toolbox" / "omnigraffle"
MAX_FILE = 64 * 1024 * 1024


def digest(path):
    p = Path(path)
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
                raise CommandError("unsupported_file", "Expected a regular file of at most 64 MiB")
            h = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
            after = os.fstat(stream.fileno())
        now = p.stat()
        attrs = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if attrs(before) != attrs(after) or attrs(after) != attrs(now):
            raise CommandError("stale_file", "File changed during fingerprinting")
        return h.hexdigest()
    except FileNotFoundError:
        return None


def canonical(path, *, output=False):
    p = Path(path).expanduser()
    if output:
        if p.is_symlink():
            raise CommandError("output_alias", "Output cannot be a symbolic link")
        p = p.parent.resolve(strict=True) / p.name
        if p.exists() and (not p.is_file() or p.stat().st_nlink != 1):
            raise CommandError("output_alias", "Output must be a regular file without hard-link aliases")
    else:
        p = p.resolve(strict=True)
    return p


def private_dir(path):
    p = Path(path).expanduser()
    if p.is_symlink():
        raise CommandError("unsafe_state", "State directory cannot be a symbolic link")
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    s = p.stat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
        raise CommandError("unsafe_state", "State directory must be owned by this user with mode 0700")
    return p.resolve()


def write_json(path, value):
    path = Path(path)
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    fd, temp = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        fsync_dir(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_json(path):
    with Path(path).open("rb") as f:
        raw = f.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise CommandError("invalid_receipt", "Receipt size limit exceeded")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise CommandError("invalid_receipt", "Expected object receipt")
    return value


class Store:
    def __init__(self, receipts=None, *, guard=None):
        self.guard = private_dir(guard or DEFAULT_STATE)
        self.receipts = private_dir(receipts or self.guard / "operations")
        self.identities = private_dir(self.guard / "identities")

    @contextmanager
    def locked(self):
        fd = os.open(self.guard / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise CommandError("busy", "Another OmniGraffle/LaTeXiT operation is active") from error
            yield
        finally:
            os.close(fd)

    def receipt_path(self, operation_id):
        # Public caller validates UUID; also prevent internal misuse.
        import uuid
        if str(uuid.UUID(operation_id)) != operation_id:
            raise CommandError("invalid_operation_id", "Expected canonical UUID")
        registered = self.identities / (operation_id + ".json")
        if registered.exists():
            return Path(read_json(registered)["receipt"])
        return self.receipts / (operation_id + ".json")

    def begin(self, operation_id, command, request):
        path = self.receipt_path(operation_id)
        request_hash = hashlib.sha256(json.dumps([command, request], sort_keys=True, allow_nan=False).encode()).hexdigest()
        if path.exists():
            prior = read_json(path)
            if prior.get("request_sha256") != request_hash:
                raise CommandError("operation_id_conflict", "Operation ID was already used for different data")
            return prior, True
        pending = self.guard / "pending.json"
        if pending.exists():
            record = read_json(pending)
            raise CommandError("reconciliation_required", f"Reconcile operation {record.get('operation_id')} before another operation", unknown=True)
        work = Path(tempfile.mkdtemp(prefix=operation_id + "-", dir=self.receipts))
        receipt = {"schema_version": 1, "operation_id": operation_id, "command": command,
                   "request_sha256": request_hash, "status": "prepared", "phase": "prepared",
                   "created_at": time.time(), "work_directory": str(work), "receipt": str(path),
                   "request": request, "release_accepted": False}
        write_json(path, receipt)
        write_json(self.identities / (operation_id + ".json"), {"receipt": str(path)})
        write_json(pending, {"operation_id": operation_id, "receipt": str(path)})
        return receipt, False

    def save(self, receipt, **updates):
        receipt.update(updates)
        write_json(receipt["receipt"], receipt)

    def finish(self, receipt, status, **updates):
        self.save(receipt, status=status, **updates)
        if status in ("committed", "completed", "rejected", "reconciled_unchanged"):
            pending = self.guard / "pending.json"
            if pending.exists() and read_json(pending).get("operation_id") == receipt["operation_id"]:
                pending.unlink()
                fsync_dir(self.guard)


def check_fingerprint(path, expected, label):
    actual = digest(path)
    if actual != expected:
        raise CommandError("stale_file", f"{label} fingerprint changed")
    return actual


def checked_copy(source, target, expected):
    check_fingerprint(source, expected, "Source")
    with Path(source).open("rb") as src, Path(target).open("xb") as dst:
        os.chmod(target, 0o600)
        shutil.copyfileobj(src, dst, 1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())
    check_fingerprint(source, expected, "Source")
    check_fingerprint(target, expected, "Staged copy")


def copy_metadata(source, target):
    """Preserve destination access controls and extended attributes on replace."""
    if sys.platform == "darwin":
        import ctypes
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        library.copyfile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_uint32]
        library.copyfile.restype = ctypes.c_int
        # SDK copyfile.h: ACL=1, STAT=2, XATTR=4; no data-copy flag.
        if library.copyfile(os.fsencode(source), os.fsencode(target), None, 7):
            raise OSError(ctypes.get_errno(), "Cannot preserve destination metadata")
    else:
        shutil.copystat(source, target, follow_symlinks=False)


def publish(store, receipt, stage, target, expected_target):
    """Copy verified output onto target volume, then atomically publish once."""
    stage, target = Path(stage), Path(target)
    expected_stage = digest(stage)
    if expected_stage is None:
        raise CommandError("verification_failed", "Staged result is missing")
    check_fingerprint(target, expected_target, "Destination")
    if expected_target is not None:
        backup = Path(receipt["work_directory"]) / "destination-original.graffle"
        checked_copy(target, backup, expected_target)
        copy_metadata(target, backup)
        store.save(receipt, backup_path=str(backup))
    # Parent must exist. A private sibling ensures rename is on the same volume.
    fd, temporary = tempfile.mkstemp(prefix=".omnigraffle-", suffix=target.suffix, dir=target.parent)
    os.close(fd)
    os.unlink(temporary)
    staged = Path(temporary)
    try:
        checked_copy(stage, staged, expected_stage)
        if expected_target is not None:
            copy_metadata(target, staged)
        store.save(receipt, phase="publish_pending", publication_stage=str(staged),
                   verified_output_sha256=expected_stage, output=str(target), expected_output_sha256=expected_target)
        check_fingerprint(target, expected_target, "Destination")
        if expected_target is None:
            # Exclusive publication: never replace a file created after the check.
            os.link(staged, target)
            staged.unlink()
        else:
            # Cooperative lock + last fingerprint check; unrelated processes do
            # not participate in the lock. Native open-document guard is separate.
            os.replace(staged, target)
        fsync_dir(target.parent)
        check_fingerprint(target, expected_stage, "Published output")
        store.save(receipt, phase="published", output_sha256=expected_stage)
        return expected_stage
    finally:
        if staged.exists():
            staged.unlink()
