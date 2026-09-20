# Codex Toolbox

A Codex plugin marketplace with reusable skills, MCP integrations, and managed
setup for instructions and runtimes.

## Start

```bash
git clone https://github.com/jialuohu/codex-toolbox.git
cd codex-toolbox
```

Follow [setup prerequisites](docs/setup.md#new-device-setup), including the
required private Docmost configuration, then run:

```bash
scripts/setup-codex-toolbox.sh
```

Setup installs plugins and runtimes and updates local Codex configuration.
Keep credentials outside Git under `CODEX_SECRETS_DIR`. Start a fresh Codex task
after setup.

## Find your next step

| Task | Read |
|---|---|
| Install, update, or configure a device | [Setup and updates](docs/setup.md) |
| Find a workflow or integration | [Documentation index](docs/README.md) |
| Browse available plugins | [Marketplace catalog](.agents/plugins/marketplace.json) |
| Change or validate the toolbox | [Development](docs/development.md) · [Repository rules](AGENTS.md) |

## For agents

1. Read [AGENTS.md](AGENTS.md) before editing this repository.
2. Use the [docs index](docs/README.md) to select one relevant guide.
3. Open the owning `plugins/<plugin>/skills/<skill>/SKILL.md` for execution rules.
   Plugin manifests, `.mcp.json` files, and setup scripts define installed behavior.

Use [`$upgrade-toolbox`](docs/development.md#upgrade-toolbox) to check upstreams
or prepare compatible upgrades. Use `$sync-toolbox` to apply published updates. Publishing requires an explicit
`$ship-toolbox` request; see [sync](docs/setup.md#sync-toolbox) and
[shipping](docs/development.md#ship-toolbox).
