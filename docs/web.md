# Web extraction

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root. Read the owning skill before using a workflow.

- [Firecrawl Routing and Budget](#firecrawl-routing-and-budget)

## Firecrawl Routing and Budget

The default `web-data-tools` plugin exposes a metered Firecrawl surface for
public HTML content. It supports only bounded `firecrawl_search`, bounded
Markdown-only `firecrawl_scrape`, and the read-only
`firecrawl_budget_status` tool. Search reserves 2 credits per request, matching
the current price for up to ten results, and basic Scrape reserves 1 credit per
page ([Firecrawl pricing](https://www.firecrawl.dev/pricing)). The proxy rejects
Crawl, Map, Monitor, Agent, Interact, Parse, Extract, structured JSON, actions,
profiles, enhanced or automatic proxies, unknown tools, and other unbounded
options.

The implicitly invocable `$community-research` skill owns requests that seek
public community or forum discussions, user reports, sentiment, or community
troubleshooting. Firecrawl is mandatory within that bounded workflow. A known
thread URL goes directly to Scrape. Discovery uses one web source with
highlights and at most five results, then scrapes no more than two selected
threads when the highlights are insufficient. Built-in Codex web search remains
the corroboration route for official or canonical sources.

The proxy enforces a fixed 900-credit cap per authenticated Firecrawl billing
period with no environment override. It reconciles local reservations against
the team's current usage through Firecrawl's read-only
[credit-usage endpoint](https://docs.firecrawl.dev/api-reference/endpoint/credit-usage),
so traffic from another client can reduce the allowance. Reservations are
persisted before forwarding and are not refunded after a failed request.
Budget, state, lock, account-credit, period-rollover, API, or
parameter-validation failures fail closed before the upstream MCP is called.
Failures use the stable codes `FIRECRAWL_BUDGET_EXHAUSTED`,
`FIRECRAWL_BUDGET_UNAVAILABLE`, and `FIRECRAWL_REQUEST_NOT_BOUNDED`. When that
blocks a required community pass, use built-in web search and include a
degraded-coverage notice. Never bypass the cap through another endpoint,
another client, or the separate connected Firecrawl app.

Budget state is stored atomically with private permissions at
`${CODEX_HOME:-~/.codex}/state/firecrawl-budget.json`. Inspect the read-only
status without spending Search or Scrape credits:

```bash
plugins/web-data-tools/scripts/run-firecrawl-mcp.sh status
```

The status reports the cap, counted credits, remaining toolbox allowance,
account remaining credits, billing-period dates, and the allowed tool names. It
never reports Firecrawl credentials. Firecrawl remains prohibited for private
local files, saved Zotero content, Obsidian vault content, and other private
workspace data unless the user explicitly asks to send that data to Firecrawl.
