# ADR 003 — Evaluation Framework: LLM-as-Judge over Human Annotation Only

**Status:** Accepted  
**Date:** 2024-01-01

---

## Context

Every RAG generation must be scored for quality. The scores drive:
1. Training pair selection (high-quality generations → fine-tuning data)
2. Quality monitoring (degradation alerts in Grafana)
3. Pipeline A/B comparison

Two approaches were evaluated:

**Human annotation** has a human reviewer score each generation on faithfulness, relevance,
and context usage. Gold standard quality. Cons: does not scale — at 1,000 queries/day,
reviewing every generation would require a full-time annotator. Latency is days to weeks,
not seconds. Cannot gate fine-tuning pipelines that run automatically.

**LLM-as-Judge (automated)** uses an LLM to evaluate generations against the RAGAS metric
framework. Scores available within seconds. Scales to any query volume. Can trigger
automated workflows (fine-tuning, alerts). Cons: the judge is itself an LLM and can be
wrong. Correlation with human judgments is high (~0.85) but not perfect.

---

## Decision

Use **automated LLM-as-judge evaluation** (RAGAS-inspired) with four metrics:

- **Faithfulness** (0.35 weight) — claim extraction + context verification
- **Answer Relevance** (0.30 weight) — generated question similarity to original query
- **Context Precision** (0.20 weight) — proportion of retrieved chunks that were useful
- **Context Recall** (0.15 weight) — proportion of answer sentences attributable to context

All four run in parallel via `asyncio.gather`. Overall score = weighted sum.

Human feedback is collected via thumbs up/down (PATCH /runs/{id}/rating) and stored
in `evaluations.user_rating`. When |automated_overall − user_rating/5| > 0.3, the
evaluation is flagged as `calibration_needed`.

The judge always uses `llama-3.3-70b-versatile` (Groq) — never a fine-tuned model.
Evaluating with a fine-tuned model creates circular feedback: the model would score
its own style of answer highly, inflating scores and corrupting training data.

---

## Known Failure Modes

| Failure mode | Detection | Mitigation |
|---|---|---|
| Judge overconfident on its own style | Calibration drift > 0.3 | Flag + human review queue |
| Faithfulness false positives on vague claims | Low precision on calibration set | Tighten claim extraction prompt |
| Answer relevance gaming (verbose non-answers) | Low user_rating despite high score | Weight user_rating in overall if available |
| Context recall underscoring on implicit attribution | Sentence-level check misses paraphrases | Switch to paragraph-level attribution |
| Prompt injection in ingested docs manipulating judge | Injection pattern scanner | Pre-screen all chunks before evaluation |

**Calibration check:** Run the judge on the 30-example annotated set in
`evaluation/calibration/annotated_set.json`. Pearson correlation must exceed 0.85.
If it drops below 0.75 in production monitoring, halt automated fine-tuning until
re-calibrated.

---

## Consequences

**Positive:**
- Scores available in seconds, not days
- Every generation is evaluated — comprehensive coverage
- Enables automated fine-tuning pipeline and quality alerting
- Human feedback supplements automated scores, not replaces them

**Negative:**
- Cannot fully replace human judgment for high-stakes decisions
- Judge quality is bounded by the capability of `llama-3.3-70b-versatile`
- 4 LLM calls per evaluation adds ~$0.01–0.05 cost per query
- Parallel execution reduces latency but not cost
