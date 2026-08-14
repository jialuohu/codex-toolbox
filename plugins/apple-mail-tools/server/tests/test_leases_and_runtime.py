from __future__ import annotations

import json
import time
from pathlib import Path

from apple_mail_tools.leases import LeaseStore
from apple_mail_tools.runtime_stamp import check_stamp, fingerprint, write_stamp


def test_expired_and_malformed_leases_are_cleaned(tmp_path: Path) -> None:
    root = tmp_path / "leases"
    root.mkdir(mode=0o700)
    store = LeaseStore(root)
    token, target, expiry = store.create_target("file.txt")
    target.write_text("body")
    receipt = store.finalize(token, target, expiry, {"name": "file.txt"})
    receipt_path = target.parent / "lease.json"
    value = json.loads(receipt_path.read_text())
    value["expires_at"] = time.time() - 1
    receipt_path.write_text(json.dumps(value))
    receipt_path.chmod(0o600)
    assert store.cleanup_expired() == 1
    assert not Path(receipt["path"]).exists()


def test_runtime_stamp_covers_fixed_bridge(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "src" / "package").mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    (project / "uv.lock").write_text("version = 1\n")
    bridge = project / "scripts" / "mail_bridge.applescript"
    bridge.write_text("return true\n")
    (project / "src" / "package" / "module.py").write_text("VALUE = 1\n")
    stamp = tmp_path / "stamp"
    expected = fingerprint(project)
    write_stamp(project, stamp, expected=expected)
    assert check_stamp(project, stamp) is True
    bridge.write_text("return false\n")
    assert check_stamp(project, stamp) is False
