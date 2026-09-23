#!/usr/bin/env bash
set -euo pipefail

fixture_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
output_dir="${1:-$(mktemp -d "${TMPDIR:-/tmp}/jev-cu-fixture.XXXXXX")}"
app_path="$output_dir/JevCUFixture.app"

mkdir -p "$app_path/Contents/MacOS"
swiftc -parse-as-library -O -o "$app_path/Contents/MacOS/JevCUFixture" \
  "$fixture_dir/native/JevCUFixture.swift"
cat > "$app_path/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>JevCUFixture</string>
  <key>CFBundleIdentifier</key><string>ai.typesafe.codex.JevCUFixture</string>
  <key>CFBundleName</key><string>JevCUFixture</string>
  <key>CFBundlePackageType</key><string>APPL</string>
</dict></plist>
PLIST

printf '%s\n' "$app_path"
