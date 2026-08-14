from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "stevens-presentation-tools"
SKILLS_ROOT = PLUGIN_ROOT / "skills"
CORE_SKILL = SKILLS_ROOT / "stevens-slides"
MANIFEST_PATH = CORE_SKILL / "references" / "template-manifest.json"
CHECKSUM_PATH = CORE_SKILL / "references" / "asset-checksums.json"
TEMPLATE_CHECKER = CORE_SKILL / "scripts" / "check_templates.py"
SKILL_NAMES = (
    "stevens-slides",
    "stevens-slides-white",
    "stevens-slides-dark",
)


class StevensPresentationToolsTests(unittest.TestCase):
    def test_public_plugin_registration_and_default_install(self) -> None:
        marketplace = json.loads(
            (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
        )
        entry = next(
            plugin
            for plugin in marketplace["plugins"]
            if plugin["name"] == "stevens-presentation-tools"
        )
        self.assertEqual(
            entry["source"],
            {"source": "local", "path": "./plugins/stevens-presentation-tools"},
        )
        self.assertEqual(
            entry["policy"],
            {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        )
        setup = (ROOT / "scripts" / "setup-codex-toolbox.sh").read_text(encoding="utf-8")
        default_body = setup.split("DEFAULT_PLUGINS=(", 1)[1].split(")", 1)[0]
        self.assertEqual(default_body.count('"stevens-presentation-tools"'), 1)

    def test_plugin_and_skill_metadata(self) -> None:
        plugin = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(plugin["name"], "stevens-presentation-tools")
        self.assertEqual(plugin["version"], "0.2.0")
        self.assertEqual(plugin["skills"], "./skills/")
        self.assertNotIn("mcpServers", plugin)
        self.assertEqual(plugin["interface"]["capabilities"], ["Read", "Write"])

        for skill_name in SKILL_NAMES:
            skill_dir = SKILLS_ROOT / skill_name
            skill_text = skill_dir.joinpath("SKILL.md").read_text(encoding="utf-8")
            agent_text = skill_dir.joinpath("agents", "openai.yaml").read_text(encoding="utf-8")
            self.assertTrue(skill_text.startswith("---\nname:"), skill_name)
            self.assertIn("description:", skill_text, skill_name)
            self.assertIn("display_name:", agent_text, skill_name)
            self.assertIn("allow_implicit_invocation: true", agent_text, skill_name)

    def test_manifest_and_distributable_asset_inventory(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "2.0.0")
        self.assertEqual(manifest["defaultTheme"], "white")
        self.assertEqual(set(manifest["themes"]), {"white", "dark"})
        self.assertEqual(
            manifest["templateStructure"]["theme"],
            {"slides": 18, "masters": 2, "layouts": 39, "notesSlides": 18, "indexSlide": 1},
        )
        self.assertEqual(
            manifest["templateStructure"]["gallery"],
            {"slides": 4, "masters": 2, "layouts": 22, "notesSlides": 4},
        )
        self.assertEqual(len(manifest["archetypes"]), 17)
        self.assertEqual(
            [item["slideNumber"] for item in manifest["archetypes"]],
            list(range(2, 19)),
        )

        inventory = json.loads(CHECKSUM_PATH.read_text(encoding="utf-8"))
        self.assertEqual(inventory["algorithm"], "sha256")
        self.assertEqual(len(inventory["files"]), 22)
        self.assertFalse(list(CORE_SKILL.rglob("*.inspect.ndjson")))
        self.assertTrue((CORE_SKILL / "assets" / "licenses" / "Saira-OFL.txt").is_file())
        self.assertTrue((CORE_SKILL / "assets" / "licenses" / "IBM-Plex-OFL.txt").is_file())

    def test_template_bundle_passes_structural_validation(self) -> None:
        result = subprocess.run(
            [sys.executable, TEMPLATE_CHECKER],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Stevens presentation templates: OK", result.stdout)

    def test_public_files_do_not_contain_private_absolute_paths(self) -> None:
        for path in PLUGIN_ROOT.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            self.assertNotIn("/Users/", content, path)

    def test_source_deck_has_no_personal_or_sharepoint_metadata(self) -> None:
        source = (
            CORE_SKILL
            / "assets"
            / "source"
            / "Stevens-PPT-TPL-2022-INSTRUCT.pptx"
        )
        with ZipFile(source) as archive:
            names = archive.namelist()
            self.assertNotIn("ppt/authors.xml", names)
            self.assertFalse(
                any(
                    name.startswith(("customXml/", "ppt/comments/", "ppt/people/"))
                    for name in names
                )
            )
            external_relationships = []
            searchable = bytearray()
            for name in names:
                if not name.endswith((".xml", ".rels")):
                    continue
                payload = archive.read(name)
                searchable.extend(payload)
                if name.endswith(".rels") and b'TargetMode="External"' in payload:
                    external_relationships.append(name)

        text = searchable.decode("utf-8", errors="ignore")
        self.assertFalse(external_relationships)
        self.assertIsNone(
            re.search(
                r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
                text,
                flags=re.IGNORECASE,
            )
        )
        for forbidden in (
            "/Users/",
            "C:\\Users\\",
            "userId=",
            "providerId=",
            "SharedWithUsers",
            "TaxCatchAll",
            "DocumentLibraryForm",
        ):
            self.assertNotIn(forbidden, text)
        self.assertRegex(text, r"<dc:creator>Walnut Exporter</dc:creator>")
        self.assertRegex(
            text,
            r"<lastModifiedBy>Walnut Exporter</lastModifiedBy>",
        )

    def test_all_powerpoint_assets_exclude_private_package_metadata(self) -> None:
        decks = sorted((CORE_SKILL / "assets").rglob("*.pptx"))
        self.assertEqual(len(decks), 4)
        for deck in decks:
            with ZipFile(deck) as archive:
                names = archive.namelist()
                self.assertNotIn("ppt/authors.xml", names, deck)
                self.assertFalse(
                    any(
                        name.startswith(("customXml/", "ppt/comments/", "ppt/people/"))
                        for name in names
                    ),
                    deck,
                )
                searchable = b"".join(
                    archive.read(name)
                    for name in names
                    if name.endswith((".xml", ".rels"))
                ).decode("utf-8", errors="ignore")
            emails = {
                match.casefold()
                for match in re.findall(
                    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
                    searchable,
                    flags=re.IGNORECASE,
                )
            }
            self.assertLessEqual(
                emails,
                {"name@stevens.edu"},
                deck,
            )
            for forbidden in (
                "Stacey Greene",
                "agreene@stevens.edu",
                "Ivan Caro",
                "Michael Hofman",
                "/Users/",
                "C:\\Users\\",
                "userId=",
                "providerId=",
                "SharedWithUsers",
                "TaxCatchAll",
                "DocumentLibraryForm",
                'TargetMode="External"',
            ):
                self.assertNotIn(forbidden, searchable, deck)

    def test_eps_brand_assets_have_neutral_metadata(self) -> None:
        eps_assets = sorted((CORE_SKILL / "assets" / "brand").glob("*.eps"))
        self.assertEqual(len(eps_assets), 4)
        for asset in eps_assets:
            payload = asset.read_bytes()
            self.assertNotIn(b"Michael Hofman", payload, asset)
            self.assertNotRegex(
                payload,
                rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
                rb"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
                asset,
            )
            self.assertIn(b"%%For: (Stevens Assets)", payload, asset)


if __name__ == "__main__":
    unittest.main()
