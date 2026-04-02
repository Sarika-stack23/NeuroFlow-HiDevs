"""Application configuration — all env vars typed and documented."""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────────
    postgres_url: str = Field(..., description="Full asyncpg connection string")
    postgres_password: str = Field(..., description="Postgres password")

    # ── Redis ─────────────────────────────────────────────────────
    redis_url: str = Field(..., description="Redis connection URL")
    redis_password: str = Field("", description="Redis password")

    # ── LLM Providers ─────────────────────────────────────────────
    groq_api_key: str = Field(..., description="Groq API key (chat/generation)")
    openai_api_key: str = Field("", description="OpenAI API key — used ONLY for embeddings (text-embedding-3-small)")
    anthropic_api_key: str = Field("", description="Anthropic API key (optional fallback)")

    # ── MLflow ────────────────────────────────────────────────────
    mlflow_tracking_uri: str = Field("http://localhost:5000", description="MLflow tracking URI")

    # ── Security ──────────────────────────────────────────────────
    jwt_secret_key: str = Field(..., description="256-bit secret for JWT signing")
    jwt_algorithm: str = Field("HS256", description="JWT signing algorithm")
    jwt_expire_minutes: int = Field(60, description="JWT expiry in minutes")
    plugin_secrets_key: str = Field("", description="Fernet key for encrypting secrets")

    # ── Telemetry ─────────────────────────────────────────────────
    otel_exporter_otlp_endpoint: str = Field(
        "http://localhost:4317", description="OTLP collector endpoint"
    )
    sentry_dsn: str = Field("", description="Sentry DSN for error tracking")

    # ── App ───────────────────────────────────────────────────────
    environment: str = Field("development", description="development | staging | production")
    log_level: str = Field("INFO", description="Log level")
    max_upload_size_mb: int = Field(100, description="Max file upload size in MB")
    ingest_queue_key: str = Field("queue:ingest", description="Redis queue key for ingestion")

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
