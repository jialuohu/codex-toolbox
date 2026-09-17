# Coder

[Documentation index](README.md) · [Repository](../README.md)

Run shell commands from the repository root.

## Coder MCP

The default `coder-tools` plugin runs `coder exp mcp server` locally and uses
the Coder CLI's existing authenticated deployment. It exposes a process-level
read-only allowlist for inspecting workspaces, templates, tasks, files, apps,
and logs; workspace commands, file writes, builds, creates, updates, and
deletes are not available.

On each device, install a compatible Coder CLI and authenticate it before
running the toolbox setup:

```bash
coder login <deployment-url>
```

After setup, start a fresh Codex task so the Coder MCP tools are loaded. The
plugin intentionally uses the local stdio server rather than Coder's remote
HTTP MCP endpoint, so the deployment does not need the HTTP MCP or OAuth2
experiments enabled.
