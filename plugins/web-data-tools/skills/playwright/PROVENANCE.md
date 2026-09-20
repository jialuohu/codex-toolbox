# Playwright provenance

This skill adapts the Apache-2.0 OpenAI curated Playwright skill at
[`openai/skills@49f948faa9258a0c61caceaf225e179651397431`](https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.curated/playwright).
The source entrypoint, wrapper, and two references are unchanged upstream
since `a5119697b819090e00e5d11ee1d86834d7c1043a`. The Microsoft-derived copyright
notice remains in [NOTICE.txt](NOTICE.txt), with the full [license](LICENSE.txt).

Toolbox changes resolve the wrapper relative to its installed skill directory
and check the resolved CLI version before using version-specific examples.
Selected reference examples follow the immutable Microsoft runtime release
[`v0.1.21`, commit `74354ecc7a43da16d91a9bc54fa8db8283a3fcf5`](https://github.com/microsoft/playwright-cli/tree/74354ecc7a43da16d91a9bc54fa8db8283a3fcf5):
request inspection, callback syntax, theme/media emulation, and the default
configuration path. The wrapper is preserved; this
reference refresh does not install a runtime or grant browser write authority.

[The import receipt](upstream.json) records source and local checksums. The
historical instruction baseline remains unchanged.
