from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_fixed_bridge_has_no_shell_send_or_permanent_delete_path() -> None:
    script = (ROOT / "scripts" / "mail_bridge.applescript").read_text()
    lowered = script.casefold()
    assert "do shell script" not in lowered
    assert "run script" not in lowered
    assert re.search(r"\bsend\s+(?:draft|message|outgoing|source)", lowered) is None
    assert re.search(r"\bdelete\s+(?:message|mailbox|account)", lowered) is None
    assert "empty trash" not in lowered
    assert "source of message" not in lowered


def test_server_logs_no_message_content() -> None:
    source = "\n".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    assert "logging." not in source
    assert "print(body" not in source
    assert "shell=True" not in source
