import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "drawio-tools"
SETUP = ROOT / "scripts" / "setup-drawio-tools.sh"
DESKTOP = PLUGIN / "scripts" / "drawio-desktop.sh"


class DrawioToolsContractTests(unittest.TestCase):
    def test_manifest_mcp_and_lock_are_exact(self) -> None:
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
        mcp = json.loads((PLUGIN / ".mcp.json").read_text())
        lock = json.loads((PLUGIN / "runtime" / "bootstrap" / "package-lock.json").read_text())

        self.assertEqual(manifest["name"], "drawio-tools")
        self.assertEqual(manifest["version"], "0.1.1")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        server = mcp["mcpServers"]["drawio"]
        self.assertEqual(server["command"], "/bin/sh")
        self.assertEqual(server["args"], ["scripts/run-drawio-mcp.sh"])
        self.assertEqual(
            server["enabled_tools"],
            [
                "open_drawio_xml",
                "open_drawio_csv",
                "open_drawio_mermaid",
                "search_shapes",
                "list_pages",
                "get_page",
                "set_page",
            ],
        )
        self.assertEqual(server["default_tools_approval_mode"], "auto")
        self.assertEqual(server["tools"], {"set_page": {"approval_mode": "prompt"}})

        self.assertEqual(lock["packages"][""]["dependencies"]["@drawio/mcp"], "1.4.0")
        package = lock["packages"]["node_modules/@drawio/mcp"]
        self.assertEqual(package["version"], "1.4.0")
        self.assertEqual(
            package["integrity"],
            "sha512-DRg8oveMZSN5rgH6TAtkfaGSm364GzJV53uqJE9ug4EYCORjCgEpapFr0XLi037kq2OXdM2Z/vgAyj7N6vbjiA==",
        )

    def test_check_fails_closed_when_runtime_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as codex_home:
            result = subprocess.run(
                [str(SETUP), "--check"],
                cwd=ROOT,
                env={**os.environ, "CODEX_HOME": codex_home},
                text=True,
                capture_output=True,
            )
            self.assertFalse((Path(codex_home) / "runtime").exists())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime directory is missing", result.stderr)

    def test_desktop_helper_uses_embed_export_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fake = temp / "fake-drawio"
            log = temp / "args.jsonl"
            fake.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    import os
                    import pathlib
                    import sys

                    if sys.argv[1:] == ["--version"]:
                        print("31.1.8")
                        raise SystemExit(0)
                    args = sys.argv[1:]
                    pathlib.Path(os.environ["DRAWIO_TEST_LOG"]).write_text(json.dumps(args))
                    output = pathlib.Path(args[args.index("-o") + 1])
                    fmt = args[args.index("-f") + 1]
                    payload = {"png": b"\\x89PNG\\r\\n\\x1a\\nfixture", "svg": b"<svg/>", "pdf": b"%PDF-fixture"}[fmt]
                    output.write_bytes(payload)
                    """
                )
            )
            fake.chmod(0o755)
            source = temp / "source.drawio"
            source.write_text("<mxfile/>")
            output = temp / "source.svg"
            env = {
                **os.environ,
                "DRAWIO_DESKTOP_BIN": str(fake),
                "DRAWIO_TEST_LOG": str(log),
            }
            subprocess.run(
                [str(DESKTOP), "--doctor"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                [str(DESKTOP), "--export", "svg", str(source), str(output)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            args = json.loads(log.read_text())

        self.assertEqual(args, ["-x", "-f", "svg", "-e", "-b", "10", "-o", str(output), str(source)])


if __name__ == "__main__":
    unittest.main()
