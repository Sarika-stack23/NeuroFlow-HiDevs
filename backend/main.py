"""NeuroFlow FastAPI application."""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import make_asgi_app

from config import settings
from db.pool import close_pool, create_pool
from db.health import check_postgres, check_redis, check_mlflow
from monitoring.metrics import init_metrics
from resilience.circuit_breaker import CircuitBreakerRegistry
from api.auth import router as auth_router
from api.ingest import router as ingest_router
from api.query import router as query_router
from api.evaluations import router as eval_router
from api.pipelines import router as pipeline_router
from api.finetune import router as finetune_router
from api.admin import router as admin_router

logger = structlog.get_logger()


def setup_telemetry() -> None:
    provider = TracerProvider()
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    # Startup
    logger.info("neuroflow.startup", environment=settings.environment)
    setup_telemetry()
    await create_pool()
    init_metrics()
    CircuitBreakerRegistry.initialize()
    logger.info("neuroflow.ready")
    yield
    # Shutdown
    await close_pool()
    logger.info("neuroflow.shutdown")


app = FastAPI(
    title="NeuroFlow",
    description="Production multi-modal LLM orchestration platform with RAG and fine-tuning",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import uuid


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Request-ID"] = str(uuid.uuid4())
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Instrument FastAPI
FastAPIInstrumentor.instrument_app(app)

# Routers
app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(ingest_router, tags=["Ingestion"])
app.include_router(query_router, tags=["Query"])
app.include_router(eval_router, tags=["Evaluation"])
app.include_router(pipeline_router, tags=["Pipelines"])
app.include_router(finetune_router, tags=["Fine-Tuning"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health", tags=["System"], summary="System health check")
async def health():
    """Check connectivity to Postgres, Redis, and MLflow."""
    pg_ok = await check_postgres()
    redis_ok = await check_redis()
    mlflow_ok = await check_mlflow()

    from resilience.circuit_breaker import CircuitBreakerRegistry
    cb_status = CircuitBreakerRegistry.get_all_status()

    import redis.asyncio as aioredis
    r = aioredis.from_url(settings.redis_url)
    queue_depth = await r.llen(settings.ingest_queue_key)
    await r.aclose()

    all_ok = pg_ok and redis_ok and mlflow_ok
    any_cb_open = any(v["state"] == "open" for v in cb_status.values())
    status = "ok" if (all_ok and not any_cb_open) else "degraded"
    if not pg_ok or not redis_ok:
        status = "critical"

    return {
        "status": status,
        "checks": {
            "postgres": {"status": "ok" if pg_ok else "error"},
            "redis": {"status": "ok" if redis_ok else "error"},
            "mlflow": {"status": "ok" if mlflow_ok else "error"},
            "circuit_breakers": cb_status,
            "queue_depth": queue_depth,
        },
    }
