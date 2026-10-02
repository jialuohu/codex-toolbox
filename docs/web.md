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
verified ordinary HTML page. Supported X/Twitter hosts reserve **30 credits**
(1 base credit plus the documented 29-credit Grok processing surcharge):
`x.com`, `www.x.com`, `twitter.com`, `www.twitter.com`, and `mobile.twitter.com`.
This follows the [Firecrawl billing documentation](https://docs.firecrawl.dev/billing)
reviewed on 2026-10-02; it is a current pricing assumption, not a guarantee about
future provider charges. Other X/Twitter subdomains are rejected until reviewed.
X output carries an **AI-processed retrieval** notice and must not be presented
as a verified verbatim transcript. The proxy rejects
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

The proxy applies a fixed 900-credit cap to conservative reservations per
authenticated Firecrawl billing period, with no environment override. It reconciles local reservations against
the team's current usage through Firecrawl's read-only
[credit-usage endpoint](https://docs.firecrawl.dev/api-reference/endpoint/credit-usage),
so traffic from another client can reduce the allowance. Reservations are
persisted before forwarding and are not refunded after a failed request.
Each call has a durable reservation identity; valid returned `creditsUsed`
values add only a positive difference, once, including after a process restart.
Duplicate responses cannot charge the reservation again. Unknown, missing, or
interrupted outcomes keep their original reservation. When remote usage cannot
be attributed to pending calls, the proxy also protects those reservations;
the resulting count may exceed actual billed usage. It reports a conservative
allowance, not an exact invoice.

Ordinary URLs first receive a public HEAD check with no cookies, credentials,
proxy, or response body processing. This check connects **directly from the
local machine**, separately from Firecrawl's upstream retrieval: each target
sees the machine's network IP and the toolbox User-Agent. DNS answers must all be public; the socket
uses a validated address to prevent DNS rebinding. Each redirect is checked,
with at most three redirects and ten seconds total, and the verified final URL
is sent to Firecrawl. Redirects into supported X hosts reserve 30. Direct X
URLs already reserve 30 and do not need the HEAD check. A failed, unsafe,
cyclic, or unverifiable target is refused before a metered call.

Firecrawl can observe a different redirect or change its pricing. A charge
above the reservation, malformed cost metadata, or an unexpected returned
target/processor durably blocks further metered calls. Already incurred excess
charges cannot be undone; this local admission guard is not a provider-enforced
spending ceiling. Budget status exposes the blocked reason for review.
Returned target checks deliberately require the same scheme, resource path,
and query, apart from supported X host aliases and the equivalent empty/root
path. A newly appended path slash, HTTP-to-HTTPS change, or dropped X query
parameter is an unexpected provider target, even if it appears harmless.
Version-1 state migrates under the existing file lock without reducing its
count. Unresolved reservations spanning a billing-period rollover remain
blocked for review rather than being silently erased. Do not remove or reset
the state to bypass that block. Accounting blocks also survive rollover after
all reservations settle; fresh account usage alone does not clear them. A
separately reviewed accounting/pricing repair is required to restore access.
There is no reset or acknowledgement command that bypasses this review.
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
