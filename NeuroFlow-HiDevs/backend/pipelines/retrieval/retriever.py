"""Hybrid retrieval pipeline — dense + sparse + metadata, fused via RRF."""
import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog

from db.pool import get_pool

logger = structlog.get_logger()


@dataclass
class RetrievalResult:
    id: str
    document_id: str
    document_name: str
    content: str
    chunk_index: int
    token_count: int
    metadata: dict
    score: float = 0.0
    page_number: int | None = None


def reciprocal_rank_fusion(
    result_lists: list[list[RetrievalResult]], k: int = 60
) -> list[RetrievalResult]:
    """Combine multiple ranked lists via RRF. Higher score = better."""
    scores: dict[str, float] = {}
    registry: dict[str, RetrievalResult] = {}

    for results in result_lists:
        for rank, item in enumerate(results):
            scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (k + rank + 1)
            registry[item.id] = item

    fused = sorted(registry.values(), key=lambda x: scores[x.id], reverse=True)
    for item in fused:
        item.score = scores[item.id]
    return fused


class Retriever:
    async def _dense_retrieval(self, query: str, k: int, embedding: list[float]) -> list[RetrievalResult]:
        pool = get_pool()
        rows = await pool.fetch(
            """SELECT c.id, c.document_id, c.content, c.chunk_index, c.token_count,
                      c.metadata, d.filename,
                      1 - (c.embedding <=> $1::vector) AS score
               FROM chunks c
               JOIN documents d ON d.id = c.document_id
               WHERE c.embedding IS NOT NULL
               ORDER BY c.embedding <=> $1::vector
               LIMIT $2""",
            str(embedding), k,
        )
        return [
            RetrievalResult(
                id=str(r["id"]), document_id=str(r["document_id"]),
                document_name=r["filename"], content=r["content"],
                chunk_index=r["chunk_index"], token_count=r["token_count"],
                metadata=dict(r["metadata"] or {}), score=float(r["score"] or 0),
                page_number=r["metadata"].get("page_number") if r["metadata"] else None,
            )
            for r in rows
        ]

    async def _sparse_retrieval(self, query: str, k: int) -> list[RetrievalResult]:
        pool = get_pool()
        rows = await pool.fetch(
            """SELECT c.id, c.document_id, c.content, c.chunk_index, c.token_count,
                      c.metadata, d.filename,
                      ts_rank_cd(to_tsvector('english', c.content),
                                 plainto_tsquery('english', $1)) AS score
               FROM chunks c
               JOIN documents d ON d.id = c.document_id
               WHERE to_tsvector('english', c.content) @@ plainto_tsquery('english', $1)
               ORDER BY score DESC
               LIMIT $2""",
            query, k,
        )
        return [
            RetrievalResult(
                id=str(r["id"]), document_id=str(r["document_id"]),
                document_name=r["filename"], content=r["content"],
                chunk_index=r["chunk_index"], token_count=r["token_count"],
                metadata=dict(r["metadata"] or {}), score=float(r["score"] or 0),
            )
            for r in rows
        ]

    async def retrieve(self, query: str, k: int = 20) -> list[dict[str, Any]]:
        from providers.base import RoutingCriteria
        from providers.router import get_router
        router = get_router()
        provider, _ = await router.route(RoutingCriteria(task_type="embedding"))
        embeddings = await provider.embed([query])
        query_embedding = embeddings[0]

        dense_task = self._dense_retrieval(query, k, query_embedding)
        sparse_task = self._sparse_retrieval(query, k)

        dense_results, sparse_results = await asyncio.gather(dense_task, sparse_task)

        fused = reciprocal_rank_fusion([dense_results, sparse_results])

        # Cross-encoder reranking (top 20)
        reranked = await self._rerank(query, fused[:20])
        return [vars(r) for r in reranked[:k // 2]]

    async def _rerank(self, query: str, candidates: list[RetrievalResult]) -> list[RetrievalResult]:
        if not candidates:
            return candidates
        try:
            from providers.base import ChatMessage, RoutingCriteria
            from providers.router import get_router
            router = get_router()
            provider, _ = await router.route(RoutingCriteria(task_type="classification"))

            async def score_one(c: RetrievalResult) -> float:
                result = await provider.complete(
                    [ChatMessage(role="user", content=(
                        f"Rate the relevance of this passage to the query on a scale 0-10.\n"
                        f"Query: {query}\nPassage: {c.content[:500]}\nReturn only the number."
                    ))],
                    temperature=0.0, max_tokens=5,
                )
                try:
                    return float(result.content.strip().split()[0])
                except Exception:
                    return 5.0

            scores = await asyncio.gather(*[score_one(c) for c in candidates])
            for c, s in zip(candidates, scores):
                c.score = s / 10.0
            return sorted(candidates, key=lambda x: x.score, reverse=True)
        except Exception as e:
            logger.warning("reranker.failed", error=str(e))
            return candidates
