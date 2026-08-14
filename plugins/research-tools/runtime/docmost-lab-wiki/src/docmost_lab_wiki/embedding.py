"""Offline embeddings and Markdown-aware token chunking."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from docmost_lab_wiki.constants import (
    CHUNK_OVERLAP_TOKENS,
    CHUNK_TARGET_TOKENS,
    MODEL_DIMENSIONS,
    MODEL_NAME,
    QUERY_INSTRUCTION,
)

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


class EmbeddingBackend(Protocol):
    """Small injectable boundary used by indexing and retrieval tests."""

    @property
    def dimensions(self) -> int: ...

    @property
    def model_version(self) -> str: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, question: str) -> list[float]: ...

    def token_offsets(self, text: str) -> list[tuple[int, int]]: ...


class _VectorLike(Protocol):
    def tolist(self) -> list[float]: ...


@dataclass(frozen=True)
class ChunkText:
    heading: str
    text: str
    token_count: int


class FastEmbedBackend:
    """Pinned FastEmbed backend opened from one verified local path."""

    def __init__(self, model_path: Path, *, model_version: str) -> None:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from fastembed import TextEmbedding
        from tokenizers import Tokenizer

        self._model = TextEmbedding(
            model_name=MODEL_NAME,
            specific_model_path=str(model_path),
            local_files_only=True,
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer = Tokenizer.from_file(str(model_path / "tokenizer.json"))
        self._model_version = model_version

    @property
    def dimensions(self) -> int:
        return MODEL_DIMENSIONS

    @property
    def model_version(self) -> str:
        return self._model_version

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = [cast(_VectorLike, vector) for vector in self._model.embed(texts, batch_size=64)]
        return [self._validated_vector(vector.tolist()) for vector in vectors]

    def embed_query(self, question: str) -> list[float]:
        vector = cast(
            _VectorLike,
            next(iter(self._model.embed([f"{QUERY_INSTRUCTION}{question}"], batch_size=1))),
        )
        return self._validated_vector(vector.tolist())

    def token_offsets(self, text: str) -> list[tuple[int, int]]:
        encoding = self._tokenizer.encode(text, add_special_tokens=False)
        return list(encoding.offsets)

    def _validated_vector(self, vector: list[float]) -> list[float]:
        converted = [float(value) for value in vector]
        if len(converted) != self.dimensions:
            raise RuntimeError("Embedding model returned an unexpected dimension")
        return converted


def chunk_markdown(
    markdown: str,
    *,
    context_prefix: str,
    backend: EmbeddingBackend,
) -> list[ChunkText]:
    """Chunk each Markdown heading section into 420-token windows with 60 overlap."""

    chunks: list[ChunkText] = []
    prefix = context_prefix.rstrip() + "\n\n"
    prefix_tokens = len(backend.token_offsets(prefix))
    body_target = max(64, CHUNK_TARGET_TOKENS - prefix_tokens)
    body_overlap = min(CHUNK_OVERLAP_TOKENS, body_target - 1)
    for heading, section in _markdown_sections(markdown):
        offsets = backend.token_offsets(section)
        if not offsets:
            continue
        start = 0
        while start < len(offsets):
            end = min(len(offsets), start + body_target)
            first_char = offsets[start][0]
            last_char = offsets[end - 1][1]
            body = section[first_char:last_char].strip()
            if body:
                text = f"{prefix}{body}"
                chunks.append(
                    ChunkText(
                        heading=heading,
                        text=text,
                        token_count=len(backend.token_offsets(text)),
                    )
                )
            if end == len(offsets):
                break
            start = end - body_overlap
    return chunks


def _markdown_sections(markdown: str) -> list[tuple[str, str]]:
    matches = list(_HEADING.finditer(markdown))
    if not matches:
        return [("", markdown)]
    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        sections.append(("", markdown[: matches[0].start()]))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((match.group(2).strip(), markdown[match.start() : end]))
    return sections
