"""Unit tests for PipelineConfig Pydantic validation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

import pytest
from pydantic import ValidationError
from models.pipeline import PipelineConfig


VALID_CONFIG = {
    "name": "test-pipeline",
    "description": "A test pipeline",
    "ingestion": {
        "chunking_strategy": "fixed_size",
        "chunk_size_tokens": 512,
        "chunk_overlap_tokens": 64,
    },
    "retrieval": {
        "dense_k": 20,
        "sparse_k": 15,
        "reranker": "cross-encoder",
        "top_k_after_rerank": 8,
        "query_expansion": True,
        "metadata_filters_enabled": True,
    },
    "generation": {
        "max_context_tokens": 4000,
        "temperature": 0.3,
        "system_prompt_variant": "precise",
    },
    "evaluation": {
        "auto_evaluate": True,
        "training_threshold": 0.82,
    },
}


def test_valid_config_passes():
    config = PipelineConfig(**VALID_CONFIG)
    assert config.name == "test-pipeline"


def test_unknown_top_level_key_rejected():
    bad = {**VALID_CONFIG, "unknown_key": "value"}
    with pytest.raises(ValidationError):
        PipelineConfig(**bad)


def test_unknown_nested_key_rejected():
    bad = dict(VALID_CONFIG)
    bad["retrieval"] = {**VALID_CONFIG["retrieval"], "bad_param": True}
    with pytest.raises(ValidationError):
        PipelineConfig(**bad)


def test_invalid_chunking_strategy():
    bad = dict(VALID_CONFIG)
    bad["ingestion"] = {**VALID_CONFIG["ingestion"], "chunking_strategy": "random"}
    with pytest.raises(ValidationError):
        PipelineConfig(**bad)


def test_chunk_size_too_small():
    bad = dict(VALID_CONFIG)
    bad["ingestion"] = {**VALID_CONFIG["ingestion"], "chunk_size_tokens": 10}
    with pytest.raises(ValidationError):
        PipelineConfig(**bad)


def test_temperature_out_of_range():
    bad = dict(VALID_CONFIG)
    bad["generation"] = {**VALID_CONFIG["generation"], "temperature": 3.0}
    with pytest.raises(ValidationError):
        PipelineConfig(**bad)


def test_invalid_reranker():
    bad = dict(VALID_CONFIG)
    bad["retrieval"] = {**VALID_CONFIG["retrieval"], "reranker": "magic-reranker"}
    with pytest.raises(ValidationError):
        PipelineConfig(**bad)


def test_training_threshold_bounds():
    bad = dict(VALID_CONFIG)
    bad["evaluation"] = {"auto_evaluate": True, "training_threshold": 0.1}
    with pytest.raises(ValidationError):
        PipelineConfig(**bad)


def test_defaults_applied():
    minimal = {"name": "minimal"}
    config = PipelineConfig(**minimal)
    assert config.retrieval.dense_k == 20
    assert config.generation.temperature == 0.3
    assert config.evaluation.auto_evaluate is True
