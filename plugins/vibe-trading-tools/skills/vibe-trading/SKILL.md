---
name: vibe-trading
description: Use when finance workflows need Vibe-Trading market data, backtests, factor analysis, screening, research swarms, Shadow Account reports, or MCP tool discovery.
---

# Vibe-Trading

## Overview

Use Vibe-Trading for research-heavy finance work: market data, backtests, factor analysis, screening, research swarms, trade-journal analysis, and Shadow Account reports. Use Alpaca MCP for direct Alpaca account, order, asset, crypto, options, and news workflows.

## Routing

| Need | Prefer |
| --- | --- |
| Research a strategy or market thesis | `vibe_trading` |
| Fetch broad market data or fundamentals | `vibe_trading` |
| Run a backtest, factor analysis, or screen | `vibe_trading` |
| Run a multi-agent research swarm | `vibe_trading` |
| Analyze trade journals or Shadow Account reports | `vibe_trading` |
| Inspect or change Alpaca account/orders | Alpaca MCP |

## Configuration

The toolbox plugin launches the upstream PyPI package with `uvx --from vibe-trading-ai vibe-trading-mcp`, tracking the latest published version. Optional provider and data-source overrides may live in `CODEX_SECRETS_DIR/vibe-trading.env`. Native Vibe-Trading state, provider config, run history, and connector profiles live under `VIBE_TRADING_HOME/`.

Do not put API keys, OAuth state, broker credentials, or `.env` contents in the toolbox repo.

## Smoke Test

After setup, verify the MCP server is visible:

```bash
codex mcp list
```

For live discovery, start the configured command through an MCP client and confirm tools such as `list_skills` and `get_market_data` are present before relying on the integration.

## Safety

Vibe-Trading's MCP surface is for research and read-oriented connector workflows; it is not the default path for direct broker order actions. Treat generated files, backtest runs, reports, connector selection, and swarm execution as local state changes under `VIBE_TRADING_HOME/`.
