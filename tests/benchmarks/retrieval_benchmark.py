"""
Retrieval benchmark — measures Hit Rate@K and MRR@K.
Run: python tests/benchmarks/retrieval_benchmark.py
Requires: running NeuroFlow instance + populated DB.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))


# ── Synthetic test set — replace chunk IDs with real ones after ingestion ──
TEST_SET = [
    {"query": "What is HNSW indexing?", "relevant_chunk_ids": []},
    {"query": "How does attention work in transformers?", "relevant_chunk_ids": []},
    {"query": "What is reciprocal rank fusion?", "relevant_chunk_ids": []},
    {"query": "Explain vector embeddings", "relevant_chunk_ids": []},
    {"query": "What is context precision?", "relevant_chunk_ids": []},
    {"query": "How does fine-tuning improve RAG?", "relevant_chunk_ids": []},
    {"query": "What is a circuit breaker?", "relevant_chunk_ids": []},
    {"query": "Explain chunking strategies", "relevant_chunk_ids": []},
    {"query": "What are RAGAS metrics?", "relevant_chunk_ids": []},
    {"query": "How does cross-encoder reranking work?", "relevant_chunk_ids": []},
]


def compute_hit_rate(results: list[dict], relevant_ids: list[str], k: int = 10) -> float:
    result_ids = [str(r.get("id", "")) for r in results[:k]]
    return 1.0 if any(rid in result_ids for rid in relevant_ids) else 0.0


def compute_mrr(results: list[dict], relevant_ids: list[str], k: int = 10) -> float:
    for rank, r in enumerate(results[:k], 1):
        if str(r.get("id", "")) in relevant_ids:
            return 1.0 / rank
    return 0.0


def compute_ndcg(results: list[dict], relevant_ids: list[str], k: int = 10) -> float:
    import math
    dcg = 0.0
    for rank, r in enumerate(results[:k], 1):
        if str(r.get("id", "")) in relevant_ids:
            dcg += 1.0 / math.log2(rank + 1)
    ideal_dcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant_ids), k)))
    return dcg / ideal_dcg if ideal_dcg > 0 else 0.0


async def run_benchmark():
    from db.pool import create_pool
    from pipelines.retrieval.retriever import Retriever

    await create_pool()
    retriever = Retriever()

    metrics = {
        "dense_only":        {"hit_rate": [], "mrr": [], "ndcg": []},
        "sparse_only":       {"hit_rate": [], "mrr": [], "ndcg": []},
        "hybrid_rrf":        {"hit_rate": [], "mrr": [], "ndcg": []},
        "hybrid_reranked":   {"hit_rate": [], "mrr": [], "ndcg": []},
    }

    for test in TEST_SET:
        query = test["query"]
        relevant = test.get("relevant_chunk_ids", [])

        if not relevant:
            # No ground truth — skip metric computation, just run to verify no crash
            await retriever.retrieve(query, k=10)
            continue

        # Dense only
        from providers.base import RoutingCriteria
        from providers.router import get_router
        router = get_router()
        provider, _ = await router.route(RoutingCriteria(task_type="embedding"))
        emb = await provider.embed([query])
        dense = await retriever._dense_retrieval(query, 10, emb[0])
        metrics["dense_only"]["hit_rate"].append(compute_hit_rate([vars(r) for r in dense], relevant))
        metrics["dense_only"]["mrr"].append(compute_mrr([vars(r) for r in dense], relevant))
        metrics["dense_only"]["ndcg"].append(compute_ndcg([vars(r) for r in dense], relevant))

        # Sparse only
        sparse = await retriever._sparse_retrieval(query, 10)
        metrics["sparse_only"]["hit_rate"].append(compute_hit_rate([vars(r) for r in sparse], relevant))
        metrics["sparse_only"]["mrr"].append(compute_mrr([vars(r) for r in sparse], relevant))
        metrics["sparse_only"]["ndcg"].append(compute_ndcg([vars(r) for r in sparse], relevant))

        # Hybrid RRF (no reranking)
        from pipelines.retrieval.retriever import reciprocal_rank_fusion
        fused = reciprocal_rank_fusion([dense, sparse])
        metrics["hybrid_rrf"]["hit_rate"].append(compute_hit_rate([vars(r) for r in fused], relevant))
        metrics["hybrid_rrf"]["mrr"].append(compute_mrr([vars(r) for r in fused], relevant))
        metrics["hybrid_rrf"]["ndcg"].append(compute_ndcg([vars(r) for r in fused], relevant))

        # Hybrid + reranked
        reranked = await retriever.retrieve(query, k=10)
        metrics["hybrid_reranked"]["hit_rate"].append(compute_hit_rate(reranked, relevant))
        metrics["hybrid_reranked"]["mrr"].append(compute_mrr(reranked, relevant))
        metrics["hybrid_reranked"]["ndcg"].append(compute_ndcg(reranked, relevant))

    # Aggregate
    def avg(lst): return round(sum(lst) / len(lst), 4) if lst else None

    summary = {
        strategy: {
            "hit_rate_at_10": avg(m["hit_rate"]),
            "mrr_at_10": avg(m["mrr"]),
            "ndcg_at_10": avg(m["ndcg"]),
        }
        for strategy, m in metrics.items()
    }

    print("\n=== Retrieval Benchmark Results ===\n")
    print(f"{'Strategy':<25} {'Hit@10':>8} {'MRR@10':>8} {'NDCG@10':>9}")
    print("-" * 55)
    for s, r in summary.items():
        print(f"{s:<25} {str(r['hit_rate_at_10']):>8} {str(r['mrr_at_10']):>8} {str(r['ndcg_at_10']):>9}")

    # Check requirement: hybrid+reranked must beat dense-only by ≥15% on MRR
    d_mrr = summary["dense_only"]["mrr_at_10"] or 0
    r_mrr = summary["hybrid_reranked"]["mrr_at_10"] or 0
    improvement = (r_mrr - d_mrr) / d_mrr if d_mrr > 0 else 0
    print(f"\nHybrid+Reranked vs Dense MRR improvement: {improvement:.1%} (target: ≥15%)")
    print(f"Requirement met: {'YES ✓' if improvement >= 0.15 else 'NO — needs tuning'}")

    # Save results
    out_path = Path("tests/benchmarks/retrieval_benchmark_results.json")
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "summary": summary,
            "hybrid_vs_dense_mrr_improvement": improvement,
            "requirement_met": improvement >= 0.15,
        }, f, indent=2)

    # Also write markdown table
    md_path = Path("tests/benchmarks/retrieval_benchmark_results.md")
    with open(md_path, "w") as f:
        f.write("# Retrieval Benchmark Results\n\n")
        f.write(f"| Strategy | Hit Rate@10 | MRR@10 | NDCG@10 |\n")
        f.write(f"|---|---|---|---|\n")
        for s, r in summary.items():
            f.write(f"| {s} | {r['hit_rate_at_10']} | {r['mrr_at_10']} | {r['ndcg_at_10']} |\n")
        f.write(f"\n**Hybrid+Reranked vs Dense MRR improvement: {improvement:.1%}**\n")

    print(f"\nResults saved to {out_path} and {md_path}")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
