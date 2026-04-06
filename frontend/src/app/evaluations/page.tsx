"use client";
import { useEffect, useRef, useState } from "react";
import { getEvaluations } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? "bg-green-500" : pct >= 60 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div>
      <div className="flex justify-between text-xs mb-0.5">
        <span className="text-gray-400">{label}</span>
        <span className="text-gray-300">{pct}%</span>
      </div>
      <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function EvalCard({ eval: e, expanded, onClick }: { eval: any; expanded: boolean; onClick: () => void }) {
  const score = Number(e.overall_score || 0);
  const color = score >= 0.8 ? "text-green-400 border-green-800" : score >= 0.6 ? "text-yellow-400 border-yellow-800" : "text-red-400 border-red-800";
  return (
    <div
      onClick={onClick}
      className={`bg-gray-900 border rounded-xl p-4 cursor-pointer transition-all ${expanded ? "border-indigo-700" : "border-gray-800 hover:border-gray-700"}`}
    >
      <div className="flex justify-between items-start gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-200 truncate">{e.query || "—"}</p>
          <p className="text-xs text-gray-500 mt-0.5">{e.pipeline_id?.slice(0, 8)}… · {e.model_used || "—"}</p>
        </div>
        <span className={`text-base font-bold border px-2 py-0.5 rounded-lg shrink-0 ${color}`}>
          {score.toFixed(2)}
        </span>
      </div>

      {expanded && (
        <div className="mt-4 space-y-2 border-t border-gray-800 pt-4">
          <ScoreBar label="Faithfulness" value={e.faithfulness || 0} />
          <ScoreBar label="Answer Relevance" value={e.answer_relevance || 0} />
          <ScoreBar label="Context Precision" value={e.context_precision || 0} />
          <ScoreBar label="Context Recall" value={e.context_recall || 0} />
        </div>
      )}
    </div>
  );
}

export default function EvaluationsPage() {
  const [evals, setEvals] = useState<any[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    getEvaluations({ page: 1, page_size: 50 }).then(setEvals).catch(() => {});

    // SSE live feed
    const token = typeof window !== "undefined" ? localStorage.getItem("neuroflow_token") : "";
    const es = new EventSource(`${API_BASE}/evaluations/stream`);
    esRef.current = es;
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        setEvals((prev) => [data, ...prev].slice(0, 200));
      } catch {}
    };
    return () => es.close();
  }, []);

  return (
    <div className="p-6 max-w-3xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-white">Evaluation Feed</h1>
        <div className="flex items-center gap-2 text-xs text-green-400">
          <span className="w-2 h-2 rounded-full bg-green-400 pulse-dot inline-block" />
          Live
        </div>
      </div>

      <div className="space-y-3">
        {evals.map((e) => (
          <EvalCard
            key={e.eval_id || e.id}
            eval={e}
            expanded={expanded === (e.eval_id || e.id)}
            onClick={() => setExpanded(expanded === (e.eval_id || e.id) ? null : (e.eval_id || e.id))}
          />
        ))}
        {evals.length === 0 && (
          <div className="text-gray-600 text-sm text-center py-12">
            No evaluations yet. Run a query to see results here.
          </div>
        )}
      </div>
    </div>
  );
}
