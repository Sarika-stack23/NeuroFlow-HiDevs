"""Pydantic schema for pipeline configuration — rejects unknown keys."""
from pydantic import BaseModel, Field, model_validator


class IngestionConfig(BaseModel):
    model_config = {"extra": "forbid"}
    chunking_strategy: str = Field("fixed_size", pattern="^(fixed_size|semantic|hierarchical)$")
    chunk_size_tokens: int = Field(512, ge=64, le=2048)
    chunk_overlap_tokens: int = Field(64, ge=0, le=256)
    extractors_enabled: list[str] = Field(default_factory=lambda: ["pdf", "docx", "image", "csv", "url"])


class RetrievalConfig(BaseModel):
    model_config = {"extra": "forbid"}
    dense_k: int = Field(20, ge=1, le=100)
    sparse_k: int = Field(20, ge=1, le=100)
    reranker: str = Field("cross-encoder", pattern="^(cross-encoder|none)$")
    top_k_after_rerank: int = Field(8, ge=1, le=30)
    query_expansion: bool = True
    metadata_filters_enabled: bool = True


class ModelRoutingConfig(BaseModel):
    model_config = {"extra": "forbid"}
    task_type: str = "rag_generation"
    max_cost_per_call: float | None = None


class GenerationConfig(BaseModel):
    model_config = {"extra": "forbid"}
    model_routing: ModelRoutingConfig = Field(default_factory=ModelRoutingConfig)
    max_context_tokens: int = Field(4000, ge=500, le=16000)
    temperature: float = Field(0.3, ge=0.0, le=2.0)
    system_prompt_variant: str = Field("precise", pattern="^(precise|analytical|creative)$")


class EvaluationConfig(BaseModel):
    model_config = {"extra": "forbid"}
    auto_evaluate: bool = True
    training_threshold: float = Field(0.82, ge=0.5, le=1.0)


class PipelineConfig(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(..., max_length=100)
    description: str = ""
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
