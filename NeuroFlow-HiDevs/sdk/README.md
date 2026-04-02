# NeuroFlow SDK

Python client for the NeuroFlow RAG platform.

## Install

```bash
pip install ./sdk
```

## Quickstart

```python
import asyncio
from neuroflow import NeuroFlowClient

async def main():
    client = NeuroFlowClient(
        base_url="http://localhost:8000",
        api_key="your-jwt-token"
    )

    # Ingest a document
    doc = await client.ingest_file("report.pdf")
    print(f"Ingested {doc.id} — {doc.chunk_count} chunks")

    # Non-streaming query
    result = await client.query("What is the main finding?", pipeline_id="your-pipeline-id")
    print(result.generation)

    # Streaming query
    async for token in await client.query("Summarize the risks", pipeline_id="your-pipeline-id", stream=True):
        print(token, end="", flush=True)

    # Get evaluation score
    eval_result = await client.get_evaluation(result.run_id)
    print(f"Overall score: {eval_result.overall_score:.2f}")

asyncio.run(main())
```
