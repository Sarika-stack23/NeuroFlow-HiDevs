"""NeuroFlow Python SDK — async client for the NeuroFlow API."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator

import httpx


@dataclass
class Document:
    id: str
    filename: str
    source_type: str
    status: str
    chunk_count: int | None = None
    metadata: dict | None = None


@dataclass
class QueryResult:
    run_id: str
    generation: str
    citations: list[dict]
    chunks_used: int
    model_used: str | None = None


@dataclass
class EvaluationResult:
    eval_id: str
    run_id: str
    faithfulness: float
    answer_relevance: float
    context_precision: float
    context_recall: float
    overall_score: float


class NeuroFlowClient:
    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=120,
        )

    async def ingest_file(self, file_path: str | Path, pipeline_id: str | None = None) -> Document:
        """Upload and ingest a file. Polls until ingestion is complete."""
        path = Path(file_path)
        async with self._client() as client:
            with open(path, "rb") as f:
                params = {}
                if pipeline_id:
                    params["pipeline_id"] = pipeline_id
                resp = await client.post(
                    "/ingest",
                    files={"file": (path.name, f, "application/octet-stream")},
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                doc_id = data["document_id"]

            # Poll for completion
            for _ in range(60):
                await asyncio.sleep(2)
                status_resp = await client.get(f"/documents/{doc_id}")
                doc = status_resp.json()
                if doc["status"] in ("complete", "error"):
                    return Document(
                        id=doc["id"],
                        filename=doc["filename"],
                        source_type=doc["source_type"],
                        status=doc["status"],
                        chunk_count=doc.get("chunk_count"),
                        metadata=doc.get("metadata"),
                    )
        raise TimeoutError(f"Document {doc_id} did not complete ingestion in time")

    async def ingest_url(self, url: str, pipeline_id: str | None = None) -> Document:
        """Ingest a URL. Polls until ingestion is complete."""
        async with self._client() as client:
            body: dict = {"url": url}
            if pipeline_id:
                body["pipeline_id"] = pipeline_id
            resp = await client.post("/ingest/url", json=body)
            resp.raise_for_status()
            doc_id = resp.json()["document_id"]

            for _ in range(60):
                await asyncio.sleep(2)
                doc = (await client.get(f"/documents/{doc_id}")).json()
                if doc["status"] in ("complete", "error"):
                    return Document(**{k: doc[k] for k in ("id", "filename", "source_type", "status") if k in doc})
        raise TimeoutError("URL ingestion timed out")

    async def query(
        self,
        query: str,
        pipeline_id: str,
        stream: bool = False,
    ) -> QueryResult | AsyncGenerator[str, None]:
        """
        Run a RAG query.
        If stream=True, returns an async generator of token strings.
        If stream=False, waits for full completion and returns QueryResult.
        """
        async with self._client() as client:
            resp = await client.post(
                "/query",
                json={"query": query, "pipeline_id": pipeline_id, "stream": True},
            )
            resp.raise_for_status()
            run_id = resp.json()["run_id"]

        if stream:
            return self._stream_tokens(run_id)
        else:
            return await self._collect_result(run_id)

    async def _stream_tokens(self, run_id: str) -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=120,
        ) as client:
            async with client.stream("GET", f"/query/{run_id}/stream") as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        if data.get("type") == "token":
                            yield data.get("delta", "")
                        elif data.get("type") == "done":
                            return

    async def _collect_result(self, run_id: str) -> QueryResult:
        full_text = ""
        citations: list[dict] = []
        async for token in self._stream_tokens(run_id):
            full_text += token

        async with self._client() as client:
            run = (await client.get(f"/query/{run_id}/stream")).json()
        return QueryResult(
            run_id=run_id,
            generation=full_text,
            citations=citations,
            chunks_used=0,
        )

    async def get_evaluation(self, run_id: str, wait: bool = True) -> EvaluationResult | None:
        """Get evaluation results for a query run. Optionally waits for async eval."""
        async with self._client() as client:
            for _ in range(30 if wait else 1):
                resp = await client.get("/evaluations", params={"page": 1, "page_size": 100})
                evals = resp.json()
                for e in evals:
                    if e.get("run_id") == run_id:
                        return EvaluationResult(
                            eval_id=e["id"],
                            run_id=run_id,
                            faithfulness=e.get("faithfulness", 0),
                            answer_relevance=e.get("answer_relevance", 0),
                            context_precision=e.get("context_precision", 0),
                            context_recall=e.get("context_recall", 0),
                            overall_score=e.get("overall_score", 0),
                        )
                if not wait:
                    break
                await asyncio.sleep(3)
        return None

    async def list_pipelines(self) -> list[dict]:
        async with self._client() as client:
            resp = await client.get("/pipelines")
            resp.raise_for_status()
            return resp.json()

    async def create_pipeline(self, config: dict) -> dict:
        async with self._client() as client:
            resp = await client.post("/pipelines", json=config)
            resp.raise_for_status()
            return resp.json()
