# Draw.io helper reference

## Setup

The toolbox installs the exact `@drawio/mcp@1.6.0` runtime under
`${CODEX_HOME:-$HOME/.codex}/runtime/drawio-tools/active`. Normal MCP startup
does not invoke `npm`, `npx`, or the network.

The toolbox disables npm lifecycle scripts and remote icon supplementation.
`routing: "libavoid"` uses the verified bundled routing source and WASM,
ignoring per-user CDN caches. Server-side XML `postLayout: "elk"` is unavailable:
the tool reports that layout did not run and retains the supplied coordinates.
Mermaid ELK selection only transforms source for the requested editor.
Inherited `DRAWIO_ICON_SERVICE_URL` and `DRAWIO_ELK_URL` cannot override this policy.

```bash
scripts/setup-drawio-tools.sh --check
scripts/setup-drawio-tools.sh --install
scripts/setup-drawio-tools.sh --install --with-desktop
```

The Desktop option is intentionally separate because it may run
`brew install --cask drawio` on macOS. On other platforms, install draw.io
Desktop manually or set `DRAWIO_DESKTOP_BIN` to an existing executable.

## Desktop helper

Run from the installed plugin root or use its absolute path:

```text
scripts/drawio-desktop.sh --doctor
scripts/drawio-desktop.sh --open INPUT.drawio
scripts/drawio-desktop.sh --export png INPUT.drawio OUTPUT.png
scripts/drawio-desktop.sh --export svg INPUT.drawio OUTPUT.svg
scripts/drawio-desktop.sh --export pdf INPUT.drawio OUTPUT.pdf
```

Inputs and outputs must be absolute paths. Export uses draw.io Desktop's
`--embed-diagram` behavior so the image or PDF retains the diagram XML.

## Recovery

- `Draw.io runtime is missing or invalid`: rerun `scripts/setup-drawio-tools.sh --install` from the toolbox checkout.
- `draw.io Desktop CLI not found`: rerun setup with `--with-desktop`, install it manually, or set `DRAWIO_DESKTOP_BIN`.
- Browser opens the wrong deployment: set `DRAWIO_BASE_URL` to the trusted self-hosted draw.io base URL and start a fresh Codex task.
- Export fails: retain the `.drawio` source, report the helper command and failure, and do not use cloud rasterization as a silent fallback.
