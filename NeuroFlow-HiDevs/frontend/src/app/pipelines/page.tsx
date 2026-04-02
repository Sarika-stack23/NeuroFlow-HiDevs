"use client";
import { useEffect, useState } from "react";
import { getPipelines, createPipeline, getPipelineAnalytics } from "@/lib/api";
import { Plus, X, TrendingUp } from "lucide-react";
import { RadarChart, PolarGrid, PolarAngleAxis, Radar, ResponsiveContainer } from "recharts";

const SCORE_COLOR = (score: number) =>
  score >= 0.8 ? "text-green-400" : score >= 0.6 ? "text-yellow-400" : "text-red-400";

const DEFAULT_CONFIG = JSON.stringify({
  name: "my-pipeline",
  ingestion: { chunking_strategy: "fixed_size", chunk_size_tokens: 512 },
  retrieval: { dense_k: 20, sparse_k: 15, top_k_after_rerank: 8 },
  generation: { max_context_tokens: 4000, temperature: 0.3 },
  evaluation: { auto_evaluate: true },
}, null, 2);

export default function PipelinesPage() {
  const [pipelines, setPipelines] = useState<any[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [configText, setConfigText] = useState(DEFAULT_CONFIG);
  const [configError, setConfigError] = useState("");
  const [selected, setSelected] = useState<any>(null);
  const [analytics, setAnalytics] = useState<any>(null);

  const load = () => getPipelines().then(setPipelines).catch(() => {});

  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    try {
      const parsed = JSON.parse(configText);
      setConfigError("");
      await createPipeline(parsed);
      setShowCreate(false);
      load();
    } catch (e: any) {
      setConfigError(e.response?.data?.detail || e.message);
    }
  };

  const handleSelect = async (p: any) => {
    setSelected(p);
    const a = await getPipelineAnalytics(p.id).catch(() => null);
    setAnalytics(a);
  };

  const radarData = analytics?.quality ? [
    { metric: "Faithfulness", value: analytics.quality.faithfulness || 0 },
    { metric: "Relevance", value: analytics.quality.answer_relevance || 0 },
    { metric: "Precision", value: analytics.quality.context_precision || 0 },
    { metric: "Recall", value: analytics.quality.context_recall || 0 },
  ] : [];

  return (
    <div className="flex h-full">
      {/* List */}
      <div className="flex-1 p-6">
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-2xl font-bold text-white">Pipelines</h1>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm px-4 py-2 rounded-lg transition-colors"
          >
            <Plus size={15} /> New Pipeline
          </button>
        </div>

        <div className="grid gap-3">
          {pipelines.map((p) => {
            const score = Number(p.avg_score || 0);
            return (
              <div
                key={p.id}
                onClick={() => handleSelect(p)}
                className="bg-gray-900 border border-gray-800 hover:border-indigo-700 rounded-xl p-4 cursor-pointer transition-colors"
              >
                <div className="flex justify-between items-center">
                  <div>
                    <div className="font-medium text-white">{p.name}</div>
                    <div className="text-xs text-gray-500 mt-0.5">v{p.version} · {p.run_count || 0} runs (7d)</div>
                  </div>
                  <div className={`text-lg font-bold ${SCORE_COLOR(score)}`}>
                    {score > 0 ? score.toFixed(2) : "—"}
                  </div>
                </div>
              </div>
            );
          })}
          {pipelines.length === 0 && (
            <div className="text-gray-600 text-sm text-center py-12">No pipelines yet. Create your first one.</div>
          )}
        </div>
      </div>

      {/* Analytics drawer */}
      {selected && (
        <div className="w-96 bg-gray-900 border-l border-gray-800 p-6 overflow-auto">
          <div className="flex justify-between items-center mb-4">
            <h2 className="font-semibold text-white">{selected.name}</h2>
            <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-white">
              <X size={16} />
            </button>
          </div>

          {analytics && (
            <>
              <div className="grid grid-cols-2 gap-3 mb-6">
                {[["P50 Latency", analytics.latency?.p50], ["P95 Latency", analytics.latency?.p95]].map(([label, val]) => (
                  <div key={label as string} className="bg-gray-800 rounded-lg p-3">
                    <div className="text-xs text-gray-500">{label}</div>
                    <div className="text-lg font-bold text-white">{val ? `${Math.round(val as number)}ms` : "—"}</div>
                  </div>
                ))}
              </div>

              {radarData.length > 0 && (
                <div className="h-52">
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart data={radarData}>
                      <PolarGrid stroke="#374151" />
                      <PolarAngleAxis dataKey="metric" tick={{ fill: "#9ca3af", fontSize: 11 }} />
                      <Radar dataKey="value" stroke="#6366f1" fill="#6366f1" fillOpacity={0.3} />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-[560px] max-h-[80vh] flex flex-col">
            <div className="flex justify-between items-center mb-4">
              <h2 className="font-semibold text-white">Create Pipeline</h2>
              <button onClick={() => setShowCreate(false)} className="text-gray-500 hover:text-white">
                <X size={16} />
              </button>
            </div>
            <textarea
              value={configText}
              onChange={(e) => setConfigText(e.target.value)}
              className="flex-1 bg-gray-800 text-green-300 text-xs font-mono rounded-lg p-4 resize-none focus:outline-none border border-gray-700 min-h-[300px]"
              spellCheck={false}
            />
            {configError && <div className="mt-2 text-xs text-red-400">{configError}</div>}
            <div className="flex gap-3 mt-4 justify-end">
              <button onClick={() => setShowCreate(false)} className="text-gray-400 hover:text-white text-sm px-4 py-2">Cancel</button>
              <button onClick={handleCreate} className="bg-indigo-600 hover:bg-indigo-500 text-white text-sm px-4 py-2 rounded-lg">Create</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
