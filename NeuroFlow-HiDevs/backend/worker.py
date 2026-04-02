"""Async ingestion worker — pulls jobs from Redis queue and processes documents."""
import asyncio
import json
import uuid

import redis.asyncio as aioredis
import structlog
from opentelemetry import trace

from config import settings
from db.pool import create_pool, get_pool
from pipelines.ingestion.chunker import auto_chunk
from pipelines.ingestion.extractors.pdf_extractor import extract_pdf
from pipelines.ingestion.extractors.docx_extractor import extract_docx
from pipelines.ingestion.extractors.csv_extractor import extract_csv
from pipelines.ingestion.extractors.url_extractor import extract_url

logger = structlog.get_logger()
tracer = trace.get_tracer("neuroflow.ingestion")

EXTRACTORS = {
    "pdf": lambda path, _: extract_pdf(path),
    "docx": lambda path, _: extract_docx(path),
    "csv": lambda path, _: extract_csv(path),
}


async def process_job(job: dict) -> None:
    doc_id = job["document_id"]
    source_type = job["source_type"]
    file_path = job.get("file_path")
    url = job.get("url")

    pool = get_pool()

    with tracer.start_as_current_span("ingestion.process") as span:
        span.set_attribute("document_id", doc_id)
        span.set_attribute("source_type", source_type)

        try:
            await pool.execute(
                "UPDATE documents SET status='processing' WHERE id=$1", doc_id
            )

            # ── Extract ────────────────────────────────────────────
            with tracer.start_as_current_span(f"ingestion.extract.{source_type}"):
                if source_type == "url" and url:
                    pages = await extract_url(url)
                elif source_type == "image" and file_path:
                    from pipelines.ingestion.extractors.image_extractor import extract_image
                    pages = await extract_image(file_path)
                elif file_path and source_type in EXTRACTORS:
                    pages = EXTRACTORS[source_type](file_path, None)
                else:
                    raise ValueError(f"Cannot extract source_type={source_type}")

            # ── Chunk ──────────────────────────────────────────────
            with tracer.start_as_current_span("ingestion.chunk"):
                all_chunks = []
                for page in pages:
                    chunks = auto_chunk(
                        text=page.content,
                        content_type=page.content_type,
                        source_type=source_type,
                        page_count=len(pages),
                    )
                    for c in chunks:
                        c.metadata.update(page.metadata)
                        c.metadata["page_number"] = page.page_number
                    all_chunks.extend(chunks)

            if not all_chunks:
                raise ValueError("No chunks extracted from document")

            # ── Embed ──────────────────────────────────────────────
            with tracer.start_as_current_span("ingestion.embed"):
                from providers.base import RoutingCriteria
                from providers.router import get_router
                router = get_router()
                provider, _ = await router.route(RoutingCriteria(task_type="embedding"))
                texts = [c.content for c in all_chunks]
                embeddings = await provider.embed(texts)

            # ── Write to DB ────────────────────────────────────────
            with tracer.start_as_current_span("ingestion.write_db"):
                for i, (chunk, embedding) in enumerate(zip(all_chunks, embeddings)):
                    chunk_id = str(uuid.uuid4())
                    await pool.execute(
                        """INSERT INTO chunks (id, document_id, content, embedding,
                               chunk_index, token_count, metadata)
                           VALUES ($1, $2, $3, $4::vector, $5, $6, $7)""",
                        chunk_id, doc_id, chunk.content,
                        str(embedding), chunk.chunk_index,
                        chunk.token_count, json.dumps(chunk.metadata),
                    )

                await pool.execute(
                    "UPDATE documents SET status='complete', chunk_count=$1 WHERE id=$2",
                    len(all_chunks), doc_id,
                )

            logger.info(
                "ingestion.complete",
                document_id=doc_id,
                chunks=len(all_chunks),
                source_type=source_type,
            )

        except Exception as exc:
            logger.error("ingestion.failed", document_id=doc_id, error=str(exc))
            await pool.execute(
                "UPDATE documents SET status='error' WHERE id=$1", doc_id
            )


async def run_worker() -> None:
    await create_pool()
    r = aioredis.from_url(settings.redis_url)
    logger.info("worker.started")

    while True:
        try:
            item = await r.brpop(settings.ingest_queue_key, timeout=5)
            if item:
                _, raw = item
                job = json.loads(raw)
                await process_job(job)
        except Exception as exc:
            logger.error("worker.error", error=str(exc))
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run_worker())
