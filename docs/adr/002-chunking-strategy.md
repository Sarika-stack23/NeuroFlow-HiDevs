# ADR 002 — Chunking Strategy: Fixed-size as Default with Semantic and Hierarchical Variants

**Status:** Accepted  
**Date:** 2024-01-01

---

## Context

Chunking strategy is one of the highest-leverage decisions in a RAG system. The chunk size
and splitting method directly determine retrieval quality. Three approaches were evaluated:

**Fixed-size chunking** splits at token boundaries (512 tokens, 64-token overlap).
Simple, fast, predictable. Overlap ensures context at chunk boundaries is not lost.
Risk: may split mid-sentence or mid-paragraph, breaking semantic coherence.

**Sentence-boundary chunking** splits at sentence ends (`.`, `!`, `?`), grouping
sentences until a token budget is reached. Preserves grammatical units. Risk: sentences
vary wildly in length — very long sentences create oversized chunks, very short ones
create tiny chunks with little context.

**Semantic chunking** embeds every sentence and finds topic shift points where cosine
similarity between adjacent sentences drops below a threshold (0.7). Creates
semantically coherent segments regardless of token count. Risk: expensive — requires
one embedding call per sentence; produces variable-length chunks that are hard to predict.

**Hierarchical chunking** follows document structure: each heading-level section becomes
a parent chunk; sub-sections become children. Preserves navigational context and enables
parent-level retrieval when sub-section chunks match. Requires structured input (DOCX with
heading styles, PDFs with detected chapters).

---

## Decision

Use **fixed-size (512 tokens, 64 overlap)** as the default, with automatic strategy
selection based on content signals:

| Condition | Strategy |
|-----------|----------|
| `content_type == "table"` | fixed_size (tables are already structured) |
| `source_type == "docx"` AND has heading styles | hierarchical |
| `source_type == "pdf"` AND `page_count > 50` | semantic (long docs have coherent sections) |
| All other cases | fixed_size |

Fixed-size is always used for tables because semantic boundaries are not meaningful in
tabular data — each row or row-group should stay together.

The 512-token size was chosen based on our embedding model's effective range.
`text-embedding-3-small` was trained with sequences up to 8192 tokens but achieves
peak retrieval performance on passages of 200–600 tokens.

Overlap of 64 tokens (12.5%) prevents context loss at chunk boundaries without
excessive duplication.

---

## Consequences

**Positive:**
- Fixed-size is deterministic — same document always produces same chunks
- Hierarchical chunking dramatically improves precision for structured documents
- Semantic chunking improves recall for long narrative documents
- Strategy is a pipeline config parameter — easy to A/B test per use case

**Negative:**
- Fixed-size can split mid-argument in analytical documents
- Semantic chunking is slow (~1s per page) and requires sklearn dependency
- Hierarchical requires clean heading styles — poorly formatted DOCX falls back to fixed

**When to switch:** If retrieval MRR@10 stays below 0.60 after tuning, run an ablation:
test semantic chunking on all content types. If semantic improves MRR by >5%, switch
the default.
