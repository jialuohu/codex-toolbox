"""Explicit, offline verification of the frozen 2026-09-24 campaign evidence.

This check is outside unittest discovery. Both evidence locations must be
supplied by the caller; importing the module reads no local session data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import correction


def verify(results: Path, sessions_day: Path) -> dict:
    audited = correction.build_correction(results, sessions_day)
    summary = audited["summary"]
    expected = {
        "corrected_statuses": {"success": 48, "timeout": 24},
        "timeouts_with_observed_pass_sequences": [38, 41, 47],
        "timeouts_with_verified_ui": 1,
    }
    mismatches = [key for key, value in expected.items() if summary.get(key) != value]
    if len(summary.get("corrected_false_failure_sequences", [])) != 15:
        mismatches.append("corrected_false_failure_sequences")
    if "Synthetic records" in json.dumps(audited):
        mismatches.append("synthetic_records")
    return {"verified": not mismatches, "mismatches": mismatches}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--sessions-day", required=True, type=Path)
    args = parser.parse_args()
    report = verify(args.results, args.sessions_day)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
