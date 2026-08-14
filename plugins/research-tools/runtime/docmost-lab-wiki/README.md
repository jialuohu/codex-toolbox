# docmost-lab-wiki runtime

This locked Python 3.12 package applies complete private Docmost JSONL snapshots to a separate
Obsidian Lab Wiki, builds an offline SQLite FTS5 plus exact-cosine index, and exposes read-only
search, status, and lint commands. It never authenticates to or contacts Docmost. The owning
`$docmost-lab-wiki` skill alone prepares and releases snapshots through the two read-only MCP tools.

Production embeddings use FastEmbed 0.8.0 and a setup-preloaded, checksum-verified local copy of
`BAAI/bge-small-en-v1.5`. Normal CLI operation forces offline Hugging Face behavior and passes the
exact local model path to FastEmbed.
