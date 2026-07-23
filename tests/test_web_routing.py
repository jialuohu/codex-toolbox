import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLOBAL_AGENTS = ROOT / "config" / "codex" / "AGENTS.global.md"
SETUP_CHECKER = ROOT / "scripts" / "check-codex-toolbox-setup.py"


class WebRoutingContractTests(unittest.TestCase):
    def test_global_routes_ordinary_search_to_codex_before_firecrawl(self) -> None:
        text = GLOBAL_AGENTS.read_text(encoding="utf-8")

        codex_position = text.index("Use built-in Codex web search by default")
        firecrawl_position = text.index("Use Firecrawl only")
        self.assertLess(codex_position, firecrawl_position)
        for expected in (
            "ordinary public discovery",
            "current facts",
            "documentation",
            "news",
            "citations",
            "full-page clean Markdown",
            "JavaScript rendering",
            "structured extraction",
            "site mapping or crawling",
            "monitoring",
        ):
            self.assertIn(expected, text)

    def test_global_limits_firecrawl_search_and_crawl_cost(self) -> None:
        text = GLOBAL_AGENTS.read_text(encoding="utf-8")

        for expected in (
            "without `scrapeOptions`",
            "limit of 5 or less",
            "scrape only the selected URLs",
            "explicit page limit",
            "Interact or Agent",
        ):
            self.assertIn(expected, text)

    def test_setup_checker_enforces_the_cost_aware_web_route(self) -> None:
        text = SETUP_CHECKER.read_text(encoding="utf-8")

        for expected in (
            "Use built-in Codex web search by default",
            "Use Firecrawl only",
            "without `scrapeOptions`",
            "limit of 5 or less",
            "explicit page limit",
        ):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
