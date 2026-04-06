# ADR 004 — Model Routing: Cost-Aware Groq-First Routing Matrix

**Status:** Accepted  
**Date:** 2024-01-01

---

## Context

NeuroFlow routes queries to different models based on task type, cost constraints,
capability requirements, and whether a fine-tuned model is available.
All chat/generation routes to Groq. Embeddings route to OpenAI (Groq has no embeddings API).

---

## Routing Matrix

| Query Type | Hard Requirements | Default Model | Override Conditions |
|---|---|---|---|
| `rag_generation` (simple factual) | — | `llama-3.1-8b-instant` | prefer_fine_tuned=True → fine-tuned if available |
| `rag_generation` (analytical/comparative) | — | `llama-3.3-70b-versatile` | max_cost limits to 8b |
| `evaluation` | no fine-tuned | `llama-3.3-70b-versatile` | never downgrade for cost |
| `classification` (injection check, query type) | low latency | `llama-3.1-8b-instant` | always cheapest |
| `image_description` | vision=True | `llama-3.2-11b-vision-preview` | upgrade to 90b for complex diagrams |
| `embedding` | — | OpenAI `text-embedding-3-small` | no Groq alternative |

---

## Routing Logic (implemented in `providers/router.py`)

```
1. Load model list from Redis (router:models) — updated on fine-tune job completion
2. Apply hard filters:
   a. require_vision=True  → keep only vision-capable models
   b. require_long_context → keep only context_window > 32k
   c. task_type=evaluation → remove fine-tuned models
   d. max_cost_per_call    → remove models exceeding budget
3. If prefer_fine_tuned: prefer fine-tuned models for matching task_type
4. Filter to task_type match
5. Sort by est_cost_per_call → select cheapest that satisfies all constraints
6. Fallback: llama-3.1-8b-instant if no candidates survive filtering
```

---

## Cost Estimates per Query (approximate)

| Scenario | Model | Est. cost |
|---|---|---|
| Simple RAG, short context | llama-3.1-8b-instant | $0.001 |
| Complex RAG, long context | llama-3.3-70b-versatile | $0.01 |
| Evaluation (4 metrics) | llama-3.3-70b-versatile × 4 | $0.04 |
| Image description | llama-3.2-11b-vision-preview | $0.005 |
| Embedding (512 tokens) | text-embedding-3-small | $0.0001 |

Total cost per query (RAG + evaluation): ~$0.05 average.

---

## Consequences

**Positive:**
- Groq provides 10–30× lower latency than OpenAI for same model class
- Cost-aware routing prevents runaway spending when max_cost_per_call is set
- Fine-tuned model routing closes the quality improvement loop automatically
- Fallback chain prevents hard failures when preferred model is unavailable

**Negative:**
- Groq rate limits (30 RPM on free tier, 6000 RPM on paid) can cause queuing under load
- No Groq embeddings endpoint — OpenAI dependency cannot be eliminated
- Fine-tuned model routing only activates when Groq exposes fine-tuning API
- Router reads from Redis on every call — adds ~1ms; mitigated by connection pooling
