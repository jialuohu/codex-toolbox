# Provenance

This plugin adapts exactly these eight Apache-2.0 skill documents from
https://github.com/googleworkspace/cli, release tag `v0.22.5` at commit
`705fb0ecac6f4249679958f6325b809b63fdde17`:

- `skills/gws-shared/SKILL.md`
- `skills/gws-gmail/SKILL.md`
- `skills/gws-gmail-read/SKILL.md`
- `skills/gws-gmail-triage/SKILL.md`
- `skills/gws-gmail-send/SKILL.md`
- `skills/gws-gmail-reply/SKILL.md`
- `skills/gws-gmail-reply-all/SKILL.md`
- `skills/gws-gmail-forward/SKILL.md`

The upstream documents were normalized to Codex frontmatter and receive a
small `agents/openai.yaml` discovery file. Local modifications limit the
surface to Gmail, require the toolbox's isolated alias/profile contract and
live identity verification, scrub ambient credentials, forbid connector
fallback, constrain attachments to absolute paths, make composition draft-first,
and omit unsafe raw Gmail API areas. No upstream runtime code is vendored.
