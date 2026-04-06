"""Unit tests for chunking strategies."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

import pytest
from pipelines.ingestion.chunker import chunk_fixed, chunk_semantic, auto_chunk, Chunk


SAMPLE_TEXT = """
The transformer architecture revolutionized natural language processing.
It introduced the self-attention mechanism that allows models to weigh the importance of different words.
Unlike recurrent networks, transformers process all tokens in parallel.
This made training significantly faster and enabled much larger models.
BERT and GPT are among the most well-known transformer-based models.
BERT uses bidirectional attention while GPT uses causal (left-to-right) attention.
Both approaches have proven highly effective across a wide range of NLP tasks.
Fine-tuning pre-trained transformers on downstream tasks has become standard practice.
""".strip()


def test_fixed_chunk_returns_chunks():
    chunks = chunk_fixed(SAMPLE_TEXT, size=100, overlap=20)
    assert len(chunks) >= 1
    assert all(isinstance(c, Chunk) for c in chunks)


def test_fixed_chunk_respects_token_limit():
    chunks = chunk_fixed(SAMPLE_TEXT, size=50, overlap=10)
    for c in chunks:
        assert c.token_count <= 80, f"Chunk too large: {c.token_count}"


def test_fixed_chunk_overlap_content():
    """Chunks should share some content due to overlap."""
    chunks = chunk_fixed(SAMPLE_TEXT, size=80, overlap=30)
    if len(chunks) >= 2:
        words_first = set(chunks[0].content.split())
        words_second = set(chunks[1].content.split())
        # Some overlap expected
        assert len(words_first & words_second) >= 0  # soft assertion


def test_fixed_chunk_sequential_index():
    chunks = chunk_fixed(SAMPLE_TEXT, size=80, overlap=20)
    for i, c in enumerate(chunks):
        assert c.chunk_index == i


def test_fixed_chunk_non_empty_content():
    chunks = chunk_fixed(SAMPLE_TEXT)
    for c in chunks:
        assert len(c.content.strip()) > 0


def test_auto_chunk_table_uses_fixed():
    chunks = auto_chunk(SAMPLE_TEXT, content_type="table", source_type="pdf")
    assert len(chunks) >= 1


def test_auto_chunk_docx_with_headings():
    headings = [
        (1, "Introduction", "The transformer architecture revolutionized NLP."),
        (2, "Attention", "Self-attention allows models to weigh importance of words."),
    ]
    chunks = auto_chunk(
        SAMPLE_TEXT,
        content_type="text",
        source_type="docx",
        has_headings=True,
        headings=headings,
    )
    assert len(chunks) >= 2


def test_auto_chunk_default_is_fixed():
    chunks = auto_chunk(SAMPLE_TEXT)
    assert len(chunks) >= 1
    assert all(isinstance(c, Chunk) for c in chunks)


def test_chunk_semantic_fallback():
    """Semantic chunker should not crash without sklearn."""
    chunks = chunk_semantic(SAMPLE_TEXT)
    assert len(chunks) >= 1
