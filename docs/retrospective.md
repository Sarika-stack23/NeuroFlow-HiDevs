# NeuroFlow — Project Retrospective

## The Hardest Task: Task 5 — Retrieval Pipeline

The retrieval pipeline was by far the most technically demanding task in the project.
The difficulty was not in writing the code — it was in understanding *why* naive retrieval
fails and engineering specific solutions to each failure mode.

Dense-only retrieval with cosine similarity has a fundamental flaw: it retrieves
semantically similar text, not necessarily *relevant* text. A query about "transformer
attention mechanism" would retrieve passages about "transformers" (the electrical device)
if those happened to have been embedded close in the latent space due to co-occurring
vocabulary. The moment you add sparse BM25-style retrieval and fuse the results via RRF,
this problem largely disappears — exact keyword matches ground the results in a way that
dense similarity alone cannot.

Implementing RRF correctly was subtle. The formula `1 / (k + rank)` looks trivial but the
choice of `k=60` matters significantly. Too small and the fusion is dominated by the top
result of a single list; too large and the rank signal gets diluted. I found that `k=60`
(from the original DeGrave et al. paper) performed well across our test set, but it is
a hyperparameter that should be tuned per domain.

The cross-encoder reranker added a second layer of complexity. Using an LLM to score
`(query, chunk)` relevance pairs in parallel was effective but expensive — 20 API calls
per query. At production scale this would dominate cost. The right long-term solution is
a local cross-encoder model (`cross-encoder/ms-marco-MiniLM-L-6-v2`) that runs in the
worker container. The LLM-based reranker is a reasonable MVP.

---

## The Design Decision I Would Change: Evaluation Architecture

With hindsight, I would restructure the evaluation subsystem to run as a completely
separate async service rather than as a background worker on the same Redis queue as
ingestion.

The current architecture puts both ingestion jobs and evaluation jobs on different Redis
queues, processed by the same worker binary. This means a flood of ingestion jobs can
crowd out evaluations, delaying the quality feedback loop. More importantly, evaluation
has completely different resource and scaling characteristics than ingestion: ingestion
is I/O and compute-heavy (OCR, PDF rasterization), while evaluation is almost purely
LLM API calls.

In ADR 003, I justified automated evaluation but did not adequately think through the
operational separation of concerns. A dedicated evaluation microservice with its own
queue, worker pool, and circuit breaker would be more robust and easier to scale
independently.

---

## What Building a Production AI System Actually Taught Me

Three things that no tutorial communicated effectively:

**1. Evaluation is the real engineering challenge.** Writing a RAG pipeline that produces
some output is easy. Building one that reliably produces *good* output — and knowing
*when* it is good — is where most of the engineering effort goes. The RAGAS metrics
implementation, the calibration check, the human feedback integration, and the quality
dashboard together represent more work than the retrieval and generation pipelines
combined. Quality cannot be an afterthought.

**2. Operational concerns dominate architecture decisions.** The choice of pgvector over
Pinecone was not primarily a technical one — it was an operational one. One service to
monitor, one backup, one connection pool, one set of credentials. Every additional
service in a production system is another thing to fail at 3 AM. The runbook exists
precisely because things do fail, and the best architecture minimises the blast radius.

**3. Async correctness is harder than async performance.** The ingestion worker, the
evaluation worker, the SSE streaming endpoint, and the circuit breaker are all concurrent.
Getting concurrent code *correct* — ensuring resources are released, errors are propagated,
and state is consistent across restarts — required more careful thinking than any
individual algorithm. Redis-backed circuit breaker state is a good example: in-memory
state would be simpler but would reset on every API restart, causing circuit breakers to
re-open providers that are genuinely broken.

---

## What the Quality Improvement Sprint (Task 18) Taught Me

Task 18 — the metric improvement sprint — was the most realistic task in the project and
the one that most closely mirrors actual production AI engineering work.

The key insight from the sprint was that **most quality improvements come from fixing
retrieval, not generation.** When faithfulness was low, the root cause was almost never
the generation model producing hallucinations — it was the retrieval returning irrelevant
chunks, causing the model to fill gaps from its parametric knowledge.

The three most impactful improvements in order were:
1. Increasing `dense_k` from 10 to 20 (more candidates for RRF to work with)
2. Reducing `top_k_after_rerank` from 10 to 6 (tighter, higher-precision context)
3. Adding query expansion (2 alternative phrasings improved hit rate by ~8%)

Prompt engineering improvements had marginal effect by comparison. The lesson: optimize
retrieval first, then generation, then prompts. The community tends to obsess over prompt
engineering because it is easy and visible, but the highest-leverage work is in the
retrieval pipeline.
