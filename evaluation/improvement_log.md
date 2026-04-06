# Evaluation Improvement Log

Document each improvement attempt here during the quality improvement sprint (Task 18).

---

## Attempt 1 — Increase dense_k from 10 to 20

**Change:** Updated default `dense_k` from 10 to 20 in pipeline config.

**Why expected to help:** More candidates entering RRF means the fusion step has more material
to work with. Relevant chunks that fell just outside top-10 in dense retrieval can now be
recovered by RRF.

**Before:** Hit Rate@10 = 0.71, MRR@10 = 0.54
**After:** Hit Rate@10 = 0.79, MRR@10 = 0.60

**Decision: KEEP** — +8pp Hit Rate, +6pp MRR. Clear improvement.

---

## Attempt 2 — Reduce top_k_after_rerank from 10 to 6

**Change:** Reduced `top_k_after_rerank` from 10 to 6.

**Why expected to help:** Fewer but higher-precision chunks in the context window means
the generation model has less noise to filter. Expected to improve faithfulness and
context precision, though may slightly reduce recall.

**Before:** Faithfulness = 0.73, Context Precision = 0.68
**After:** Faithfulness = 0.81, Context Precision = 0.75

**Decision: KEEP** — Precision gains outweigh small recall reduction. Faithfulness
exceeded target threshold.

---

## Attempt 3 — Add query expansion (2 alternative phrasings)

**Change:** Enabled `query_expansion: true` in pipeline retrieval config. Generates
2 alternative phrasings via `llama-3.1-8b-instant` and retrieves for all three.

**Why expected to help:** Different phrasings activate different embedding dimensions.
A query about "transformer attention" and "self-attention mechanism" retrieves
complementary chunks that a single embedding would miss.

**Before:** Hit Rate@10 = 0.79
**After:** Hit Rate@10 = 0.84

**Decision: KEEP** — +5pp Hit Rate. Adds ~100ms latency (parallel retrieval mitigates).

---

## Notes

All improvements are configurable pipeline parameters — no hardcoded changes.
A/B test results logged in MLflow experiments under `neuroflow-quality-sprint`.
