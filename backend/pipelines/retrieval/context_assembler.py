"""Assemble retrieved chunks into a formatted context window."""
from typing import Any
import tiktoken

enc = tiktoken.get_encoding("cl100k_base")


def assemble_context(
    chunks: list[dict[str, Any]], max_tokens: int = 4000
) -> tuple[str, dict]:
    """
    Fit as many chunks as possible within token budget.
    Returns (context_string, metadata).
    """
    parts: list[str] = []
    used_chunks: list[dict] = []
    total_tokens = 0

    for i, chunk in enumerate(chunks):
        content = chunk.get("content", "")
        doc_name = chunk.get("document_name", "unknown")
        page = chunk.get("page_number")
        source_label = f"[Source {i+1} — {doc_name}" + (f", page {page}]" if page else "]")
        block = f"{source_label}\n{content}"
        block_tokens = len(enc.encode(block))

        if total_tokens + block_tokens > max_tokens:
            # Try to fit a truncated version
            remaining = max_tokens - total_tokens
            if remaining < 50:
                break
            truncated = enc.decode(enc.encode(block)[:remaining])
            parts.append(truncated)
            total_tokens += remaining
            break

        parts.append(block)
        used_chunks.append(chunk)
        total_tokens += block_tokens

    context = "\n\n".join(parts)
    return context, {
        "chunks_used": used_chunks,
        "total_tokens": total_tokens,
        "sources": list({c.get("document_name", "") for c in used_chunks}),
    }
