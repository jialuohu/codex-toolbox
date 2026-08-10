import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLOBAL_AGENTS = ROOT / "config" / "codex" / "AGENTS.global.md"
SETUP_CHECKER = ROOT / "scripts" / "check-codex-toolbox-setup.py"


class WebRoutingContractTests(unittest.TestCase):
    def test_global_routes_ordinary_search_to_codex_and_community_to_firecrawl(self) -> None:
        text = GLOBAL_AGENTS.read_text(encoding="utf-8")

        codex_position = text.index("Use built-in Codex web search by default")
        firecrawl_position = text.index("Firecrawl is mandatory")
        self.assertLess(codex_position, firecrawl_position)
        for expected in (
            "ordinary public discovery",
            "current facts",
            "documentation",
            "news",
            "citations",
            "public community or forum discussions",
            "user reports",
            "sentiment",
            "community troubleshooting",
            "official or canonical corroboration",
        ):
            self.assertIn(expected, text)

    def test_global_enforces_metered_bounded_firecrawl_route(self) -> None:
        text = GLOBAL_AGENTS.read_text(encoding="utf-8")

        for expected in (
            "known public thread URL",
            "exactly one web source",
            "no `scrapeOptions`",
            "limit of 5 or less",
            "no more than two selected threads",
            "fixed 900-credit billing-period cap",
            "`firecrawl_budget_status`",
            "Markdown-only `firecrawl_scrape`",
            "community coverage is degraded",
            "separate connected Firecrawl app",
            "private local files",
        ):
            self.assertIn(expected, text)
        for retired_promise in (
            "Every map or crawl must have an explicit page limit",
            "Use Firecrawl Interact or Agent",
            "After using `firecrawl_search`, call the Firecrawl feedback tool",
        ):
            self.assertNotIn(retired_promise, text)

    def test_setup_checker_enforces_the_metered_community_route(self) -> None:
        text = SETUP_CHECKER.read_text(encoding="utf-8")

        for expected in (
            "Use built-in Codex web search by default",
            "Firecrawl is mandatory",
            "public community or forum discussions",
            "known public thread URL",
            "exactly one web source",
            "no `scrapeOptions`",
            "limit of 5 or less",
            "no more than two selected threads",
            "fixed 900-credit billing-period cap",
            "`firecrawl_budget_status`",
            "separate connected Firecrawl app",
        ):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
