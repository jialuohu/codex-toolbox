import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLOBAL_AGENTS = ROOT / "config" / "codex" / "AGENTS.global.md"
COMMUNITY_SKILL = (
    ROOT / "plugins" / "web-data-tools" / "skills" / "community-research" / "SKILL.md"
)
COMMUNITY_AGENT = COMMUNITY_SKILL.parent / "agents" / "openai.yaml"
WEB_PLUGIN = ROOT / "plugins" / "web-data-tools" / ".codex-plugin" / "plugin.json"


class WebRoutingContractTests(unittest.TestCase):
    def test_global_keeps_only_concise_search_dispatch(self) -> None:
        text = GLOBAL_AGENTS.read_text(encoding="utf-8")

        expected_sentence = (
            "Use built-in Codex web search for ordinary public discovery, current facts, "
            "documentation, news, and citations; use `$community-research` for public "
            "community or forum discussions, user reports, sentiment, or community "
            "troubleshooting, alongside official or canonical corroboration."
        )
        self.assertIn(expected_sentence, text)
        for detail_owned_by_the_skill in (
            "exactly one web source",
            "no `scrapeOptions`",
            "no more than two selected threads",
            "fixed 900-credit billing-period cap",
            "FIRECRAWL_BUDGET_EXHAUSTED",
        ):
            self.assertNotIn(detail_owned_by_the_skill, text)

    def test_community_skill_owns_bounded_metered_firecrawl_contract(self) -> None:
        text = COMMUNITY_SKILL.read_text(encoding="utf-8")
        normalized = " ".join(text.split())

        for expected in (
            "known public thread URL",
            "exactly one web source",
            "no `scrapeOptions`",
            "result limit of 5 or less",
            "no more than two selected threads",
            "fixed 900-credit billing-period cap",
            "`firecrawl_budget_status`",
            "Markdown-only `firecrawl_scrape`",
            "separate connected Firecrawl app",
            "private local files",
            "community coverage is degraded",
            "official or canonical",
        ):
            self.assertIn(expected, normalized)
        for stable_error_code in (
            "FIRECRAWL_BUDGET_EXHAUSTED",
            "FIRECRAWL_BUDGET_UNAVAILABLE",
            "FIRECRAWL_REQUEST_NOT_BOUNDED",
        ):
            self.assertIn(stable_error_code, normalized)

    def test_community_skill_is_implicit_and_plugin_version_is_current(self) -> None:
        agent_text = COMMUNITY_AGENT.read_text(encoding="utf-8")
        manifest = json.loads(WEB_PLUGIN.read_text(encoding="utf-8"))

        self.assertIn("allow_implicit_invocation: true", agent_text)
        self.assertEqual(manifest["version"], "0.5.0")
        self.assertIn("community research", manifest["description"].lower())


if __name__ == "__main__":
    unittest.main()
