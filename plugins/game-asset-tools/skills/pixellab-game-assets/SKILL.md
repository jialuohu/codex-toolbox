---
name: pixellab-game-assets
description: Use only for PixelLab pixel-art game asset workflows, including sprites, character rotations, animations, top-down or sidescroller tilesets, isometric tiles, and map objects. Do not use for generic image generation, web search, local file work, or normal coding unless the user explicitly wants PixelLab assets.
---

# PixelLab Game Assets

Use PixelLab MCP only when the user wants pixel-art game assets or wants to inspect existing PixelLab asset jobs.

## Boundaries

- Do not use PixelLab for generic image generation, UI mockups, document images, web search, local files, or ordinary code edits.
- Creation and animation tools can spend PixelLab credits. Ask for explicit confirmation before starting broad batches or ambiguous generation.
- Do not use PixelLab chat or sandbox tools. They are intentionally disabled in this plugin.

## Workflow

1. Match the request to the narrowest PixelLab asset type: character, animation, top-down tileset, sidescroller tileset, isometric tile, or map object.
2. Prefer status and list tools for follow-ups about existing assets.
3. For new assets, call the relevant creation tool once the requested asset, style, size, and perspective are clear enough.
4. Treat creation tools as non-blocking: capture the returned job or asset ID, then use the corresponding `get_*` tool to check status later.
5. Give the user the returned IDs and download/status links when available.

## Tool Notes

- Character generation supports 4 or 8 directions.
- Animation tools operate on existing character or object IDs.
- Connected top-down tilesets can chain terrain transitions by reusing base tile IDs.
- Sidescroller tilesets target side-view platformer terrain.
- Isometric tiles are single tile assets; 32 px is usually the practical quality default.
