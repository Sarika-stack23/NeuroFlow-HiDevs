"""POST /ingest — file and URL ingestion with deduplication and async processing."""
import hashlib
import json
import uuid
from typing import Annotated

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, HttpUrl

from api.auth import get_current_user, require_scope
from config import settings
from db.pool import get_pool
from resilience.rate_limiter import rate_limit

router = APIRouter()
logger = structlog.get_logger()

ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "text/csv": "csv",
    "text/plain": "text",
}


class IngestURLBody(BaseModel):
    url: HttpUrl
    pipeline_id: str | None = None


class IngestResponse(BaseModel):
    document_id: str
    status: str
    duplicate: bool


async def _check_queue_backpressure() -> None:
    r = aioredis.from_url(settings.redis_url)
    depth = await r.llen(settings.ingest_queue_key)
    await r.aclose()
    if depth > 100:
        raise HTTPException(
            status_code=503,
            detail={"error": "ingestion_queue_full", "queue_depth": depth, "retry_after": 30},
        )


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Ingest a file or URL",
    description="Upload a PDF, DOCX, image, or CSV file, or provide a URL. Processing is async.",
    tags=["Ingestion"],
)
async def ingest_file(
    file: UploadFile = File(...),
    pipeline_id: str | None = None,
    _: dict = Depends(require_scope("ingest")),
    __=Depends(rate_limit(10, 3600, "ingest")),
):
    await _check_queue_backpressure()

    # Validate size
    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")

    # Validate type
    content_type = file.content_type or ""
    source_type = ALLOWED_TYPES.get(content_type)
    if not source_type:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {content_type}")

    # Deduplication
    content_hash = hashlib.sha256(content).hexdigest()
    pool = get_pool()
    existing = await pool.fetchrow(
        "SELECT id FROM documents WHERE content_hash = $1", content_hash
    )
    if existing:
        return IngestResponse(
            document_id=str(existing["id"]), status="complete", duplicate=True
        )

    # Create document row
    doc_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO documents (id, filename, source_type, content_hash, pipeline_id, status)
           VALUES ($1, $2, $3, $4, $5, 'queued')""",
        doc_id, file.filename or "upload", source_type, content_hash, pipeline_id,
    )

    # Save file to temp storage
    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{source_type}")
    tmp.write(content)
    tmp.close()

    # Enqueue
    r = aioredis.from_url(settings.redis_url)
    await r.lpush(
        settings.ingest_queue_key,
        json.dumps({"document_id": doc_id, "file_path": tmp.name, "source_type": source_type}),
    )
    await r.aclose()

    logger.info("ingest.queued", document_id=doc_id, source_type=source_type)
    return IngestResponse(document_id=doc_id, status="queued", duplicate=False)


@router.post("/ingest/url", response_model=IngestResponse, tags=["Ingestion"])
async def ingest_url(
    body: IngestURLBody,
    _: dict = Depends(require_scope("ingest")),
):
    await _check_queue_backpressure()

    url_str = str(body.url)
    import ipaddress, socket
    # SSRF protection
    try:
        host = body.url.host  # type: ignore
        ip = socket.gethostbyname(host)
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback:
            raise HTTPException(status_code=400, detail="Private/loopback URLs not allowed")
    except HTTPException:
        raise
    except Exception:
        pass

    content_hash = hashlib.sha256(url_str.encode()).hexdigest()
    pool = get_pool()
    existing = await pool.fetchrow("SELECT id FROM documents WHERE content_hash = $1", content_hash)
    if existing:
        return IngestResponse(document_id=str(existing["id"]), status="complete", duplicate=True)

    doc_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO documents (id, filename, source_type, content_hash, pipeline_id, status)
           VALUES ($1, $2, 'url', $3, $4, 'queued')""",
        doc_id, url_str[:200], content_hash, body.pipeline_id,
    )

    r = aioredis.from_url(settings.redis_url)
    await r.lpush(
        settings.ingest_queue_key,
        json.dumps({"document_id": doc_id, "url": url_str, "source_type": "url"}),
    )
    await r.aclose()
    return IngestResponse(document_id=doc_id, status="queued", duplicate=False)


@router.get("/documents/{document_id}", tags=["Ingestion"])
async def get_document(document_id: str, _: dict = Depends(get_current_user)):
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM documents WHERE id = $1", document_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(row)
