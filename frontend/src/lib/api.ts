import axios from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const api = axios.create({ baseURL: API_BASE });

// Inject auth token from localStorage
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("neuroflow_token");
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;

// ── Pipelines ─────────────────────────────────────────────────────────────────
export const getPipelines = () => api.get("/pipelines").then((r) => r.data);
export const createPipeline = (body: object) => api.post("/pipelines", body).then((r) => r.data);
export const getPipelineAnalytics = (id: string) =>
  api.get(`/pipelines/${id}/analytics`).then((r) => r.data);
export const comparePipelines = (body: object) =>
  api.post("/pipelines/compare", body).then((r) => r.data);

// ── Documents ─────────────────────────────────────────────────────────────────
export const uploadFile = (file: File, pipelineId?: string) => {
  const form = new FormData();
  form.append("file", file);
  if (pipelineId) form.append("pipeline_id", pipelineId);
  return api.post("/ingest", form).then((r) => r.data);
};
export const getDocument = (id: string) => api.get(`/documents/${id}`).then((r) => r.data);

// ── Query ─────────────────────────────────────────────────────────────────────
export const submitQuery = (query: string, pipelineId: string) =>
  api.post("/query", { query, pipeline_id: pipelineId, stream: true }).then((r) => r.data);

// ── Evaluations ───────────────────────────────────────────────────────────────
export const getEvaluations = (params?: object) =>
  api.get("/evaluations", { params }).then((r) => r.data);
export const getAggregate = () => api.get("/evaluations/aggregate").then((r) => r.data);
export const patchRating = (runId: string, rating: number) =>
  api.patch(`/runs/${runId}/rating`, { rating }).then((r) => r.data);

// ── Auth ──────────────────────────────────────────────────────────────────────
export const getToken = (clientId: string, clientSecret: string) =>
  api.post("/auth/token", { client_id: clientId, client_secret: clientSecret }).then((r) => r.data);
