"""Chunking strategies: fixed_size, semantic, hierarchical."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import tiktoken

enc = tiktoken.get_encoding("cl100k_base")

ChunkStrategy = Literal["fixed_size", "semantic", "hierarchical"]


@dataclass
class Chunk:
    content: str
    chunk_index: int
    token_count: int
    metadata: dict = field(default_factory=dict)


def _count_tokens(text: str) -> int:
    return len(enc.encode(text))


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


# ── Fixed-size chunking ───────────────────────────────────────────────────────

def chunk_fixed(text: str, size: int = 512, overlap: int = 64) -> list[Chunk]:
    sentences = _split_sentences(text)
    chunks: list[Chunk] = []
    current: list[str] = []
    current_tokens = 0
    idx = 0

    for sent in sentences:
        sent_tokens = _count_tokens(sent)
        if current_tokens + sent_tokens > size and current:
            content = " ".join(current)
            chunks.append(Chunk(content=content, chunk_index=idx, token_count=_count_tokens(content)))
            idx += 1
            # Overlap: keep last sentences up to overlap tokens
            overlap_buf: list[str] = []
            overlap_toks = 0
            for s in reversed(current):
                st = _count_tokens(s)
                if overlap_toks + st > overlap:
                    break
                overlap_buf.insert(0, s)
                overlap_toks += st
            current = overlap_buf
            current_tokens = overlap_toks
        current.append(sent)
        current_tokens += sent_tokens

    if current:
        content = " ".join(current)
        chunks.append(Chunk(content=content, chunk_index=idx, token_count=_count_tokens(content)))

    return chunks


# ── Semantic chunking ─────────────────────────────────────────────────────────

def chunk_semantic(text: str, similarity_threshold: float = 0.7) -> list[Chunk]:
    """Split on topic shifts by embedding sentences and finding similarity drops."""
    sentences = _split_sentences(text)
    if len(sentences) < 3:
        return chunk_fixed(text)

    try:
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        # Use simple TF-IDF-like similarity for speed (no LLM call)
        from sklearn.feature_extraction.text import TfidfVectorizer
        vectorizer = TfidfVectorizer()
        vecs = vectorizer.fit_transform(sentences).toarray()

        split_indices: list[int] = [0]
        for i in range(1, len(sentences) - 1):
            sim = cosine_similarity([vecs[i - 1]], [vecs[i]])[0][0]
            if sim < similarity_threshold:
                split_indices.append(i)
        split_indices.append(len(sentences))

        chunks: list[Chunk] = []
        for ci in range(len(split_indices) - 1):
            seg = " ".join(sentences[split_indices[ci]:split_indices[ci + 1]])
            chunks.append(Chunk(content=seg, chunk_index=ci, token_count=_count_tokens(seg)))
        return chunks
    except ImportError:
        return chunk_fixed(text)


# ── Hierarchical chunking ─────────────────────────────────────────────────────

def chunk_hierarchical(text: str, headings: list[tuple[int, str, str]] | None = None) -> list[Chunk]:
    """
    headings: list of (level, heading_text, section_content)
    Falls back to fixed_size if no heading info.
    """
    if not headings:
        return chunk_fixed(text)

    chunks: list[Chunk] = []
    idx = 0
    for level, heading, content in headings:
        sub_chunks = chunk_fixed(content)
        for sc in sub_chunks:
            sc.chunk_index = idx
            sc.metadata = {"heading": heading, "heading_level": level}
            chunks.append(sc)
            idx += 1
    return chunks


# ── Auto-select strategy ──────────────────────────────────────────────────────

def auto_chunk(
    text: str,
    content_type: str = "text",
    source_type: str = "pdf",
    page_count: int = 1,
    has_headings: bool = False,
    headings: list | None = None,
    size: int = 512,
    overlap: int = 64,
) -> list[Chunk]:
    if content_type == "table":
        return chunk_fixed(text, size=size, overlap=overlap)
    if has_headings and source_type == "docx":
        return chunk_hierarchical(text, headings)
    if source_type == "pdf" and page_count > 50:
        return chunk_semantic(text)
    return chunk_fixed(text, size=size, overlap=overlap)
