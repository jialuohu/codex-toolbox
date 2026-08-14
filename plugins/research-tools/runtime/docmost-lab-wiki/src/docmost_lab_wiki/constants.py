"""Pinned schema and model constants."""

from __future__ import annotations

SNAPSHOT_SCHEMA_VERSION = "docmost.workspace-snapshot.v1"
INDEX_SCHEMA_VERSION = "docmost.lab-wiki-index.v1"
NOTE_SCHEMA_VERSION = "docmost.lab-wiki-note.v1"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_REPOSITORY = "Qdrant/bge-small-en-v1.5-onnx-Q"
MODEL_REVISION = "c32e6154d1bb7a0e47c5e745fd895e7700f44385"
MODEL_FILE = "model_optimized.onnx"
MODEL_FILE_SIZE = 66_465_124
MODEL_FILE_SHA256 = "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431"
MODEL_DIMENSIONS = 384
MODEL_MAX_TOKENS = 512
CHUNK_TARGET_TOKENS = 420
CHUNK_OVERLAP_TOKENS = 60
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
FRESHNESS_WARNING_HOURS = 36
RRF_K = 60
RETRIEVAL_CANDIDATES = 50
FINAL_CONTEXT_CHUNKS = 12
MAX_CHUNKS_PER_PAGE = 2

MANAGED_START_PREFIX = "<!-- docmost-lab-wiki:managed:start sha256="
MANAGED_END = "<!-- docmost-lab-wiki:managed:end -->"
NOTES_START = "<!-- docmost-lab-wiki:notes:start -->"
NOTES_END = "<!-- docmost-lab-wiki:notes:end -->"
SYNTHESIS_START = "<!-- docmost-lab-wiki:synthesis:start -->"
SYNTHESIS_END = "<!-- docmost-lab-wiki:synthesis:end -->"
