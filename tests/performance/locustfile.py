"""
Locust load test for NeuroFlow.
Run: locust -f tests/performance/locustfile.py -H http://localhost:8000 --headless -u 50 -r 5 --run-time 5m
"""
import json
import random
import os
from locust import HttpUser, task, between, events

TOKEN = os.getenv("NEUROFLOW_API_KEY", "")
PIPELINE_ID = os.getenv("NEUROFLOW_PIPELINE_ID", "")

SAMPLE_QUERIES = [
    "What is retrieval augmented generation?",
    "How does attention work in transformers?",
    "What are the main components of a RAG pipeline?",
    "Explain the difference between dense and sparse retrieval.",
    "What is reciprocal rank fusion?",
    "How does cross-encoder reranking work?",
    "What metrics are used to evaluate RAG systems?",
    "What is context precision in RAGAS?",
    "How does fine-tuning improve RAG performance?",
    "What is a circuit breaker pattern?",
]


class QueryUser(HttpUser):
    weight = 7
    wait_time = between(1, 3)

    def on_start(self):
        self.headers = {"Authorization": f"Bearer {TOKEN}"}
        if not PIPELINE_ID:
            resp = self.client.get("/pipelines", headers=self.headers)
            pipelines = resp.json()
            self.pipeline_id = pipelines[0]["id"] if pipelines else ""
        else:
            self.pipeline_id = PIPELINE_ID

    @task(3)
    def submit_query(self):
        query = random.choice(SAMPLE_QUERIES)
        with self.client.post(
            "/query",
            json={"query": query, "pipeline_id": self.pipeline_id, "stream": True},
            headers=self.headers,
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 429:
                resp.success()  # Rate limit is expected behaviour, not failure
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")

    @task(1)
    def get_evaluations(self):
        self.client.get("/evaluations?page=1&page_size=10", headers=self.headers)

    @task(1)
    def check_health(self):
        self.client.get("/health")


class IngestUser(HttpUser):
    weight = 2
    wait_time = between(5, 15)

    def on_start(self):
        self.headers = {"Authorization": f"Bearer {TOKEN}"}

    @task
    def ingest_url(self):
        test_urls = [
            "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
            "https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)",
        ]
        url = random.choice(test_urls)
        with self.client.post(
            "/ingest/url",
            json={"url": url},
            headers=self.headers,
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 503):  # 503 = queue full, expected under load
                resp.success()
            else:
                resp.failure(f"Unexpected: {resp.status_code}")


class AdminUser(HttpUser):
    weight = 1
    wait_time = between(10, 30)

    def on_start(self):
        self.headers = {"Authorization": f"Bearer {TOKEN}"}

    @task
    def get_pipelines(self):
        self.client.get("/pipelines", headers=self.headers)

    @task
    def get_aggregate_evals(self):
        self.client.get("/evaluations/aggregate", headers=self.headers)


@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    """Save load test results on exit."""
    stats = environment.stats
    total = stats.total

    results = {
        "total_requests": total.num_requests,
        "total_failures": total.num_failures,
        "failure_rate": total.fail_ratio,
        "p50_ms": total.get_response_time_percentile(0.50),
        "p95_ms": total.get_response_time_percentile(0.95),
        "p99_ms": total.get_response_time_percentile(0.99),
        "rps": total.current_rps,
    }

    print("\n=== Load Test Results ===")
    for k, v in results.items():
        print(f"  {k}: {v}")

    passed = results["p95_ms"] < 5000 and results["failure_rate"] < 0.02
    print(f"\n  RESULT: {'PASS ✓' if passed else 'FAIL ✗'}")
    print(f"  (P95 < 5000ms and error rate < 2%)")

    with open("tests/performance/load_test_results.json", "w") as f:
        json.dump({**results, "passed": passed}, f, indent=2)
