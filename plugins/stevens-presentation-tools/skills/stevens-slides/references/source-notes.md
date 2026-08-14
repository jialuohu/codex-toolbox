# Source and asset notes

The plugin packages only the supplied Stevens positive and negative identifiers,
official star variants, one campus image, the 2022 PowerPoint source template,
the generated theme templates, and the required Saira Condensed and IBM Plex
Sans weights.

The packaged source template is privacy-sanitized. It contains no personal
author list, email address, account identifier, SharePoint custom XML, comments,
or external relationship. Its four rendered slide compositions match the
supplied source except that empty slide-local placeholders are removed and the
generic `Date` prompt reads `PRESENTATION DAY`.

The generated white, dark, and gallery PowerPoint decks clear imported author
and comment records before export and are checked with the same package-level
privacy assertions as the source template.

The four EPS star variants also have privacy-neutral metadata: the supplied
vector drawing bytes are preserved while personal author and Adobe XMP document
identifiers are replaced with same-length neutral values.

Use this speaker-note pattern for template-derived slides:

```text
[Sources]
- Stevens Institute of Technology Visual Identity Guide (2023), supplied brand resource.
- Stevens PowerPoint Template Guide (2022), supplied presentation resource.
- Example copy and data are illustrative; replace before presenting.
```

Add the campus-image source when the slide uses it. For real presentations,
replace the illustrative entry with the actual sources for every non-trivial
claim and external asset.

Stevens trademarks remain the property of Stevens Institute of Technology.
Do not alter the supplied identifiers. Font licenses are stored under
`assets/licenses/`; asset provenance and SHA-256 checksums are stored at the
plugin root and in `asset-checksums.json`.
