# Mono-Color provenance

Photo Tools includes an unofficial, non-affiliated Codex adaptation of
[yanliudesign/mono-color-skill](https://github.com/yanliudesign/mono-color-skill),
pinned to commit `c8ff70597ddedcd65f21a0b528f6a70c35690b0a`.

The complete upstream skill is preserved byte-for-byte as
[upstream.md](skills/mono-color/references/upstream.md). Its six design-system
catalogs, evaluation fixtures, evaluation validator, and
[MIT license](skills/mono-color/references/LICENSE) are also preserved.
[The import manifest](mono-color-upstream.json) records each upstream path,
local path, and SHA-256 checksum. Refresh only through an intentional source
update with license review and validation; normal skill use never downloads
updates.

The toolbox-owned entrypoint adds concise discovery, research palette
selection, existing figure-tool routing, and Codex image-generation/output
handling. These adaptations do not edit the imported workflow. The import
retains upstream's catalog-over-prose precedence: do not invent catalog IDs
for recipes mentioned only in its prose.

## Assets and scope

The MIT license covers the software and instructions. The original generated
artwork and third-party reference images have separate restrictions under
[the upstream asset license](https://github.com/yanliudesign/mono-color-skill/blob/c8ff70597ddedcd65f21a0b528f6a70c35690b0a/ASSET-LICENSE.md).
They are not bundled. View the
[upstream examples](https://github.com/yanliudesign/mono-color-skill#selected-examples)
and [reference attribution](https://github.com/yanliudesign/mono-color-skill/blob/c8ff70597ddedcd65f21a0b528f6a70c35690b0a/REFERENCES.md)
there instead. Swatches, generated boards, board-building scripts, and the
example-poster builder are also omitted; they are not required to use the skill.

## Validation

Run `python3 -m unittest tests.test_mono_color tests.test_check_codex_toolbox_setup`
from the toolbox checkout. These offline checks verify packaging, checksums,
catalog integrity, and upstream evaluation fixtures without image generation.
The upstream design-system validator is not bundled because it requires the
excluded artwork and generated reference boards; toolbox tests cover the
catalog contract independently.

`tests/fixtures/mono-color-routing.json` contains acceptance prompts for
editorial generation, prompt-only output, research colors, and unrelated work.
Tests check their structure and reference reachability; this does not prove
live model routing or image quality. Keep them separate from the existing
fixed routing-audit corpus. Behavioral checks should inspect the chosen
workflow and tool actions without generating sample artwork during installation.
