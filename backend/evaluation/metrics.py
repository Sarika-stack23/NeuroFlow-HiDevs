"""RAGAS-inspired evaluation metrics using Groq as judge."""
from __future__ import annotations

import asyncio
import json

import structlog

from providers.base import ChatMessage, RoutingCriteria
from providers.router import get_router

logger = structlog.get_logger()


async def _judge(prompt: str) -> str:
    router = get_router()
    provider, _ = await router.route(RoutingCriteria(task_type="evaluation"))
    result = await provider.complete(
        [ChatMessage(role="user", content=prompt)],
        temperature=0.0,
        max_tokens=512,
    )
    return result.content.strip()


async def evaluate_faithfulness(query: str, answer: str, context: str) -> float:
    """Are all claims in the answer grounded in the retrieved context?"""
    if not answer.strip() or not context.strip():
        return 0.0

    # Step 1: Extract claims
    claims_raw = await _judge(
        f"List all factual claims made in the following answer as a JSON array of strings.\n"
        f"Answer: {answer}\nReturn ONLY a JSON array, no other text."
    )
    try:
        claims = json.loads(claims_raw)
        if not isinstance(claims, list):
            claims = [answer]
    except Exception:
        claims = [s.strip() for s in answer.split(".") if s.strip()][:10]

    if not claims:
        return 1.0

    # Step 2: Verify each claim against context
    async def check_claim(claim: str) -> float:
        verdict = await _judge(
            f"Is the following claim supported by the context? Answer 'yes', 'no', or 'partial'.\n"
            f"Context: {context[:2000]}\nClaim: {claim}"
        )
        v = verdict.lower()
        if "yes" in v:
            return 1.0
        if "partial" in v:
            return 0.5
        return 0.0

    scores = await asyncio.gather(*[check_claim(c) for c in claims[:10]])
    return sum(scores) / len(scores)


async def evaluate_answer_relevance(query: str, answer: str) -> float:
    """Does the answer address what was asked?"""
    if not answer.strip():
        return 0.0

    raw = await _judge(
        f"Generate 3-5 questions that the following answer could be a direct response to.\n"
        f"Answer: {answer}\nReturn ONLY a JSON array of question strings."
    )
    try:
        questions = json.loads(raw)
        if not isinstance(questions, list):
            questions = [query]
    except Exception:
        return 0.5

    # Embed original query and generated questions, compute cosine similarity
    try:
        import numpy as np

        router = get_router()
        provider, _ = await router.route(RoutingCriteria(task_type="embedding"))
        all_texts = [query] + questions[:5]
        embeddings = await provider.embed(all_texts)
        q_vec = np.array(embeddings[0])
        gen_vecs = [np.array(e) for e in embeddings[1:]]

        sims = [
            float(np.dot(q_vec, v) / (np.linalg.norm(q_vec) * np.linalg.norm(v) + 1e-9))
            for v in gen_vecs
        ]
        return float(sum(sims) / len(sims))
    except Exception:
        return 0.5


async def evaluate_context_precision(
    query: str, chunks: list[str], answer: str
) -> float:
    """Were the retrieved chunks actually useful?"""
    if not chunks:
        return 0.0

    async def is_useful(i: int, chunk: str) -> tuple[int, bool]:
        verdict = await _judge(
            f"Was this passage useful in generating the answer? Answer 'yes' or 'no'.\n"
            f"Query: {query}\nAnswer: {answer[:500]}\nPassage: {chunk[:500]}"
        )
        return i, "yes" in verdict.lower()

    results = await asyncio.gather(*[is_useful(i, c) for i, c in enumerate(chunks[:10])])
    results_sorted = sorted(results, key=lambda x: x[0])

    # Weighted precision: earlier chunks get more weight
    numerator = sum((1.0 / (i + 1)) for i, useful in results_sorted if useful)
    denominator = sum(1.0 / (i + 1) for i in range(len(results_sorted)))
    return numerator / denominator if denominator > 0 else 0.0


async def evaluate_context_recall(
    query: str, chunks: list[str], answer: str
) -> float:
    """Were the relevant sources retrieved?"""
    if not answer.strip():
        return 0.0

    sentences = [s.strip() for s in answer.split(".") if len(s.strip()) > 20]
    if not sentences:
        return 0.5

    context = "\n\n".join(chunks[:8])

    async def is_attributable(sent: str) -> bool:
        verdict = await _judge(
            f"Can the following sentence be attributed to (supported by) the provided context?\n"
            f"Context: {context[:2000]}\nSentence: {sent}\nAnswer 'yes' or 'no'."
        )
        return "yes" in verdict.lower()

    results = await asyncio.gather(*[is_attributable(s) for s in sentences[:10]])
    return sum(results) / len(results)
