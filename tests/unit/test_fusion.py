"""Unit tests for Reciprocal Rank Fusion."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

import pytest
from pipelines.retrieval.retriever import RetrievalResult, reciprocal_rank_fusion


def _make_result(id: str, score: float = 1.0) -> RetrievalResult:
    return RetrievalResult(
        id=id, document_id="doc1", document_name="test.pdf",
        content=f"Content for {id}", chunk_index=0, token_count=50,
        metadata={}, score=score,
    )


def test_rrf_single_list():
    results = [_make_result(str(i)) for i in range(5)]
    fused = reciprocal_rank_fusion([results])
    assert len(fused) == 5
    # First item should have highest RRF score
    assert fused[0].score >= fused[-1].score


def test_rrf_boosts_shared_results():
    list_a = [_make_result("chunk_x"), _make_result("chunk_y"), _make_result("chunk_z")]
    list_b = [_make_result("chunk_x"), _make_result("chunk_w"), _make_result("chunk_v")]
    fused = reciprocal_rank_fusion([list_a, list_b])

    ids = [r.id for r in fused]
    shared_rank = ids.index("chunk_x")
    unique_rank_a = ids.index("chunk_y")
    # chunk_x appears in both lists so should rank higher than chunk_y
    assert shared_rank < unique_rank_a


def test_rrf_merges_all_unique_items():
    list_a = [_make_result("a1"), _make_result("a2")]
    list_b = [_make_result("b1"), _make_result("b2")]
    fused = reciprocal_rank_fusion([list_a, list_b])
    assert len(fused) == 4


def test_rrf_empty_lists():
    fused = reciprocal_rank_fusion([[], []])
    assert fused == []


def test_rrf_formula_correctness():
    """Verify RRF score = sum(1/(k+rank)) across lists."""
    k = 60
    item = _make_result("shared")
    list_a = [item]
    list_b = [item]
    fused = reciprocal_rank_fusion([list_a, list_b], k=k)
    expected = 2 * (1.0 / (k + 1))
    assert abs(fused[0].score - expected) < 1e-9


def test_rrf_three_lists():
    list_a = [_make_result("x"), _make_result("y")]
    list_b = [_make_result("x"), _make_result("z")]
    list_c = [_make_result("x"), _make_result("w")]
    fused = reciprocal_rank_fusion([list_a, list_b, list_c])
    # x appears in all three, should be first
    assert fused[0].id == "x"
