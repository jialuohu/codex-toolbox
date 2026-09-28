"""Explicit operator adoption for an uncertain thread/start receipt."""

from __future__ import annotations

import argparse
import asyncio
import json

from .ipc import BrokerUnavailable, broker_request


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover an uncertain Codex task creation")
    sub = parser.add_subparsers(dest="action", required=True)
    adopt = sub.add_parser("adopt", help="Adopt a user-confirmed task ID for an unknown creation")
    adopt.add_argument("--idempotency-key", required=True)
    adopt.add_argument("--task-id", required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(broker_request("recover_adopt", {
            "idempotency_key": args.idempotency_key, "task_id": args.task_id,
        }))
    except BrokerUnavailable as exc:
        result = {"ok": False, "error": {"code": "broker_unavailable", "message": str(exc)}}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1
