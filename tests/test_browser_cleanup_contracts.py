"""Static browser lifecycle contracts; no GUI calls or claims of RAM recovery."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLAYWRIGHT = ROOT / "plugins/web-data-tools/skills/playwright"
PLANNER = ROOT / "plugins/workflow-tools/skills/chatgpt-planner"


def required_reference(entry: str, target: str) -> bool:
    """The mandatory link must precede the entrypoint's first action section."""
    preamble = entry.split("\n## ", 1)[0].lower()
    return f"]({target})" in preamble and any(
        word in preamble for word in ("mandatory", "required")
    )


def unscoped_browser_examples(text: str) -> list[str]:
    """Version/help probes have no browser lifecycle; other PWCLI calls do."""
    return [line for line in text.splitlines()
            if re.match(r'^\s*"\$PWCLI"\s+', line)
            and not re.match(r'^\s*"\$PWCLI"\s+--(?:version|help)\b', line)
            and not re.match(r'^\s*"\$PWCLI"\s+--session "\$PW_SESSION"\s+', line)]


def table_rows(text: str) -> dict[str, str]:
    return {parts[1].strip(): parts[2].strip()
            for line in text.splitlines() if line.startswith("| ")
            and len(parts := line.split("|")) == 4}


class BrowserCleanupContractTests(unittest.TestCase):
    def test_lifecycle_references_are_mandatory_and_reachable(self):
        for skill, target in ((PLAYWRIGHT, "references/lifecycle.md"),
                              (PLANNER, "references/browser-lifecycle.md")):
            with self.subTest(skill=skill.name):
                entry = skill / "SKILL.md"
                text = entry.read_text()
                self.assertTrue(required_reference(text, target))
                self.assertTrue((skill / target).is_file())
                # Removing the required entry link cannot pass on a later list link.
                mutated = text.replace(f"]({target})", "](missing-lifecycle.md)", 1)
                self.assertFalse(required_reference(mutated, target))

    def test_playwright_examples_are_explicitly_scoped(self):
        entry = (PLAYWRIGHT / "SKILL.md").read_text()
        lifecycle = (PLAYWRIGHT / "references/lifecycle.md").read_text()
        self.assertIn('require("node:crypto").randomUUID()', entry)
        self.assertIn("never generate it per command", entry)
        self.assertEqual(unscoped_browser_examples(entry), [])
        self.assertIn('close', entry)
        for command in ("open https://example.com", "snapshot", "close", "detach"):
            with self.subTest(command=command):
                ambient = entry + f'\n"$PWCLI" {command}\n'
                self.assertEqual(unscoped_browser_examples(ambient), [f'"$PWCLI" {command}'])
        self.assertIn("unscoped examples in the imported", lifecycle)
        self.assertIn("inherited `PLAYWRIGHT_CLI_SESSION`", lifecycle)
        self.assertIn("borrowed", lifecycle)
        self.assertIn("do not\nclose or detach that existing session", lifecycle)

    def test_playwright_created_attached_and_borrowed_dispositions_differ(self):
        lifecycle = (PLAYWRIGHT / "references/lifecycle.md").read_text()
        rows = table_rows(lifecycle)
        created = next(v for k, v in rows.items() if k.startswith("Owned `open`"))
        attached = next(v for k, v in rows.items() if k.startswith("Owned `attach`"))
        borrowed = next(v for k, v in rows.items() if k.startswith("Borrowed session"))
        self.assertIn('"$PWCLI" --session "$PW_SESSION" close', created)
        self.assertIn('"$PWCLI" --session "$PW_SESSION" detach', attached)
        self.assertIn("leave the external browser running", attached)
        self.assertIn("Preserve", borrowed)
        self.assertIn('"$PWCLI" --session "$PW_SESSION" list', lifecycle)
        self.assertIn("exact session is no longer running", lifecycle)
        self.assertIn("A command exit\nalone does not establish cleanup", lifecycle)
        self.assertIn("Never use `close-all`, `kill-all`, `delete-data`", lifecycle)

    def test_planner_owns_tabs_without_changing_conversation_state(self):
        lifecycle = (PLANNER / "references/browser-lifecycle.md").read_text()
        flat = " ".join(lifecycle.split())
        for rule in ("persistent Codex task ID", "concrete browser ID",
                     "exact returned tab ID", "creation result",
                     "selected from the user's inventory are borrowed",
                     "same owned tab during one consultation",
                     "fresh inventory and verify that exact ID is absent",
                     "A close-call result alone is",
                     "Do not store prompt text, cookies, or credentials",
                     "or add it to planner state"):
            self.assertIn(rule, flat)
        self.assertIn("Keep ChatGPT history, saved conversation UUIDs, task mappings, request hashes,", lifecycle)
        self.assertIn("reservations, and profiles", lifecycle)
        self.assertIn("never guess close, handoff, or inventory methods", lifecycle)
        self.assertIn("single entrypoint call", lifecycle)
        self.assertIn("do not combine it with inventory, waits", lifecycle)

    def test_planner_finalizes_completion_reuse_probe_and_predispatch_failure(self):
        lifecycle = (PLANNER / "references/browser-lifecycle.md").read_text()
        rows = table_rows(lifecycle)
        for outcome in ("Completed response", "`reuse`", "Setup probe", "Failure before dispatch"):
            with self.subTest(outcome=outcome):
                matching = [action for key, action in rows.items() if key.startswith(outcome)]
                self.assertEqual(len(matching), 1)
                self.assertIn("Close", matching[0])
        pending = next(v for k, v in rows.items() if k.startswith("Unresolved reservation"))
        self.assertIn("Retain and hand off the exact tab", pending)
        self.assertIn("never repeat a send", pending)
        self.assertIn("mode change or timeout never releases", lifecycle)
        for reference in ("transport.md", "connection.md"):
            self.assertIn("](browser-lifecycle.md)", (PLANNER / "references" / reference).read_text())

    def test_both_contracts_preserve_handoffs_pending_work_and_unknown_ownership(self):
        for path in (PLAYWRIGHT / "references/lifecycle.md",
                     PLANNER / "references/browser-lifecycle.md"):
            with self.subTest(path=path):
                text = path.read_text()
                rows = table_rows(text)
                handoff = next(v for k, v in rows.items() if k.startswith("Explicit request"))
                self.assertIn("Retain", handoff)
                pending = [v for k, v in rows.items() if "pending downloads" in k]
                self.assertEqual(len(pending), 1)
                self.assertIn("Preserve", pending[0])
                self.assertIn("unknown outcome", text)
                self.assertIn("unverified", text)
                self.assertIn("task context", text)
                self.assertRegex(" ".join(text.split()), r"(?i)(?:do not|never).*\b(?:kill|process-name)")

    def test_static_validation_does_not_claim_live_resource_recovery(self):
        for path in (PLAYWRIGHT / "references/lifecycle.md",
                     PLANNER / "references/browser-lifecycle.md"):
            text = path.read_text()
            self.assertIn("RAM", text)
            self.assertRegex(" ".join(text.split()), r"They do not (?:prove|demonstrate)")


if __name__ == "__main__":
    unittest.main()
