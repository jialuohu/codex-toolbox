"""Build the pasteable CUA controller payload from its readable source."""

import argparse
import hashlib
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SOURCE = SCRIPTS / "controller.js"
OUTPUT = SCRIPTS / "controller.compact.js"
TERSER_VERSION = "5.39.0"


def build() -> bytes:
    source = SOURCE.read_bytes()
    result = subprocess.run(
        ["npm", "exec", "--yes", f"--package=terser@{TERSER_VERSION}", "--",
         "terser", str(SOURCE), "--compress", "--mangle", "--ecma", "2020"],
        capture_output=True, check=True,
    )
    if not result.stdout.strip():
        raise RuntimeError("Terser produced an empty controller")
    header = ("// Generated from controller.js by build-controller-compact.py "
              f"with terser@{TERSER_VERSION}.\n"
              f"// source-sha256: {hashlib.sha256(source).hexdigest()}\n")
    return header.encode("ascii") + result.stdout.rstrip(b"\n") + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare with the checked-in payload")
    args = parser.parse_args()
    payload = build()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != payload:
            raise SystemExit("controller.compact.js is stale; regenerate it")
        print(f"controller.compact.js is current ({len(payload)} bytes)")
    else:
        OUTPUT.write_bytes(payload)
        print(f"wrote {OUTPUT.name} ({len(payload)} bytes)")


if __name__ == "__main__":
    main()
